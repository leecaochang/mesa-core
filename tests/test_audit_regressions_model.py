"""Regressions for the 1.2.1 audit: data model, store, portability, leases.

Companion to tests/conformance/test_audit_regressions.py, which covers the
policy findings. Each test fails against 1.2.0.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from mesa_core.backends import MemoryBackend
from mesa_core.exceptions import InvalidCursorError, MesaValidationError
from mesa_core.integration_import import import_from_integration
from mesa_core.lease import LeaseManager
from mesa_core.portability import import_profiles
from mesa_core.profile import ControlMode, SemanticProfile
from mesa_core.store import DeploymentDefaults, ProfileStore

from .conformance.test_conflict import make_profile

T0 = datetime(2026, 7, 15, 12, 0, 0)


def store() -> ProfileStore:
    return ProfileStore(backend=MemoryBackend())


# ------------------------------------------------- enrichment survives resolution


ENRICHED = {
    "semantic_profile": {
        "metadata_origin": {"source": "user"},
        "semantic_tags": ["lighting.ambient"],
        "helper_traits": {"controls_automations": ["automation.night"]},
        "semantic_routing": {"intent_tags": ["evening_scene"]},
        "x_vendor_ext": {"hello": "world"},
        "operational_boundaries": {"control_mode": "confirm", "x_vendor_flag": True},
    },
    "privacy_classification": {"level": "normal", "x_vendor_privacy": "note"},
}


@pytest.mark.parametrize(
    "field", ["helper_traits", "semantic_routing", "x_vendor_ext", "semantic_tags"]
)
def test_effective_profile_keeps_unmodelled_fields(field: str) -> None:
    """A complete effective profile stays complete (Spec 23 forward compatibility)."""
    s = store()
    s.set("light.den", SemanticProfile.from_dict("light.den", ENRICHED))
    assert field in s.get_effective("light.den").to_dict()["semantic_profile"]


def test_effective_profile_keeps_nested_unmodelled_fields() -> None:
    s = store()
    s.set("light.den", SemanticProfile.from_dict("light.den", ENRICHED))
    doc = s.get_effective("light.den").to_dict()
    assert doc["semantic_profile"]["operational_boundaries"]["x_vendor_flag"] is True
    assert doc["privacy_classification"]["x_vendor_privacy"] == "note"


def test_inherited_enrichment_is_carried_from_the_domain_layer() -> None:
    s = store()
    s.set_domain_profile(
        "light",
        SemanticProfile.from_dict(
            "light",
            {
                "semantic_profile": {
                    "metadata_origin": {"source": "developer"},
                    "x_domain_ext": {"from": "domain"},
                }
            },
        ),
    )
    s.set("light.den", make_profile("light.den"))
    assert s.get_effective("light.den").to_dict()["semantic_profile"]["x_domain_ext"] == {
        "from": "domain"
    }


def test_more_specific_layer_wins_for_unmodelled_fields() -> None:
    s = ProfileStore(backend=MemoryBackend(), get_entity_device=lambda eid: "light")
    for scope, setter in (("domain", s.set_domain_profile), ("device", s.set_device_profile)):
        setter(
            "light",
            SemanticProfile.from_dict(
                "light",
                {
                    "semantic_profile": {
                        "metadata_origin": {"source": "developer"},
                        "x_ext": scope,
                    }
                },
            ),
        )
    s.set(
        "light.den",
        SemanticProfile.from_dict(
            "light.den",
            {"semantic_profile": {"metadata_origin": {"source": "user"}, "x_ext": "entity"}},
        ),
    )
    assert s.get_effective("light.den").to_dict()["semantic_profile"]["x_ext"] == "entity"


# -------------------------------------------------- edits are not silently dropped


def test_mutating_a_parsed_profile_then_storing_it_persists_the_edit() -> None:
    """get, tighten, set is the natural read-modify-write; it used to no-op."""
    s = store()
    s.set("light.z", make_profile("light.z", boundaries={"control_mode": "confirm"}))
    profile = s.get("light.z")
    assert profile is not None
    profile.operational_boundaries.control_mode = ControlMode.PROHIBITED
    s.set("light.z", profile)
    reloaded = s.get("light.z")
    assert reloaded is not None
    assert reloaded.operational_boundaries.control_mode == ControlMode.PROHIBITED


def test_mutation_reflected_in_to_dict() -> None:
    profile = make_profile("light.z", boundaries={"control_mode": "confirm"})
    profile.operational_boundaries.control_mode = ControlMode.PROHIBITED
    doc = profile.to_dict()
    assert doc["semantic_profile"]["operational_boundaries"]["control_mode"] == "prohibited"


def test_roundtrip_of_an_untouched_profile_is_stable() -> None:
    original = SemanticProfile.from_dict("light.den", ENRICHED)
    once = original.to_dict()
    twice = SemanticProfile.from_dict("light.den", once).to_dict()
    assert once == twice


def test_programmatic_profile_does_not_serialise_defaults_as_declarations() -> None:
    """Rule E reads declarations, so inventing them changes inheritance."""
    profile = SemanticProfile(entity_id="light.x")
    profile.semantic_tags = ["lighting.ambient"]
    doc = profile.to_dict()
    boundaries = doc["semantic_profile"].get("operational_boundaries", {})
    assert "control_mode" not in boundaries
    assert "triggers_automations" not in boundaries
    assert "privacy_classification" not in doc
    assert not SemanticProfile.from_dict("light.x", doc).declared(
        "operational_boundaries.control_mode"
    )


def test_programmatic_profile_serialises_a_non_default_value() -> None:
    profile = SemanticProfile(entity_id="light.x")
    profile.operational_boundaries.control_mode = ControlMode.PROHIBITED
    doc = profile.to_dict()
    assert doc["semantic_profile"]["operational_boundaries"]["control_mode"] == "prohibited"
    assert SemanticProfile.from_dict("light.x", doc).declared(
        "operational_boundaries.control_mode"
    )


def test_declared_default_survives_a_roundtrip() -> None:
    """An explicitly declared confirm must stay declared, not vanish as a default."""
    profile = make_profile("light.x", boundaries={"control_mode": "confirm"})
    doc = profile.to_dict()
    assert doc["semantic_profile"]["operational_boundaries"]["control_mode"] == "confirm"
    assert SemanticProfile.from_dict("light.x", doc).declared(
        "operational_boundaries.control_mode"
    )


# ------------------------------------------------------ diagnostic profile (Rule D)


def test_untrusted_entity_diagnostic_does_not_displace_a_trusted_domain_one() -> None:
    s = store()
    s.set_domain_profile(
        "light",
        SemanticProfile.from_dict(
            "light",
            {
                "semantic_profile": {"metadata_origin": {"source": "developer"}},
                "diagnostic_profile": {"source": "developer-domain"},
            },
        ),
    )
    s.set(
        "light.x",
        SemanticProfile.from_dict(
            "light.x",
            {
                "semantic_profile": {
                    "metadata_origin": {
                        "source": "inferred_ai",
                        "confidence": 0.8,
                        "generated_at": "2026-01-01T00:00:00",
                    }
                },
                "diagnostic_profile": {"source": "inferred-entity"},
            },
        ),
    )
    assert s.get_effective("light.x").diagnostic_profile == {"source": "developer-domain"}


def test_trusted_entity_diagnostic_still_wins_on_scope() -> None:
    s = store()
    s.set_domain_profile(
        "light",
        SemanticProfile.from_dict(
            "light",
            {
                "semantic_profile": {"metadata_origin": {"source": "developer"}},
                "diagnostic_profile": {"source": "developer-domain"},
            },
        ),
    )
    s.set(
        "light.x",
        SemanticProfile.from_dict(
            "light.x",
            {
                "semantic_profile": {"metadata_origin": {"source": "user"}},
                "diagnostic_profile": {"source": "user-entity"},
            },
        ),
    )
    assert s.get_effective("light.x").diagnostic_profile == {"source": "user-entity"}


# ------------------------------------------------------------- cursors (Spec 9.2)


def test_cursor_is_invalidated_by_a_profile_content_change() -> None:
    s = store()
    for i in range(5):
        s.set(f"light.l{i}", make_profile(f"light.l{i}", boundaries={"control_mode": "confirm"}))
    cursor = s.query(limit=2).next_cursor
    assert cursor is not None
    s.set("light.l3", make_profile("light.l3", boundaries={"control_mode": "prohibited"}))
    with pytest.raises(InvalidCursorError, match="invalidated by profile changes"):
        s.query(limit=2, cursor=cursor)


def test_cursor_still_works_when_nothing_changed() -> None:
    s = store()
    for i in range(5):
        s.set(f"light.l{i}", make_profile(f"light.l{i}"))
    cursor = s.query(limit=2).next_cursor
    assert [row.entity_id for row in s.query(limit=2, cursor=cursor).rows] == [
        "light.l2",
        "light.l3",
    ]


# ------------------------------------------------------- portable import (4.12)


def test_import_rejects_a_reserved_key_in_the_entities_section() -> None:
    s = store()
    archive = {
        "mesa_export": {
            "format_version": "1.0",
            "entities": {
                "__domain__:lock": {
                    "semantic_profile": {
                        "metadata_origin": {"source": "user"},
                        "operational_boundaries": {"control_mode": "autonomous"},
                    }
                }
            },
        }
    }
    result = import_profiles(s, archive)
    assert result.imported == 0
    assert "entities:__domain__:lock" in result.invalid
    assert s.get_domain_profile("lock") is None


def test_import_quarantines_a_non_object_section() -> None:
    result = import_profiles(
        store(), {"mesa_export": {"format_version": "1.0", "entities": ["not", "a", "dict"]}}
    )
    assert "entities" in result.invalid


@pytest.mark.parametrize("defaults", ["garbage", 42, ["a"], None])
def test_import_quarantines_non_object_deployment_defaults(defaults: Any) -> None:
    # Explicit null is a wrong type like any other non-object, not "absent".
    result = import_profiles(
        store(), {"mesa_export": {"format_version": "1.0", "deployment_defaults": defaults}}
    )
    assert "deployment_defaults" in result.invalid


def test_import_of_an_omitted_section_is_fine() -> None:
    result = import_profiles(store(), {"mesa_export": {"format_version": "1.0"}})
    assert result.ok


@pytest.mark.parametrize("section", ["entities", "domains", "areas"])
def test_import_rejects_an_explicit_null_section(section: str) -> None:
    result = import_profiles(
        store(), {"mesa_export": {"format_version": "1.0", section: None}}
    )
    assert section in result.invalid


def test_roundtrip_export_import_still_works() -> None:
    from mesa_core.portability import export_profiles

    source = store()
    source.set("light.a", make_profile("light.a", boundaries={"control_mode": "confirm"}))
    source.set_domain_profile("lock", make_profile("lock", boundaries={"control_mode": "prohibited"}))
    target = store()
    result = import_profiles(target, export_profiles(source))
    assert result.ok and result.imported == 2
    assert target.get_domain_profile("lock") is not None


# --------------------------------------------------- deployment defaults (Spec 5.8)


@pytest.mark.parametrize(
    "overrides",
    [
        {"light": "not-a-dict"},
        {"light": ["control_mode"]},
        {"light": None},
        {"light": {"control_mode": "bogus"}},
        {"light": {"triggers_automations": "bogus"}},
        {"lock": "control_mode is prohibited"},
    ],
)
def test_malformed_domain_overrides_rejected_at_parse(overrides: Any) -> None:
    with pytest.raises(MesaValidationError):
        DeploymentDefaults.from_dict({"domain_overrides": overrides})


def test_wellformed_domain_overrides_accepted() -> None:
    defaults = DeploymentDefaults.from_dict(
        {"default_control_mode": "confirm", "domain_overrides": {"light": {"control_mode": "autonomous"}}}
    )
    assert defaults.control_mode_for("light") == ControlMode.AUTONOMOUS


def test_malformed_triggers_domains_rejected() -> None:
    with pytest.raises(MesaValidationError, match="array of strings"):
        DeploymentDefaults.from_dict({"triggers_automations_domains": "input_boolean"})


# -------------------------------------------------- integration sidecar (Spec 8)


def test_invalid_json_sidecar_raises_the_documented_error(tmp_path: Path) -> None:
    (tmp_path / "mesa_profile.json").write_text('{"semantic_profile": {')
    with pytest.raises(MesaValidationError, match="not valid JSON"):
        import_from_integration(tmp_path)


def test_valid_sidecar_still_imports(tmp_path: Path) -> None:
    (tmp_path / "mesa_profile.json").write_text(
        json.dumps({"semantic_profile": {"operational_boundaries": {"control_mode": "confirm"}}})
    )
    profile = import_from_integration(tmp_path)
    assert profile is not None and profile.inheritance_scope == "integration"


# ----------------------------------------------------------- leases (Spec 21.4)


def test_same_session_refresh_supersedes_rather_than_overlapping() -> None:
    manager = LeaseManager()
    first = manager.request(["light.kitchen"], 10.0, session_id="s1", now=T0)
    second = manager.request(
        ["light.kitchen"], 10.0, session_id="s1", now=T0 + timedelta(seconds=5)
    )
    active = manager.active_leases(T0 + timedelta(seconds=5))
    assert len(active) == 1
    assert active[0].lease_id == second.lease_id
    assert first.lease_id != second.lease_id


def test_refresh_does_not_fire_a_phantom_expiry_for_a_held_entity() -> None:
    """mesa_lease_expired tells automations to resume; the hold is continuous."""
    events: list[dict[str, Any]] = []
    manager = LeaseManager(on_lease_event=events.append)
    manager.request(["light.kitchen"], 10.0, session_id="s1", now=T0)
    manager.request(["light.kitchen"], 10.0, session_id="s1", now=T0 + timedelta(seconds=5))
    manager.expire(T0 + timedelta(seconds=10))
    assert events == []
    assert manager.active_leases(T0 + timedelta(seconds=10))


def test_refresh_keeps_entities_the_new_request_did_not_cover() -> None:
    manager = LeaseManager()
    manager.request(["light.a", "light.b"], 10.0, session_id="s1", now=T0)
    manager.request(["light.a"], 10.0, session_id="s1", now=T0 + timedelta(seconds=1))
    held = {e for lease in manager.active_leases(T0 + timedelta(seconds=1)) for e in lease.entities}
    assert held == {"light.a", "light.b"}


def test_releasing_the_returned_lease_frees_the_entity_after_a_refresh() -> None:
    manager = LeaseManager()
    manager.request(["light.kitchen"], 30.0, session_id="s1", now=T0)
    second = manager.request(
        ["light.kitchen"], 30.0, session_id="s1", now=T0 + timedelta(seconds=1)
    )
    manager.release(second.lease_id, session_id="s1", now=T0 + timedelta(seconds=2))
    other = manager.request(
        ["light.kitchen"], 30.0, session_id="s2", now=T0 + timedelta(seconds=3)
    )
    assert other.granted


def test_repeated_refreshes_do_not_accumulate_leases() -> None:
    manager = LeaseManager()
    for i in range(20):
        manager.request(["light.kitchen"], 30.0, session_id="s1", now=T0 + timedelta(seconds=i))
    assert len(manager.active_leases(T0 + timedelta(seconds=20))) == 1


def test_a_raising_event_callback_does_not_abandon_session_releases() -> None:
    """Spec 21.4: session termination releases all associated leases."""

    def boom(_event: dict[str, Any]) -> None:
        raise RuntimeError("host event bus is down")

    manager = LeaseManager(on_lease_event=boom)
    for i in range(5):
        manager.request([f"light.y{i}"], 30.0, session_id="doomed", now=T0)
    assert manager.release_session("doomed", now=T0 + timedelta(seconds=1)) == 5
    assert manager.active_leases(T0 + timedelta(seconds=1)) == []


def test_a_raising_get_state_denies_rather_than_escaping() -> None:
    def boom(_entity: str) -> str:
        raise RuntimeError("HA down")

    s = store()
    s.set(
        "automation.night",
        SemanticProfile.from_dict(
            "automation.night",
            {
                "semantic_profile": {
                    "metadata_origin": {"source": "user"},
                    "cooperative_priority": {"level": "protected"},
                    "environmental_dependencies": {"trigger_entities": ["light.kitchen"]},
                }
            },
        ),
    )
    manager = LeaseManager(s, get_state=boom)
    response = manager.request(["light.kitchen"], 10.0, session_id="s1", now=T0)
    assert not response.granted
    assert any("fail-closed" in w for w in response.warnings)


def test_concurrent_requests_for_one_entity_grant_exactly_once() -> None:
    """arequest offloads to threads, and granting is a check-then-act."""
    import asyncio

    async def main() -> list[Any]:
        manager = LeaseManager()
        return await asyncio.gather(
            *(
                manager.arequest(["light.kitchen"], 30.0, session_id=f"session-{i}")
                for i in range(8)
            )
        )

    for _ in range(30):
        responses = asyncio.run(main())
        assert sum(1 for r in responses if r.granted) == 1


# =================================================================
# Second-audit regressions (1.2.1 remediation retest)
# =================================================================


def test_cursor_invalidated_by_inherited_domain_change() -> None:
    """The fingerprint must cover inherited layers: a domain-tag change can move
    a row across the page boundary without any entity document changing."""
    s = store()
    for i in range(5):
        s.set(f"light.l{i}", make_profile(f"light.l{i}", tags=["lighting.ambient"]))
    cursor = s.query(limit=2).next_cursor
    assert cursor is not None
    s.set_domain_profile("light", make_profile("light", tags=["lighting.task"]))
    with pytest.raises(InvalidCursorError, match="invalidated by profile changes"):
        s.query(limit=2, cursor=cursor)


def test_cursor_invalidated_by_deployment_defaults_change() -> None:
    s = store()
    for i in range(5):
        s.set(f"light.l{i}", make_profile(f"light.l{i}"))
    cursor = s.query(limit=2).next_cursor
    assert cursor is not None
    s.set_deployment_defaults(DeploymentDefaults(default_control_mode=ControlMode.PROHIBITED))
    with pytest.raises(InvalidCursorError, match="invalidated by profile changes"):
        s.query(limit=2, cursor=cursor)


def test_intent_filter_matches_inherited_routing() -> None:
    """intent_tags inherited from a domain profile are exposed by get_effective,
    so the intent filter must match them too (Spec 9.2)."""
    s = store()
    s.set_domain_profile("light", SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "user"}, "semantic_routing": {"intent_tags": ["evening"]}}}))
    s.set("light.x", make_profile("light.x", tags=["lighting.ambient"]))
    rows = s.query(intents=["evening"]).rows
    assert [r.entity_id for r in rows] == ["light.x"]


def test_set_rejects_a_mutation_that_makes_the_profile_invalid() -> None:
    """Read-modify-write must not be able to poison the store (validate on write)."""
    from mesa_core.profile import MetadataOrigin

    s = store()
    s.set("light.z", make_profile("light.z", boundaries={"control_mode": "confirm"}))
    p = s.get("light.z")
    assert p is not None
    p.metadata.source = MetadataOrigin.INFERRED_AI  # now missing confidence/generated_at
    with pytest.raises(MesaValidationError):
        s.set("light.z", p)
    # The store still holds the original, loadable profile.
    reloaded = s.get("light.z")
    assert reloaded is not None
    assert reloaded.metadata.source == MetadataOrigin.USER


def test_set_still_accepts_a_valid_mutation() -> None:
    from mesa_core.profile import ControlMode as CM

    s = store()
    s.set("light.z", make_profile("light.z", boundaries={"control_mode": "confirm"}))
    p = s.get("light.z")
    assert p is not None
    p.operational_boundaries.control_mode = CM.PROHIBITED
    s.set("light.z", p)
    assert s.get("light.z").operational_boundaries.control_mode == CM.PROHIBITED


# =================================================================
# Third-audit regressions (second remediation retest)
# =================================================================


def test_unconfirmed_hybrid_enrichment_cannot_override_developer() -> None:
    """Rule D is per field for hybrid, including unmodelled enrichment: a hybrid
    layer that confirmed only semantic_tags cannot overwrite a developer vendor
    field."""
    s = store()
    s.set_domain_profile("light", SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_policy": "trusted"}}))
    s.set("light.x", SemanticProfile.from_dict("light.x", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["semantic_tags"]},
        "x_policy": "hijacked"}}))
    assert s.get_effective("light.x").to_dict()["semantic_profile"]["x_policy"] == "trusted"


def test_confirmed_hybrid_enrichment_does_override_developer() -> None:
    s = store()
    s.set_domain_profile("light", SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_policy": "trusted"}}))
    s.set("light.x", SemanticProfile.from_dict("light.x", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["x_policy"]},
        "x_policy": "confirmed"}}))
    assert s.get_effective("light.x").to_dict()["semantic_profile"]["x_policy"] == "confirmed"


def test_inferred_only_enrichment_is_still_carried() -> None:
    """A lower-tier field with no trusted competitor is not dropped."""
    s = store()
    s.set("light.z", SemanticProfile.from_dict("light.z", {"semantic_profile": {
        "metadata_origin": {"source": "inferred_ai", "confidence": 0.9,
                            "generated_at": "2026-01-01T00:00:00"},
        "x_hint": "kept"}}))
    assert s.get_effective("light.z").to_dict()["semantic_profile"]["x_hint"] == "kept"


def test_set_rejects_a_malformed_typed_field_with_controlled_error() -> None:
    """A malformed typed field must fail the write as MesaValidationError, not a
    raw AttributeError from serialization."""
    s = store()
    s.set("light.z", make_profile("light.z", boundaries={"control_mode": "confirm"}))
    p = s.get("light.z")
    assert p is not None
    p.operational_boundaries.control_mode = "bogus"  # type: ignore[assignment]
    with pytest.raises(MesaValidationError):
        s.set("light.z", p)


def test_set_deployment_defaults_revalidates_a_mutated_dataclass() -> None:
    """A mutable DeploymentDefaults mutated to an invalid shape must not write."""
    s = store()
    defaults = DeploymentDefaults()
    defaults.domain_overrides = {"light": "bad"}  # type: ignore[dict-item]
    with pytest.raises(MesaValidationError):
        s.set_deployment_defaults(defaults)
    assert s.get_deployment_defaults() is None


def test_set_deployment_defaults_still_accepts_a_valid_dataclass() -> None:
    s = store()
    s.set_deployment_defaults(DeploymentDefaults(default_control_mode=ControlMode.AUTONOMOUS))
    assert s.get_deployment_defaults() is not None


# =================================================================
# Fourth-audit regressions
# =================================================================


@pytest.mark.parametrize("bad", [
    {"default_control_mode": "bogus"},
    {"domain_overrides": {"light": "not-an-object"}},
    {"triggers_automations_domains": [1]},
])
def test_import_quarantines_a_malformed_defaults_object(bad: dict) -> None:
    """DeploymentDefaults.from_dict now raises MesaValidationError; a malformed
    defaults object must be quarantined, not abort the whole import."""
    result = import_profiles(store(), {"mesa_export": {"format_version": "1.0",
                                                       "deployment_defaults": bad}})
    assert "deployment_defaults" in result.invalid
    assert not result.ok


def test_nested_enrichment_composes_disjoint_subfields() -> None:
    """Rule E per subfield: a developer subfield and an inferred-only subfield of
    the same object both survive (the object is not resolved atomically)."""
    s = store()
    s.set_domain_profile("light", SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "helper_traits": {"note": "dev"}}}))
    s.set("light.x", SemanticProfile.from_dict("light.x", {"semantic_profile": {
        "metadata_origin": {"source": "inferred_ai", "confidence": 0.9,
                            "generated_at": "2026-01-01T00:00:00"},
        "helper_traits": {"new_hint": "inferred-only"}}}))
    ht = s.get_effective("light.x").to_dict()["semantic_profile"]["helper_traits"]
    assert ht == {"note": "dev", "new_hint": "inferred-only"}


def test_hybrid_can_confirm_a_nested_enrichment_subfield() -> None:
    s = store()
    s.set_domain_profile("light", SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "helper_traits": {"note": "dev"}}}))
    s.set("light.x", SemanticProfile.from_dict("light.x", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["helper_traits.note"]},
        "helper_traits": {"note": "confirmed"}}}))
    assert s.get_effective("light.x").to_dict()["semantic_profile"]["helper_traits"] == {
        "note": "confirmed"}


def test_unconfirmed_hybrid_nested_subfield_cannot_override_developer() -> None:
    s = store()
    s.set_domain_profile("light", SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "helper_traits": {"note": "dev"}}}))
    s.set("light.x", SemanticProfile.from_dict("light.x", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["semantic_tags"]},
        "helper_traits": {"note": "hijack"}}}))
    assert s.get_effective("light.x").to_dict()["semantic_profile"]["helper_traits"] == {
        "note": "dev"}


def test_profile_valid_for_is_inherited_when_the_specific_layer_omits_it() -> None:
    """Rule E: a domain invalidation trigger must not vanish when the entity
    profile omits profile_valid_for."""
    s = store()
    s.set_domain_profile("light", SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"},
        "profile_valid_for": {"conditions": ["dev-trigger"]}}}))
    s.set("light.x", SemanticProfile.from_dict("light.x", {"semantic_profile": {
        "metadata_origin": {"source": "user"}}}))
    assert s.get_effective("light.x").metadata.profile_valid_for == {"conditions": ["dev-trigger"]}


def test_unconfirmed_hybrid_profile_valid_for_cannot_overwrite_developer() -> None:
    s = store()
    s.set_domain_profile("light", SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"},
        "profile_valid_for": {"conditions": ["dev"]}}}))
    s.set("light.x", SemanticProfile.from_dict("light.x", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["semantic_tags"]},
        "profile_valid_for": {"conditions": ["hijack"]}}}))
    assert s.get_effective("light.x").metadata.profile_valid_for == {"conditions": ["dev"]}


def test_resolving_profile_valid_for_does_not_mutate_the_layer() -> None:
    s = store()
    s.set_domain_profile("light", SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"},
        "profile_valid_for": {"conditions": ["dev"]}}}))
    s.set("light.x", SemanticProfile.from_dict("light.x", {"semantic_profile": {
        "metadata_origin": {"source": "user"},
        "profile_valid_for": {"conditions": ["entity"]}}}))
    assert s.get_effective("light.x").metadata.profile_valid_for == {"conditions": ["entity"]}
    assert s.get_domain_profile("light").metadata.profile_valid_for == {"conditions": ["dev"]}
