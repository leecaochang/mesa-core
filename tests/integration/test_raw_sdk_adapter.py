"""Raw MCP SDK adapter integration test (skipped when mcp is not installed)."""

from __future__ import annotations

import asyncio

import pytest

mcp_server = pytest.importorskip("mcp.server")

from mesa_core.backends import MemoryBackend  # noqa: E402
from mesa_core.mcp.tools import register_mesa_tools  # noqa: E402
from mesa_core.store import ProfileStore  # noqa: E402


def test_register_into_raw_sdk_server_and_dispatch() -> None:
    server = mcp_server.Server("mesa-test")
    store = ProfileStore(backend=MemoryBackend())
    registry = register_mesa_tools(store, adapter="raw_sdk", server=server)
    assert set(registry.registered) == {  # type: ignore[attr-defined]
        "mesa_query_profiles",
        "mesa_get_profile",
        "mesa_explain_profile",
        "mesa_get_caller_context",
    }
    result = asyncio.run(registry.dispatch("mesa_get_caller_context", {}))  # type: ignore[attr-defined]
    assert result["is_authenticated"] is False


def test_unknown_tool_returns_error_envelope() -> None:
    # Spec 9.6 envelope, not a raised KeyError (mesa-core 1.3).
    server = mcp_server.Server("mesa-test")
    store = ProfileStore(backend=MemoryBackend())
    registry = register_mesa_tools(store, adapter="raw_sdk", server=server)
    result = asyncio.run(registry.dispatch("mesa_frobnicate", {}))  # type: ignore[attr-defined]
    assert result == {
        "error": "unknown_tool",
        "message": "tool 'mesa_frobnicate' is not registered",
        "details": {"tool": "mesa_frobnicate"},
    }
