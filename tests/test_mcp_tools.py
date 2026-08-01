"""MESA MCP tool handler tests (Spec 9.2-9.6) using the DictToolRegistry."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mesa_core.backends import MemoryBackend
from mesa_core.lease import LeaseManager
from mesa_core.mcp.adapters import DictToolRegistry
from mesa_core.mcp.schemas import TOOL_SCHEMAS, tools_schema_document
from mesa_core.mcp.tools import register_mesa_tools
from mesa_core.privacy import CallerContext
from mesa_core.profile import SemanticProfile
from mesa_core.store import ProfileStore

from .conformance.test_conflict import make_profile

TOOL_NAMES = {
    "mesa_query_profiles",
    "mesa_get_profile",
    "mesa_explain_profile",
    "mesa_get_caller_context",
}


def make_registry(
    store: ProfileStore | None = None,
    caller_context_fn: Any = None,
) -> tuple[DictToolRegistry, ProfileStore]:
    store = store or ProfileStore(backend=MemoryBackend())
    registry = DictToolRegistry()
    register_mesa_tools(store, adapter=registry, caller_context_fn=caller_context_fn)
    return registry, store


def call(registry: DictToolRegistry, name: str, **params: Any) -> dict[str, Any]:
    return asyncio.run(registry.call(name, params))


def test_all_four_core_tools_registered() -> None:
    registry, _ = make_registry()
    assert set(registry.tools) == TOOL_NAMES


def test_query_filters_domains_and_excludes_untrusted_by_default() -> None:
    registry, store = make_registry()
    store.set("light.a", make_profile("light.a"))
    store.set("switch.b", make_profile("switch.b"))
    store.set("light.inferred", make_profile("light.inferred", origin="inferred_ai"))

    result = call(registry, "mesa_query_profiles", domains=["light"])
    assert result["mesa_version"] == "1.1"
    assert result["total_matched"] == 1
    assert result["results"][0]["entity_id"] == "light.a"

    included = call(registry, "mesa_query_profiles", domains=["light"], include_inferred=True)
    assert included["total_matched"] == 2
    inferred = next(r for r in included["results"] if r["entity_id"] == "light.inferred")
    assert inferred["staleness_status"] in ("current", "stale")


def test_query_tags_match_against_effective_set() -> None:
    registry, store = make_registry()
    # Tag declared only at domain level: effective tag set includes it (Spec 9.2).
    store.set_domain_profile(
        "light", make_profile("light", origin="developer", tags=["lighting.ambient"])
    )
    store.set("light.a", make_profile("light.a", tags=["lighting.task"]))

    any_match = call(registry, "mesa_query_profiles", tags=["lighting.ambient"])
    assert any_match["total_matched"] == 1

    all_match = call(
        registry, "mesa_query_profiles",
        tags=["lighting.ambient", "lighting.task"], tags_match="all",
    )
    assert all_match["total_matched"] == 1

    all_miss = call(
        registry, "mesa_query_profiles",
        tags=["lighting.ambient", "lighting.colour"], tags_match="all",
    )
    assert all_miss["total_matched"] == 0


def test_query_include_fields_always_keeps_provenance() -> None:
    registry, store = make_registry()
    store.set("light.a", make_profile("light.a"))
    result = call(
        registry, "mesa_query_profiles", include_fields=["operational_boundaries"]
    )
    sp = result["results"][0]["semantic_profile"]
    assert "operational_boundaries" in sp
    assert "metadata_origin" in sp  # always included (Spec 9.2)
    assert "schema_version" in sp
    assert "semantic_tags" not in sp


def test_query_min_origin_authority() -> None:
    registry, store = make_registry()
    store.set("light.dev", make_profile("light.dev", origin="developer"))
    store.set("light.usr", make_profile("light.usr", origin="user"))
    store.set("light.hyb", make_profile("light.hyb", origin="hybrid"))
    result = call(registry, "mesa_query_profiles", min_origin_authority="user")
    assert {r["entity_id"] for r in result["results"]} == {"light.dev", "light.usr"}


def test_query_pagination_and_invalid_cursor_envelope() -> None:
    registry, store = make_registry()
    for i in range(5):
        store.set(f"light.l{i}", make_profile(f"light.l{i}"))
    first = call(registry, "mesa_query_profiles", limit=2)
    assert first["pagination"]["has_more"] is True
    second = call(registry, "mesa_query_profiles", limit=2, cursor=first["pagination"]["next_cursor"])
    assert [r["entity_id"] for r in second["results"]] == ["light.l2", "light.l3"]

    bad = call(registry, "mesa_query_profiles", cursor="garbage")
    assert bad["error"] == "invalid_cursor"
    assert "message" in bad and "details" in bad


def test_query_invalid_filter_envelopes() -> None:
    registry, _store = make_registry()
    assert call(registry, "mesa_query_profiles", tags_match="some")["error"] == "invalid_query"
    assert (
        call(registry, "mesa_query_profiles", min_origin_authority="bogus")["error"]
        == "invalid_query"
    )
    assert call(registry, "mesa_query_profiles", areas=["area.x"])["error"] == "invalid_query"


def test_query_areas_filter_with_callback() -> None:
    store = ProfileStore(
        backend=MemoryBackend(),
        get_entity_area=lambda eid: "area.kitchen" if eid == "light.a" else None,
    )
    registry, _ = make_registry(store)
    store.set("light.a", make_profile("light.a"))
    store.set("light.b", make_profile("light.b"))
    result = call(registry, "mesa_query_profiles", areas=["area.kitchen"])
    assert [r["entity_id"] for r in result["results"]] == ["light.a"]


def test_get_profile_found_with_diagnostic() -> None:
    fixtures = Path(__file__).parent / "fixtures" / "profiles"
    from mesa_core import SemanticProfile

    data = json.loads((fixtures / "light_kernel.json").read_text())
    data["diagnostic_profile"] = {"state_mapping": []}
    registry, store = make_registry()
    store.set("light.a", SemanticProfile.from_dict("light.a", data))

    result = call(registry, "mesa_get_profile", entity_id="light.a")
    assert result["entity_id"] == "light.a"
    assert result["semantic_profile"]["operational_boundaries"]["control_mode"] == "autonomous"
    assert result["diagnostic_profile"] == {"state_mapping": []}

    without = call(registry, "mesa_get_profile", entity_id="light.a", include_diagnostic=False)
    assert "diagnostic_profile" not in without


def test_get_profile_not_found_envelope() -> None:
    registry, _ = make_registry()
    result = call(registry, "mesa_get_profile", entity_id="light.ghost")
    assert result["error"] == "not_found"


def test_get_profile_resolves_inheritance() -> None:
    registry, store = make_registry()
    store.set_domain_profile(
        "light",
        make_profile("light", origin="developer", boundaries={"control_mode": "autonomous"}),
    )
    result = call(registry, "mesa_get_profile", entity_id="light.unprofiled_entity")
    # No entity-level profile, but the domain profile makes it resolvable.
    assert result["semantic_profile"]["operational_boundaries"]["control_mode"] == "autonomous"


def test_explain_profile_envelope() -> None:
    registry, store = make_registry()
    store.set_domain_profile(
        "light",
        make_profile("light", origin="developer", boundaries={"control_mode": "autonomous"}),
    )
    store.set("light.a", make_profile("light.a", boundaries={"control_mode": "confirm"}))
    result = call(registry, "mesa_explain_profile", entity_id="light.a")
    assert result["conflicts_detected"] is True
    cm = next(
        e for e in result["explanation"]
        if e["field_path"] == "operational_boundaries.control_mode"
    )
    assert cm["effective_value"] == "confirm"
    assert cm["competing_values"]
    hidden = call(registry, "mesa_explain_profile", entity_id="light.a", show_conflicts=False)
    cm2 = next(
        e for e in hidden["explanation"]
        if e["field_path"] == "operational_boundaries.control_mode"
    )
    assert "competing_values" not in cm2


def test_caller_context_tool() -> None:
    ctx = CallerContext(
        caller_id="user.alice",
        roles=["primary_resident"],
        is_authenticated=True,
        session_id="sess-1",
    )
    registry, _ = make_registry(caller_context_fn=lambda: ctx)
    result = call(registry, "mesa_get_caller_context")
    assert result["caller_id"] == "user.alice"
    assert result["roles"] == ["primary_resident"]

    anonymous_registry, _ = make_registry()
    anon = call(anonymous_registry, "mesa_get_caller_context")
    assert anon["is_authenticated"] is False
    assert anon["roles"] == []


def test_caller_context_included_in_query_envelope() -> None:
    ctx = CallerContext(caller_id="user.alice", is_authenticated=True, session_id="s")
    registry, store = make_registry(caller_context_fn=lambda: ctx)
    store.set("light.a", make_profile("light.a"))
    result = call(registry, "mesa_query_profiles")
    assert result["caller_context"]["caller_id"] == "user.alice"


def test_lease_tools_registered_only_with_manager() -> None:
    registry, _ = make_registry()
    assert set(registry.tools) == TOOL_NAMES  # no lease_manager, no lease tools

    with_leases = DictToolRegistry()
    store = ProfileStore(backend=MemoryBackend())
    register_mesa_tools(store, adapter=with_leases, lease_manager=LeaseManager(store))
    assert set(with_leases.tools) == TOOL_NAMES | {"mesa_request_lease", "mesa_release_lease"}


def _lease_registry() -> DictToolRegistry:
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "automation.smoke",
        SemanticProfile.from_dict(
            "automation.smoke",
            {
                "semantic_profile": {
                    "metadata_origin": {"source": "user"},
                    "cooperative_priority": {"level": "critical"},
                    "environmental_dependencies": {"trigger_entities": ["switch.siren"]},
                }
            },
        ),
    )
    registry = DictToolRegistry()
    ctx = CallerContext(
        caller_id="agent.a", roles=[], is_authenticated=True, session_id="sess-1"
    )
    register_mesa_tools(
        store,
        adapter=registry,
        lease_manager=LeaseManager(store),
        caller_context_fn=lambda: ctx,
    )
    return registry


def test_lease_request_and_release_round_trip() -> None:
    registry = _lease_registry()
    granted = call(registry, "mesa_request_lease", entities=["light.x"], duration_seconds=10)
    assert granted["mesa_version"] == "1.1"
    assert granted["granted"] and granted["entities_granted"] == ["light.x"]

    released = call(registry, "mesa_release_lease", lease_id=granted["lease_id"])
    assert released["released"] and released["entities"] == ["light.x"]

    again = call(registry, "mesa_release_lease", lease_id=granted["lease_id"])
    assert again["error"] == "lease_not_found"


def test_lease_conflict_envelope_for_total_automation_denial() -> None:
    registry = _lease_registry()
    result = call(registry, "mesa_request_lease", entities=["switch.siren"], duration_seconds=10)
    assert result["error"] == "lease_conflict"
    assert "switch.siren" in result["details"]["denial_reasons"]


def test_lease_request_missing_params_rejected() -> None:
    registry = _lease_registry()
    assert call(registry, "mesa_request_lease", duration_seconds=10)["error"] == "invalid_query"
    assert call(registry, "mesa_request_lease", entities=["light.x"])["error"] == "invalid_query"
    assert call(registry, "mesa_release_lease")["error"] == "invalid_query"


def _moments_registry(moments: Any) -> DictToolRegistry:
    store = ProfileStore(backend=MemoryBackend())
    store.set("light.a", make_profile("light.a"))
    registry = DictToolRegistry()
    register_mesa_tools(
        store,
        adapter=registry,
        get_semantic_moments=moments if callable(moments) else lambda eid: moments,
    )
    return registry


def test_semantic_moments_opt_in_and_normalised() -> None:
    supplied = [
        {"id": "light.turned_on", "kind": "trigger", "description": "Light turned on"},
        {"kind": "trigger"},  # no id: dropped
        "not-a-dict",  # dropped
    ]
    registry = _moments_registry(supplied)
    # Off by default: no field even though the host could answer.
    assert "semantic_moments" not in call(registry, "mesa_get_profile", entity_id="light.a")
    result = call(registry, "mesa_get_profile", entity_id="light.a", include_semantic_moments=True)
    assert result["semantic_moments"] == [
        {"id": "light.turned_on", "kind": "trigger", "description": "Light turned on"}
    ]


def test_semantic_moments_omitted_when_host_cannot_answer() -> None:
    registry, store = make_registry()
    store.set("light.a", make_profile("light.a"))
    # No callback registered at all.
    no_callback = call(registry, "mesa_get_profile", entity_id="light.a", include_semantic_moments=True)
    assert "semantic_moments" not in no_callback

    # Callback answers None.
    none_registry = _moments_registry(None)
    assert "semantic_moments" not in call(
        none_registry, "mesa_get_profile", entity_id="light.a", include_semantic_moments=True
    )

    # Callback raises: omitted, not an error envelope.
    def boom(entity_id: str) -> list[dict[str, Any]]:
        raise RuntimeError("registry offline")

    raising = _moments_registry(boom)
    result = call(raising, "mesa_get_profile", entity_id="light.a", include_semantic_moments=True)
    assert "error" not in result and "semantic_moments" not in result


def test_shipped_tools_schema_in_sync() -> None:
    shipped = json.loads(
        (Path(__file__).parent.parent / "mesa_core" / "schemas" / "mesa_tools.schema.json").read_text()
    )
    assert shipped == tools_schema_document()
    assert set(shipped["tools"]) == set(TOOL_SCHEMAS)


# -- schema enforcement at the handler boundary (Finding B) --------------------
# A raw_sdk / custom registry dispatches straight to the handler, so the handler
# must enforce the declared schema itself rather than trusting a transport to.


def test_direct_dispatch_rejects_unknown_property() -> None:
    registry, store = make_registry()
    store.set("light.a", make_profile("light.a"))
    # {"domins": [...]} was previously ignored and the query ran unfiltered.
    result = call(registry, "mesa_query_profiles", domins=["light"])
    assert result["error"] == "invalid_query"
    assert "domins" in result["message"]


def test_direct_dispatch_rejects_wrong_typed_params() -> None:
    registry, store = make_registry()
    store.set("light.a", make_profile("light.a"))
    # A string is not coerced to a boolean (bool("false") is True, Spec 9.2).
    assert (
        call(registry, "mesa_query_profiles", include_inferred="false")["error"]
        == "invalid_query"
    )
    # include_fields must be an array, not a string consumed character by character.
    assert (
        call(registry, "mesa_query_profiles", include_fields="operational_boundaries")["error"]
        == "invalid_query"
    )
    # A numeric entity_id is invalid_query, not an internal server_error.
    numeric = call(registry, "mesa_get_profile", entity_id=123)
    assert numeric["error"] == "invalid_query"


def test_direct_dispatch_rejects_explicit_null() -> None:
    registry, store = make_registry()
    store.set("light.a", make_profile("light.a"))
    # The published schema names a type for every field and does not allow null,
    # so an explicit null is a wrong type, not "omitted". limit=null previously
    # reached min(None, 200) and returned a server_error.
    assert call(registry, "mesa_query_profiles", domains=None)["error"] == "invalid_query"
    assert call(registry, "mesa_query_profiles", include_inferred=None)["error"] == "invalid_query"
    assert call(registry, "mesa_query_profiles", limit=None)["error"] == "invalid_query"


def test_direct_dispatch_rejects_out_of_range_limit() -> None:
    registry, _ = make_registry()
    assert call(registry, "mesa_query_profiles", limit=9999)["error"] == "invalid_query"
    assert call(registry, "mesa_query_profiles", limit=0)["error"] == "invalid_query"


def test_query_pagination_returned_matches_results_after_denial() -> None:
    # Finding C: a row denied to the caller is omitted from results, so
    # pagination.returned must reflect the shaped list, not the pre-access page.
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "camera.front_door",
        make_profile(
            "camera.front_door",
            privacy={
                "level": "restricted",
                "deny_response_mode": "omit",
                "access_roles": {"deny_for": ["guest"]},
            },
        ),
    )
    guest = CallerContext(
        caller_id="user.guest", roles=["guest"], is_authenticated=True, session_id="s"
    )
    registry, _ = make_registry(store, caller_context_fn=lambda: guest)
    result = call(registry, "mesa_query_profiles", domains=["camera"])
    assert result["results"] == []
    assert result["pagination"]["returned"] == len(result["results"]) == 0
    # total_matched still counts the entity that matched the filters pre-shaping.
    assert result["total_matched"] == 1


# -------------------------------- MESA 1.1: filters, component_type, unknown_tool


def test_query_devices_and_integrations_filters_end_to_end() -> None:
    store = ProfileStore(
        backend=MemoryBackend(),
        get_entity_device={"light.a": "dev1", "light.b": "dev2"}.get,
        get_entity_integration={"light.a": "hue", "light.b": "hue"}.get,
    )
    registry, _ = make_registry(store)
    store.set("light.a", make_profile("light.a"))
    store.set("light.b", make_profile("light.b"))

    result = call(registry, "mesa_query_profiles", devices=["dev1"])
    assert result["total_matched"] == 1
    assert result["results"][0]["entity_id"] == "light.a"
    result = call(registry, "mesa_query_profiles", integrations=["hue"])
    assert result["total_matched"] == 2


def test_query_filters_without_callbacks_return_invalid_query() -> None:
    registry, store = make_registry()
    store.set("light.a", make_profile("light.a"))
    for param in ({"devices": ["dev1"]}, {"integrations": ["hue"]}):
        result = call(registry, "mesa_query_profiles", **param)
        assert result["error"] == "invalid_query"
        assert "callback" in result["message"]


def test_component_type_derived_from_domain() -> None:
    registry, store = make_registry()
    for entity_id, expected in (
        ("light.a", "entity"),
        ("automation.morning", "automation"),
        ("scene.movie", "scene"),
        ("person.foxy", "person"),
        ("zone.home", "zone"),
        ("input_boolean.flag", "helper"),
    ):
        store.set(entity_id, make_profile(entity_id))
        got = call(registry, "mesa_get_profile", entity_id=entity_id)
        assert got["component_type"] == expected, entity_id
