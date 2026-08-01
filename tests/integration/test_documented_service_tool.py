"""The service tool the Module Proposal documents must register and publish.

Section 6.2's Full Integration shows a `call_ha_service` tool wrapping the
enforcer. That handler is a host's own code, not mesa-core's, so nothing else
in this suite exercises it, and the audit that prompted this test found it
unusable: it took `**kwargs`, which standalone FastMCP rejects outright and the
MCP SDK publishes as a required parameter of its own, so the service parameters
that carry declared limits could not be supplied at all.

The signature below mirrors the documented one. If the documentation changes,
change it here too: the point is that the shape we tell hosts to write is a
shape both supported servers accept, with the service parameters reaching the
enforcer.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


async def call_ha_service(
    domain: str,
    service: str,
    entity_id: str,
    service_data: dict[str, Any] | None = None,
    confirmation_token: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The documented handler's signature (body irrelevant to registration)."""
    return {"service_params": {"entity_id": entity_id, **(service_data or {})}}


EXPECTED_PROPERTIES = {
    "domain",
    "service",
    "entity_id",
    "service_data",
    "confirmation_token",
}
EXPECTED_REQUIRED = {"domain", "service", "entity_id"}


def test_documented_handler_registers_on_standalone_fastmcp() -> None:
    fastmcp = pytest.importorskip("fastmcp")

    server = fastmcp.FastMCP("mesa-doc-test")
    server.tool()(call_ha_service)

    async def published() -> dict[str, Any]:
        async with fastmcp.Client(server) as client:
            tools = {tool.name: tool.inputSchema for tool in await client.list_tools()}
            return tools["call_ha_service"]

    schema = asyncio.run(published())
    assert set(schema["properties"]) == EXPECTED_PROPERTIES
    assert set(schema.get("required", [])) == EXPECTED_REQUIRED


def test_documented_handler_registers_on_mcp_sdk_fastmcp() -> None:
    pytest.importorskip("mcp.server.fastmcp")
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("mesa-doc-test")
    server.tool()(call_ha_service)

    async def published() -> dict[str, Any]:
        tools = {tool.name: tool.inputSchema for tool in await server.list_tools()}
        return tools["call_ha_service"]

    schema = asyncio.run(published())
    assert set(schema["properties"]) == EXPECTED_PROPERTIES
    assert set(schema.get("required", [])) == EXPECTED_REQUIRED


def test_service_parameters_reach_the_enforcer_call() -> None:
    # A limit is skipped when its parameter is absent from service_params, so
    # the documented handler must forward service_data rather than drop it.
    result = asyncio.run(
        call_ha_service("light", "turn_on", "light.x", {"brightness": 255})
    )
    assert result["service_params"] == {"entity_id": "light.x", "brightness": 255}


def test_variadic_handler_is_rejected_by_the_servers() -> None:
    """Why the documented signature is explicit rather than **kwargs.

    Pins the constraint that made the old example unusable, so a future edit
    reintroducing **kwargs fails here instead of in a host's deployment.
    """
    fastmcp = pytest.importorskip("fastmcp")

    async def variadic(domain: str, **kwargs: Any) -> dict[str, Any]:
        return {}

    server = fastmcp.FastMCP("mesa-doc-test")
    with pytest.raises(ValueError, match="kwargs"):
        server.tool()(variadic)
