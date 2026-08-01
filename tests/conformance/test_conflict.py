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
    if confirmed is not None:
        mo["confirmed_fields"] = confirmed
    elif origin == "hybrid":
        # REQUIRED for hybrid (Spec 5.3), as confidence is for inferred_ai.
        mo["confirmed_fields"] = []
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


# ------------------------------------------------------- device scope (MESA 1.1)


def test_rule_d_device_scope_beats_area_integration_domain() -> None:
    effective, res = resolve(
        "sensor.x",
        Layer("device", make_profile("abc123", boundaries={"reversibility_cost": "high"})),
        Layer("area", make_profile("area.hall", boundaries={"reversibility_cost": "moderate"})),
        Layer("integration", make_profile("hue", origin="developer", boundaries={"reversibility_cost": "trivial"})),
        Layer("domain", make_profile("sensor", origin="developer", boundaries={"reversibility_cost": "none"})),
    )
    assert effective.operational_boundaries.reversibility_cost == "high"
    entry = next(
        e for e in res.explanations if e.field_path == "operational_boundaries.reversibility_cost"
    )
    assert entry.provided_by_level == "device"


def test_rule_d_entity_beats_device_scope() -> None:
    effective, _ = resolve(
        "sensor.x",
        Layer("entity", make_profile("sensor.x", boundaries={"reversibility_cost": "none"})),
        Layer("device", make_profile("abc123", boundaries={"reversibility_cost": "high"})),
    )
    assert effective.operational_boundaries.reversibility_cost == "none"


