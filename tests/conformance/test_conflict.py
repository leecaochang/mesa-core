"""Conflict resolution Rules A-E (Spec 5.7; Module Proposal 7.2)."""

from __future__ import annotations

from typing import Any

from mesa_core.conflict import ConflictResolver, Layer
from mesa_core.profile import ControlMode, PrivacyLevel, SemanticProfile, TriggersAutomations


def make_profile(
    entity_id: str,
    origin: str = "user",
    boundaries: dict[str, Any] | None = None,
    privacy: dict[str, Any] | None = None,
    confirmed: list[str] | None = None,
    tags: list[str] | None = None,
) -> SemanticProfile:
    mo: dict[str, Any] = {"source": origin}
    if origin == "inferred_ai":
        mo |= {"confidence": 0.9, "generated_at": "2026-06-01T00:00:00+00:00"}
    if confirmed:
        mo["confirmed_fields"] = confirmed
    sp: dict[str, Any] = {"metadata_origin": mo}
    if boundaries is not None:
        sp["operational_boundaries"] = boundaries
    if tags is not None:
        sp["semantic_tags"] = tags
    doc: dict[str, Any] = {"semantic_profile": sp}
    if privacy is not None:
        doc["privacy_classification"] = privacy
    return SemanticProfile.from_dict(entity_id, doc)


def resolve(entity_id: str, *layers: Layer) -> tuple[SemanticProfile, Any]:
    return ConflictResolver().resolve(entity_id, list(layers))


# ---------------------------------------------------------------- Rule A


