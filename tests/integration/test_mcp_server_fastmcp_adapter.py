"""FastMCP adapter against the mcp.server.fastmcp lineage (MCP Python SDK).

The adapter claims both FastMCP lineages, but the first-round tests exercised
only the standalone `fastmcp` package. A second audit found the schema was
published differently under `mcp.server.fastmcp` and unknown fields slipped
through, so this suite drives that lineage directly: documented payloads work,
and unknown fields, out-of-range values, string scalars, and explicit nulls are
rejected (the transport's strict pydantic model forbids extras and, unlike a
lax model, does not coerce a JSON string into a boolean or integer).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

pytest.importorskip("mcp.server.fastmcp")

from mcp.server.fastmcp import FastMCP

from mesa_core.mcp.tools import register_mesa_tools

from ._mcp_common import seeded_store


def seeded_server() -> FastMCP:
    server = FastMCP("mesa-test")
    register_mesa_tools(seeded_store(), adapter="fastmcp", server=server)
    return server


def _payload(result: Any) -> dict[str, Any]:
    """Extract the JSON payload from whatever call_tool returns across versions."""
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list):
        return json.loads(result[0].text)
    assert isinstance(result, dict)
    return result


def call(name: str, args: dict[str, Any]) -> dict[str, Any] | str:
    """Return the JSON payload, or the exception type name if the call is rejected."""

    async def main() -> dict[str, Any] | str:
        try:
            return _payload(await seeded_server().call_tool(name, args))
        except Exception as err:  # transport-level rejection (pydantic extra/range)
            return type(err).__name__

    return asyncio.run(main())


def published_schemas() -> dict[str, Any]:
    async def main() -> dict[str, Any]:
        return {t.name: t.inputSchema for t in await seeded_server().list_tools()}

    return asyncio.run(main())


def test_documented_payload_works() -> None:
    result = call("mesa_get_profile", {"entity_id": "light.kitchen"})
    assert isinstance(result, dict) and result["entity_id"] == "light.kitchen"


def test_documented_query_payload_works() -> None:
    result = call("mesa_query_profiles", {"domains": ["light"]})
    assert isinstance(result, dict)
    assert "light.kitchen" in {r["entity_id"] for r in result["results"]}


def test_unknown_field_is_rejected() -> None:
    """A typo'd filter must not be silently dropped and run unfiltered."""
    assert call("mesa_query_profiles", {"domins": ["light"]}) == "ToolError"


def test_out_of_range_limit_is_rejected() -> None:
    assert call("mesa_query_profiles", {"limit": 9999}) == "ToolError"


def test_string_boolean_is_rejected_not_coerced() -> None:
    """The published schema says boolean, so a JSON string is a wrong type and
    must be rejected at the transport, not coerced (advertised == enforced)."""
    assert call("mesa_query_profiles", {"include_inferred": "false"}) == "ToolError"


def test_string_integer_is_rejected_not_coerced() -> None:
    assert call("mesa_query_profiles", {"limit": "50"}) == "ToolError"


def test_explicit_null_is_rejected() -> None:
    assert call("mesa_query_profiles", {"limit": None}) == "ToolError"


def test_published_schema_exposes_flat_fields_not_params() -> None:
    schema = published_schemas()["mesa_get_profile"]
    assert "entity_id" in schema["properties"]
    assert "params" not in schema["properties"]


def test_published_schema_forbids_additional_properties() -> None:
    """This lineage's arg model defaulted to extra='ignore'; the adapter forbids
    extras so the schema advertises the restriction the transport enforces."""
    schema = published_schemas()["mesa_query_profiles"]
    assert schema.get("additionalProperties") is False
