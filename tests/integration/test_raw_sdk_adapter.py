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


def test_sdk_v2_registered_handlers_publish_and_dispatch() -> None:
    import json

    from mcp import types

    from mesa_core.mcp.schemas import TOOL_SCHEMAS

    server = mcp_server.Server("mesa-test")
    if not hasattr(server, "get_request_handler"):
        pytest.skip("SDK v2 handler API only; SDK v1 has decorator handlers")
    register_mesa_tools(ProfileStore(MemoryBackend()), adapter="raw_sdk", server=server)

    async def scenario() -> None:
        list_entry = server.get_request_handler("tools/list")
        call_entry = server.get_request_handler("tools/call")
        listed = await list_entry.handler(None, types.PaginatedRequestParams())
        assert {tool.name for tool in listed.tools} == set(TOOL_SCHEMAS) - {
            "mesa_request_lease",
            "mesa_release_lease",
        }
        for tool in listed.tools:
            assert tool.input_schema == TOOL_SCHEMAS[tool.name]
        result = await call_entry.handler(
            None, types.CallToolRequestParams(name="mesa_get_caller_context", arguments={})
        )
        assert json.loads(result.content[0].text)["is_authenticated"] is False
        invalid = await call_entry.handler(
            None, types.CallToolRequestParams(name="mesa_query_profiles", arguments={"limit": "50"})
        )
        assert json.loads(invalid.content[0].text)["error"] == "invalid_query"
        missing = await call_entry.handler(
            None, types.CallToolRequestParams(name="missing", arguments={})
        )
        assert json.loads(missing.content[0].text)["error"] == "unknown_tool"

    asyncio.run(scenario())


@pytest.mark.parametrize("mesa_first", [False, True])
def test_host_tools_coexist_in_either_registration_order(mesa_first):
    import json

    from mcp import types

    server = mcp_server.Server("composed")
    is_v2 = hasattr(server, "add_request_handler")

    def install_mesa():
        register_mesa_tools(ProfileStore(MemoryBackend()), adapter="raw_sdk", server=server)

    if mesa_first:
        install_mesa()
    if is_v2:

        async def host_list(context, params):
            return types.ListToolsResult(
                tools=[types.Tool(name="host_tool", input_schema={"type": "object"})]
            )

        async def host_call(context, params):
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="host-result")]
            )

        server.add_request_handler("tools/list", types.PaginatedRequestParams, host_list)
        server.add_request_handler("tools/call", types.CallToolRequestParams, host_call)
    else:

        @server.list_tools()
        async def host_list():
            return [types.Tool(name="host_tool", inputSchema={"type": "object"})]

        @server.call_tool()
        async def host_call(name, arguments):
            return [types.TextContent(type="text", text="host-result")]

    if not mesa_first:
        install_mesa()

    async def scenario():
        if is_v2:
            listed = await server.get_request_handler("tools/list").handler(
                None, types.PaginatedRequestParams()
            )

            async def call(name):
                return await server.get_request_handler("tools/call").handler(
                    None, types.CallToolRequestParams(name=name, arguments={})
                )
        else:
            listed = (
                await server.request_handlers[types.ListToolsRequest](
                    types.ListToolsRequest(method="tools/list")
                )
            ).root

            async def call(name):
                return (
                    await server.request_handlers[types.CallToolRequest](
                        types.CallToolRequest(
                            method="tools/call",
                            params=types.CallToolRequestParams(name=name, arguments={}),
                        )
                    )
                ).root

        assert "host_tool" in {tool.name for tool in listed.tools}
        assert "mesa_get_caller_context" in {tool.name for tool in listed.tools}
        assert (await call("host_tool")).content[0].text == "host-result"
        assert (
            json.loads((await call("mesa_get_caller_context")).content[0].text)["is_authenticated"]
            is False
        )

    asyncio.run(scenario())
