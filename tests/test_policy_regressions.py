"""Safety, privacy, storage and ingestion regressions verified in October 2026."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
import logging
import os
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest

import mesa_core
from examples.ha_service_tool import build_call_ha_service
from mesa_core import (
    InheritanceResolver,
    MesaEnforcer,
    ProfileStore,
    SemanticProfile,
    TriggerValidator,
    import_profiles,
)
from mesa_core.backends import MemoryBackend
from mesa_core.backends.jsonfile import JsonFileBackend
from mesa_core.backends.sqlite import SqliteBackend
from mesa_core.exceptions import MesaEnforcementError, MesaValidationError
from mesa_core.integration_import import import_from_integration
from mesa_core.lease import LeaseManager
from mesa_core.mcp.adapters import DictToolRegistry
from mesa_core.mcp.tools import register_mesa_tools
from mesa_core.privacy import CallerContext
from mesa_core.profile import ControlMode
from mesa_core.validation import validate_document

NOW = datetime.now(UTC).isoformat()
INFERRED = {"source": "inferred_ai", "confidence": 0.9, "generated_at": NOW}
ADMIN = CallerContext(caller_id="u", roles=["admin"], is_authenticated=True, session_id="s")
GUEST = CallerContext(caller_id="g", roles=["guest"], is_authenticated=True, session_id="s")
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
SCHEMA = json.loads(
    (Path(mesa_core.__file__).parent / "schemas" / "mesa_profile.schema.json").read_text(
        encoding="utf-8"
    )
)


def profile(
    entity_id: str, sp: dict[str, Any], privacy: dict[str, Any] | None = None
) -> SemanticProfile:
    doc: dict[str, Any] = {"semantic_profile": sp}
    if privacy is not None:
        doc["privacy_classification"] = privacy
    return SemanticProfile.from_dict(entity_id, doc)


def control_mode(store: ProfileStore, entity_id: str) -> str:
    return store.get_effective(entity_id).operational_boundaries.control_mode.value


# --- P1: the prohibited floor for locks (Spec 4, 5.4 Rule 3, 5.7 Rule E, 5.8) ------


def test_unrelated_area_profile_keeps_the_prohibited_baseline() -> None:
    """An area profile that never mentions control_mode must not unlock a lock.

    Rule E: defaults apply when no profile at any level specifies the field;
    Spec 5.8: the floor is tightening-only. Observed: confirm, and lock.unlock
    is then allowed after one confirmation round-trip.
    """
    store = ProfileStore(MemoryBackend(), get_entity_area=lambda e: "hall")
    assert control_mode(store, "lock.front_door") == "prohibited"
    store.set_area_profile(
        "hall",
        profile(
            "hall",
            {"metadata_origin": {"source": "user"}, "inheritance_scope": "area"},
            {"level": "normal"},
        ),
    )
    assert control_mode(store, "lock.front_door") == "prohibited"


def test_inferred_confirm_cannot_override_a_prohibited_baseline() -> None:
    """Spec 5.4 Rule 3: 'an inferred confirm may override a baseline of autonomous'
    only; an unconfirmed inferred value may never loosen."""
    store = ProfileStore(MemoryBackend())
    store.set(
        "lock.front_door",
        profile(
            "lock.front_door",
            {"metadata_origin": INFERRED, "operational_boundaries": {"control_mode": "confirm"}},
        ),
    )
    assert control_mode(store, "lock.front_door") == "prohibited"


def test_inferred_profile_cannot_loosen_a_prohibited_deployment_default() -> None:
    store = ProfileStore(MemoryBackend())
    store.set_deployment_defaults({"domain_overrides": {"lock": {"control_mode": "prohibited"}}})
    store.set(
        "lock.front_door",
        profile(
            "lock.front_door",
            {"metadata_origin": INFERRED, "semantic_tags": ["security.access_control"]},
        ),
    )
    assert control_mode(store, "lock.front_door") == "prohibited"


def test_deployment_defaults_without_a_lock_entry_do_not_make_locks_autonomous() -> None:
    """Getting Started 3.3: deployment_defaults 'supplements the built-in baseline'
    and the prohibited baseline 'protects you automatically'. Observed: an
    unprofiled lock.unlock is allowed outright in enforced mode."""
    store = ProfileStore(MemoryBackend())
    store.set_deployment_defaults({"default_control_mode": "autonomous"})
    result = MesaEnforcer(store, mode="enforced").evaluate(
        "lock.front_door", "lock.unlock", {}, ADMIN
    )
    assert not result.allowed


# --- P1: retrieval wired as documented must honour every inheritance layer -----------


def test_registered_tools_resolve_through_the_enforcers_resolver() -> None:
    """Module 6.2 passes the callback-equipped resolver only to MesaEnforcer and
    then registers the tools with enforcer=. The tools fall back to a resolver
    without callbacks, so a device-scope deny_for that the enforcer applies is
    invisible to mesa_get_profile (Spec 2 L1: MUST NOT expose to deny_for roles)."""
    store = ProfileStore(MemoryBackend())
    resolver = InheritanceResolver(store=store, get_entity_device=lambda e: "cam1")
    store.set_device_profile(
        "cam1",
        profile(
            "cam1",
            {"metadata_origin": {"source": "user"}, "inheritance_scope": "device"},
            {
                "level": "restricted",
                "deny_response_mode": "omit",
                "access_roles": {"deny_for": ["guest"]},
            },
        ),
    )
    store.set(
        "camera.nursery",
        profile("camera.nursery", {"metadata_origin": {"source": "user"}}, {"level": "normal"}),
    )
    enforcer = MesaEnforcer(store=store, resolver=resolver)
    assert not enforcer.evaluate("camera.nursery", "camera.turn_on", {}, GUEST).allowed
    registry = DictToolRegistry()
    register_mesa_tools(store, adapter=registry, enforcer=enforcer, caller_context_fn=lambda: GUEST)
    out = asyncio.run(registry.call("mesa_get_profile", {"entity_id": "camera.nursery"}))
    assert out.get("error") in {"not_found", "forbidden"}, out


# --- P1: omitted entities leak through query counts -----------------------------------


def test_query_counts_cannot_probe_an_omitted_entity() -> None:
    """Spec 7.1 omit: 'Entity absent from response'. Observed: total_matched
    reveals whether a denied camera carries a tag or sits in an area."""
    store = ProfileStore(MemoryBackend(), get_entity_area=lambda e: "master_bedroom")
    store.set(
        "camera.bedroom",
        profile(
            "camera.bedroom",
            {"metadata_origin": {"source": "user"}, "semantic_tags": ["presence.sleep_tracking"]},
            {
                "level": "restricted",
                "deny_response_mode": "omit",
                "access_roles": {"deny_for": ["guest"]},
            },
        ),
    )
    registry = DictToolRegistry()
    register_mesa_tools(store, adapter=registry, caller_context_fn=lambda: GUEST)
    for probe in ({"tags": ["presence.sleep_tracking"]}, {"areas": ["master_bedroom"]}):
        out = asyncio.run(registry.call("mesa_query_profiles", probe))
        assert out["total_matched"] == 0, (probe, out["total_matched"])


# --- P1/P2: inferred helper profiles and cascade caution (Spec 5.4 Rule 9, 6.1) -------


def test_inferred_helper_cannot_assert_deployment_defined() -> None:
    """deployment_defined without affected_automations MUST be treated as none
    (Spec 6.1), and an inferred helper MUST NOT assert none (Rule 9)."""
    store = ProfileStore(MemoryBackend())
    store.set(
        "input_boolean.guest_mode",
        profile(
            "input_boolean.guest_mode",
            {
                "metadata_origin": INFERRED,
                "operational_boundaries": {"triggers_automations": "deployment_defined"},
            },
        ),
    )
    effective = store.get_effective("input_boolean.guest_mode")
    assert effective.operational_boundaries.triggers_automations.value == "likely"


def test_cross_check_covers_deployment_defined_without_affected_automations() -> None:
    store = ProfileStore(MemoryBackend())
    store.set(
        "input_boolean.away",
        profile(
            "input_boolean.away",
            {
                "metadata_origin": {"source": "user"},
                "operational_boundaries": {"triggers_automations": "deployment_defined"},
            },
        ),
    )
    configs = [
        {"id": "arrive", "trigger": [{"platform": "state", "entity_id": "input_boolean.away"}]}
    ]
    assert TriggerValidator(store).validate(lambda: configs), (
        "an equivalent-to-none declaration went unchecked"
    )


# --- P2: freshness and timestamp validation (Spec 5.2 to 5.4) ------------------------


def test_future_generated_at_does_not_report_current() -> None:
    p = profile(
        "light.x", {"metadata_origin": {**INFERRED, "generated_at": "2099-01-01T00:00:00+00:00"}}
    )
    assert p.staleness_status() != "current"


def test_generated_at_must_be_an_iso_8601_timestamp() -> None:
    doc = {"semantic_profile": {"metadata_origin": {**INFERRED, "generated_at": "not a date"}}}
    assert validate_document(doc).errors


# --- P2: enforcement consistency (Spec 4) ---------------------------------------------


def test_advisory_non_interactive_confirm_is_not_stricter_than_prohibited() -> None:
    """Spec 4: with no interaction channel, confirm is treated AS prohibited.
    Observed in advisory mode: confirm denied, prohibited allowed."""
    store = ProfileStore(MemoryBackend())
    for eid, mode in (("light.c", "confirm"), ("light.p", "prohibited")):
        store.set(
            eid,
            profile(
                eid,
                {
                    "metadata_origin": {"source": "user"},
                    "operational_boundaries": {"control_mode": mode},
                },
            ),
        )
    enforcer = MesaEnforcer(store, mode="advisory", interactive=False)
    confirm = enforcer.evaluate("light.c", "light.turn_on", {}, ADMIN).allowed
    prohibited = enforcer.evaluate("light.p", "light.turn_on", {}, ADMIN).allowed
    assert confirm == prohibited


# --- P2: error contracts and storage ---------------------------------------------------


def test_sidecar_with_oversized_integer_raises_the_documented_error(tmp_path: Path) -> None:
    (tmp_path / "integ").mkdir()
    (tmp_path / "integ" / "mesa_profile.json").write_text(
        '{"semantic_profile": {"metadata_origin": {"source": "user"}, "x_big": ' + "9" * 5000 + "}}"
    )
    with pytest.raises(MesaValidationError):
        import_from_integration(tmp_path / "integ")


def test_json_backend_lists_only_keys_it_can_read(tmp_path: Path) -> None:
    (tmp_path / "light%2Ex.json").write_text(
        json.dumps(
            {
                "semantic_profile": {
                    "metadata_origin": {"source": "user"},
                    "operational_boundaries": {"control_mode": "prohibited"},
                }
            }
        )
    )
    backend = JsonFileBackend(tmp_path)
    for key in backend.list_keys():
        assert backend.read(key) is not None, f"listed key {key!r} is unreadable"


def test_sqlite_backend_closes_its_connections(tmp_path: Path) -> None:
    """Python 3.13+ emits ResourceWarning for an unclosed sqlite3 connection."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        backend = SqliteBackend(tmp_path / "p.db")
        backend.write("light.a", {"x": 1})
        backend.read("light.a")
        backend.list_keys()
        gc.collect()
    assert not [w for w in caught if issubclass(w.category, ResourceWarning)]