def test_rule_a_most_restrictive_wins() -> None:
    effective, res = resolve(
        "light.x",
        Layer("entity", make_profile("light.x", boundaries={"control_mode": "autonomous"})),
        Layer("domain", make_profile("light", origin="developer", boundaries={"control_mode": "confirm"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM
    assert res.conflicts_detected


def test_rule_a_inferred_prohibited_preserved_against_developer_autonomous() -> None:
    effective, _ = resolve(
        "light.x",
        Layer("entity", make_profile("light.x", origin="inferred_ai", boundaries={"control_mode": "prohibited"})),
        Layer("domain", make_profile("light", origin="developer", boundaries={"control_mode": "autonomous"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.PROHIBITED


def test_rule_a_read_only_wins_tie_with_prohibited() -> None:
    effective, _ = resolve(
        "sensor.x",
        Layer("entity", make_profile("sensor.x", boundaries={"control_mode": "prohibited"})),
        Layer("domain", make_profile("sensor", origin="developer", boundaries={"control_mode": "read_only"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.READ_ONLY


def test_rule_a_exception_valid_loosening_override() -> None:
    override = make_profile(
        "media_player.x",
        origin="user",
        boundaries={
            "control_mode": "autonomous",
            "override_control_mode": True,
            "control_reason": "Operator knows autonomous control is safe here.",
        },
    )
    effective, res = resolve(
        "media_player.x",
        Layer("entity", override),
        Layer("domain", make_profile("media_player", origin="developer", boundaries={"control_mode": "confirm"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.AUTONOMOUS
    entry = next(
        e for e in res.explanations if e.field_path == "operational_boundaries.control_mode"
    )
    assert entry.conflict and "exception" in (entry.conflict_resolution or "")


def test_rule_a_override_rejected_without_control_reason() -> None:
    override = make_profile(
        "media_player.x",
        boundaries={"control_mode": "autonomous", "override_control_mode": True},
    )
    effective, res = resolve(
        "media_player.x",
        Layer("entity", override),
        Layer("domain", make_profile("media_player", origin="developer", boundaries={"control_mode": "confirm"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM
    assert any("malformed" in w for w in res.warnings)


def test_rule_a_override_rejected_from_non_user_origin() -> None:
    override = make_profile(
        "media_player.x",
        origin="hybrid",
        confirmed=["operational_boundaries.control_mode"],
        boundaries={
            "control_mode": "autonomous",
            "override_control_mode": True,
            "control_reason": "attempted loosening",
        },
    )
    effective, _ = resolve(
        "media_player.x",
        Layer("entity", override),
        Layer("domain", make_profile("media_player", origin="developer", boundaries={"control_mode": "confirm"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM


def test_rule_a_override_cannot_loosen_prohibited() -> None:
    override = make_profile(
        "lock.x",
        boundaries={
            "control_mode": "autonomous",
            "override_control_mode": True,
            "control_reason": "attempted loosening of prohibited",
        },
    )
    effective, res = resolve(
        "lock.x",
        Layer("entity", override),
        Layer("domain", make_profile("lock", origin="developer", boundaries={"control_mode": "prohibited"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.PROHIBITED
    assert any("cannot loosen" in w for w in res.warnings)


def test_rule_a_unconfirmed_inferred_autonomous_read_as_confirm() -> None:
    effective, res = resolve(
        "light.x",
        Layer("entity", make_profile("light.x", origin="inferred_ai", boundaries={"control_mode": "autonomous"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM
    assert any("Rule 8" in w for w in res.warnings)


# ---------------------------------------------------------------- Rule B


def test_rule_b_likely_sticky_upward() -> None:
    effective, _ = resolve(
        "input_boolean.x",
        Layer("entity", make_profile("input_boolean.x", boundaries={"triggers_automations": "none"})),
        Layer("domain", make_profile("input_boolean", origin="developer", boundaries={"triggers_automations": "likely"})),
    )
    assert effective.operational_boundaries.triggers_automations == TriggersAutomations.LIKELY


def test_rule_b_entity_override_with_human_reason() -> None:
    override = make_profile(
        "input_boolean.x",
        boundaries={
            "triggers_automations": "none",
            "override_triggers_automations": True,
            "human_reason": "Dashboard-only toggle, no automations reference it.",
        },
    )
    effective, _ = resolve(
        "input_boolean.x",
        Layer("entity", override),
        Layer("domain", make_profile("input_boolean", origin="developer", boundaries={"triggers_automations": "likely"})),
    )
    assert effective.operational_boundaries.triggers_automations == TriggersAutomations.NONE


def test_rule_b_override_rejected_without_human_reason() -> None:
    override = make_profile(
        "input_boolean.x",
        boundaries={"triggers_automations": "none", "override_triggers_automations": True},
    )
    effective, res = resolve(
        "input_boolean.x",
        Layer("entity", override),
        Layer("domain", make_profile("input_boolean", origin="developer", boundaries={"triggers_automations": "likely"})),
    )
    assert effective.operational_boundaries.triggers_automations == TriggersAutomations.LIKELY
    assert any("malformed" in w for w in res.warnings)


def test_rule_b_deployment_defined_override() -> None:
    override = make_profile(
        "input_select.mode",
        boundaries={
            "triggers_automations": "deployment_defined",
            "override_triggers_automations": True,
            "human_reason": "Operator catalogued the affected automations precisely.",
        },
    )
    effective, _ = resolve(
        "input_select.mode",
        Layer("entity", override),
        Layer("area", make_profile("area.kitchen", boundaries={"triggers_automations": "likely"})),
    )
    assert (
        effective.operational_boundaries.triggers_automations
        == TriggersAutomations.DEPLOYMENT_DEFINED
    )


def test_rule_b_inferred_helper_none_read_as_likely() -> None:
    effective, res = resolve(
        "input_boolean.x",
        Layer("entity", make_profile("input_boolean.x", origin="inferred_ai", boundaries={"triggers_automations": "none"})),
    )
    assert effective.operational_boundaries.triggers_automations == TriggersAutomations.LIKELY
    assert any("Rule 9" in w for w in res.warnings)


# ---------------------------------------------------------------- Rule C


def test_rule_c_most_restrictive_privacy_wins() -> None:
    effective, res = resolve(
        "camera.x",
        Layer("entity", make_profile("camera.x", privacy={"level": "normal"})),
        Layer("domain", make_profile("camera", origin="inferred_ai", privacy={"level": "restricted"})),
    )
    assert effective.privacy_classification.level == PrivacyLevel.RESTRICTED
    assert res.conflicts_detected


def test_rule_c_regardless_of_origin_authority() -> None:
    effective, _ = resolve(
        "sensor.x",
        Layer("entity", make_profile("sensor.x", origin="developer", privacy={"level": "public"})),
        Layer("area", make_profile("area.bedroom", origin="user", privacy={"level": "sensitive"})),
    )
    assert effective.privacy_classification.level == PrivacyLevel.SENSITIVE


def test_rule_c_single_declaration_no_conflict() -> None:
    effective, res = resolve(
        "sensor.x",
        Layer("entity", make_profile("sensor.x", privacy={"level": "sensitive"})),
    )
    assert effective.privacy_classification.level == PrivacyLevel.SENSITIVE
    assert not res.conflicts_detected


# ---------------------------------------------------------------- Rule D


def test_rule_d_user_entity_overrides_developer_domain() -> None:
    effective, _ = resolve(
        "vacuum.x",
        Layer("entity", make_profile("vacuum.x", origin="user", boundaries={"reversibility_cost": "high"})),
        Layer("domain", make_profile("vacuum", origin="developer", boundaries={"reversibility_cost": "none"})),
    )
    assert effective.operational_boundaries.reversibility_cost == "high"


def test_rule_d_inferred_entity_never_overrides_developer_domain() -> None:
    effective, res = resolve(
        "vacuum.x",
        Layer("entity", make_profile("vacuum.x", origin="inferred_ai", boundaries={"reversibility_cost": "high"})),
        Layer("domain", make_profile("vacuum", origin="developer", boundaries={"reversibility_cost": "none"})),
    )
    assert effective.operational_boundaries.reversibility_cost == "none"
    entry = next(
        e for e in res.explanations if e.field_path == "operational_boundaries.reversibility_cost"
    )
    assert entry.conflict and "lower-tier" in (entry.conflict_resolution or "")


def test_rule_d_lower_tier_resolution_when_no_trusted_declaration() -> None:
    effective, _ = resolve(
        "sensor.x",
        Layer("entity", make_profile("sensor.x", origin="inferred_ai", boundaries={"state_volatility": "high"})),
        Layer("domain", make_profile("sensor", origin="unknown", boundaries={"state_volatility": "low"})),
    )
    assert effective.operational_boundaries.state_volatility == "high"


def test_rule_d_origin_authority_breaks_equal_scope_tie() -> None:
    # Two domain-level declarations: developer beats user at equal scope.
    effective, _ = resolve(
        "light.x",
        Layer("domain", make_profile("light", origin="user", boundaries={"side_effect_scope": "room_localized"})),
        Layer("domain", make_profile("light", origin="developer", boundaries={"side_effect_scope": "entity_only"})),
    )
    assert effective.operational_boundaries.side_effect_scope == "entity_only"


# ---------------------------------------------------------------- Rule E


def test_rule_e_absence_is_inherited_not_defaulted() -> None:
    effective, _ = resolve(
        "light.x",
        Layer("entity", make_profile("light.x", boundaries={"control_mode": "confirm"})),
        Layer("domain", make_profile("light", origin="developer", boundaries={"reversibility_cost": "trivial"})),
    )
    # reversibility_cost comes from the domain layer; absence at entity level is not a conflict.
    assert effective.operational_boundaries.reversibility_cost == "trivial"


def test_rule_e_undeclared_fields_stay_unset() -> None:
    effective, _ = resolve(
        "light.x",
        Layer("entity", make_profile("light.x", boundaries={"control_mode": "confirm"})),
    )
    assert effective.operational_boundaries.reversible is None
    assert effective.operational_boundaries.side_effect_scope is None


def test_effective_tags_are_union_across_levels() -> None:
    effective, _ = resolve(
        "light.x",
        Layer("entity", make_profile("light.x", tags=["lighting.task"])),
        Layer("domain", make_profile("light", origin="developer", tags=["lighting.ambient", "lighting.task"])),
    )
    assert set(effective.semantic_tags) == {"lighting.task", "lighting.ambient"}
