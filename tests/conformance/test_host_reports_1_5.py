"""Regressions for the host integration report fixed in mesa-core 1.5.0."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from mesa_core import HA_TARGET_SELECTOR_KEYS
from mesa_core.backends import MemoryBackend
from mesa_core.enforcer import MesaEnforcer
from mesa_core.exceptions import MesaError
from mesa_core.inheritance import InheritanceResolver
from mesa_core.lease import LeaseManager
from mesa_core.mcp.tools import MesaToolHandlers
from mesa_core.privacy import CallerContext
from mesa_core.profile import HA_AUTOMATION_SELECTOR_KEYS, SemanticProfile
from mesa_core.store import ProfileStore
from mesa_core.trigger_validator import entities_by_role
from mesa_core.validation import validate_document

ALWAYS = {"entity": "light.x", "operator": "eq", "value": "on"}


def _profile(entity_id: str, boundaries: dict[str, Any], **body: Any) -> SemanticProfile:
    return SemanticProfile.from_dict(
        entity_id,
        {
            "semantic_profile": {
                "metadata_origin": {"source": "user"},
                "operational_boundaries": boundaries,
                **body,
            }
        },
    )


def _limit(**spec: Any) -> dict[str, Any]:
    return {
        "id": "cap",
        "predicate": ALWAYS,
        "limit": {
            "service": "light.turn_on",
            "parameter": "brightness",
            "max_value": 100,
            **spec,
        },
        "human_reason": "night cap",
    }


def _enforcer(
    limit: dict[str, Any] | None = None, mode: str = "enforced", control: str = "autonomous"
) -> MesaEnforcer:
    store = ProfileStore(MemoryBackend())
    boundaries: dict[str, Any] = {"control_mode": control, "enforcement_mode": mode}
    if limit is not None:
        boundaries["declared_limits"] = [limit]
    store.set("light.x", _profile("light.x", boundaries))
    return MesaEnforcer(store=store, mode=mode, get_state=lambda _: "on")


@pytest.fixture
def audit_events() -> Iterator[list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            event = getattr(record, "mesa_audit_event", None)
            if event is not None:
                events.append(event)

    handler = Collect()
    audit = logging.getLogger("mesa_core.audit")
    audit.addHandler(handler)
    yield events
    audit.removeHandler(handler)


# --------------- limits on an absent parameter


def test_an_absent_parameter_passes_by_default() -> None:
    result = _enforcer(_limit()).evaluate("light.x", "light.turn_on", {})
    assert result.allowed


@pytest.mark.parametrize("params", [{}, {"brightness_pct": 100}, {"flash": "long"}])
def test_when_absent_refuse_blocks_a_call_without_the_parameter(params: dict[str, Any]) -> None:
    result = _enforcer(_limit(when_absent="refuse")).evaluate("light.x", "light.turn_on", params)
    assert not result.allowed
    assert result.rule_applied == "declared_limit:cap"
    assert "brightness is absent" in result.reason
    assert "night cap" in result.reason


def test_when_absent_refuse_issues_no_challenge() -> None:
    enforcer = _enforcer(_limit(when_absent="refuse"), control="confirm")
    result = enforcer.evaluate("light.x", "light.turn_on", {})
    assert result.rule_applied == "declared_limit:cap"
    assert result.confirmation_challenge is None


def test_when_absent_refuse_still_measures_a_supplied_value() -> None:
    enforcer = _enforcer(_limit(when_absent="refuse"))
    assert enforcer.evaluate("light.x", "light.turn_on", {"brightness": 50}).allowed
    over = enforcer.evaluate("light.x", "light.turn_on", {"brightness": 255})
    assert over.rule_applied == "declared_limit:cap"


def test_when_absent_refuse_binds_only_its_own_service() -> None:
    enforcer = _enforcer(_limit(when_absent="refuse"))
    assert enforcer.evaluate("light.x", "light.turn_off", {}).allowed


def test_when_absent_refuse_respects_a_false_predicate() -> None:
    limit = _limit(when_absent="refuse")
    limit["predicate"] = {"entity": "light.x", "operator": "eq", "value": "off"}
    assert _enforcer(limit).evaluate("light.x", "light.turn_on", {}).allowed


def test_when_absent_refuse_only_warns_in_advisory_mode() -> None:
    enforcer = _enforcer(_limit(when_absent="refuse"), mode="advisory")
    result = enforcer.evaluate("light.x", "light.turn_on", {})
    assert result.allowed
    assert any("brightness is absent" in warning for warning in result.warnings)


def test_a_malformed_when_absent_fails_closed_at_enforcement() -> None:
    # The validator rejects this, but enforcement must not depend on it.
    enforcer = _enforcer()
    spec = {"service": "light.turn_on", "parameter": "brightness", "when_absent": "bogus"}
    assert enforcer._check_limit({"limit": spec}, "light.turn_on", {}) is not None


def test_when_absent_survives_inheritance() -> None:
    store = ProfileStore(MemoryBackend())
    store.set_domain_profile(
        "light",
        _profile(
            "light",
            {
                "control_mode": "autonomous",
                "enforcement_mode": "enforced",
                "declared_limits": [_limit(when_absent="refuse")],
            },
        ),
    )
    enforcer = MesaEnforcer(store=store, mode="enforced", get_state=lambda _: "on")
    assert enforcer.evaluate("light.y", "light.turn_on", {}).rule_applied == "declared_limit:cap"


def test_a_temporal_effect_carries_when_absent() -> None:
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    store = ProfileStore(MemoryBackend())
    store.set(
        "light.x",
        _profile(
            "light.x",
            {
                "control_mode": "autonomous",
                "enforcement_mode": "enforced",
                "temporal_constraints": [
                    {
                        "id": "night",
                        "condition": {"type": "day_of_week", "days": days},
                        "effect": {
                            "service": "light.turn_on",
                            "parameter": "brightness",
                            "max_value": 100,
                            "when_absent": "refuse",
                        },
                    }
                ],
            },
        ),
    )
    result = MesaEnforcer(store=store, mode="enforced").evaluate("light.x", "light.turn_on", {})
    assert result.rule_applied == "declared_limit:night"


def test_when_absent_is_validated() -> None:
    def document(spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "semantic_profile": {"operational_boundaries": {"declared_limits": [_limit(**spec)]}}
        }

    assert validate_document(document({"when_absent": "refuse"})).ok
    assert validate_document(document({"when_absent": "allow"})).ok
    assert not validate_document(document({"when_absent": "bogus"})).ok


# --------------- exclude blocks


def test_the_shared_keys_place_exclude_on_service_calls_only() -> None:
    assert "exclude" in HA_TARGET_SELECTOR_KEYS
    assert "exclude" not in HA_AUTOMATION_SELECTOR_KEYS


@pytest.mark.parametrize(
    "params",
    [
        {"exclude": {"entity_id": "light.y"}},
        {"target": {"exclude": {"entity_id": "light.y"}}},
        {"target": {"entity_id": "light.x", "exclude": {"area_id": "kitchen"}}},
    ],
)
def test_an_exclude_block_is_refused(params: dict[str, Any]) -> None:
    result = _enforcer(control="confirm").evaluate("light.x", "light.turn_on", params)
    assert not result.allowed
    assert result.rule_applied == "contradictory_target"
    assert "exclude block" in result.reason
    assert result.confirmation_challenge is None


def test_an_excluded_entity_is_not_an_automation_reference() -> None:
    config = {
        "triggers": [
            {
                "trigger": "state",
                "target": {"area_id": "kitchen", "exclude": {"entity_id": "light.out"}},
            }
        ],
        "actions": [
            {"action": "light.turn_on", "target": {"device_id": "d1", "exclude": {"area_id": "a"}}}
        ],
    }
    calls: list[tuple[str, str]] = []

    def expand(kind: str, ref: str) -> list[str]:
        calls.append((kind, ref))
        return [f"light.{ref}"]

    references = entities_by_role(config, expand)
    assert references["trigger"] == {"light.kitchen"}
    assert references["action"] == {"light.d1"}
    assert sorted(calls) == [("area_id", "kitchen"), ("device_id", "d1")]


def test_a_data_field_named_exclude_is_still_walked() -> None:
    config = {"actions": [{"data": {"exclude": {"entity_id": "light.named"}}}]}
    assert entities_by_role(config)["action"] == {"light.named"}


# --------------- non-mapping targets


@pytest.mark.parametrize(
    "target",
    ["kitchen", "mobile_app_phone", ["+15551234", "+15555678"], 7, None, True],
)
def test_a_plain_target_is_service_data(target: Any) -> None:
    result = _enforcer().evaluate("light.x", "light.turn_on", {"target": target})
    assert result.allowed
    assert result.rule_applied is None


@pytest.mark.parametrize(
    "target",
    [
        "{{ area_entities('kitchen') }}",
        "{% if x %}a{% endif %}",
        ["kitchen", "{{ x }}"],
        [{"entity_id": "lock.front_door"}],
        [{"entity_id": "light.x"}],
        [["nested"]],
        ("a", "b"),
    ],
)
def test_a_target_that_could_resolve_is_refused(target: Any) -> None:
    result = _enforcer(control="confirm").evaluate("light.x", "light.turn_on", {"target": target})
    assert not result.allowed
    assert result.rule_applied == "contradictory_target"
    assert result.confirmation_challenge is None


def test_a_target_block_is_still_checked() -> None:
    result = _enforcer().evaluate("light.x", "light.turn_on", {"target": {"area_id": "kitchen"}})
    assert result.rule_applied == "contradictory_target"


def test_a_limit_can_constrain_a_plain_target() -> None:
    limit = {
        "id": "recipients",
        "predicate": ALWAYS,
        "limit": {
            "service": "light.turn_on",
            "parameter": "target",
            "permitted_values": ["alice"],
        },
    }
    enforcer = _enforcer(limit)
    assert enforcer.evaluate("light.x", "light.turn_on", {"target": "alice"}).allowed
    refused = enforcer.evaluate("light.x", "light.turn_on", {"target": "mallory"})
    assert refused.rule_applied == "declared_limit:recipients"


def test_a_challenge_binds_a_plain_target() -> None:
    enforcer = _enforcer(control="confirm")
    challenge = enforcer.evaluate(
        "light.x", "light.turn_on", {"target": "alice"}
    ).confirmation_challenge
    assert challenge is not None
    assert challenge["parameters"]["target"] == "alice"


# --------------- lease store rule and scrub


class ScopedView:
    """A per-caller view that neither lists nor returns what it hides."""

    def __init__(self, inner: ProfileStore, hidden: set[str]) -> None:
        self._inner = inner
        self._hidden = hidden

    def entity_keys(self) -> list[str]:
        return [key for key in self._inner.entity_keys() if key not in self._hidden]

    def get(self, entity_id: str) -> SemanticProfile | None:
        return None if entity_id in self._hidden else self._inner.get(entity_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


HIDDEN = "automation.secret_guard"
CALLER = CallerContext(caller_id="agent", session_id="s1")


def _lease_store(level: str, extra: dict[str, Any] | None = None) -> ProfileStore:
    store = ProfileStore(MemoryBackend())
    store.set("light.x", _profile("light.x", {"control_mode": "autonomous"}))
    store.set("light.free", _profile("light.free", {"control_mode": "autonomous"}))
    store.set(
        HIDDEN,
        _profile(
            HIDDEN,
            {"control_mode": "autonomous"},
            cooperative_priority={"level": level},
            environmental_dependencies={"trigger_entities": ["light.x"]},
            **(extra or {}),
        ),
    )
    return store


def _scoped_handlers(store: ProfileStore) -> MesaToolHandlers:
    view: Any = ScopedView(store, {HIDDEN})
    return MesaToolHandlers(
        store=view,
        resolver=InheritanceResolver(store=view),
        caller_context_fn=lambda: CALLER,
        lease_manager=LeaseManager(store=store),
        store_is_scoped_view=True,
    )


def _request(handlers: MesaToolHandlers, *entities: str) -> dict[str, Any]:
    return asyncio.run(
        handlers.mesa_request_lease({"entities": list(entities), "duration_seconds": 10})
    )


def test_handlers_refuse_a_lease_manager_on_another_store() -> None:
    other = ProfileStore(MemoryBackend())
    with pytest.raises(MesaError, match="must use the registered profile store"):
        MesaToolHandlers(ProfileStore(MemoryBackend()), lease_manager=LeaseManager(other))


def test_handlers_accept_a_declared_scoped_view() -> None:
    store = _lease_store("critical")
    assert _scoped_handlers(store).lease_manager is not None


def test_handlers_accept_a_manager_with_no_store() -> None:
    MesaToolHandlers(ProfileStore(MemoryBackend()), lease_manager=LeaseManager())


def test_a_scoped_store_hides_a_critical_automation_on_total_denial() -> None:
    response = _request(_scoped_handlers(_lease_store("critical")), "light.x")
    assert response["error"] == "lease_conflict"
    assert HIDDEN not in str(response)
    assert response["details"]["denial_reasons"] == {
        "light.x": "entity is protected by automation policy"
    }


def test_a_scoped_store_hides_a_protected_automation_on_partial_denial() -> None:
    response = _request(_scoped_handlers(_lease_store("protected")), "light.x", "light.free")
    assert response["entities_granted"] == ["light.free"]
    assert HIDDEN not in str(response)


def test_a_scoped_store_hides_an_assertive_automation_conflict_and_warning() -> None:
    response = _request(_scoped_handlers(_lease_store("assertive")), "light.x")
    assert response["granted"] is True
    assert HIDDEN not in str(response)


def test_a_scoped_store_hides_a_malformed_automation_warning() -> None:
    store = _lease_store("critical", {"intent_archetype": "not an object"})
    assert HIDDEN not in str(_request(_scoped_handlers(store), "light.x"))


def test_a_visible_automation_is_still_named() -> None:
    store = _lease_store("critical")
    handlers = MesaToolHandlers(
        store, caller_context_fn=lambda: CALLER, lease_manager=LeaseManager(store)
    )
    assert HIDDEN in str(_request(handlers, "light.x"))


def test_the_consulted_list_is_never_serialized() -> None:
    store = _lease_store("critical")
    response = LeaseManager(store=store).request(["light.x"], 10, session_id="s1")
    assert response.automations_consulted == [HIDDEN]
    assert "automations_consulted" not in response.to_dict()


# --------------- policy_unavailable audit


class FailingBackend(MemoryBackend):
    def read(self, key: str) -> dict[str, Any] | None:
        raise OSError("disk failure")


def _assert_blocked_event(event: dict[str, Any], entity_id: str) -> None:
    assert event["event_type"] == "enforcement_decision"
    assert event["decision"] == "blocked"
    assert event["rule_applied"] == "policy_unavailable"
    assert event["entity_id"] == entity_id
    assert event["action"] == "light.turn_on"


def test_a_failed_resolution_is_audited(audit_events: list[dict[str, Any]]) -> None:
    enforcer = MesaEnforcer(store=ProfileStore(FailingBackend()), mode="enforced")
    caller = CallerContext(caller_id="agent")
    result = enforcer.evaluate("light.x", "light.turn_on", {}, caller_context=caller)
    assert not result.allowed
    assert result.rule_applied == "policy_unavailable"
    assert result.evaluated_control_mode is None
    assert len(audit_events) == 1
    event = audit_events[0]
    _assert_blocked_event(event, "light.x")
    assert event["caller_id"] == "agent"
    assert event["roles"] == caller.effective_roles()
    assert event["details"] == {"cause": "policy_resolution_failed", "error": "OSError"}


def test_a_corrupt_stored_profile_is_audited(audit_events: list[dict[str, Any]]) -> None:
    backend = MemoryBackend(
        {"light.x": {"semantic_profile": {"operational_boundaries": {"control_mode": "bogus"}}}}
    )
    result = MesaEnforcer(store=ProfileStore(backend), mode="enforced").evaluate(
        "light.x", "light.turn_on", {}
    )
    assert result.rule_applied == "policy_unavailable"
    assert len(audit_events) == 1
    _assert_blocked_event(audit_events[0], "light.x")
    assert audit_events[0]["details"]["cause"] == "policy_resolution_failed"


def test_a_malformed_entity_id_is_audited(audit_events: list[dict[str, Any]]) -> None:
    enforcer = MesaEnforcer(store=ProfileStore(MemoryBackend()), mode="enforced")
    result = enforcer.evaluate("not an id", "light.turn_on", {})
    assert result.rule_applied == "policy_unavailable"
    assert len(audit_events) == 1
    _assert_blocked_event(audit_events[0], "not an id")


def test_both_policy_unavailable_paths_are_told_apart(
    audit_events: list[dict[str, Any]],
) -> None:
    enforcer = _enforcer()
    explain = enforcer.resolver.explain

    def corrupted(entity_id: str) -> Any:
        explanation = explain(entity_id)
        explanation.effective_profile.operational_boundaries.control_mode = "bogus"
        return explanation

    enforcer.resolver.explain = corrupted  # type: ignore[method-assign]
    result = enforcer.evaluate("light.x", "light.turn_on", {})
    assert result.rule_applied == "policy_unavailable"
    assert len(audit_events) == 1
    _assert_blocked_event(audit_events[0], "light.x")
    assert audit_events[0]["details"] == {"cause": "unrecognized_control_mode"}