def test_rule_a_device_scope_tightens_freely() -> None:
    effective, _ = resolve(
        "light.strip",
        Layer("device", make_profile("abc123", boundaries={"control_mode": "confirm"})),
        Layer("integration", make_profile("hue", origin="developer", boundaries={"control_mode": "autonomous"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM


def test_rule_a_override_rejected_at_device_scope() -> None:
    # The loosening override is entity-only (Spec 5.7 Rule A); a device-scope
    # profile declaring it is malformed and the inherited confirm stands.
    override = make_profile(
        "abc123",
        origin="user",
        boundaries={
            "control_mode": "autonomous",
            "override_control_mode": True,
            "control_reason": "operator wants the whole device autonomous",
        },
    )
    effective, res = resolve(
        "media_player.x",
        Layer("device", override),
        Layer("domain", make_profile("media_player", origin="developer", boundaries={"control_mode": "confirm"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM
    assert any("override_control_mode is malformed" in w for w in res.warnings)


def test_rule_b_override_rejected_at_device_scope() -> None:
    override = make_profile(
        "abc123",
        origin="user",
        boundaries={
            "triggers_automations": "none",
            "override_triggers_automations": True,
            "human_reason": "no automations reference this device",
        },
    )
    effective, res = resolve(
        "input_boolean.flag",
        Layer("device", override),
        Layer("domain", make_profile("input_boolean", origin="developer", boundaries={"triggers_automations": "likely"})),
    )
    assert effective.operational_boundaries.triggers_automations == TriggersAutomations.LIKELY
    assert any("override_triggers_automations is malformed" in w for w in res.warnings)


# ------------------------------------------- capability hint (Spec 4, MESA 1.1)


def make_capability_profile(
    name: str,
    hint: str,
    origin: str = "developer",
    boundaries: dict[str, Any] | None = None,
) -> SemanticProfile:
    mo: dict[str, Any] = {"source": origin}
    if origin == "inferred_ai":
        mo |= {"confidence": 0.9, "generated_at": "2026-06-01T00:00:00+00:00"}
    sp: dict[str, Any] = {
        "metadata_origin": mo,
        "capability_semantics": {"control_mode": hint},
    }
    if boundaries is not None:
        sp["operational_boundaries"] = boundaries
    return SemanticProfile.from_dict(name, {"semantic_profile": sp})


def test_capability_hint_contributes_when_boundaries_silent() -> None:
    effective, res = resolve(
        "light.x",
        Layer("integration", make_capability_profile("hue", "confirm")),
        Layer("domain", make_profile("light", origin="developer", boundaries={"control_mode": "autonomous"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM
    entry = next(
        e for e in res.explanations if e.field_path == "operational_boundaries.control_mode"
    )
    assert entry.provided_by_level == "integration"
    assert entry.conflict and "capability" in (entry.conflict_resolution or "")


def test_capability_hint_inert_when_boundaries_declare() -> None:
    # operational_boundaries.control_mode is the integration profile's
    # contribution; the hint asserts nothing alongside it.
    effective, res = resolve(
        "light.x",
        Layer("integration", make_capability_profile("hue", "prohibited", boundaries={"control_mode": "confirm"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM
    assert not any("capability" in w for w in res.warnings)


def test_capability_hint_never_loosens() -> None:
    effective, _ = resolve(
        "light.x",
        Layer("integration", make_capability_profile("hue", "autonomous")),
        Layer("entity", make_profile("light.x", boundaries={"control_mode": "confirm"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM


def test_capability_hint_ignored_outside_integration_scope() -> None:
    # capability_semantics on any non-integration layer never participates.
    effective, _ = resolve(
        "light.x",
        Layer("entity", make_capability_profile("light.x", "prohibited")),
        Layer("domain", make_profile("light", origin="developer", boundaries={"control_mode": "autonomous"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.AUTONOMOUS


def test_capability_hint_uncontested_win_surfaces_warning() -> None:
    effective, res = resolve(
        "light.x",
        Layer("integration", make_capability_profile("hue", "confirm")),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM
    entry = next(
        e for e in res.explanations if e.field_path == "operational_boundaries.control_mode"
    )
    assert not entry.conflict
    assert any("capability_semantics.control_mode" in w for w in res.warnings)


def test_capability_hint_malformed_value_ignored_with_warning() -> None:
    # Stored documents cannot carry a malformed hint past validation, but a
    # programmatically built layer can; it must be dropped, not resolved.
    profile = make_profile("hue", origin="developer")
    profile.raw = {"semantic_profile": {"capability_semantics": {"control_mode": "banana"}}}
    effective, res = resolve(
        "light.x",
        Layer("integration", profile),
        Layer("domain", make_profile("light", origin="developer", boundaries={"control_mode": "autonomous"})),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.AUTONOMOUS
    assert any("capability hint ignored" in w for w in res.warnings)


def test_capability_hint_rule_8_coercion_for_inferred_origin() -> None:
    effective, res = resolve(
        "light.x",
        Layer("integration", make_capability_profile("hue", "autonomous", origin="inferred_ai")),
    )
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM
    assert any("Rule 8" in w for w in res.warnings)


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


# ------------------------------------------- Rule D union (declared_limits / temporal)


def _limit(limit_id: str, **limit_spec: Any) -> dict[str, Any]:
    return {
        "id": limit_id,
        "predicate": {"entity": "input_boolean.night_mode", "operator": "eq", "value": True},
        "limit": {"service": "media_player.volume_set", "parameter": "volume_level", **limit_spec},
    }


def _limit_ids(profile: SemanticProfile) -> set[str]:
    return {entry["id"] for entry in profile.operational_boundaries.declared_limits}


def _limit_by_id(profile: SemanticProfile, limit_id: str) -> dict[str, Any]:
    return next(
        entry
        for entry in profile.operational_boundaries.declared_limits
        if entry["id"] == limit_id
    )


def test_declared_limits_union_distinct_ids_across_layers() -> None:
    # The audit's core finding: an entity-level limit must not erase a
    # domain-level safety limit. Distinct ids compose, and are not a conflict.
    effective, res = resolve(
        "media_player.kitchen",
        Layer(
            "entity",
            make_profile(
                "media_player.kitchen",
                boundaries={"declared_limits": [_limit("source_allowlist", permitted_values=["aux"])]},
            ),
        ),
        Layer(
            "domain",
            make_profile(
                "media_player",
                origin="developer",
                boundaries={"declared_limits": [_limit("night_volume_cap", max_value=0.4)]},
            ),
        ),
    )
    assert _limit_ids(effective) == {"source_allowlist", "night_volume_cap"}
    assert not res.conflicts_detected


def test_declared_limits_same_id_trusted_entity_overrides_domain() -> None:
    # Reusing an id is a deliberate per-entry override: most specific scope wins.
    effective, res = resolve(
        "media_player.kitchen",
        Layer(
            "entity",
            make_profile(
                "media_player.kitchen",
                origin="user",
                boundaries={"declared_limits": [_limit("cap", max_value=0.8)]},
            ),
        ),
        Layer(
            "domain",
            make_profile(
                "media_player",
                origin="developer",
                boundaries={"declared_limits": [_limit("cap", max_value=0.4)]},
            ),
        ),
    )
    assert _limit_ids(effective) == {"cap"}
    assert _limit_by_id(effective, "cap")["limit"]["max_value"] == 0.8
    entry = next(
        e for e in res.explanations if e.field_path == "operational_boundaries.declared_limits"
    )
    assert entry.conflict and "same-id" in (entry.conflict_resolution or "")


def test_declared_limits_lower_tier_cannot_override_trusted_same_id() -> None:
    # An inferred entity limit must not loosen a developer domain limit it shares
    # an id with: the trusted tier is preserved (mirrors scalar Rule D).
    effective, _ = resolve(
        "media_player.kitchen",
        Layer(
            "entity",
            make_profile(
                "media_player.kitchen",
                origin="inferred_ai",
                boundaries={"declared_limits": [_limit("cap", max_value=1.0)]},
            ),
        ),
        Layer(
            "domain",
            make_profile(
                "media_player",
                origin="developer",
                boundaries={"declared_limits": [_limit("cap", max_value=0.4)]},
            ),
        ),
    )
    assert _limit_by_id(effective, "cap")["limit"]["max_value"] == 0.4


def test_declared_limits_single_layer_unchanged() -> None:
    effective, res = resolve(
        "media_player.kitchen",
        Layer(
            "domain",
            make_profile(
                "media_player",
                origin="developer",
                boundaries={"declared_limits": [_limit("night_volume_cap", max_value=0.4)]},
            ),
        ),
    )
    assert _limit_ids(effective) == {"night_volume_cap"}
    assert not res.conflicts_detected


def test_temporal_constraints_union_across_layers() -> None:
    def _tc(tc_id: str) -> dict[str, Any]:
        return {
            "id": tc_id,
            "condition": {"type": "time_range", "start_time": "22:00", "end_time": "06:00"},
            "effect": {"control_mode": "confirm"},
        }

    effective, res = resolve(
        "media_player.kitchen",
        Layer(
            "entity",
            make_profile(
                "media_player.kitchen",
                boundaries={"temporal_constraints": [_tc("entity_quiet_hours")]},
            ),
        ),
        Layer(
            "domain",
            make_profile(
                "media_player",
                origin="developer",
                boundaries={"temporal_constraints": [_tc("domain_night_lock")]},
            ),
        ),
    )
    ids = {tc["id"] for tc in effective.operational_boundaries.temporal_constraints}
    assert ids == {"entity_quiet_hours", "domain_night_lock"}
    assert not res.conflicts_detected


def test_effective_tags_are_union_across_levels() -> None:
    effective, _ = resolve(
        "light.x",
        Layer("entity", make_profile("light.x", tags=["lighting.task"])),
        Layer("domain", make_profile("light", origin="developer", tags=["lighting.ambient", "lighting.task"])),
    )
    assert set(effective.semantic_tags) == {"lighting.task", "lighting.ambient"}


# ------------------------------------------------------ merge() two-profile convenience


def test_merge_higher_authority_wins_rule_d_field() -> None:
    # merge() treats the first profile as the more specific scope (entity over domain).
    higher = make_profile("light.x", origin="user", boundaries={"reversibility_cost": "high"})
    lower = make_profile("light", origin="developer", boundaries={"reversibility_cost": "none"})
    merged = ConflictResolver().merge(higher, lower)
    assert merged.operational_boundaries.reversibility_cost == "high"


def test_merge_preserves_tightening_regardless_of_authority() -> None:
    # Rule A still wins: the lower profile's prohibited is preserved even though the
    # higher profile is the more specific scope and declares autonomous.
    higher = make_profile("light.x", origin="user", boundaries={"control_mode": "autonomous"})
    lower = make_profile("light", origin="developer", boundaries={"control_mode": "prohibited"})
    merged = ConflictResolver().merge(higher, lower)
    assert merged.operational_boundaries.control_mode == ControlMode.PROHIBITED


# ---------------------------------------------------------------- person_traits (Rule D)


def person_profile(entity_id: str, origin: str = "user", **traits: Any) -> SemanticProfile:
    mo: dict[str, Any] = {"source": origin}
    if origin == "inferred_ai":
        mo |= {"confidence": 0.9, "generated_at": "2026-06-01T00:00:00+00:00"}
    doc = {"semantic_profile": {"metadata_origin": mo, "person_traits": dict(traits)}}
    return SemanticProfile.from_dict(entity_id, doc)


def test_person_traits_inherited_from_domain_layer() -> None:
    effective, _ = resolve(
        "person.kid",
        Layer("entity", make_profile("person.kid", boundaries={"control_mode": "confirm"})),
        Layer("domain", person_profile("person", is_minor=True, household_role="child")),
    )
    assert effective.person_traits.is_minor is True
    assert effective.person_traits.household_role == "child"


def test_person_traits_entity_scope_beats_domain() -> None:
    effective, res = resolve(
        "person.teen",
        Layer("entity", person_profile("person.teen", is_minor=False)),
        Layer("domain", person_profile("person", is_minor=True)),
    )
    assert effective.person_traits.is_minor is False
    assert res.conflicts_detected


def test_person_traits_lower_tier_never_overrides_trusted() -> None:
    effective, _ = resolve(
        "person.kid",
        Layer("entity", person_profile("person.kid", origin="inferred_ai", is_minor=False)),
        Layer("domain", person_profile("person", origin="user", is_minor=True)),
    )
    assert effective.person_traits.is_minor is True
