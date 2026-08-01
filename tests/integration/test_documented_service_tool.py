"""The service tool the Module Proposal documents, exercised rather than read.

Section 6.2's `call_ha_service` is a host's own code, so nothing in mesa-core
runs it, and successive audits found real defects there: a `**kwargs` signature
neither supported server accepts, a merge order that let a caller replace the
enforced target, and a guard the documentation grew that its own regression
fixture never had. Each survived because the copyable text and the tested text
were different objects.

They are now the same object. `examples/ha_service_tool.py` is the source, this
module imports it, and `test_documented_handler_matches_the_module_proposal`
asserts the Module embeds that file's marked region verbatim.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest

from mesa_core import MesaEnforcer
from mesa_core.backends import MemoryBackend
from mesa_core.exceptions import MesaEnforcementError
from mesa_core.privacy import CallerContext
from mesa_core.profile import SemanticProfile
from mesa_core.store import ProfileStore

ROOT = Path(__file__).parent.parent.parent
EXAMPLE_PATH = ROOT / "examples" / "ha_service_tool.py"
MODULE_DOC = ROOT / "documents" / "MESA-Module.md"


def _load_example() -> Any:
    spec = importlib.util.spec_from_file_location("mesa_example_ha_service", EXAMPLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


example = _load_example()

CALLER = CallerContext(caller_id="agent", roles=["owner"], is_authenticated=True, session_id="s1")
EXPECTED_PROPERTIES = {"domain", "service", "entity_id", "service_data", "confirmation_token"}
EXPECTED_REQUIRED = {"domain", "service", "entity_id"}


def build_tool(control_mode: str = "confirm") -> Any:
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "light.x",
        SemanticProfile.from_dict(
            "light.x",
            {
                "semantic_profile": {
                    "metadata_origin": {"source": "user"},
                    "operational_boundaries": {
                        "control_mode": control_mode,
                        "enforcement_mode": "enforced",
                    },
                }
            },
        ),
    )

    async def perform_ha_call(domain: str, service: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"called": f"{domain}.{service}", "data": data}

    return example.build_call_ha_service(
        MesaEnforcer(store=store, mode="enforced"), lambda: CALLER, perform_ha_call
    )


# ---------------------------------------------------------------- registration


def test_documented_handler_registers_on_standalone_fastmcp() -> None:
    fastmcp = pytest.importorskip("fastmcp")

    server = fastmcp.FastMCP("mesa-doc-test")
    server.tool()(build_tool())

    async def published() -> dict[str, Any]:
        async with fastmcp.Client(server) as client:
            return {t.name: t.inputSchema for t in await client.list_tools()}["call_ha_service"]

    schema = asyncio.run(published())
    assert set(schema["properties"]) == EXPECTED_PROPERTIES
    assert set(schema.get("required", [])) == EXPECTED_REQUIRED


def test_documented_handler_registers_on_mcp_sdk_fastmcp() -> None:
    pytest.importorskip("mcp.server.fastmcp")
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("mesa-doc-test")
    server.tool()(build_tool())
    schema = asyncio.run(server.list_tools())[0].inputSchema
    assert set(schema["properties"]) == EXPECTED_PROPERTIES
    assert set(schema.get("required", [])) == EXPECTED_REQUIRED


# ------------------------------------------------------------- the host guard


@pytest.mark.parametrize(
    "reserved",
    ["entity_id", "target", "area_id", "config_entry_id", "device_id", "floor_id", "label_id"],
)
def test_every_reserved_target_key_is_rejected(reserved: str) -> None:
    # Each of these can reach entities the call never evaluated, so an
    # entity-targeted tool refuses them instead of forwarding them.
    tool = build_tool()
    with pytest.raises(MesaEnforcementError, match="target fields"):
        asyncio.run(tool("light", "turn_on", "light.x", {reserved: "whatever"}))


def test_the_guard_covers_every_shared_selector() -> None:
    # If Home Assistant gains a selector and the shared constant learns it, the
    # host guard must learn it too rather than silently keep forwarding it.
    from mesa_core import HA_TARGET_SELECTOR_KEYS

    assert set(HA_TARGET_SELECTOR_KEYS) <= example.RESERVED_TARGET_KEYS


def test_service_data_reaches_the_enforcer_and_the_call() -> None:
    tool = build_tool(control_mode="autonomous")
    result = asyncio.run(tool("light", "turn_on", "light.x", {"brightness": 255}))
    assert result["ok"] is True
    assert result["result"]["data"] == {"entity_id": "light.x", "brightness": 255}


def test_confirm_returns_a_challenge_instead_of_raising() -> None:
    tool = build_tool(control_mode="confirm")
    result = asyncio.run(tool("light", "turn_on", "light.x", {"brightness": 255}))
    challenge = result["requires_confirmation"]
    assert challenge["entity_id"] == "light.x"
    assert challenge["parameters"] == {"brightness": 255, "entity_id": "light.x"}


def test_prohibited_raises() -> None:
    tool = build_tool(control_mode="prohibited")
    with pytest.raises(MesaEnforcementError):
        asyncio.run(tool("light", "turn_on", "light.x", {"brightness": 255}))


# --------------------------------------------------- the copyable text matches


def test_documented_handler_matches_the_module_proposal() -> None:
    """The Module must embed this file's marked region verbatim.

    Without this, the documented version and the exercised version drift, which
    is exactly how the guard above ended up in the documentation but not in the
    fixture that was supposed to protect it.
    """
    source = EXAMPLE_PATH.read_text()
    marked = source.split("# --- docs:call_ha_service:start\n")[1]
    marked = marked.split("# --- docs:call_ha_service:end")[0].rstrip("\n")
    assert marked.strip(), "marker region is empty"
    assert marked in MODULE_DOC.read_text(), (
        "documents/MESA-Module.md does not contain examples/ha_service_tool.py's marked "
        "region verbatim; update the document to match the example"
    )


def test_documented_handler_is_the_only_service_tool_in_the_module() -> None:
    # Guards against a second, unexercised copy reappearing in the document.
    assert len(re.findall(r"async def call_ha_service\(", MODULE_DOC.read_text())) == 1


# ------------------------------------- why the signature is explicit, not **kwargs


async def variadic_handler(domain: str, **kwargs: Any) -> dict[str, Any]:
    return {}


def test_variadic_handler_is_rejected_by_standalone_fastmcp() -> None:
    fastmcp = pytest.importorskip("fastmcp")

    server = fastmcp.FastMCP("mesa-doc-test")
    with pytest.raises(ValueError, match="kwargs"):
        server.tool()(variadic_handler)


def test_variadic_handler_publishes_an_unusable_schema_on_the_mcp_sdk() -> None:
    """The SDK accepts **kwargs but publishes it as a required parameter.

    Registration succeeding is what let this defect survive review; the schema
    is the evidence that a caller still cannot pass `brightness`.
    """
    pytest.importorskip("mcp.server.fastmcp")
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("mesa-doc-test")
    server.tool()(variadic_handler)
    schema = asyncio.run(server.list_tools())[0].inputSchema
    assert "kwargs" in schema["properties"]
    assert "kwargs" in schema.get("required", [])
    assert "brightness" not in schema["properties"]
