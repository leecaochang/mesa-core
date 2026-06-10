"""Inferred profile rules 1-9 at consumption time (Spec 5.4; Module Proposal 7.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mesa_core.backends import MemoryBackend
from mesa_core.enforcer import MesaEnforcer
from mesa_core.profile import ControlMode, SemanticProfile, TriggersAutomations
from mesa_core.store import ProfileStore

NOON = datetime(2026, 6, 13, 12, 0)


def inferred_profile(
    entity_id: str, boundaries: dict[str, Any], confidence: float = 0.9
) -> SemanticProfile:
    return SemanticProfile.from_dict(
        entity_id,
        {
            "semantic_profile": {
                "metadata_origin": {
                    "source": "inferred_ai",
                    "confidence": confidence,
                    "generated_at": "2026-06-01T00:00:00+00:00",
                },
                "operational_boundaries": boundaries,
            }
        },
    )


def store_with(entity_id: str, profile: SemanticProfile) -> ProfileStore:
    store = ProfileStore(backend=MemoryBackend())
    store.set(entity_id, profile)
    return store


def test_inferred_prohibited_is_enforced() -> None:
    # Tightening from an inferred profile is always honoured (Rule 3 / Rule A).
    store = store_with("switch.x", inferred_profile("switch.x", {"control_mode": "prohibited"}))
    result = MesaEnforcer(store).evaluate("switch.x", "switch.turn_on", current_time=NOON)
    assert not result.allowed
    assert result.rule_applied == "control_mode:prohibited"


def test_inferred_autonomous_resolves_to_confirm() -> None:
    # An unconfirmed inferred autonomous may not take effect (Rules 3/8).
    store = store_with("light.x", inferred_profile("light.x", {"control_mode": "autonomous"}))
    effective = store.get_effective("light.x")
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM
    result = MesaEnforcer(store).evaluate("light.x", "light.turn_on", current_time=NOON)
    assert not result.allowed
    assert result.confirmation_challenge is not None


def test_hybrid_confirmed_autonomous_is_honoured() -> None:
    # Human confirmation promotes the field (Rule 6).
    profile = SemanticProfile.from_dict(
        "light.x",
        {
            "semantic_profile": {
                "metadata_origin": {
                    "source": "hybrid",
                    "confidence": 1.0,
                    "confirmed_fields": ["operational_boundaries.control_mode"],
                },
                "operational_boundaries": {"control_mode": "autonomous"},
            }
        },
    )
    store = store_with("light.x", profile)
    assert MesaEnforcer(store).evaluate("light.x", "light.turn_on", current_time=NOON).allowed


def test_inferred_helper_none_resolves_to_likely() -> None:
    # Rule 9: helper-domain inferred profiles may not assert none.
    store = store_with(
        "input_boolean.flag",
        inferred_profile("input_boolean.flag", {"triggers_automations": "none"}),
    )
    effective = store.get_effective("input_boolean.flag")
    assert effective.operational_boundaries.triggers_automations == TriggersAutomations.LIKELY
    # The same assertion on a non-helper domain is preserved.
    store2 = store_with(
        "sensor.power", inferred_profile("sensor.power", {"triggers_automations": "none"})
    )
    assert (
        store2.get_effective("sensor.power").operational_boundaries.triggers_automations
        == TriggersAutomations.NONE
    )


def test_low_confidence_inferred_profile_warns() -> None:
    store = store_with(
        "switch.x", inferred_profile("switch.x", {"control_mode": "prohibited"}, confidence=0.5)
    )
    result = MesaEnforcer(store).evaluate("switch.x", "switch.turn_on", current_time=NOON)
    assert any("0.50" in w and "Rule 3" in w for w in result.warnings)


def test_confident_inferred_profile_does_not_warn() -> None:
    store = store_with(
        "switch.x", inferred_profile("switch.x", {"control_mode": "prohibited"}, confidence=0.9)
    )
    result = MesaEnforcer(store).evaluate("switch.x", "switch.turn_on", current_time=NOON)
    assert not any("Rule 3" in w for w in result.warnings)


def test_developer_profile_supersedes_inferred_for_declared_fields() -> None:
    # Rule 7 via Rule D: trusted declarations win for non-safety fields.
    store = ProfileStore(backend=MemoryBackend())
    store.set("vacuum.x", inferred_profile("vacuum.x", {"reversibility_cost": "high"}))
    dev = SemanticProfile.from_dict(
        "vacuum",
        {
            "semantic_profile": {
                "metadata_origin": {"source": "developer", "confidence": 1.0},
                "operational_boundaries": {"reversibility_cost": "none"},
            }
        },
    )
    store.set_domain_profile("vacuum", dev)
    effective = store.get_effective("vacuum.x")
    assert effective.operational_boundaries.reversibility_cost == "none"
