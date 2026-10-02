"""Public call results retain the restriction actually evaluated by the core."""

from datetime import datetime

import pytest

from mesa_core import (
    CallerContext,
    ControlMode,
    MesaEnforcer,
    MesaError,
    MetadataOrigin,
    ProfileStore,
    SemanticProfile,
)
from mesa_core.backends import MemoryBackend


def profile(boundaries: dict) -> SemanticProfile:
    return SemanticProfile.from_dict(
        "light.test",
        {"semantic_profile": {"operational_boundaries": boundaries}},
        default_origin=MetadataOrigin.USER,
    )


@pytest.mark.parametrize("server_mode", ["advisory", "enforced"])
@pytest.mark.parametrize("control_mode", list(ControlMode))
def test_call_result_reports_control_mode_on_all_decisions(server_mode, control_mode):
    store = ProfileStore(MemoryBackend())
    store.set("light.test", profile({"control_mode": control_mode.value}))
    result = MesaEnforcer(store, mode=server_mode).evaluate("light.test", "light.turn_on")
    assert result.evaluated_control_mode == control_mode
    assert result.allowed == (server_mode == "advisory" or control_mode == ControlMode.AUTONOMOUS)
    if control_mode == ControlMode.CONFIRM and server_mode == "enforced":
        assert result.confirmation_challenge is not None


@pytest.mark.parametrize("server_mode", ["advisory", "enforced"])
@pytest.mark.parametrize(
    "hour, expected", [(12, ControlMode.AUTONOMOUS), (23, ControlMode.READ_ONLY)]
)
def test_inherited_temporal_mode_is_reported_without_mutating_profile(server_mode, hour, expected):
    store = ProfileStore(MemoryBackend())
    store.set_domain_profile(
        "light",
        profile(
            {
                "control_mode": "autonomous",
                "temporal_constraints": [
                    {
                        "id": "night_read_only",
                        "condition": {
                            "type": "time_range",
                            "start_time": "23:00",
                            "end_time": "06:00",
                        },
                        "effect": {"control_mode": "read_only"},
                    }
                ],
            }
        ),
    )
    enforcer = MesaEnforcer(store, mode=server_mode)
    result = enforcer.evaluate(
        "light.test", "light.turn_on", current_time=datetime(2026, 10, 2, hour, 30)
    )
    assert result.evaluated_control_mode == expected
    assert result.allowed == (server_mode == "advisory" or expected == ControlMode.AUTONOMOUS)
    assert result.active_constraint_ids == (["night_read_only"] if hour == 23 else [])
    assert result.effective_profile.operational_boundaries.control_mode == ControlMode.AUTONOMOUS
    assert (
        enforcer.resolver.resolve("light.test").operational_boundaries.control_mode
        == ControlMode.AUTONOMOUS
    )


def test_unevaluable_temporal_restriction_is_reported():
    store = ProfileStore(MemoryBackend())
    store.set(
        "light.test",
        profile(
            {
                "control_mode": "autonomous",
                "temporal_constraints": [
                    {
                        "id": "calendar_read_only",
                        "condition": {
                            "type": "calendar_entity",
                            "calendar_entity": "calendar.missing",
                            "negate": True,
                        },
                        "effect": {"control_mode": "read_only"},
                    }
                ],
            }
        ),
    )
    result = MesaEnforcer(store, mode="advisory").evaluate("light.test", "light.turn_on")
    assert result.allowed
    assert result.evaluated_control_mode == ControlMode.READ_ONLY
    assert result.active_constraint_ids == ["calendar_read_only"]
    assert any("fail-closed" in warning for warning in result.warnings)


