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
            return {
                tool.name: tool.model_dump(by_alias=True)["inputSchema"]
                for tool in await client.list_tools()
            }

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
            return {
                tool.name: tool.model_dump(by_alias=True)["inputSchema"]
                for tool in await client.list_tools()
            }

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


@pytest.mark.parametrize(
    "payload",
    [
        {"limit": "50"},
        {"limit": True},
        {"include_inferred": "false"},
        {"include_inferred": None},
        {"domains": "light"},
        {"domains": [1]},
    ],
)
def test_strict_parameters_survive_framework_validation(payload: dict[str, Any]) -> None:
    with pytest.raises(Exception, match=r"(?i)valid|unexpected|error"):
        call("mesa_query_profiles", payload)


def test_streamable_http_retrieval_and_lease_roundtrip() -> None:
    """Exercise real HTTP lifecycle/serialization, not only in-memory dispatch."""
    import socket
    import threading
    import time

    import uvicorn

    from mesa_core.lease import LeaseManager
    from mesa_core.privacy import CallerContext

    server = fastmcp.FastMCP("mesa-http-test")
    store = seeded_store()
    register_mesa_tools(
        store,
        adapter="fastmcp",
        server=server,
        lease_manager=LeaseManager(store),
        caller_context_fn=lambda: CallerContext(
            "agent", is_authenticated=True, session_id="http-test"
        ),
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = uvicorn.Server(uvicorn.Config(server.http_app(), log_level="error"))
    thread = threading.Thread(target=lambda: app.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not app.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert app.started

        async def scenario() -> None:
            async with fastmcp.Client(f"http://127.0.0.1:{port}/mcp") as client:
                tools = {tool.name for tool in await client.list_tools()}
                assert tools == CORE_TOOLS | {"mesa_request_lease", "mesa_release_lease"}
                profile = (
                    await client.call_tool("mesa_get_profile", {"entity_id": "light.kitchen"})
                ).data
                assert profile["entity_id"] == "light.kitchen"
                query = (await client.call_tool("mesa_query_profiles", {"domains": ["light"]})).data
                assert query["results"][0]["entity_id"] == "light.kitchen"
                explanation = (
                    await client.call_tool("mesa_explain_profile", {"entity_id": "light.kitchen"})
                ).data
                assert "explanation" in explanation
                caller = (await client.call_tool("mesa_get_caller_context", {})).data
                assert caller["caller_id"] == "agent"
                lease = (
                    await client.call_tool(
                        "mesa_request_lease", {"entities": ["light.kitchen"], "duration_seconds": 5}
                    )
                ).data
                assert lease["granted"]
                release = (
                    await client.call_tool("mesa_release_lease", {"lease_id": lease["lease_id"]})
                ).data
                assert "error" not in release
                with pytest.raises(Exception, match=r"(?i)valid|unexpected|error"):
                    await client.call_tool("mesa_query_profiles", {"include_inferred": "false"})

        asyncio.run(scenario())
    finally:
        app.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()
