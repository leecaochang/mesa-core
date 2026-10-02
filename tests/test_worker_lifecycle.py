"""Hosts can drain and release policy workers through public lifecycle APIs."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar

import pytest

from mesa_core import (
    MesaError,
    ProfileStore,
    SemanticProfile,
    ashutdown_policy_workers,
    shutdown_policy_workers,
)
from mesa_core.backends import MemoryBackend


def policy_threads():
    return {thread for thread in threading.enumerate() if thread.name.startswith("mesa-policy")}


def assert_stopped():
    assert not policy_threads()
    assert not any(thread.name == "mesa-shutdown" for thread in threading.enumerate())


@pytest.fixture(autouse=True)
def cleanup_workers():
    shutdown_policy_workers()
    yield
    shutdown_policy_workers()


def observe_shutdown(monkeypatch, loop):
    """Signal when the real executor begins draining, without replacing its work."""
    entered = asyncio.Event()
    original = ThreadPoolExecutor.shutdown

    def shutdown(executor, *args, **kwargs):
        if not loop.is_closed():
            loop.call_soon_threadsafe(entered.set)
        return original(executor, *args, **kwargs)

    monkeypatch.setattr(ThreadPoolExecutor, "shutdown", shutdown)
    return entered


def test_sync_shutdown_is_idempotent_and_later_async_use_restarts_workers():
    caller = ContextVar("lifecycle_caller", default="absent")
    seen = []

    class ContextBackend(MemoryBackend):
        def list_keys(self, prefix=None):
            seen.append(caller.get())
            return super().list_keys(prefix)

    store = ProfileStore(ContextBackend())
    reset = caller.set("request")
    try:
        assert asyncio.run(store.aentity_keys()) == []
        first = policy_threads()
        assert first
        shutdown_policy_workers()
        shutdown_policy_workers()
        assert_stopped()
        assert asyncio.run(store.aentity_keys()) == []
        assert policy_threads() and first.isdisjoint(policy_threads())
        assert seen == ["request", "request"]
    finally:
        caller.reset(reset)


def test_async_shutdown_allows_host_loop_and_single_default_worker_to_finish(monkeypatch):
    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        entered, release = asyncio.Event(), asyncio.Event()
        closing = observe_shutdown(monkeypatch, loop)

        async def bridge():
            entered.set()
            await release.wait()
            return await asyncio.to_thread(lambda: [])

        class BridgeBackend(MemoryBackend):
            def list_keys(self, prefix=None):
                return asyncio.run_coroutine_threadsafe(bridge(), loop).result(timeout=3)

        work = asyncio.create_task(ProfileStore(BridgeBackend()).aentity_keys())
        await asyncio.wait_for(entered.wait(), 3)
        shutdown = asyncio.create_task(ashutdown_policy_workers())
        try:
            await asyncio.wait_for(closing.wait(), 3)
            assert not shutdown.done()
        finally:
            release.set()
            assert await asyncio.wait_for(work, 3) == []
            await asyncio.wait_for(shutdown, 3)
        assert_stopped()
        await ashutdown_policy_workers()
        assert_stopped()

    asyncio.run(scenario())


def test_concurrent_shutdown_drains_accepted_writes_and_refuses_new_work(monkeypatch):
    async def scenario():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release = threading.Event()
        closing = observe_shutdown(monkeypatch, loop)

        class BlockingBackend(MemoryBackend):
            def write(self, key, value):
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(3):
                    raise TimeoutError("write was not released")
                super().write(key, value)

        store = ProfileStore(BlockingBackend())
        keys = [f"light.worker_{i}" for i in range(40)]
        writes = [asyncio.create_task(store.aset(key, SemanticProfile(key))) for key in keys]
        await asyncio.wait_for(entered.wait(), 3)
        shutdowns = [asyncio.create_task(ashutdown_policy_workers()) for _ in range(2)]
        try:
            await asyncio.wait_for(closing.wait(), 3)
            with pytest.raises(MesaError, match="shutting down"):
                await store.aentity_keys()
            assert not any(task.done() for task in shutdowns)
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(*writes), 3)
            await asyncio.wait_for(asyncio.gather(*shutdowns), 3)
        assert_stopped()
        assert set(store.entity_keys()) == set(keys)
        assert set(await store.aentity_keys()) == set(keys)
        await ashutdown_policy_workers()
        assert_stopped()

    asyncio.run(scenario())


def test_cancellation_waits_for_shutdown_cleanup(monkeypatch):
    async def scenario():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release = threading.Event()
        closing = observe_shutdown(monkeypatch, loop)

        class BlockingBackend(MemoryBackend):
            def list_keys(self, prefix=None):
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(3):
                    raise TimeoutError("read was not released")
                return []

        work = asyncio.create_task(ProfileStore(BlockingBackend()).aentity_keys())
        await asyncio.wait_for(entered.wait(), 3)
        shutdown = asyncio.create_task(ashutdown_policy_workers())
        try:
            await asyncio.wait_for(closing.wait(), 3)
            shutdown.cancel()
            await asyncio.sleep(0)
            assert not shutdown.done()
            shutdown.cancel()
            await asyncio.sleep(0)
            assert not shutdown.done()
        finally:
            release.set()
            await asyncio.wait_for(work, 3)
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(shutdown, 3)
        assert_stopped()

    asyncio.run(scenario())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_policy_callback_cannot_join_its_own_worker(asynchronous):
    class ClosingBackend(MemoryBackend):
        def list_keys(self, prefix=None):
            if asynchronous:
                asyncio.run(ashutdown_policy_workers())
            else:
                shutdown_policy_workers()
            return []

    with pytest.raises(MesaError, match="own pool"):
        asyncio.run(ProfileStore(ClosingBackend()).aentity_keys())