@pytest.mark.parametrize("base_mode", ["autonomous", "prohibited", "read_only"])
@pytest.mark.parametrize("effects", [("read_only", "prohibited"), ("prohibited", "read_only")])
def test_temporal_read_only_wins_equally_restrictive_ties(base_mode, effects):
    store = ProfileStore(MemoryBackend())
    store.set(
        "light.test",
        profile(
            {
                "control_mode": base_mode,
                "temporal_constraints": [
                    {
                        "id": mode,
                        "condition": {
                            "type": "time_range",
                            "start_time": "00:00",
                            "end_time": "00:00",
                        },
                        "effect": {"control_mode": mode},
                    }
                    for mode in effects
                ],
            }
        ),
    )
    result = MesaEnforcer(store, mode="advisory").evaluate("light.test", "light.turn_on")
    assert result.allowed
    assert result.evaluated_control_mode == ControlMode.READ_ONLY
    assert result.effective_profile.operational_boundaries.control_mode == ControlMode(base_mode)
    assert result.active_constraint_ids == list(effects)


def test_privacy_adjustment_is_reported_on_allowed_and_confirmed_calls():
    store = ProfileStore(MemoryBackend())
    data = profile({"control_mode": "autonomous"}).to_dict()
    data["privacy_classification"] = {"level": "restricted"}
    store.set("light.test", SemanticProfile.from_dict("light.test", data))
    enforcer = MesaEnforcer(store)
    result = enforcer.evaluate("light.test", "light.turn_on")
    assert not result.allowed
    assert result.evaluated_control_mode == ControlMode.CONFIRM
    assert result.effective_profile.operational_boundaries.control_mode == ControlMode.AUTONOMOUS
    challenge = result.confirmation_challenge
    assert challenge is not None
    approved = enforcer.evaluate(
        "light.test",
        "light.turn_on",
        confirmation_token={
            **challenge,
            "approved_by": "operator",
            "approved_at": datetime.now().isoformat(),
        },
    )
    assert approved.allowed
    assert approved.evaluated_control_mode == ControlMode.CONFIRM


def test_privacy_denial_still_reports_evaluated_temporal_mode():
    store = ProfileStore(MemoryBackend())
    data = profile(
        {
            "control_mode": "autonomous",
            "temporal_constraints": [
                {
                    "id": "read_only",
                    "condition": {"type": "time_range", "start_time": "00:00", "end_time": "00:00"},
                    "effect": {"control_mode": "read_only"},
                }
            ],
        }
    ).to_dict()
    data["privacy_classification"] = {"level": "normal", "access_roles": {"deny_for": ["guest"]}}
    store.set("light.test", SemanticProfile.from_dict("light.test", data))
    result = MesaEnforcer(store).evaluate(
        "light.test",
        "light.turn_on",
        caller_context=CallerContext(caller_id="guest", roles=["guest"], is_authenticated=True),
    )
    assert not result.allowed
    assert result.rule_applied == "privacy:deny_for"
    assert result.evaluated_control_mode == ControlMode.READ_ONLY


def test_limit_refusal_reports_mode_before_control_gate():
    store = ProfileStore(MemoryBackend())
    store.set(
        "light.test",
        profile(
            {
                "control_mode": "read_only",
                "declared_limits": [
                    {
                        "id": "brightness",
                        "predicate": {
                            "entity": "input_boolean.dim_mode",
                            "operator": "eq",
                            "value": "on",
                        },
                        "limit": {
                            "service": "light.turn_on",
                            "parameter": "brightness",
                            "max_value": 10,
                        },
                    }
                ],
            }
        ),
    )
    result = MesaEnforcer(store, get_state=lambda _entity: "on").evaluate(
        "light.test", "light.turn_on", {"brightness": 255}
    )
    assert not result.allowed
    assert result.rule_applied == "declared_limit:brightness"
    assert result.evaluated_control_mode == ControlMode.READ_ONLY


def test_early_refusals_do_not_claim_an_evaluated_mode(monkeypatch):
    enforcer = MesaEnforcer(ProfileStore(MemoryBackend()))
    contradictory = enforcer.evaluate("light.test", "light.turn_on", {"entity_id": "light.other"})
    assert not contradictory.allowed
    assert contradictory.rule_applied == "contradictory_target"
    assert contradictory.evaluated_control_mode is None

    def unavailable(_entity_id):
        raise MesaError("policy unavailable")

    monkeypatch.setattr(enforcer.resolver, "explain", unavailable)
    result = enforcer.evaluate("light.test", "light.turn_on")
    assert not result.allowed
    assert result.rule_applied == "policy_unavailable"
    assert result.evaluated_control_mode is None
