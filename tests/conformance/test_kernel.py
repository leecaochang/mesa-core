"""Kernel field validation (Module Proposal 7.2; Spec Sections 4-5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mesa_core import (
    ControlMode,
    MesaValidationError,
    MetadataOrigin,
    PersonTraits,
    PrivacyLevel,
    SemanticProfile,
    TriggersAutomations,
    validate_document,
)

MALFORMED_DIR = Path(__file__).parent / "malformed"

KERNEL = {
    "semantic_profile": {
        "semantic_tags": ["lighting.ambient"],
        "operational_boundaries": {
            "control_mode": "autonomous",
            "triggers_automations": "none",
            "reversible": True,
            "reversibility_cost": "none",
            "side_effect_scope": "entity_only",
        },
    },
    "privacy_classification": {"level": "normal"},
}


def test_kernel_profile_parses() -> None:
    p = SemanticProfile.from_dict("light.living_room", KERNEL)
    assert p.operational_boundaries.control_mode == ControlMode.AUTONOMOUS
    assert p.operational_boundaries.triggers_automations == TriggersAutomations.NONE
    assert p.operational_boundaries.reversible is True
    assert p.operational_boundaries.side_effect_scope == "entity_only"
    assert p.privacy_classification.level == PrivacyLevel.NORMAL
    assert p.semantic_tags == ["lighting.ambient"]


def test_absent_control_mode_defaults_to_confirm() -> None:
    p = SemanticProfile.from_dict("switch.x", {"semantic_profile": {}})
    assert p.operational_boundaries.control_mode == ControlMode.CONFIRM
    assert not p.declared("operational_boundaries.control_mode")


def test_absent_triggers_automations_defaults_to_unknown() -> None:
    p = SemanticProfile.from_dict("switch.x", {"semantic_profile": {}})
    assert p.operational_boundaries.triggers_automations == TriggersAutomations.UNKNOWN


@pytest.mark.parametrize("value", ["autonomous", "confirm", "read_only", "prohibited"])
def test_all_control_mode_values_accepted(value: str) -> None:
    doc = {"semantic_profile": {"operational_boundaries": {"control_mode": value}}}
    p = SemanticProfile.from_dict("light.x", doc)
    assert p.operational_boundaries.control_mode == ControlMode(value)


@pytest.mark.parametrize("value", ["likely", "none", "unknown", "deployment_defined"])
def test_all_triggers_values_accepted(value: str) -> None:
    doc = {"semantic_profile": {"operational_boundaries": {"triggers_automations": value}}}
    p = SemanticProfile.from_dict("sensor.x", doc)
    assert p.operational_boundaries.triggers_automations == TriggersAutomations(value)


@pytest.mark.parametrize("value", ["public", "normal", "sensitive", "restricted"])
def test_all_privacy_levels_accepted(value: str) -> None:
    doc = {"semantic_profile": {}, "privacy_classification": {"level": value}}
    p = SemanticProfile.from_dict("sensor.x", doc)
    assert p.privacy_classification.level == PrivacyLevel(value)


@pytest.mark.parametrize(
    "fixture",
    [
        "missing_confidence.json",
        "missing_generated_at.json",
        "invalid_operator.json",
        "invalid_control_mode.json",
    ],
)
def test_malformed_fixtures_rejected(fixture: str) -> None:
    data = json.loads((MALFORMED_DIR / fixture).read_text())
    report = validate_document(data)
    assert not report.ok, f"{fixture} must be rejected"
    with pytest.raises(MesaValidationError):
        SemanticProfile.from_dict("light.x", data)


def test_trust_laundering_surfaces_warning() -> None:
    data = json.loads((MALFORMED_DIR / "trust_laundering.json").read_text())
    report = validate_document(data)
    assert report.ok  # not a hard rejection
    assert any("trust laundering" in w for w in report.warnings)


def test_absent_metadata_origin_defaults_to_unknown() -> None:
    p = SemanticProfile.from_dict("light.x", KERNEL)
    assert p.metadata.source == MetadataOrigin.UNKNOWN


def test_sidecar_default_origin_is_developer() -> None:
    # Spec 5.3: location-based provenance default for integration sidecar imports.
    p = SemanticProfile.from_dict("light.x", KERNEL, default_origin=MetadataOrigin.DEVELOPER)
    assert p.metadata.source == MetadataOrigin.DEVELOPER


def test_explicit_origin_beats_location_default() -> None:
    doc = {
        "semantic_profile": {
            "metadata_origin": {"source": "user", "confidence": 1.0},
        },
        "privacy_classification": {"level": "normal"},
    }
    p = SemanticProfile.from_dict("light.x", doc, default_origin=MetadataOrigin.DEVELOPER)
    assert p.metadata.source == MetadataOrigin.USER


def test_unknown_fields_survive_round_trip() -> None:
    doc = {
        "semantic_profile": {
            "operational_boundaries": {"control_mode": "confirm"},
            "future_field": {"nested": [1, 2, 3]},
        },
        "privacy_classification": {"level": "normal"},
        "vendor_extension": "kept",
    }
    p = SemanticProfile.from_dict("light.x", doc)
    out = p.to_dict()
    assert out["semantic_profile"]["future_field"] == {"nested": [1, 2, 3]}
    assert out["vendor_extension"] == "kept"


def test_nested_privacy_classification_accepted() -> None:
    doc = {"semantic_profile": {"privacy_classification": {"level": "sensitive"}}}
    p = SemanticProfile.from_dict("camera.x", doc)
    assert p.privacy_classification.level == PrivacyLevel.SENSITIVE
    assert p.declared("privacy_classification.level")


def test_parsing_is_faithful_for_inferred_profiles() -> None:
    # Trust coercions (Spec 5.4 Rules 3/8/9) are applied at resolution time, not
    # parse time: the parsed view reflects the document (see test_inferred.py).
    doc = {
        "semantic_profile": {
            "metadata_origin": {
                "source": "inferred_ai",
                "confidence": 0.9,
                "generated_at": "2026-06-01T00:00:00+00:00",
            },
            "operational_boundaries": {"control_mode": "autonomous"},
        }
    }
    p = SemanticProfile.from_dict("light.x", doc)
    assert p.operational_boundaries.control_mode == ControlMode.AUTONOMOUS
    assert p.is_inferred()


def _inferred_profile(generated_at: str, window: int = 60) -> SemanticProfile:
    return SemanticProfile.from_dict(
        "sensor.x",
        {
            "semantic_profile": {
                "metadata_origin": {
                    "source": "inferred_ai",
                    "confidence": 0.8,
                    "generated_at": generated_at,
                    "staleness_window_days": window,
                }
            }
        },
    )


def test_staleness_status_windows() -> None:
    now = datetime(2026, 6, 10, tzinfo=UTC)
    fresh = _inferred_profile((now - timedelta(days=0)).isoformat())
    mid = _inferred_profile((now - timedelta(days=30)).isoformat())
    stale = _inferred_profile((now - timedelta(days=61)).isoformat())
    assert fresh.staleness_status(now) == "current"
    assert mid.staleness_status(now) == "current"
    assert stale.staleness_status(now) == "stale"


def test_staleness_unknown_when_unparseable() -> None:
    p = _inferred_profile("not-a-date")
    assert p.staleness_status() == "unknown"


def test_trusted_profiles_do_not_decay() -> None:
    p = SemanticProfile.from_dict("light.x", KERNEL)
    assert p.staleness_status() == "current"


def test_invalid_tag_rejected() -> None:
    for bad in ["Lighting.Ambient", "my-vendor.thing", "lighting.not_canonical"]:
        doc = {"semantic_profile": {"semantic_tags": [bad]}}
        report = validate_document(doc)
        assert not report.ok, f"tag {bad!r} must be rejected"


def test_vendor_tag_accepted_as_opaque() -> None:
    doc = {"semantic_profile": {"semantic_tags": ["myvendor.lighting.circadian_advanced"]}}
    assert validate_document(doc).ok


def test_ha_condition_predicate_accepted() -> None:
    # Spec 6.3: native HA condition syntax is accepted alongside canonical tokens.
    doc = {
        "semantic_profile": {
            "operational_boundaries": {
                "control_mode": "autonomous",
                "declared_limits": [
                    {
                        "id": "cinema_mode_limit",
                        "predicate": {
                            "type": "ha_condition",
                            "condition": {
                                "condition": "state",
                                "entity_id": "input_boolean.cinema_mode",
                                "state": "on",
                            },
                        },
                        "limit": {
                            "service": "light.turn_on",
                            "parameter": "brightness",
                            "max_value": 128,
                        },
                    }
                ],
            }
        }
    }
    assert validate_document(doc).ok
    # ha_condition without a condition object is malformed.
    doc["semantic_profile"]["operational_boundaries"]["declared_limits"][0]["predicate"] = {
        "type": "ha_condition"
    }
    assert not validate_document(doc).ok


def test_person_traits_parsed_into_typed_model() -> None:
    doc = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "person_traits": {
                "household_role": "child",
                "is_minor": True,
                "associated_zones": ["zone.school"],
            },
        }
    }
    p = SemanticProfile.from_dict("person.kid", doc)
    assert p.person_traits.is_minor is True
    assert p.person_traits.household_role == "child"
    assert p.person_traits.associated_zones == ["zone.school"]
    assert p.declared("person_traits.is_minor")
    assert not p.declared("person_traits.presence_entity")
    # Raw round-trip is unchanged by the typed model.
    assert p.to_dict()["semantic_profile"]["person_traits"] == doc["semantic_profile"]["person_traits"]


def test_person_traits_programmatic_serialisation() -> None:
    profile = SemanticProfile(
        entity_id="person.kid",
        person_traits=PersonTraits(household_role="child", is_minor=True),
    )
    sp = profile.to_dict()["semantic_profile"]
    assert sp["person_traits"] == {"household_role": "child", "is_minor": True}
    # Undeclared person_traits are omitted entirely.
    assert "person_traits" not in SemanticProfile(entity_id="light.x").to_dict()["semantic_profile"]
