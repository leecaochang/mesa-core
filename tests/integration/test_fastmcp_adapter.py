"""FastMCP adapter integration test (skipped when fastmcp is not installed).

Registration names alone are not evidence the adapter works: 1.2.0 registered
all four tools under the right names while publishing an input schema that
rejected every payload the specification documents. These tests assert what a
client actually sees and what a documented call actually does.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

fastmcp = pytest.importorskip("fastmcp")

from mesa_core.mcp.schemas import TOOL_SCHEMAS  # noqa: E402
from mesa_core.mcp.tools import register_mesa_tools  # noqa: E402

from ._mcp_common import CORE_TOOLS, seeded_store  # noqa: E402


def make_server() -> Any:
    server = fastmcp.FastMCP("mesa-test")
    register_mesa_tools(seeded_store(), adapter="fastmcp", server=server)
    return server


def published_schemas() -> dict[str, Any]:
    async def main() -> dict[str, Any]:
        async with fastmcp.Client(make_server()) as client:
            return {tool.name: tool.inputSchema for tool in await client.list_tools()}

    return asyncio.run(main())


def call(name: str, payload: dict[str, Any]) -> Any:
    async def main() -> Any:
        async with fastmcp.Client(make_server()) as client:
            return (await client.call_tool(name, payload)).data

    return asyncio.run(main())


def test_register_into_real_fastmcp_server() -> None:
    server = fastmcp.FastMCP("mesa-test")
    registry = register_mesa_tools(seeded_store(), adapter="fastmcp", server=server)
    assert set(registry.registered) == CORE_TOOLS  # type: ignore[attr-defined]


@pytest.mark.parametrize("name", sorted(CORE_TOOLS))
def test_published_schema_matches_the_declared_schema(name: str) -> None:
    """What a client is told the tool takes must be what the tool declares."""
    published = published_schemas()[name]
    declared = TOOL_SCHEMAS[name]
    assert set(published.get("properties", {})) == set(declared.get("properties", {}))
    assert set(published.get("required", [])) == set(declared.get("required", []))
    assert "params" not in published.get("properties", {})


def test_published_schema_keeps_declared_constraints() -> None:
    limit = published_schemas()["mesa_query_profiles"]["properties"]["limit"]
    assert limit["minimum"] == 1
    assert limit["maximum"] == 200


def _lease_schemas() -> dict[str, Any]:
    from mesa_core.lease import LeaseManager

    async def main() -> dict[str, Any]:
        server = fastmcp.FastMCP("mesa-test")
        register_mesa_tools(
            seeded_store(), adapter="fastmcp", server=server, lease_manager=LeaseManager()
        )
        async with fastmcp.Client(server) as client:
            return {tool.name: tool.inputSchema for tool in await client.list_tools()}

    return asyncio.run(main())


def _numeric_keywords(spec: dict[str, Any]) -> set[str]:
    """The numeric-bound keywords a spec publishes, at the top level or inside
    an anyOf branch (a strict int-or-float number publishes an anyOf)."""
    keys = set(spec)
    for branch in spec.get("anyOf", []):
        keys |= set(branch)
    return keys


def test_lease_numeric_constraints_publish_json_schema_keywords() -> None:
    """The published lease schema must use exclusiveMinimum/minimum/maximum, not
    Pydantic's gt/ge/le which standard JSON Schema validators ignore."""
    props = _lease_schemas()["mesa_request_lease"]["properties"]
    duration = _numeric_keywords(props["duration_seconds"])
    assert "exclusiveMinimum" in duration
    assert not ({"gt", "ge", "le"} & duration)
    priority = _numeric_keywords(props["caller_priority"])
    assert {"minimum", "maximum"} <= priority
    assert not ({"gt", "ge", "le"} & priority)


def test_lease_transport_rejects_out_of_bound_numbers() -> None:
    from mesa_core.lease import LeaseManager

    async def main() -> list[str]:
        server = fastmcp.FastMCP("mesa-test")
        register_mesa_tools(
            seeded_store(), adapter="fastmcp", server=server, lease_manager=LeaseManager()
        )
        outcomes: list[str] = []
        async with fastmcp.Client(server) as client:
            for args in (
                {"entities": ["light.x"], "duration_seconds": 0},
                {"entities": ["light.x"], "duration_seconds": "5"},
                {"entities": ["light.x"], "duration_seconds": 5, "caller_priority": 2},
            ):
                try:
                    await client.call_tool("mesa_request_lease", args)
                    outcomes.append("accepted")
                except Exception:
                    outcomes.append("rejected")
        return outcomes

    assert asyncio.run(main()) == ["rejected", "rejected", "rejected"]


def test_documented_get_profile_payload_is_accepted() -> None:
    """The exact input shape documented in Spec 9.5."""
    assert call("mesa_get_profile", {"entity_id": "light.kitchen"})["entity_id"] == "light.kitchen"


def test_documented_query_payload_is_accepted() -> None:
    result = call("mesa_query_profiles", {"domains": ["light"]})
    assert [row["entity_id"] for row in result["results"]] == ["light.kitchen"]


def test_documented_explain_payload_is_accepted() -> None:
    assert "explanation" in call("mesa_explain_profile", {"entity_id": "light.kitchen"})


def test_no_argument_tool_is_callable() -> None:
    assert call("mesa_get_caller_context", {})["caller_id"] == "anonymous"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"limit": -5}, id="below_minimum"),
        pytest.param({"limit": 9999}, id="above_maximum"),
        pytest.param({"include_inferred": 3}, id="wrong_type"),
        pytest.param({"domins": ["light"]}, id="unknown_field"),
    ],
)
def test_schema_violations_are_rejected_at_the_transport(payload: dict[str, Any]) -> None:
    with pytest.raises(Exception, match=r"(?i)valid|unexpected|error"):
        call("mesa_query_profiles", payload)


def test_missing_required_argument_is_rejected() -> None:
    with pytest.raises(Exception, match=r"(?i)valid|required|missing"):
        call("mesa_get_profile", {})