def test_sqlite_prefix_listing_matches_the_other_backends(tmp_path: Path) -> None:
    sqlite, memory = SqliteBackend(tmp_path / "p.db"), MemoryBackend()
    for backend in (sqlite, memory):
        backend.write("__DOMAIN__:shout", {"x": 1})
    assert sqlite.list_keys("__domain__:") == memory.list_keys("__domain__:")


# --- P2/P3: mesa-lint input handling -------------------------------------------------


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")

# --- Leases (Enrichment 11 and 21.5) -----------------------------------------------------


def automation_store(
    cooperative_priority: Any, *, entity_override: Any = "__absent__"
) -> ProfileStore:
    """automation.guard monitors lock.front; optionally a domain profile carries the priority."""
    store = ProfileStore(MemoryBackend())
    sp: dict[str, Any] = {
        "metadata_origin": {"source": "user"},
        "environmental_dependencies": {"trigger_entities": ["lock.front"]},
    }
    if entity_override == "__absent__":
        sp["cooperative_priority"] = cooperative_priority
    else:
        store.set_domain_profile(
            "automation",
            profile(
                "automation",
                {
                    "metadata_origin": {"source": "user"},
                    "inheritance_scope": "domain",
                    "cooperative_priority": cooperative_priority,
                },
            ),
        )
        sp["cooperative_priority"] = entity_override
    store.set("automation.guard", profile("automation.guard", sp))
    return store


