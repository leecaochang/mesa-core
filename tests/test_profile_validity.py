"""SemanticProfile.validity_warnings: profile_valid_for evaluation (Spec 5.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mesa_core.backends import MemoryBackend
from mesa_core.profile import SemanticProfile
from mesa_core.store import ProfileStore

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def profile(pvf: dict[str, Any], *, last_updated: str | None = None) -> SemanticProfile:
    sp: dict[str, Any] = {
        "metadata_origin": {"source": "user"},
        "profile_valid_for": pvf,
    }
    if last_updated is not None:
        sp["last_updated"] = last_updated
    return SemanticProfile.from_dict("light.x", {"semantic_profile": sp})


def test_no_declaration_is_silent() -> None:
    p = SemanticProfile.from_dict(
        "light.x", {"semantic_profile": {"metadata_origin": {"source": "user"}}}
    )
    assert p.validity_warnings(now=NOW) == []


def test_overdue_review_warns() -> None:
    p = profile({"review_after_days": 30}, last_updated="2026-01-01T00:00:00+00:00")
    warnings = p.validity_warnings(now=NOW)
    assert len(warnings) == 1 and "due for review" in warnings[0]


def test_review_within_window_is_silent() -> None:
    p = profile({"review_after_days": 365}, last_updated="2026-07-01T00:00:00+00:00")
    assert p.validity_warnings(now=NOW) == []


def test_review_anchor_falls_back_to_generated_at() -> None:
    doc = {
        "semantic_profile": {
            "metadata_origin": {
                "source": "inferred_ai",
                "confidence": 0.9,
                "generated_at": "2026-01-01T00:00:00+00:00",
            },
            "profile_valid_for": {"review_after_days": 30},
        }
    }
    p = SemanticProfile.from_dict("light.x", doc)
    warnings = p.validity_warnings(now=NOW)
    assert len(warnings) == 1 and "due for review" in warnings[0]


def test_unevaluable_anchor_warns_instead_of_silence() -> None:
    p = profile({"review_after_days": 30})  # no last_updated, no generated_at
    warnings = p.validity_warnings(now=NOW)
    assert len(warnings) == 1 and "cannot be evaluated" in warnings[0]

    garbled = profile({"review_after_days": 30}, last_updated="yesterday-ish")
    warnings = garbled.validity_warnings(now=NOW)
    assert len(warnings) == 1 and "cannot be evaluated" in warnings[0]


def test_mixed_timezone_awareness_compares_wall_clocks() -> None:
    p = profile({"review_after_days": 30}, last_updated="2026-01-01T00:00:00")
    assert any("due for review" in w for w in p.validity_warnings(now=NOW))


def test_invalidated_by_entities_requires_registry() -> None:
    p = profile({"invalidated_by_entities": ["light.gone", "light.kept"]})
    # No registry supplied: the check is skipped without noise.
    assert p.validity_warnings(now=NOW) == []
    warnings = p.validity_warnings(now=NOW, known_entity_ids=["light.kept"])
    assert len(warnings) == 1 and "light.gone" in warnings[0]
    assert p.validity_warnings(now=NOW, known_entity_ids=["light.kept", "light.gone"]) == []


def test_version_pins_compare_exact_strings() -> None:
    p = profile({"integration_version": "2.4.1", "ha_version": "2026.5"})
    assert p.validity_warnings(now=NOW) == []  # no current versions supplied
    assert p.validity_warnings(now=NOW, integration_version="2.4.1", ha_version="2026.5") == []
    warnings = p.validity_warnings(now=NOW, integration_version="2.5.0", ha_version="2026.8")
    assert len(warnings) == 2
    assert any("integration_version mismatch" in w for w in warnings)
    assert any("ha_version mismatch" in w for w in warnings)


def test_evaluates_merged_effective_profile() -> None:
    # profile_valid_for resolves per subfield across layers; the effective
    # profile carries the merged object, and both subfields evaluate.
    store = ProfileStore(backend=MemoryBackend())
    store.set_integration_profile(
        "light",
        SemanticProfile.from_dict(
            "light",
            {
                "semantic_profile": {
                    "metadata_origin": {"source": "developer"},
                    "last_updated": "2026-01-01T00:00:00+00:00",
                    "profile_valid_for": {"review_after_days": 30},
                }
            },
        ),
    )
    store.set(
        "light.x",
        SemanticProfile.from_dict(
            "light.x",
            {
                "semantic_profile": {
                    "metadata_origin": {"source": "user"},
                    "last_updated": "2026-01-01T00:00:00+00:00",
                    "profile_valid_for": {"invalidated_by_entities": ["light.gone"]},
                }
            },
        ),
    )
    effective = store.get_effective("light.x")
    warnings = effective.validity_warnings(now=NOW, known_entity_ids=["light.x"])
    assert any("due for review" in w for w in warnings)
    assert any("light.gone" in w for w in warnings)


# ------------- staleness reflects invalidation triggers (Spec 5.4, audit 11 F1)


def inferred(pvf: dict[str, Any], *, generated: str, last_updated: str | None = None):
    sp: dict[str, Any] = {
        "metadata_origin": {"source": "inferred_ai", "confidence": 0.9, "generated_at": generated},
        "profile_valid_for": pvf,
    }
    if last_updated is not None:
        sp["last_updated"] = last_updated
    return SemanticProfile.from_dict("light.x", {"semantic_profile": sp})


def test_fired_review_window_makes_an_inferred_profile_stale() -> None:
    # Spec 5.4: stale is "age exceeded OR an invalidation trigger fired".
    # The age here is fresh; only the review window has elapsed.
    p = inferred(
        {"review_after_days": 30},
        generated="2026-07-30T00:00:00+00:00",
        last_updated="2026-01-01T00:00:00+00:00",
    )
    assert p.staleness_status(NOW) == "stale"


def test_fired_version_pin_makes_an_inferred_profile_stale() -> None:
    p = inferred({"integration_version": "2.4.1"}, generated="2026-07-30T00:00:00+00:00")
    assert p.staleness_status(NOW) == "current"  # no host version supplied
    assert p.staleness_status(NOW, integration_version="2.4.1") == "current"
    assert p.staleness_status(NOW, integration_version="2.5.0") == "stale"


def test_fired_entity_invalidation_makes_an_inferred_profile_stale() -> None:
    p = inferred({"invalidated_by_entities": ["light.gone"]}, generated="2026-07-30T00:00:00+00:00")
    assert p.staleness_status(NOW) == "current"  # no registry supplied
    assert p.staleness_status(NOW, known_entity_ids=["light.x"]) == "stale"
    assert p.staleness_status(NOW, known_entity_ids=["light.x", "light.gone"]) == "current"


def test_fired_trigger_outranks_unknown_age() -> None:
    # A fired trigger is definite evidence; an undeterminable age is not.
    # Rule 1 requires generated_at on an inferred profile, so the reachable
    # unknown-age case is a present-but-unparseable timestamp.
    doc: dict[str, Any] = {
        "semantic_profile": {
            "metadata_origin": {
                "source": "inferred_ai",
                "confidence": 0.9,
                "generated_at": "sometime last spring",
            },
            "last_updated": "2026-01-01T00:00:00+00:00",
            "profile_valid_for": {"review_after_days": 30},
        }
    }
    p = SemanticProfile.from_dict("light.x", doc)
    assert p.staleness_status(NOW) == "stale"
    # Without the fired trigger the same profile is unknown, not stale.
    del doc["semantic_profile"]["profile_valid_for"]
    assert SemanticProfile.from_dict("light.x", doc).staleness_status(NOW) == "unknown"


def test_unevaluable_trigger_does_not_flip_the_status() -> None:
    # Declared but unanchored review window: reported as a warning, but it has
    # not fired, so a fresh profile stays current.
    doc = {
        "semantic_profile": {
            "metadata_origin": {
                "source": "inferred_ai",
                "confidence": 0.9,
                "generated_at": "2026-07-30T00:00:00+00:00",
            },
            "profile_valid_for": {"review_after_days": 30},
        }
    }
    p = SemanticProfile.from_dict("light.x", doc)
    # generated_at anchors review_after_days here, so use a doc with neither.
    bare = SemanticProfile.from_dict(
        "light.x",
        {
            "semantic_profile": {
                "metadata_origin": {"source": "user"},
                "profile_valid_for": {"review_after_days": 30},
            }
        },
    )
    assert any("cannot be evaluated" in w for w in bare.validity_warnings(now=NOW))
    assert p.staleness_status(NOW) == "current"


def test_trusted_profiles_still_do_not_decay() -> None:
    # Spec 5.4 scopes staleness_status to inferred profiles; a user profile
    # with a fired trigger surfaces a warning but is not "stale".
    p = profile({"review_after_days": 1}, last_updated="2026-01-01T00:00:00+00:00")
    assert p.staleness_status(NOW) == "current"
    assert p.validity_warnings(now=NOW)
