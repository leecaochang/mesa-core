"""Profile inheritance resolution (Spec 5.6, 5.8; Module Proposal 7.2)."""

from __future__ import annotations

from typing import Any

from mesa_core.backends import MemoryBackend
from mesa_core.inheritance import InheritanceResolver
from mesa_core.profile import ControlMode, PrivacyLevel, SemanticProfile, TriggersAutomations
from mesa_core.store import ProfileStore

from .test_conflict import make_profile


def make_store(**kwargs: Any) -> ProfileStore:
    return ProfileStore(backend=MemoryBackend(), **kwargs)


def test_domain_default_applies_when_no_entity_profile() -> None:
    store = make_store()
    store.set_domain_profile(
        "light",
        make_profile("light", origin="developer", boundaries={"control_mode": "autonomous"}),
    )
    effective = store.get_effective("light.kitchen")
    assert effective.operational_boundaries.control_mode == ControlMode.AUTONOMOUS


def test_area_tightens_domain_default() -> None:
    # The Spec 5.6 practical example: bedroom area declares confirm over an
    # integration's autonomous; all bedroom lights now require confirmation.
    store = make_store(get_entity_area=lambda eid: "area.bedroom")
    store.set_domain_profile(
        "light",
        make_profile("light", origin="developer", boundaries={"control_mode": "autonomous"}),
    )
    store.set_area_profile(
        "area.bedroom", make_profile("area.bedroom", boundaries={"control_mode": "confirm"})
    )
    effective = store.get_effective("light.bedroom_ceiling")
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM


def test_entity_overrides_area_for_rule_d_fields() -> None:
    store = make_store(get_entity_area=lambda eid: "area.bedroom")
    store.set_area_profile(
        "area.bedroom",
        make_profile("area.bedroom", boundaries={"reversibility_cost": "moderate"}),
    )
    store.set(
        "light.bedside",
        make_profile("light.bedside", boundaries={"reversibility_cost": "none"}),
    )
    effective = store.get_effective("light.bedside")
    assert effective.operational_boundaries.reversibility_cost == "none"


def test_three_level_inheritance_no_conflicts() -> None:
    store = make_store(get_entity_area=lambda eid: "area.study")
    store.set_domain_profile(
        "light",
        make_profile(
            "light",
            origin="developer",
            boundaries={"reversibility_cost": "none"},
            tags=["lighting.ambient"],
        ),
    )
    store.set_area_profile(
        "area.study", make_profile("area.study", boundaries={"state_volatility": "low"})
    )
    store.set(
        "light.desk",
        make_profile(
            "light.desk", boundaries={"control_mode": "autonomous"}, tags=["lighting.task"]
        ),
    )
    explanation = store._default_resolver().explain("light.desk")
    effective = explanation.effective_profile
    assert effective.operational_boundaries.control_mode == ControlMode.AUTONOMOUS
    assert effective.operational_boundaries.reversibility_cost == "none"
    assert effective.operational_boundaries.state_volatility == "low"
    assert set(effective.semantic_tags) == {"lighting.task", "lighting.ambient"}
    assert not explanation.conflicts_detected
    levels = {e.field_path: e.provided_by_level for e in explanation.explanation}
    assert levels["operational_boundaries.control_mode"] == "entity"
    assert levels["operational_boundaries.reversibility_cost"] == "domain"
    assert levels["operational_boundaries.state_volatility"] == "area"


def test_likely_sticky_across_levels() -> None:
    store = make_store()
    store.set_domain_profile(
        "input_boolean",
        make_profile(
            "input_boolean", origin="developer", boundaries={"triggers_automations": "likely"}
        ),
    )
    store.set(
        "input_boolean.flag",
        make_profile("input_boolean.flag", boundaries={"triggers_automations": "none"}),
    )
    effective = store.get_effective("input_boolean.flag")
    assert effective.operational_boundaries.triggers_automations == TriggersAutomations.LIKELY


def test_baseline_applies_to_unprofiled_entities() -> None:
    store = make_store()
    assert (
        store.get_effective("light.anything").operational_boundaries.control_mode
        == ControlMode.AUTONOMOUS
    )
    assert (
        store.get_effective("lock.front").operational_boundaries.control_mode
        == ControlMode.PROHIBITED
    )
    assert (
        store.get_effective("cover.garage").operational_boundaries.control_mode
        == ControlMode.CONFIRM
    )
    assert (
        store.get_effective("input_boolean.x").operational_boundaries.triggers_automations
        == TriggersAutomations.LIKELY
    )


def test_deployment_defaults_replace_baseline() -> None:
    store = make_store()
    store.set_deployment_defaults(
        {
            "default_control_mode": "confirm",
            "domain_overrides": {"media_player": {"control_mode": "autonomous"}},
        }
    )
    effective = store.get_effective("media_player.kitchen")
    assert effective.operational_boundaries.control_mode == ControlMode.AUTONOMOUS
    # Domains without an override fall to the configured default, not the baseline.
    assert (
        store.get_effective("light.x").operational_boundaries.control_mode
        == ControlMode.CONFIRM
    )


def test_any_profile_beats_deployment_defaults() -> None:
    store = make_store()
    store.set_deployment_defaults(
        {"domain_overrides": {"light": {"control_mode": "autonomous"}}}
    )
    store.set("light.locked", make_profile("light.locked", boundaries={"control_mode": "prohibited"}))
    effective = store.get_effective("light.locked")
    assert effective.operational_boundaries.control_mode == ControlMode.PROHIBITED


def test_person_entities_default_to_sensitive() -> None:
    store = make_store()
    effective = store.get_effective("person.alice")
    assert effective.privacy_classification.level == PrivacyLevel.SENSITIVE
    # Explicit classification still wins (and can only be more restrictive via Rule C).
    store.set("person.bob", make_profile("person.bob", privacy={"level": "restricted"}))
    assert (
        store.get_effective("person.bob").privacy_classification.level
        == PrivacyLevel.RESTRICTED
    )


def test_explain_reports_baseline_provenance() -> None:
    store = make_store()
    resolver = InheritanceResolver(store=store)
    explanation = resolver.explain("lock.front")
    entry = next(
        e for e in explanation.explanation
        if e.field_path == "operational_boundaries.control_mode"
    )
    assert entry.effective_value == "prohibited"
    assert entry.provided_by_level == "built_in_baseline"
    assert not entry.conflict


def test_explain_to_dict_round_trip() -> None:
    store = make_store()
    store.set_domain_profile(
        "light",
        make_profile("light", origin="developer", boundaries={"control_mode": "autonomous"}),
    )
    store.set("light.x", make_profile("light.x", boundaries={"control_mode": "confirm"}))
    explanation = InheritanceResolver(store=store).explain("light.x")
    payload = explanation.to_dict()
    assert payload["entity_id"] == "light.x"
    assert payload["conflicts_detected"] is True
    cm = next(
        e for e in payload["explanation"]
        if e["field_path"] == "operational_boundaries.control_mode"
    )
    assert cm["effective_value"] == "confirm"
    assert cm["competing_values"] is not None
    hidden = explanation.to_dict(show_conflicts=False)
    cm2 = next(
        e for e in hidden["explanation"]
        if e["field_path"] == "operational_boundaries.control_mode"
    )
    assert "competing_values" not in cm2


def test_effective_profile_serialises() -> None:
    store = make_store()
    store.set("light.x", make_profile("light.x", boundaries={"control_mode": "autonomous"}))
    effective = store.get_effective("light.x")
    out = effective.to_dict()
    assert out["semantic_profile"]["operational_boundaries"]["control_mode"] == "autonomous"
    assert isinstance(effective, SemanticProfile)
