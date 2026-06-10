"""FastMCP adapter integration test (skipped when fastmcp is not installed)."""

from __future__ import annotations

import pytest

fastmcp = pytest.importorskip("fastmcp")

from mesa_core.backends import MemoryBackend  # noqa: E402
from mesa_core.mcp.tools import register_mesa_tools  # noqa: E402
from mesa_core.store import ProfileStore  # noqa: E402


def test_register_into_real_fastmcp_server() -> None:
    server = fastmcp.FastMCP("mesa-test")
    store = ProfileStore(backend=MemoryBackend())
    registry = register_mesa_tools(store, adapter="fastmcp", server=server)
    assert set(registry.registered) == {  # type: ignore[attr-defined]
        "mesa_query_profiles",
        "mesa_get_profile",
        "mesa_explain_profile",
        "mesa_get_caller_context",
    }