@pytest.mark.parametrize("priority", [{}, {"level": None}, {"levl": "critical"}])
def test_lease_check_fails_closed_on_a_missing_priority_level(priority: dict[str, Any]) -> None:
    """Enrichment 11.2: level is REQUIRED. A misspelled level VALUE already fails
    closed; a missing or misspelled KEY grants the lease with no warning."""
    response = LeaseManager(automation_store(priority)).request(
        ["lock.front"], 10, session_id="a", now=T0
    )
    assert not response.granted


def test_entity_null_priority_cannot_erase_an_inherited_critical_level() -> None:
    store = automation_store({"level": "critical"}, entity_override=None)
    response = LeaseManager(store).request(["lock.front"], 10, session_id="a", now=T0)
    assert not response.granted


@pytest.mark.parametrize("state", [True, "ON", b"on", {"state": "on"}])
def test_lease_get_state_unusable_value_fails_closed(state: Any) -> None:
    """A protected automation whose state cannot be read as 'on'/'off' must count
    as active, as None/'unavailable'/'unknown' already do (CHANGELOG 1.2.1)."""
    manager = LeaseManager(automation_store({"level": "protected"}), get_state=lambda e: state)
    assert not manager.request(["lock.front"], 10, session_id="a", now=T0).granted


def test_lease_tools_without_caller_context_do_not_share_one_session() -> None:
    """Spec 9.4: session_id is REQUIRED and scopes leases. Without caller context,
    every caller shares session '' and silently takes over the other's lease."""
    registry = DictToolRegistry()
    register_mesa_tools(
        ProfileStore(MemoryBackend()), adapter=registry, lease_manager=LeaseManager()
    )
    first = asyncio.run(
        registry.call(
            "mesa_request_lease", {"entities": ["climate.living"], "duration_seconds": 30}
        )
    )
    second = asyncio.run(
        registry.call(
            "mesa_request_lease", {"entities": ["climate.living"], "duration_seconds": 30}
        )
    )
    assert first.get("error") == "invalid_query"
    assert second.get("granted") is not True, second


