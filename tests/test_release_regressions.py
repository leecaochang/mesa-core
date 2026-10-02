"""Behavior checks for the October audit repairs and compatibility boundaries."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from mesa_core import MesaEnforcer, ProfileStore, SemanticProfile
from mesa_core.backends import JsonFileBackend, MemoryBackend, SqliteBackend
from mesa_core.enforcer import ConfirmationManager
from mesa_core.exceptions import MesaError
from mesa_core.mcp.adapters import DictToolRegistry
from mesa_core.mcp.tools import register_mesa_tools
from mesa_core.privacy import CallerContext
from mesa_core.profile import ControlMode, OperationalBoundaries


def test_constructor_default_is_an_explicit_declaration_and_can_be_removed():
    store = ProfileStore(MemoryBackend())
    p = SemanticProfile(
        "light.x", operational_boundaries=OperationalBoundaries(control_mode=ControlMode.CONFIRM)
    )
    store.set("light.x", p)
    assert store.get("light.x").declared("operational_boundaries.control_mode")
    p = store.get("light.x")
    p.undeclare("operational_boundaries.control_mode")
    store.set("light.x", p)
    assert not store.get("light.x").declared("operational_boundaries.control_mode")


def test_legacy_caseful_scope_is_read_and_migrated_without_losing_permissions(tmp_path):
    path = tmp_path / "__area__%3ANursery.json"
    path.write_text('{"protected": true}', encoding="utf-8")
    path.chmod(0o640)
    backend = JsonFileBackend(tmp_path)
    assert backend.list_keys() == ["__area__:Nursery"]
    assert backend.read("__area__:nursery") is None
    assert backend.read("__area__:Nursery") == {"protected": True}
    backend.write("__area__:Nursery", {"protected": False})
    assert not path.exists()
    assert backend.read("__area__:Nursery") == {"protected": False}
    assert backend._path("__area__:Nursery").stat().st_mode & 0o777 == 0o640


def test_sqlite_memory_overwrite_literal_prefix_and_close():
    with SqliteBackend(":memory:") as backend:
        backend.write("a\\_X", {"value": 1})
        backend.write("a\\_X", {"value": 2})
        backend.write("aZZX", {})
        assert backend.read("a\\_X") == {"value": 2}
        assert backend.list_keys("a\\_") == ["a\\_X"]
        assert backend.list_keys("a\\_x") == []
    import sqlite3

    with pytest.raises(sqlite3.ProgrammingError):
        backend.read("a\\_X")


def test_policy_workers_do_not_starve_host_default_executor():
    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))

        async def registry_lookup():
            return await asyncio.to_thread(lambda: "hall")

        def area(_):
            return asyncio.run_coroutine_threadsafe(registry_lookup(), loop).result(timeout=3)

        store = ProfileStore(MemoryBackend(), get_entity_area=area)
        store.set_area_profile(
            "hall",
            SemanticProfile.from_dict(
                "hall",
                {
                    "metadata_origin": {"source": "user"},
                    "operational_boundaries": {"control_mode": "prohibited"},
                },
            ),
        )
        decisions = await asyncio.wait_for(
            asyncio.gather(
                *(MesaEnforcer(store).aevaluate("light.x", "light.turn_on") for _ in range(40))
            ),
            timeout=8,
        )
        assert all(d.rule_applied == "control_mode:prohibited" for d in decisions)

    asyncio.run(scenario())


def test_caller_is_snapshotted_once_before_storage_await():
    async def scenario():
        entered, resume = asyncio.Event(), asyncio.Event()
        current = CallerContext("guest", ["guest"], True, "guest-session")
        calls = 0

        class PausingBackend(MemoryBackend):
            def read(self, key):
                if key == "light.x":
                    loop.call_soon_threadsafe(entered.set)
                    asyncio.run_coroutine_threadsafe(resume.wait(), loop).result(timeout=3)
                return super().read(key)

        loop = asyncio.get_running_loop()
        store = ProfileStore(PausingBackend())
        store.set(
            "light.x",
            SemanticProfile.from_dict(
                "light.x",
                {
                    "semantic_profile": {"metadata_origin": {"source": "user"}},
                    "privacy_classification": {
                        "level": "normal",
                        "access_roles": {"deny_for": ["guest"]},
                    },
                },
            ),
        )

        def caller():
            nonlocal calls
            calls += 1
            return current

        registry = DictToolRegistry()
        register_mesa_tools(store, adapter=registry, caller_context_fn=caller)
        task = asyncio.create_task(registry.call("mesa_get_profile", {"entity_id": "light.x"}))
        await asyncio.wait_for(entered.wait(), timeout=3)
        current.roles[:] = ["admin"]
        resume.set()
        result = await asyncio.wait_for(task, timeout=3)
        assert result["error"] == "not_found"
        assert calls == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("ttl", [0, -1, 121, True, 0.5, float("nan")])
def test_confirmation_ttl_is_bounded(ttl):
    with pytest.raises(ValueError):
        ConfirmationManager(ttl_seconds=ttl)


def test_confirmation_capacity_and_expiry_are_bounded():
    manager = ConfirmationManager(ttl_seconds=1)
    now = datetime.now(UTC)
    for _ in range(4096):
        manager.issue("light.x", "light.turn_on", {}, now)
    with pytest.raises(MesaError, match="capacity"):
        manager.issue("light.x", "light.turn_on", {}, now)
    assert manager.issue("light.x", "light.turn_on", {}, now + timedelta(seconds=2))


def test_bare_diagnostic_profile_has_same_canonical_location():
    p = SemanticProfile.from_dict("light.x", {"diagnostic_profile": {"state": "healthy"}})
    assert p.diagnostic_profile == {"state": "healthy"}
    assert p.to_dict()["diagnostic_profile"] == {"state": "healthy"}


@pytest.mark.parametrize("tags_match", ["any", "all"])
def test_explicit_empty_tag_filter_never_returns_all_rows(tags_match):
    store = ProfileStore(MemoryBackend())
    store.set(
        "light.x", SemanticProfile.from_dict("light.x", {"metadata_origin": {"source": "user"}})
    )
    assert store.query(tags=[], tags_match=tags_match).total_matched == 0


def test_registered_lease_manager_adopts_store_and_rejects_mismatch():
    from mesa_core.lease import LeaseManager

    store = ProfileStore(MemoryBackend())
    manager = LeaseManager()
    register_mesa_tools(store, adapter=DictToolRegistry(), lease_manager=manager)
    assert manager.store is store
    assert manager.resolver is store.resolver
    with pytest.raises(MesaError, match="registered profile store"):
        register_mesa_tools(
            store,
            adapter=DictToolRegistry(),
            lease_manager=LeaseManager(ProfileStore(MemoryBackend())),
        )