def test_session_teardown_survives_a_failing_audit_handler() -> None:
    class Boom(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise RuntimeError("audit sink down")

    manager = LeaseManager()
    for i in range(5):
        manager.request([f"light.y{i}"], 30, session_id="doomed", now=T0)
    audit = logging.getLogger("mesa_core.audit")
    handler, old_level = Boom(), audit.level
    old_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    audit.addHandler(handler)
    audit.setLevel(logging.INFO)
    try:
        manager.release_session("doomed", now=T0)
    finally:
        audit.removeHandler(handler)
        audit.setLevel(old_level)
        logging.disable(old_disable)
    assert manager.active_leases(T0) == []


def test_lease_denial_does_not_reveal_an_automation_the_caller_cannot_read() -> None:
    store = automation_store({"level": "critical"})
    guard = store.get("automation.guard")
    assert guard is not None
    doc = guard.to_dict()
    doc["privacy_classification"] = {
        "level": "sensitive",
        "deny_response_mode": "omit",
        "access_roles": {"deny_for": ["guest"]},
    }
    store.set("automation.guard", SemanticProfile.from_dict("automation.guard", doc))
    registry = DictToolRegistry()
    register_mesa_tools(
        store, adapter=registry, lease_manager=LeaseManager(store), caller_context_fn=lambda: GUEST
    )
    out = asyncio.run(
        registry.call("mesa_request_lease", {"entities": ["lock.front"], "duration_seconds": 10})
    )
    assert out["error"] == "lease_conflict"
    assert out["details"]["granted_duration_seconds"] == 0
    assert out["details"]["entities_denied"] == ["lock.front"]
    assert "automation.guard" not in json.dumps(out)


# --- The documented service tool (examples/ha_service_tool.py, Module 6.2) ------------


def run_tool(store: ProfileStore, **call: Any) -> list[tuple[str, str, dict[str, Any]]]:
    forwarded: list[tuple[str, str, dict[str, Any]]] = []

    async def perform(domain: str, service: str, data: dict[str, Any]) -> str:
        forwarded.append((domain, service, data))
        return "done"

    tool = build_call_ha_service(MesaEnforcer(store, mode="enforced"), lambda: ADMIN, perform)
    with contextlib.suppress(MesaEnforcementError):
        asyncio.run(tool(**call))
    return forwarded


def test_service_tool_canonicalises_before_evaluating() -> None:
    """Spec 6: hosts MUST canonicalise before evaluation; Home Assistant lower-cases
    domains, services and entity IDs, so 'Light'/'Turn_On' executes as light.turn_on."""
    store = ProfileStore(MemoryBackend())
    store.set(
        "light.kitchen",
        profile(
            "light.kitchen",
            {
                "metadata_origin": {"source": "user"},
                "operational_boundaries": {
                    "control_mode": "autonomous",
                    "declared_limits": [
                        {
                            "id": "night_cap",
                            "predicate": {
                                "entity": "input_boolean.night",
                                "operator": "eq",
                                "value": True,
                            },
                            "limit": {
                                "service": "light.turn_on",
                                "parameter": "brightness",
                                "max_value": 10,
                            },
                        }
                    ],
                },
            },
        ),
    )
    assert (
        run_tool(
            store,
            domain="light",
            service="turn_on",
            entity_id="light.kitchen",
            service_data={"brightness": 255},
        )
        == []
    )
    assert (
        run_tool(
            store,
            domain="Light",
            service="Turn_On",
            entity_id="light.kitchen",
            service_data={"brightness": 255},
        )
        == []
    )


def test_service_tool_binds_the_service_to_the_evaluated_entity() -> None:
    """script.* has a confirm baseline (Spec 5.8); naming an autonomous light as the
    'entity' must not let the script run unconfirmed."""
    forwarded = run_tool(
        ProfileStore(MemoryBackend()),
        domain="script",
        service="open_garage",
        entity_id="light.kitchen",
    )
    assert forwarded == [], forwarded


# --- Privacy and retrieval ----------------------------------------------------------------


def test_entity_access_roles_cannot_erase_an_inherited_deny_for() -> None:
    """Spec 7: where classifications conflict between levels, the more restrictive
    MUST take precedence. Observed: access_roles is replaced wholesale (Rule D)."""
    store = ProfileStore(MemoryBackend())
    store.set_domain_profile(
        "camera",
        profile(
            "camera",
            {"metadata_origin": {"source": "developer"}, "inheritance_scope": "domain"},
            {"level": "sensitive", "access_roles": {"deny_for": ["guest"]}},
        ),
    )
    store.set(
        "camera.porch",
        profile(
            "camera.porch",
            {
                "metadata_origin": {"source": "user"},
                "operational_boundaries": {"control_mode": "autonomous"},
            },
            {"level": "sensitive", "access_roles": {"restricted_for": ["caregiver"]}},
        ),
    )
    result = MesaEnforcer(store).evaluate("camera.porch", "camera.turn_on", {}, GUEST)
    assert result.rule_applied == "privacy:deny_for", (result.allowed, result.rule_applied)


def test_bare_string_roles_cannot_bypass_deny_for() -> None:
    store = ProfileStore(MemoryBackend())
    store.set(
        "camera.nursery",
        profile(
            "camera.nursery",
            {
                "metadata_origin": {"source": "user"},
                "operational_boundaries": {"control_mode": "autonomous"},
            },
            {"level": "sensitive", "access_roles": {"deny_for": ["guest"]}},
        ),
    )
    caller = CallerContext(caller_id="g", roles="guest", is_authenticated=True, session_id="s")  # type: ignore[arg-type]
    result = MesaEnforcer(store).evaluate("camera.nursery", "camera.turn_on", {}, caller)
    assert result.rule_applied == "privacy:deny_for", (result.allowed, result.rule_applied)


def hidden_camera_registry() -> DictToolRegistry:
    store = ProfileStore(MemoryBackend())
    store.set(
        "camera.nursery",
        profile(
            "camera.nursery",
            {"metadata_origin": {"source": "user"}},
            {
                "level": "restricted",
                "deny_response_mode": "omit",
                "access_roles": {"deny_for": ["guest"]},
            },
        ),
    )
    store.set_area_profile(
        "nursery",
        profile(
            "nursery",
            {"metadata_origin": {"source": "user"}, "inheritance_scope": "area"},
            {"level": "sensitive"},
        ),
    )
    registry = DictToolRegistry()
    register_mesa_tools(store, adapter=registry, caller_context_fn=lambda: GUEST)
    return registry


def test_explain_does_not_reveal_which_hidden_entities_exist() -> None:
    registry = hidden_camera_registry()
    hidden = asyncio.run(registry.call("mesa_explain_profile", {"entity_id": "camera.nursery"}))
    missing = asyncio.run(registry.call("mesa_explain_profile", {"entity_id": "camera.ghost"}))
    assert ("error" in hidden) == ("error" in missing), (hidden, sorted(missing))


def test_reserved_store_keys_are_not_retrievable_as_entities() -> None:
    out = asyncio.run(
        hidden_camera_registry().call("mesa_get_profile", {"entity_id": "__area__:nursery"})
    )
    assert "error" in out, out


def test_cursor_from_one_query_is_rejected_by_another() -> None:
    store = ProfileStore(MemoryBackend())
    for eid in [f"light.l{i}" for i in range(5)] + [f"switch.s{i}" for i in range(4)]:
        store.set(eid, profile(eid, {"metadata_origin": {"source": "user"}}))
    registry = DictToolRegistry()
    register_mesa_tools(store, adapter=registry)
    first = asyncio.run(registry.call("mesa_query_profiles", {"domains": ["light"], "limit": 2}))
    reused = asyncio.run(
        registry.call(
            "mesa_query_profiles",
            {"domains": ["switch"], "limit": 2, "cursor": first["pagination"]["next_cursor"]},
        )
    )
    assert reused.get("error") == "invalid_cursor", [
        r["entity_id"] for r in reused.get("results", [])
    ]


def test_audit_events_reach_a_handler_attached_as_documented() -> None:
    """Module 4.11: 'Hosts attach a logging handler'. Spec 7.1: implementations MUST
    log the required events. Under Python's default configuration they are dropped."""
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    audit, root = logging.getLogger("mesa_core.audit"), logging.getLogger()
    handler, old_root, old_audit = Capture(), root.level, audit.level
    logging.disable(logging.NOTSET)
    root.setLevel(logging.WARNING)
    audit.setLevel(logging.NOTSET)
    audit.addHandler(handler)
    try:
        MesaEnforcer(ProfileStore(MemoryBackend())).evaluate(
            "lock.front_door", "lock.unlock", {}, ADMIN
        )
    finally:
        audit.removeHandler(handler)
        root.setLevel(old_root)
        audit.setLevel(old_audit)
        logging.disable(logging.NOTSET)
    assert records, "the blocked lock call produced no audit record"


# --- Storage, resolution wiring and import (Spec 5.6, 5.7, 7, Module 4.2, 4.12) ---------


def test_enforcer_uses_the_resolver_attached_to_its_store() -> None:
    """Module 4.2 documents attach_resolver(); store.get_effective then reports the
    area prohibition, but MesaEnforcer(store) builds its own resolver and allows."""
    store = ProfileStore(MemoryBackend())
    store.attach_resolver(InheritanceResolver(store=store, get_entity_area=lambda e: "nursery"))
    store.set_area_profile(
        "nursery",
        profile(
            "nursery",
            {
                "metadata_origin": {"source": "user"},
                "inheritance_scope": "area",
                "operational_boundaries": {"control_mode": "prohibited"},
            },
        ),
    )
    store.set(
        "camera.nursery",
        profile(
            "camera.nursery",
            {
                "metadata_origin": {"source": "user"},
                "operational_boundaries": {"control_mode": "autonomous"},
            },
        ),
    )
    assert control_mode(store, "camera.nursery") == "prohibited"
    result = MesaEnforcer(store).evaluate("camera.nursery", "camera.turn_on", {}, ADMIN)
    assert result.rule_applied == "control_mode:prohibited", (result.allowed, result.rule_applied)


def test_rule_b_inferred_none_cannot_override_a_trusted_declaration() -> None:
    """Spec 5.6: inferred_ai and unknown profiles never override trusted-tier
    declarations regardless of level. 'none' lets agents skip cascade reasoning."""
    store = ProfileStore(MemoryBackend())
    store.set_domain_profile(
        "switch",
        profile(
            "switch",
            {
                "metadata_origin": {"source": "developer"},
                "inheritance_scope": "domain",
                "operational_boundaries": {"triggers_automations": "unknown"},
            },
        ),
    )
    store.set(
        "switch.pump",
        profile(
            "switch.pump",
            {
                "metadata_origin": INFERRED,
                "operational_boundaries": {"triggers_automations": "none"},
            },
        ),
    )
    assert (
        store.get_effective("switch.pump").operational_boundaries.triggers_automations.value
        == "unknown"
    )


def test_inferred_deny_response_mode_cannot_reveal_a_hidden_entity() -> None:
    """Spec 5.4 Rule 3: unconfirmed inferred values MUST NOT drive access decisions.
    An inferred 'error' turns the trusted 'omit' (not_found) into forbidden."""
    store = ProfileStore(MemoryBackend())
    store.set_domain_profile(
        "camera",
        profile(
            "camera",
            {"metadata_origin": {"source": "developer"}, "inheritance_scope": "domain"},
            {"level": "sensitive", "access_roles": {"deny_for": ["guest"]}},
        ),
    )
    store.set(
        "camera.yard",
        profile(
            "camera.yard",
            {"metadata_origin": INFERRED},
            {"level": "sensitive", "deny_response_mode": "error"},
        ),
    )
    registry = DictToolRegistry()
    register_mesa_tools(store, adapter=registry, caller_context_fn=lambda: GUEST)
    out = asyncio.run(registry.call("mesa_get_profile", {"entity_id": "camera.yard"}))
    assert out.get("error") == "not_found", out


def test_entity_api_cannot_overwrite_the_deployment_defaults() -> None:
    store = ProfileStore(MemoryBackend())
    store.set_deployment_defaults({"default_control_mode": "prohibited"})
    # Rejecting the reserved key is the fix; the assertion checks the defaults survive.
    with contextlib.suppress(Exception):
        store.set("__deployment_defaults__", profile("x", {"metadata_origin": {"source": "user"}}))
    defaults = store.get_deployment_defaults()
    assert defaults is not None and defaults.default_control_mode.value == "prohibited"


def test_one_corrupt_document_does_not_abort_an_unrelated_query(tmp_path: Path) -> None:
    store = ProfileStore(JsonFileBackend(tmp_path))
    store.set("light.a", profile("light.a", {"metadata_origin": {"source": "user"}}))
    (tmp_path / "switch.c.json").write_text('{"semantic_profile": {"x')
    result = store.query(domains=["light"])
    assert [row.entity_id for row in result.rows] == ["light.a"]


def test_import_quarantines_any_bad_document_instead_of_aborting() -> None:
    """Module 4.12: failures are quarantined in ImportResult.invalid and never written."""

    def doc() -> dict[str, Any]:
        return {
            "semantic_profile": {
                "metadata_origin": {"source": "user"},
                "operational_boundaries": {"control_mode": "autonomous"},
            }
        }

    deep: Any = 1
    for _ in range(3000):
        deep = [deep]
    bad = doc()
    bad["semantic_profile"]["x_vendor"] = deep
    store = ProfileStore(MemoryBackend())
    archive = {
        "mesa_export": {
            "format_version": "1.1",
            "entities": {"light.a": doc(), "light.b": bad, "light.c": doc()},
        }
    }
    result = import_profiles(store, archive)
    assert "light.c" in store.entity_keys() and result.invalid, (store.entity_keys(), result)


# --- Validation and persistence (Spec 4, 5.2 to 5.3, 6.4, 6.5, 23) ------------------------


def test_read_modify_write_tightening_to_confirm_persists() -> None:
    """Spec 4: an operator may always tighten. get, set control_mode=CONFIRM, set
    stores nothing because to_dict() omits default-valued fields unless declared."""
    store = ProfileStore(MemoryBackend(), get_entity_integration=lambda e: "hue")
    store.set_integration_profile(
        "hue",
        profile(
            "hue",
            {
                "metadata_origin": {"source": "developer"},
                "inheritance_scope": "integration",
                "operational_boundaries": {"control_mode": "autonomous"},
            },
        ),
    )
    store.set(
        "light.x",
        profile(
            "light.x",
            {"metadata_origin": {"source": "user"}, "semantic_tags": ["lighting.ambient"]},
        ),
    )
    edited = store.get("light.x")
    assert edited is not None
    edited.operational_boundaries.control_mode = ControlMode.CONFIRM
    store.set("light.x", edited)
    assert control_mode(store, "light.x") == "confirm"


def test_declared_limit_without_a_bound_is_rejected() -> None:
    """A limit whose bound key is misspelt constrains nothing; temporal effects
    already reject the same shape."""
    doc = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "operational_boundaries": {
                "declared_limits": [
                    {
                        "id": "cap",
                        "predicate": {"entity": "input_boolean.n", "operator": "eq", "value": True},
                        "limit": {
                            "service": "light.turn_on",
                            "parameter": "brightness",
                            "max_valeu": 10,
                        },
                    }
                ]
            },
        }
    }
    assert validate_document(doc).errors


def test_hhmm_rejects_a_trailing_newline() -> None:
    doc = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "operational_boundaries": {
                "temporal_constraints": [
                    {
                        "id": "q",
                        "condition": {
                            "type": "time_range",
                            "start_time": "08:00\n",
                            "end_time": "09:00",
                        },
                        "effect": {"control_mode": "prohibited"},
                    }
                ]
            },
        }
    }
    assert validate_document(doc).errors


@pytest.mark.parametrize(
    "doc",
    [
        {"semantic_profile": {"metadata_origin": {"source": "user", "last_updated": 5}}},
        {
            "semantic_profile": {
                "metadata_origin": {"source": "user", "staleness_window_days": float("inf")}
            }
        },
    ],
    ids=["origin_last_updated", "non_finite_number"],
)
def test_validator_and_canonical_schema_agree(doc: dict[str, Any]) -> None:
    """memory/validator-schema-agreement.md: divergent structural acceptance is a defect."""
    schema_ok = not list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(doc))
    assert (not validate_document(doc).errors) == schema_ok
