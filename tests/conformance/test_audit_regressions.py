"""Regressions for the 1.2.1 security audit.

Each test reproduces a fail-open or contract break found in 1.2.0 and fails
against that release. Grouped by the finding they pin so the reason a check
exists stays legible.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import pytest

from mesa_core import validation
from mesa_core.backends import MemoryBackend
from mesa_core.conflict import ConflictResolver, Layer
from mesa_core.enforcer import MesaEnforcer
from mesa_core.exceptions import MesaError, MesaValidationError
from mesa_core.mcp.tools import MesaToolHandlers
from mesa_core.privacy import CallerContext
from mesa_core.profile import ControlMode, SemanticProfile, TriggersAutomations
from mesa_core.store import DeploymentDefaults, ProfileStore

from .test_conflict import make_profile

SATURDAY_NOON = datetime(2026, 1, 3, 12, 0)


def store() -> ProfileStore:
    return ProfileStore(backend=MemoryBackend())


def inferred(entity_id: str, **boundaries: Any) -> SemanticProfile:
    return make_profile(entity_id, origin="inferred_ai", boundaries=boundaries or None)


# ---------------------------------------------- baseline scope (Spec 5.8, Rule 8)


@pytest.mark.parametrize("origin", ["user", "developer", "inferred_ai", "hybrid"])
def test_profiled_light_without_control_mode_defaults_to_confirm(origin: str) -> None:
    """The built-in baseline is for entities with no profile at any level.

    A light profile carrying only tags resolved to autonomous, which is a silent
    autonomous default (Spec 4) and, for inferred profiles, a Rule 8 violation.
    """
    s = store()
    s.set("light.kitchen", make_profile("light.kitchen", origin=origin, tags=["lighting.ambient"]))
    effective = s.get_effective("light.kitchen")
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM


def test_unprofiled_light_still_gets_the_autonomous_baseline() -> None:
    """The baseline itself is unchanged: it still applies where it is scoped to."""
    assert (
        store().get_effective("light.kitchen").operational_boundaries.control_mode
        == ControlMode.AUTONOMOUS
    )


def test_deployment_default_does_not_loosen_an_untrusted_profile() -> None:
    """Rule 8: an inferred profile defaults to confirm regardless of domain."""
    s = store()
    s.set_deployment_defaults(DeploymentDefaults(default_control_mode=ControlMode.AUTONOMOUS))
    s.set("light.kitchen", inferred("light.kitchen"))
    assert (
        s.get_effective("light.kitchen").operational_boundaries.control_mode
        == ControlMode.CONFIRM
    )


def test_deployment_default_does_not_loosen_a_profiled_entity() -> None:
    """deployment_defaults are for unprofiled entities; a profiled one loosens
    only via the Rule A override (Spec 4 control_mode precedence, Spec 5.8). A
    profiled entity that leaves control_mode undeclared defaults to confirm even
    when an autonomous deployment default is configured."""
    s = store()
    s.set_deployment_defaults(DeploymentDefaults(default_control_mode=ControlMode.AUTONOMOUS))
    s.set("light.kitchen", make_profile("light.kitchen", tags=["lighting.ambient"]))
    assert (
        s.get_effective("light.kitchen").operational_boundaries.control_mode
        == ControlMode.CONFIRM
    )


def test_deployment_default_applies_to_an_unprofiled_entity() -> None:
    """The floor still rescues an entity with no profile at any level."""
    s = store()
    s.set_deployment_defaults(DeploymentDefaults(default_control_mode=ControlMode.AUTONOMOUS))
    assert (
        s.get_effective("switch.porch").operational_boundaries.control_mode
        == ControlMode.AUTONOMOUS
    )


# ------------------------------------------- confirmed_fields self-certification


def test_confirmed_fields_rejected_on_inferred_origin() -> None:
    """Confirmation promotes a field to hybrid (Rule 6), so this is contradictory."""
    with pytest.raises(MesaValidationError, match="only meaningful for source 'hybrid'"):
        SemanticProfile.from_dict(
            "lock.front",
            {
                "semantic_profile": {
                    "metadata_origin": {
                        "source": "inferred_ai",
                        "confidence": 0.95,
                        "generated_at": "2026-01-01T00:00:00",
                        "confirmed_fields": ["operational_boundaries.control_mode"],
                    },
                    "operational_boundaries": {"control_mode": "autonomous"},
                }
            },
        )


def test_hybrid_requires_confirmed_fields() -> None:
    with pytest.raises(MesaValidationError, match="missing 'confirmed_fields'"):
        SemanticProfile.from_dict(
            "light.x", {"semantic_profile": {"metadata_origin": {"source": "hybrid"}}}
        )


def test_inferred_confirmed_fields_not_honoured_at_resolution() -> None:
    """Defence in depth: even bypassing validation, the claim carries no weight."""
    s = store()
    profile = inferred("lock.front", control_mode="autonomous")
    profile.metadata.confirmed_fields = ["operational_boundaries.control_mode"]
    s.backend.write("lock.front", profile.raw)
    assert (
        s.get_effective("lock.front").operational_boundaries.control_mode == ControlMode.CONFIRM
    )


def test_inferred_helper_cannot_self_confirm_triggers_none() -> None:
    s = store()
    profile = inferred("input_boolean.guest", triggers_automations="none")
    profile.metadata.confirmed_fields = ["operational_boundaries.triggers_automations"]
    s.backend.write("input_boolean.guest", profile.raw)
    effective = s.get_effective("input_boolean.guest")
    assert effective.operational_boundaries.triggers_automations == TriggersAutomations.LIKELY


# --------------------------------------------------- field-level hybrid trust (Rule 6)


def _limit(limit_id: str, max_value: int, reason: str) -> dict[str, Any]:
    return {
        "id": limit_id,
        "predicate": {"entity": "binary_sensor.x", "operator": "eq", "value": "on"},
        "limit": {"service": "light.turn_on", "parameter": "brightness", "max_value": max_value},
        "human_reason": reason,
    }


def test_unconfirmed_hybrid_limit_cannot_displace_a_developer_limit() -> None:
    s = store()
    s.set_domain_profile(
        "light",
        make_profile(
            "light",
            origin="developer",
            boundaries={"control_mode": "autonomous", "declared_limits": [_limit("cap", 10, "dev")]},
        ),
    )
    s.set(
        "light.kid",
        make_profile(
            "light.kid",
            origin="hybrid",
            confirmed=["semantic_tags"],
            boundaries={"declared_limits": [_limit("cap", 255, "hybrid")]},
        ),
    )
    limits = s.get_effective("light.kid").operational_boundaries.declared_limits
    assert [limit["limit"]["max_value"] for limit in limits] == [10]
    result = MesaEnforcer(s, mode="enforced").evaluate(
        "light.kid", "light.turn_on", {"brightness": 200}
    )
    assert not result.allowed


def test_confirmed_hybrid_limit_does_displace_a_developer_limit() -> None:
    """The trust is per field, not a blanket demotion of hybrid."""
    s = store()
    s.set_domain_profile(
        "light",
        make_profile(
            "light",
            origin="developer",
            boundaries={"control_mode": "autonomous", "declared_limits": [_limit("cap", 10, "dev")]},
        ),
    )
    s.set(
        "light.kid",
        make_profile(
            "light.kid",
            origin="hybrid",
            confirmed=["operational_boundaries.declared_limits"],
            boundaries={"declared_limits": [_limit("cap", 255, "confirmed")]},
        ),
    )
    limits = s.get_effective("light.kid").operational_boundaries.declared_limits
    assert [limit["limit"]["max_value"] for limit in limits] == [255]


# ------------------------------------------------------- fail-closed enforcement


@pytest.mark.parametrize("state", ["unavailable", "unknown", None])
def test_unavailable_predicate_entity_keeps_the_limit_active(state: str | None) -> None:
    """HA reports an unreadable entity as a state string, not as absent (Spec 6.5)."""
    s = store()
    s.set(
        "light.kid",
        make_profile(
            "light.kid",
            boundaries={"control_mode": "autonomous", "declared_limits": [_limit("cap", 10, "r")]},
        ),
    )
    enforcer = MesaEnforcer(s, mode="enforced", get_state=lambda _e: state)
    result = enforcer.evaluate("light.kid", "light.turn_on", {"brightness": 200})
    assert not result.allowed


def test_throwing_get_state_blocks_rather_than_escaping() -> None:
    def boom(_entity: str) -> str:
        raise RuntimeError("HA connection lost")

    s = store()
    s.set(
        "light.kid",
        make_profile(
            "light.kid",
            boundaries={"control_mode": "autonomous", "declared_limits": [_limit("cap", 10, "r")]},
        ),
    )
    result = MesaEnforcer(s, mode="enforced", get_state=boom).evaluate(
        "light.kid", "light.turn_on", {"brightness": 200}
    )
    assert not result.allowed


@pytest.mark.parametrize("mode", ["enfroced", "ENFORCED", "", "advisory ", "on"])
def test_invalid_server_mode_is_rejected(mode: str) -> None:
    with pytest.raises(MesaError, match="invalid mode"):
        MesaEnforcer(store(), mode=mode)


@pytest.mark.parametrize("mode", ["enforced", "advisory"])
def test_valid_server_modes_are_accepted(mode: str) -> None:
    assert MesaEnforcer(store(), mode=mode).mode == mode


# ------------------------------------------------------ temporal constraints (6.5)


@pytest.mark.parametrize(
    "constraint",
    [
        pytest.param(
            {
                "id": "t",
                "condition": {"type": "time_range", "start_time": "22:00", "end_time": "06:00"},
                "effect": {"max_value": 10},
            },
            id="value_constraint_without_service",
        ),
        pytest.param(
            {
                "id": "t",
                "condition": {"type": "time_range", "start_time": 2200, "end_time": "06:00"},
                "effect": {"control_mode": "prohibited"},
            },
            id="non_string_start_time",
        ),
        pytest.param(
            {
                "id": "t",
                "condition": {"type": "time_range", "start_time": "22:00"},
                "effect": {"control_mode": "prohibited"},
            },
            id="missing_end_time",
        ),
        pytest.param(
            {
                "id": "t",
                "condition": {"type": "day_of_week", "days": ["saturday"]},
                "effect": {"control_mode": "prohibited"},
            },
            id="unabbreviated_weekday",
        ),
        pytest.param(
            {
                "id": "t",
                "condition": {"type": "solar_angle", "solar_event": "moonrise"},
                "effect": {"control_mode": "prohibited"},
            },
            id="unknown_solar_event",
        ),
        pytest.param(
            {
                "id": "t",
                "condition": {"type": "time_range", "start_time": "22:00", "end_time": "06:00"},
                "effect": {"service": "light.turn_on"},
            },
            id="service_without_parameter",
        ),
        pytest.param(
            {
                "id": "t",
                "condition": {"type": "time_range", "start_time": "22:00", "end_time": "06:00"},
                "effect": {"human_reason": "nothing"},
            },
            id="effect_constrains_nothing",
        ),
    ],
)
def test_malformed_temporal_constraint_is_rejected(constraint: dict[str, Any]) -> None:
    doc = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "operational_boundaries": {"temporal_constraints": [constraint]},
        }
    }
    assert not validation.validate_document(doc).ok


def test_unrecognisable_weekday_list_is_unevaluable_and_stays_active() -> None:
    """Fail-closed at evaluation, in case such a profile is already stored."""
    from mesa_core.profile import OperationalBoundaries
    from mesa_core.temporal import TemporalEvaluator

    boundaries = OperationalBoundaries(
        control_mode=ControlMode.AUTONOMOUS,
        temporal_constraints=[
            {
                "id": "weekend",
                "condition": {"type": "day_of_week", "days": ["saturday", "sunday"]},
                "effect": {"control_mode": "prohibited"},
            }
        ],
    )
    result = TemporalEvaluator().apply(boundaries, SATURDAY_NOON)
    assert result.boundaries.control_mode == ControlMode.PROHIBITED
    assert any("could not be evaluated" in w for w in result.warnings)


def test_valid_weekday_list_still_evaluates_normally() -> None:
    from mesa_core.profile import OperationalBoundaries
    from mesa_core.temporal import TemporalEvaluator

    boundaries = OperationalBoundaries(
        control_mode=ControlMode.AUTONOMOUS,
        temporal_constraints=[
            {
                "id": "weekend",
                "condition": {"type": "day_of_week", "days": ["sat", "sun"]},
                "effect": {"control_mode": "prohibited"},
            }
        ],
    )
    assert (
        TemporalEvaluator().apply(boundaries, SATURDAY_NOON).boundaries.control_mode
        == ControlMode.PROHIBITED
    )


# ------------------------------------------------------------- access_roles (7.2)


@pytest.mark.parametrize(
    "access_roles",
    [
        {"deny_for": "guest"},
        {"deny_for": [1, 2]},
        {"restricted_for": "child"},
        {"unknown_key": ["guest"]},
        "guest",
    ],
)
def test_malformed_access_roles_rejected(access_roles: Any) -> None:
    doc = {
        "semantic_profile": {"metadata_origin": {"source": "user"}},
        "privacy_classification": {"level": "restricted", "access_roles": access_roles},
    }
    assert not validation.validate_document(doc).ok


def test_wellformed_access_roles_accepted() -> None:
    doc = {
        "semantic_profile": {"metadata_origin": {"source": "user"}},
        "privacy_classification": {
            "level": "restricted",
            "access_roles": {"deny_for": ["guest"], "unrestricted_for": ["primary_resident"]},
        },
    }
    assert validation.validate_document(doc).ok


# --------------------------------------------------- privacy on retrieval (7.2, 9.5)


def restricted_camera_store() -> ProfileStore:
    s = store()
    s.set(
        "camera.bedroom",
        SemanticProfile.from_dict(
            "camera.bedroom",
            {
                "semantic_profile": {
                    "semantic_tags": ["security.camera"],
                    "metadata_origin": {"source": "user"},
                },
                "privacy_classification": {
                    "level": "restricted",
                    "access_roles": {"deny_for": ["guest"]},
                },
            },
        ),
    )
    return s


def handlers_for(roles: list[str], s: ProfileStore | None = None) -> MesaToolHandlers:
    return MesaToolHandlers(
        store=s or restricted_camera_store(),
        caller_context_fn=lambda: CallerContext(
            caller_id="c", roles=roles, is_authenticated=True, session_id="s"
        ),
    )


def test_get_profile_denies_a_caller_in_deny_for() -> None:
    result = asyncio.run(handlers_for(["guest"]).mesa_get_profile({"entity_id": "camera.bedroom"}))
    assert result.get("error") == "not_found"
    assert "semantic_profile" not in result


def test_query_omits_an_entity_the_caller_is_denied() -> None:
    result = asyncio.run(handlers_for(["guest"]).mesa_query_profiles({}))
    assert result["results"] == []


def test_explain_denies_a_caller_in_deny_for() -> None:
    result = asyncio.run(
        handlers_for(["guest"]).mesa_explain_profile({"entity_id": "camera.bedroom"})
    )
    assert result.get("error") == "not_found"
    assert "explanation" not in result


def test_permitted_caller_still_receives_the_profile() -> None:
    result = asyncio.run(
        handlers_for(["primary_resident"]).mesa_get_profile({"entity_id": "camera.bedroom"})
    )
    assert result["entity_id"] == "camera.bedroom"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("error", "forbidden"), ("redact", None)],
)
def test_deny_response_mode_shapes_the_response(mode: str, expected: str | None) -> None:
    s = store()
    s.set(
        "camera.bedroom",
        SemanticProfile.from_dict(
            "camera.bedroom",
            {
                "semantic_profile": {"metadata_origin": {"source": "user"}},
                "privacy_classification": {
                    "level": "restricted",
                    "deny_response_mode": mode,
                    "access_roles": {"deny_for": ["guest"]},
                },
            },
        ),
    )
    result = asyncio.run(
        handlers_for(["guest"], s).mesa_get_profile({"entity_id": "camera.bedroom"})
    )
    if expected is None:
        assert result == {"entity_id": "camera.bedroom", "access": "denied"}
    else:
        assert result["error"] == expected


def test_retrieval_of_a_restricted_entity_is_audit_logged() -> None:
    """Spec 7.1: restricted entities MUST log access. Reads counted, not only writes."""
    records: list[dict[str, Any]] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            event = getattr(record, "mesa_audit_event", None)
            if event is not None:
                records.append(event)

    logger = logging.getLogger("mesa_core.audit")
    handler = Capture()
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        asyncio.run(handlers_for(["guest"]).mesa_get_profile({"entity_id": "camera.bedroom"}))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)

    assert any(
        r["event_type"] == "privacy_access"
        and r["decision"] == "denied"
        and r["entity_id"] == "camera.bedroom"
        for r in records
    )


# ------------------------------------------------- strict tool input parsing (9.2)


def test_string_false_does_not_enable_include_inferred() -> None:
    """bool("false") is True, which would defeat an opt-in privacy gate."""
    result = asyncio.run(
        MesaToolHandlers(store=store()).mesa_query_profiles({"include_inferred": "false"})
    )
    assert result["error"] == "invalid_query"


@pytest.mark.parametrize("limit", [-5, 0, 9999, "50", True])
def test_out_of_range_limit_is_rejected_not_clamped(limit: Any) -> None:
    result = asyncio.run(MesaToolHandlers(store=store()).mesa_query_profiles({"limit": limit}))
    assert result["error"] == "invalid_query"


# =================================================================
# Second-audit regressions (1.2.1 remediation retest)
# =================================================================


def _restricted_camera_domain(s: ProfileStore) -> None:
    s.set_domain_profile("camera", SemanticProfile.from_dict("camera", {
        "semantic_profile": {"metadata_origin": {"source": "developer"},
                             "operational_boundaries": {"control_mode": "autonomous"}},
        "privacy_classification": {"level": "restricted"}}))


def test_inferred_unrestricted_for_does_not_relax_access() -> None:
    """Spec 5.4 Rule 3: an unconfirmed inferred privacy field is excluded from
    access decisions entirely, not merely placed in a lower conflict tier."""
    s = store()
    _restricted_camera_domain(s)
    s.set("camera.hall", SemanticProfile.from_dict("camera.hall", {
        "semantic_profile": {"metadata_origin": {"source": "inferred_ai", "confidence": 0.9,
                             "generated_at": "2026-01-01T00:00:00"}},
        "privacy_classification": {"level": "restricted",
                                   "access_roles": {"unrestricted_for": ["guest"]}}}))
    eff = s.get_effective("camera.hall")
    assert eff.privacy_classification.access_roles is None
    from mesa_core.privacy import PrivacyEnforcer
    decision = PrivacyEnforcer().evaluate(
        eff.privacy_classification,
        CallerContext(caller_id="g", roles=["guest"], is_authenticated=True),
        entity_id="camera.hall")
    assert decision.effective_level == __import__("mesa_core.profile", fromlist=["PrivacyLevel"]).PrivacyLevel.RESTRICTED


def test_confirmed_hybrid_access_role_is_honoured() -> None:
    """A hybrid profile that confirms access_roles is trusted for that field."""
    s = store()
    _restricted_camera_domain(s)
    s.set("camera.hall", SemanticProfile.from_dict("camera.hall", {
        "semantic_profile": {"metadata_origin": {"source": "hybrid",
                             "confirmed_fields": ["privacy_classification.access_roles"]}},
        "privacy_classification": {"level": "restricted",
                                   "access_roles": {"unrestricted_for": ["guest"]}}}))
    eff = s.get_effective("camera.hall")
    assert eff.privacy_classification.access_roles == {"unrestricted_for": ["guest"]}


def test_inferred_helper_defaults_to_likely_through_deployment_override() -> None:
    """Rule 9: a helper defaults to likely regardless; a deployment override
    cannot drop a profiled inferred helper to none."""
    s = store()
    s.set_deployment_defaults(DeploymentDefaults.from_dict({"deployment_defaults": {
        "domain_overrides": {"input_boolean": {"triggers_automations": "none"}}}}))
    s.set("input_boolean.guest", inferred("input_boolean.guest"))
    assert (s.get_effective("input_boolean.guest").operational_boundaries.triggers_automations
            == TriggersAutomations.LIKELY)


def test_confirmation_token_requires_approved_by() -> None:
    s = store()
    s.set("cover.x", make_profile("cover.x", boundaries={"control_mode": "confirm"}))
    e = MesaEnforcer(s, mode="enforced")
    ch = e.evaluate("cover.x", "cover.open_cover", {}).confirmation_challenge
    r = e.evaluate("cover.x", "cover.open_cover", {},
                   confirmation_token={"challenge_id": ch["challenge_id"]})
    assert not r.allowed and "approved_by" in r.reason


def test_confirmation_token_requires_approved_at() -> None:
    s = store()
    s.set("cover.x", make_profile("cover.x", boundaries={"control_mode": "confirm"}))
    e = MesaEnforcer(s, mode="enforced")
    ch = e.evaluate("cover.x", "cover.open_cover", {}).confirmation_challenge
    r = e.evaluate("cover.x", "cover.open_cover", {},
                   confirmation_token={"challenge_id": ch["challenge_id"], "approved_by": "u"})
    assert not r.allowed and "approved_at" in r.reason


def test_complete_confirmation_token_is_audited() -> None:
    records: list[dict[str, Any]] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            event = getattr(record, "mesa_audit_event", None)
            if event is not None:
                records.append(event)

    logger = logging.getLogger("mesa_core.audit")
    handler = Capture()
    logger.addHandler(handler)
    prev = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        s = store()
        s.set("cover.x", make_profile("cover.x", boundaries={"control_mode": "confirm"}))
        e = MesaEnforcer(s, mode="enforced")
        ch = e.evaluate("cover.x", "cover.open_cover", {}).confirmation_challenge
        r = e.evaluate("cover.x", "cover.open_cover", {}, confirmation_token={
            "challenge_id": ch["challenge_id"], "approved_by": "user.alice",
            "approved_at": "2026-07-15T12:00:00"})
        assert r.allowed
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)
    approved = [e for e in records if e["decision"] == "allowed"
                and (e.get("details") or {}).get("approved_by") == "user.alice"]
    assert approved, "the approval must reach the audit trail (Spec 6.6)"


def test_inferred_entity_does_not_overwrite_developer_enrichment() -> None:
    """Rule D applies to unmodelled fields too: trusted tier wins over scope."""
    s = store()
    s.set_domain_profile("light", SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "helper_traits": {"note": "developer"}}}))
    s.set("light.x", SemanticProfile.from_dict("light.x", {"semantic_profile": {
        "metadata_origin": {"source": "inferred_ai", "confidence": 0.9,
                            "generated_at": "2026-01-01T00:00:00"},
        "helper_traits": {"note": "inferred"}}}))
    ht = s.get_effective("light.x").to_dict()["semantic_profile"]["helper_traits"]
    assert ht == {"note": "developer"}


def test_trusted_more_specific_enrichment_still_wins() -> None:
    """Within the trusted tier, the most specific layer still wins."""
    s = store()
    s.set_domain_profile("light", SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "helper_traits": {"note": "domain"}}}))
    s.set("light.x", SemanticProfile.from_dict("light.x", {"semantic_profile": {
        "metadata_origin": {"source": "user"}, "helper_traits": {"note": "entity"}}}))
    ht = s.get_effective("light.x").to_dict()["semantic_profile"]["helper_traits"]
    assert ht == {"note": "entity"}


# =================================================================
# Fourth-audit regressions
# =================================================================


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numeric_bound_is_rejected(bad: float) -> None:
    """A NaN safety bound disables its limit (every comparison with NaN is
    false), so non-finite numbers must be rejected at validation (Spec 6.4)."""
    doc = {"semantic_profile": {"metadata_origin": {"source": "user"},
           "operational_boundaries": {"declared_limits": [{
               "id": "c", "predicate": {"entity": "x.y", "operator": "eq", "value": "on"},
               "limit": {"service": "light.turn_on", "parameter": "brightness",
                         "max_value": bad}}]}}}
    assert not validation.validate_document(doc).ok


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_staleness_window_is_rejected(bad: float) -> None:
    doc = {"semantic_profile": {"metadata_origin": {"source": "user",
           "staleness_window_days": bad}}}
    assert not validation.validate_document(doc).ok
    with pytest.raises(MesaValidationError):
        SemanticProfile.from_dict("light.x", doc)


def test_non_finite_bound_fails_closed_in_limit_enforcement() -> None:
    """Defense in depth beyond validation: if a non-finite bound reaches the
    declared-limit check, the over-limit call is blocked rather than silently
    allowed (value > NaN is false, which would disable the cap). This exercises
    the max_value comparison in _check_limit, not the predicate helper."""
    enforcer = MesaEnforcer(store(), mode="enforced")
    nan_cap = {"human_reason": "cap", "limit": {"service": "light.turn_on",
               "parameter": "brightness", "max_value": float("nan")}}
    assert enforcer._check_limit(nan_cap, "light.turn_on", {"brightness": 999999}) is not None
    finite_cap = {"human_reason": "cap", "limit": {"service": "light.turn_on",
                  "parameter": "brightness", "max_value": 255}}
    # An oversized integer parameter is not comparable and also fails closed
    # rather than crashing on float() overflow.
    assert enforcer._check_limit(finite_cap, "light.turn_on", {"brightness": 10**400}) is not None
    # A within-limit call is still allowed.
    assert enforcer._check_limit(finite_cap, "light.turn_on", {"brightness": 100}) is None


def test_explain_covers_every_effective_field() -> None:
    """Spec 9.5: the explanation names which layer contributed each effective
    field, not only the kernel three."""
    s = store()
    s.set("light.x", SemanticProfile.from_dict("light.x", {
        "semantic_profile": {"metadata_origin": {"source": "user"},
            "semantic_tags": ["lighting.ambient"], "helper_traits": {"note": "x"},
            "profile_valid_for": {"review_after_days": 90, "integration_version": "2.4.1"}},
        "diagnostic_profile": {"d": 1}}))
    paths = {e.field_path for e in s.explain("light.x").explanation}
    for field in (
        "semantic_tags",
        "diagnostic_profile",
        "profile_valid_for.review_after_days",
        "profile_valid_for.integration_version",
        "helper_traits.note",
    ):
        assert field in paths, f"{field} not explained"


# =================================================================
# Fifth-audit regressions
# =================================================================


def test_oversized_integer_does_not_crash_validation() -> None:
    """A 1000-digit JSON integer is a valid finite number. Passing it to
    math.isfinite (which converts to float) raised OverflowError, crashing
    validation and mesa-lint on hostile input instead of returning a result."""
    big = 10**400
    doc = {"semantic_profile": {"metadata_origin": {"source": "user"},
           "profile_valid_for": {"review_after_days": big}}}
    assert validation.validate_document(doc).ok
    SemanticProfile.from_dict("light.x", doc)  # parses without raising


def test_oversized_integer_predicate_value_does_not_crash_enforcement() -> None:
    """A predicate whose value is an arbitrarily large JSON integer must be
    unevaluable (None), not an OverflowError from float() that crashes
    evaluation. (A huge state string converts to inf, so only the int-valued
    operand overflows.)"""
    from mesa_core.enforcer import _compare

    assert _compare("gt", "5", 10**400) is None
    assert _compare("lt", "5", 10**400) is None


@pytest.mark.parametrize("broader", ["hijack", {}, 0, [1, 2]])
def test_inferred_broader_value_cannot_erase_trusted_object_subtree(broader: Any) -> None:
    """A broader inferred value sharing a trusted object's prefix must not
    overwrite the trusted child, regardless of layer order (Rules D and E).
    Grouping candidates by exact path let parent and child never compete."""
    entity = SemanticProfile.from_dict("light.kitchen", {"semantic_profile": {
        "metadata_origin": {"source": "user"}, "x_vendor": {"trusted": 1}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "inferred_ai", "confidence": 0.5,
                            "generated_at": "2026-01-01T00:00:00Z"},
        "x_vendor": broader}})
    for order in (
        [Layer("entity", entity), Layer("domain", domain)],
        [Layer("domain", domain), Layer("entity", entity)],
    ):
        eff, res = ConflictResolver().resolve("light.kitchen", order)
        assert eff.raw["semantic_profile"]["x_vendor"] == {"trusted": 1}
        assert res.conflicts_detected


def test_disjoint_enrichment_subfields_still_compose() -> None:
    """The prefix-collision fix must not break Rule E composition of disjoint
    subfields declared at different levels."""
    entity = SemanticProfile.from_dict("light.kitchen", {"semantic_profile": {
        "metadata_origin": {"source": "user"}, "x_vendor": {"a": 1}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "user"}, "x_vendor": {"b": 2}}})
    eff, _ = ConflictResolver().resolve(
        "light.kitchen", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {"a": 1, "b": 2}


@pytest.mark.parametrize("bad_pvf", [
    {"integration_version": 2},
    {"ha_version": 5},
    {"review_after_days": "soon"},
    {"review_after_days": float("nan")},
    {"invalidated_by_entities": ["light.a", 1]},
])
def test_profile_valid_for_known_subfields_are_typed(bad_pvf: dict[str, Any]) -> None:
    """Spec 5.5 names four typed members; a malformed known member is rejected
    even though the outer object was already validated."""
    doc = {"semantic_profile": {"metadata_origin": {"source": "user"},
           "profile_valid_for": bad_pvf}}
    assert not validation.validate_document(doc).ok


def test_profile_valid_for_unknown_subfield_stays_forward_compatible() -> None:
    doc = {"semantic_profile": {"metadata_origin": {"source": "user"},
           "profile_valid_for": {"future_field": {"x": 1}, "review_after_days": 30}}}
    assert validation.validate_document(doc).ok


def test_profile_valid_for_resolves_per_subfield() -> None:
    """A domain subfield survives when the entity declares only another: the two
    compose instead of the whole object being replaced (Rule E)."""
    entity = SemanticProfile.from_dict("light.kitchen", {"semantic_profile": {
        "metadata_origin": {"source": "user"},
        "profile_valid_for": {"review_after_days": 90}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "user"},
        "profile_valid_for": {"integration_version": "2.4.1"}}})
    eff, _ = ConflictResolver().resolve(
        "light.kitchen", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert eff.metadata.profile_valid_for == {
        "review_after_days": 90, "integration_version": "2.4.1"}


def test_confirmed_hybrid_profile_valid_for_subfield_wins() -> None:
    """confirmed_fields ['profile_valid_for.review_after_days'] promotes that
    hybrid subfield to the trusted tier, so the most specific level wins."""
    entity = SemanticProfile.from_dict("light.kitchen", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid",
                            "confirmed_fields": ["profile_valid_for.review_after_days"]},
        "profile_valid_for": {"review_after_days": 30}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"},
        "profile_valid_for": {"review_after_days": 365}}})
    eff, _ = ConflictResolver().resolve(
        "light.kitchen", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert eff.metadata.profile_valid_for["review_after_days"] == 30


def test_unconfirmed_hybrid_profile_valid_for_subfield_stays_inferred() -> None:
    """An unconfirmed hybrid subfield stays in the lower tier, so a trusted
    developer domain value wins over it (Spec 5.4 Rule 6)."""
    entity = SemanticProfile.from_dict("light.kitchen", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": []},
        "profile_valid_for": {"review_after_days": 30}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"},
        "profile_valid_for": {"review_after_days": 365}}})
    eff, _ = ConflictResolver().resolve(
        "light.kitchen", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert eff.metadata.profile_valid_for["review_after_days"] == 365


def test_tag_union_reports_a_conflict_with_all_contributors() -> None:
    """Spec 9.5: two levels declaring tags is a conflict even though the union
    keeps every tag; competing_values must name each contributor."""
    entity = make_profile("light.kitchen", tags=["lighting.ambient"])
    domain = make_profile("light", origin="developer", tags=["security.camera"])
    _, res = ConflictResolver().resolve(
        "light.kitchen", [Layer("entity", entity), Layer("domain", domain)]
    )
    tag = next(e for e in res.explanations if e.field_path == "semantic_tags")
    assert tag.conflict is True
    assert {c["level"] for c in tag.competing_values or []} == {"entity", "domain"}


def test_competing_diagnostic_profiles_report_a_conflict() -> None:
    entity = SemanticProfile.from_dict("light.kitchen", {
        "semantic_profile": {"metadata_origin": {"source": "user"}},
        "diagnostic_profile": {"d": 1}})
    domain = SemanticProfile.from_dict("light", {
        "semantic_profile": {"metadata_origin": {"source": "developer"}},
        "diagnostic_profile": {"d": 2}})
    _, res = ConflictResolver().resolve(
        "light.kitchen", [Layer("entity", entity), Layer("domain", domain)]
    )
    diag = next(e for e in res.explanations if e.field_path == "diagnostic_profile")
    assert diag.conflict is True
    assert diag.effective_value == {"d": 1}  # entity is most specific


def test_competing_enrichment_leaf_reports_a_conflict() -> None:
    entity = SemanticProfile.from_dict("light.kitchen", {"semantic_profile": {
        "metadata_origin": {"source": "user"}, "x_vendor": {"mode": "a"}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": {"mode": "b"}}})
    _, res = ConflictResolver().resolve(
        "light.kitchen", [Layer("entity", entity), Layer("domain", domain)]
    )
    leaf = next(e for e in res.explanations if e.field_path == "x_vendor.mode")
    assert leaf.conflict is True
    assert leaf.effective_value == "a"


# =================================================================
# Sixth-audit regressions
# =================================================================


@pytest.mark.parametrize("state", ["nan", "inf", "Infinity", "-inf"])
def test_non_finite_state_keeps_the_limit_active(state: str) -> None:
    """float('nan') succeeds, so a numeric predicate on a non-finite state
    compared cleanly to False and dropped its limit instead of being
    unevaluable and fail-closed (Spec 6.5)."""
    s = store()
    s.set("light.kid", make_profile("light.kid", boundaries={
        "control_mode": "autonomous",
        "declared_limits": [{
            "id": "cap", "human_reason": "r",
            "predicate": {"entity": "sensor.x", "operator": "gt", "value": 20},
            "limit": {"service": "light.turn_on", "parameter": "brightness",
                      "max_value": 10}}]}))
    enforcer = MesaEnforcer(s, mode="enforced", get_state=lambda _e: state)
    result = enforcer.evaluate("light.kid", "light.turn_on", {"brightness": 200})
    assert not result.allowed


@pytest.mark.parametrize("poison", ["poison", {}, 0, [1]])
def test_lower_tier_shape_collision_cannot_erase_trusted_composition(poison: Any) -> None:
    """An untrusted atomic value must not force two trusted objects to resolve
    atomically: their disjoint subfields still compose (Rules D and E)."""
    entity = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "user"}, "x_vendor": {"a": 1}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": {"b": 2}}})
    area = SemanticProfile.from_dict("area.x", {"semantic_profile": {
        "metadata_origin": {"source": "inferred_ai", "confidence": 0.5,
                            "generated_at": "2026-01-01T00:00:00Z"},
        "x_vendor": poison}})
    eff, res = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("area", area), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {"a": 1, "b": 2}
    assert res.conflicts_detected


def test_shape_collision_preserves_a_confirmed_hybrid_child() -> None:
    """A hybrid layer whose confirmed field lies under the colliding node keeps
    the node an object, so the confirmed child is not lost to atomic resolution."""
    entity = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["x_vendor.a"]},
        "x_vendor": {"a": 1}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": {"b": 2}}})
    area = SemanticProfile.from_dict("area.x", {"semantic_profile": {
        "metadata_origin": {"source": "inferred_ai", "confidence": 0.5,
                            "generated_at": "2026-01-01T00:00:00Z"},
        "x_vendor": "poison"}})
    eff, _ = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("area", area), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {"a": 1, "b": 2}


def test_trusted_specific_scalar_still_overrides_broader_trusted_object() -> None:
    """The shape fix must not weaken Rule D: a trusted, more specific atomic
    declaration wins over a broader trusted object."""
    entity = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "user"}, "x_vendor": "explicit"}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": {"b": 2}}})
    eff, _ = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == "explicit"


def test_oversized_confidence_is_a_validation_error_not_a_crash() -> None:
    doc = {"semantic_profile": {"metadata_origin": {
        "source": "inferred_ai", "confidence": 10**400,
        "generated_at": "2026-01-01T00:00:00Z"}}}
    report = validation.validate_document(doc)
    assert not report.ok
    assert any("confidence" in e for e in report.errors)


def test_oversized_staleness_window_does_not_crash_staleness_status() -> None:
    """timedelta(days=huge) raises OverflowError; the comparison is now done in
    plain seconds, and an astronomically large window is simply never stale."""
    doc = {"semantic_profile": {"metadata_origin": {
        "source": "inferred_ai", "confidence": 0.5,
        "generated_at": "2026-01-01T00:00:00Z", "staleness_window_days": 10**400}}}
    profile = SemanticProfile.from_dict("light.x", doc)
    assert profile.staleness_status() == "current"


def test_oversized_solar_offset_is_unevaluable_and_active() -> None:
    """A validated but oversized solar_offset_minutes must leave the condition
    unevaluable (and therefore active, Spec 6.5), not raise OverflowError."""
    from mesa_core.temporal import TemporalEvaluator

    evaluator = TemporalEvaluator(get_solar_elevation=lambda at: -10.0)
    cond = {"type": "solar_angle", "solar_event": "sunset",
            "solar_offset_minutes": 10**400}
    assert evaluator.evaluate_condition(cond, SATURDAY_NOON) is None


def test_oversized_lease_duration_is_clamped_not_server_error() -> None:
    """The published schema has no upper bound because values above 30s are
    clamped; float() of the oversized integer raised OverflowError first."""
    from mesa_core.lease.manager import LeaseManager

    s = store()
    handlers = MesaToolHandlers(s, lease_manager=LeaseManager(store=s))
    result = asyncio.run(handlers.mesa_request_lease(
        {"entities": ["light.x"], "duration_seconds": 10**400}))
    assert result.get("granted") is True
    assert result.get("granted_duration_seconds") == 30.0


def test_fractional_staleness_window_is_preserved_not_truncated() -> None:
    """Spec 5.4 declares staleness_window_days a number; int() turned a 0.9-day
    window into 0, marking a half-day-old profile stale."""
    doc = {"semantic_profile": {"metadata_origin": {
        "source": "inferred_ai", "confidence": 0.5,
        "generated_at": "2026-01-03T00:00:00", "staleness_window_days": 0.9}}}
    profile = SemanticProfile.from_dict("light.x", doc)
    assert profile.metadata.staleness_window_days == 0.9
    mo = profile.to_dict()["semantic_profile"]["metadata_origin"]
    assert mo["staleness_window_days"] == 0.9
    assert profile.staleness_status(now=SATURDAY_NOON) == "current"
    assert profile.staleness_status(now=datetime(2026, 1, 4, 12, 0)) == "stale"


def test_mixed_timezone_awareness_does_not_raise() -> None:
    """A naive accepted generated_at with an aware now raised TypeError."""
    from datetime import UTC

    doc = {"semantic_profile": {"metadata_origin": {
        "source": "inferred_ai", "confidence": 0.5,
        "generated_at": "2026-01-03T00:00:00"}}}
    profile = SemanticProfile.from_dict("light.x", doc)
    assert profile.staleness_status(
        now=datetime(2026, 1, 3, 12, 0, tzinfo=UTC)) == "current"


def test_identical_declarations_across_levels_are_not_a_conflict() -> None:
    """Spec 9.5 erratum: conflict means differing values; identical multi-level
    declarations agree. Covers tags, a Rule D scalar, diagnostics, and an
    enrichment leaf in one layered pair."""
    entity = SemanticProfile.from_dict("light.k", {
        "semantic_profile": {"metadata_origin": {"source": "user"},
            "semantic_tags": ["lighting.ambient"],
            "operational_boundaries": {"reversible": True},
            "x_vendor": {"mode": "a"}},
        "diagnostic_profile": {"d": 1}})
    domain = SemanticProfile.from_dict("light", {
        "semantic_profile": {"metadata_origin": {"source": "developer"},
            "semantic_tags": ["lighting.ambient"],
            "operational_boundaries": {"reversible": True},
            "x_vendor": {"mode": "a"}},
        "diagnostic_profile": {"d": 1}})
    _, res = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    for path in ("semantic_tags", "operational_boundaries.reversible",
                 "diagnostic_profile", "x_vendor.mode"):
        entry = next(e for e in res.explanations if e.field_path == path)
        assert entry.conflict is False, f"{path} flagged identical values as a conflict"
    assert not res.conflicts_detected


# =================================================================
# Seventh-audit regressions
# =================================================================


@pytest.mark.parametrize("confirmed", [
    ["x_vendor.missing"],
    ["x_vendor.unconfirmed.deeper"],
    ["x_vendor_other.unconfirmed"],
])
def test_nonexistent_confirmed_descendant_grants_no_shape_trust(confirmed: list[str]) -> None:
    """A confirmation naming a descendant the object does not contain confirms
    nothing, so the hybrid object's unconfirmed fields must not displace a
    trusted atomic declaration (Rule D exact field-path trust)."""
    entity = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": confirmed},
        "x_vendor": {"unconfirmed": "hijack"}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": "trusted"}})
    eff, _ = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == "trusted"


def test_unconfirmed_sibling_cannot_piggyback_past_a_trusted_atomic() -> None:
    """A real confirmed child keeps the node an object, but its unconfirmed
    siblings still lose to the trusted atomic declaration at the node."""
    entity = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["x_vendor.a"]},
        "x_vendor": {"a": 1, "b": "hijack"}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": "trusted"}})
    eff, res = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {"a": 1}
    assert any("x_vendor.b" in w for w in res.warnings)


def test_unconfirmed_sibling_survives_an_untrusted_atomic() -> None:
    """Suppression applies only against a TRUSTED atomic competitor; an inferred
    scalar must not erase enrichment (never-lost fallback stays intact)."""
    entity = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["x_vendor.a"]},
        "x_vendor": {"a": 1, "b": "hint"}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "inferred_ai", "confidence": 0.5,
                            "generated_at": "2026-01-01T00:00:00Z"},
        "x_vendor": "poison"}})
    eff, _ = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {"a": 1, "b": "hint"}


def test_merged_profile_is_independent_of_its_sources() -> None:
    """Profiles support read-modify-write, so mutating a merge() result must
    not write through to the input layers."""
    src_hi = SemanticProfile.from_dict("light.k", {
        "semantic_profile": {"metadata_origin": {"source": "user"},
            "operational_boundaries": {"declared_limits": [{
                "id": "cap", "human_reason": "r",
                "predicate": {"entity": "s.x", "operator": "eq", "value": "on"},
                "limit": {"service": "light.turn_on", "parameter": "brightness",
                          "max_value": 10}}]},
            "person_traits": {"associated_zones": ["zone.home"]},
            "helper_traits": {"note": "keep"}},
        "privacy_classification": {"level": "restricted",
                                   "access_roles": {"deny_for": ["guest"]}},
        "diagnostic_profile": {"d": 1}})
    src_lo = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}}})
    merged = ConflictResolver().merge(src_hi, src_lo)

    assert merged.metadata is not src_hi.metadata
    merged.metadata.confirmed_fields.append("EVIL")
    merged.privacy_classification.access_roles["deny_for"].append("EVIL")
    merged.person_traits.associated_zones.append("EVIL")
    merged.diagnostic_profile["d"] = 999
    merged.operational_boundaries.declared_limits[0]["limit"]["max_value"] = 99999
    merged.raw["semantic_profile"]["helper_traits"]["note"] = "EVIL"

    assert src_hi.metadata.confirmed_fields == []
    assert src_hi.privacy_classification.access_roles == {"deny_for": ["guest"]}
    assert src_hi.person_traits.associated_zones == ["zone.home"]
    assert src_hi.diagnostic_profile == {"d": 1}
    assert src_hi.operational_boundaries.declared_limits[0]["limit"]["max_value"] == 10
    assert src_hi.raw["semantic_profile"]["helper_traits"]["note"] == "keep"


def test_identical_dicts_with_different_key_order_are_not_a_conflict() -> None:
    """repr() preserves insertion order, so equal access_roles objects were
    reported as differing values against the Spec 9.5 erratum."""
    entity = SemanticProfile.from_dict("light.k", {
        "semantic_profile": {"metadata_origin": {"source": "user"}},
        "privacy_classification": {"level": "restricted",
            "access_roles": {"deny_for": ["guest"], "unrestricted_for": ["admin"]}}})
    domain = SemanticProfile.from_dict("light", {
        "semantic_profile": {"metadata_origin": {"source": "developer"}},
        "privacy_classification": {"level": "restricted",
            "access_roles": {"unrestricted_for": ["admin"], "deny_for": ["guest"]}}})
    _, res = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    entry = next(
        e for e in res.explanations
        if e.field_path == "privacy_classification.access_roles"
    )
    assert entry.conflict is False
    assert not res.conflicts_detected


# =================================================================
# Eighth-audit regressions
# =================================================================


@pytest.mark.parametrize("value", [[], {}, {"b": 1}, {"b": {"c": 2}}])
def test_confirming_a_field_confirms_its_whole_value(value: Any) -> None:
    """confirmed_fields name authoritative field paths, so confirming
    x_vendor.a confirms everything declared at it. Exact-path matching made a
    confirmed non-empty object's children untrusted during recursive
    composition, discarding the confirmed value entirely while an empty object
    or array at the same confirmed path survived."""
    entity = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["x_vendor.a"]},
        "x_vendor": {"a": value}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": "trusted"}})
    eff, _ = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {"a": value}


def test_confirmed_object_subtree_outranks_a_trusted_broader_value() -> None:
    """The ancestor confirmation reaches every depth: a confirmed object's
    grandchild wins against a trusted broader declaration of the same leaf."""
    entity = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["x_vendor.a"]},
        "x_vendor": {"a": {"b": 1}}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": {"a": {"b": 2}}}})
    eff, _ = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {"a": {"b": 1}}


@pytest.mark.parametrize(("first", "second"), [
    (1, 1.0),
    (0, -0.0),
    (9007199254740992, 9007199254740992.0),
])
def test_numerically_equal_values_are_not_a_conflict(first: Any, second: Any) -> None:
    """JSON has one number type, so equal numbers with different encodings are
    identical declarations, not differing values (Spec 9.5 erratum)."""
    entity = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "user"}, "x_vendor": {"n": first}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": {"n": second}}})
    _, res = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    leaf = next(e for e in res.explanations if e.field_path == "x_vendor.n")
    assert leaf.conflict is False
    assert not res.conflicts_detected


def test_numeric_normalisation_keeps_genuinely_distinct_values_distinct() -> None:
    """Normalisation must not over-merge: booleans are not numbers, fractional
    values differ from integers, and distinct integers beyond 2**53 (where
    float would round them together) stay distinct."""
    from mesa_core.conflict import _canonical

    assert _canonical(True) != _canonical(1)
    assert _canonical(1.5) != _canonical(1)
    assert _canonical(2**60) != _canonical(2**60 + 1)


# =================================================================
# Ninth-audit regressions
# =================================================================


def test_confirmation_for_a_nested_path_does_not_trust_a_literal_dotted_key() -> None:
    """"x_vendor.a.b" in confirmed_fields always parses as nested a then b
    (Spec 5.7, Field paths); it must not grant trust to a literal property
    named "a.b" that renders identically, which would let that value displace
    a trusted declaration."""
    hybrid = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["x_vendor.a.b"]},
        "x_vendor": {"a.b": "evil"}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": {"a.b": "trusted"}}})
    eff, _ = ConflictResolver().resolve(
        "light.k", [Layer("entity", hybrid), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {"a.b": "trusted"}


def test_dotted_literal_key_and_nested_path_get_distinct_explanation_paths() -> None:
    """Both values are retained, and their explanations must not share one
    field_path: the literal dotted key renders escaped (Spec 5.7)."""
    entity = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "user"}, "x_vendor": {"a.b": 1}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": {"a": {"b": 2}}}})
    eff, res = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {"a.b": 1, "a": {"b": 2}}
    paths = [e.field_path for e in res.explanations if "x_vendor" in e.field_path]
    assert sorted(paths) == ["x_vendor.a.b", "x_vendor.a\\.b"]


def test_dotted_key_is_still_covered_by_a_confirmed_ancestor() -> None:
    """Not path-addressable means not individually confirmable; a confirmed
    ancestor still covers the whole value, dotted keys included."""
    hybrid = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["x_vendor"]},
        "x_vendor": {"a.b": "whole-confirmed"}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": {"a.b": "dev"}}})
    eff, _ = ConflictResolver().resolve(
        "light.k", [Layer("entity", hybrid), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {"a.b": "whole-confirmed"}


def test_genuinely_nested_confirmation_is_unaffected_by_the_grammar_fix() -> None:
    hybrid = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["x_vendor.a.b"]},
        "x_vendor": {"a": {"b": "confirmed"}}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": {"a": {"b": "dev"}}}})
    eff, _ = ConflictResolver().resolve(
        "light.k", [Layer("entity", hybrid), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {"a": {"b": "confirmed"}}


@pytest.mark.parametrize("reordered", [
    {"deny_for": ["child", "guest"]},
    {"deny_for": ["guest", "guest", "child"]},
])
def test_reordered_or_duplicated_role_arrays_are_not_a_conflict(
    reordered: dict[str, Any],
) -> None:
    """The privacy enforcer consumes role arrays as sets, so order and
    duplicates carry no semantics and are not differing declarations."""
    entity = SemanticProfile.from_dict("light.k", {
        "semantic_profile": {"metadata_origin": {"source": "user"}},
        "privacy_classification": {"level": "restricted",
            "access_roles": {"deny_for": ["guest", "child"]}}})
    domain = SemanticProfile.from_dict("light", {
        "semantic_profile": {"metadata_origin": {"source": "developer"}},
        "privacy_classification": {"level": "restricted", "access_roles": reordered}})
    _, res = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    entry = next(
        e for e in res.explanations
        if e.field_path == "privacy_classification.access_roles"
    )
    assert entry.conflict is False
    assert not res.conflicts_detected


def test_genuinely_different_role_sets_still_conflict() -> None:
    entity = SemanticProfile.from_dict("light.k", {
        "semantic_profile": {"metadata_origin": {"source": "user"}},
        "privacy_classification": {"level": "restricted",
            "access_roles": {"deny_for": ["guest", "child"]}}})
    domain = SemanticProfile.from_dict("light", {
        "semantic_profile": {"metadata_origin": {"source": "developer"}},
        "privacy_classification": {"level": "restricted",
            "access_roles": {"deny_for": ["child"]}}})
    _, res = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    entry = next(
        e for e in res.explanations
        if e.field_path == "privacy_classification.access_roles"
    )
    assert entry.conflict is True


# =================================================================
# Tenth-audit regressions
# =================================================================


def test_profile_valid_for_dotted_key_is_not_individually_confirmable() -> None:
    """Forward-compatible profile_valid_for keys go through the same path
    grammar as unmodelled fields: a confirmation that parses as nested
    segments must not trust a literal dotted key (Spec 5.7, Field paths)."""
    hybrid = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid",
                            "confirmed_fields": ["profile_valid_for.a.b"]},
        "profile_valid_for": {"a.b": "untrusted"}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"},
        "profile_valid_for": {"a.b": "trusted"}}})
    eff, res = ConflictResolver().resolve(
        "light.k", [Layer("entity", hybrid), Layer("domain", domain)]
    )
    assert eff.metadata.profile_valid_for == {"a.b": "trusted"}
    paths = [e.field_path for e in res.explanations if "profile_valid_for" in e.field_path]
    assert paths == ["profile_valid_for.a\\.b"]


@pytest.mark.parametrize("literal_key", ["a\\b", "a\\.b"])
def test_backslash_keys_are_not_individually_confirmable(literal_key: str) -> None:
    """Spec 5.7 makes backslash-bearing property names unaddressable too: a
    confirmed_fields entry spelling the raw key must grant no trust, so a
    trusted broader declaration wins."""
    hybrid = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid",
                            "confirmed_fields": [f"x_vendor.{literal_key}"]},
        "x_vendor": {literal_key: "untrusted"}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"},
        "x_vendor": {literal_key: "trusted"}}})
    eff, _ = ConflictResolver().resolve(
        "light.k", [Layer("entity", hybrid), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {literal_key: "trusted"}


@pytest.mark.parametrize("literal_key", ["a\\b", "a\\.b"])
def test_backslash_keys_inherit_trust_from_a_clean_confirmed_ancestor(
    literal_key: str,
) -> None:
    """Unaddressable does not mean untrustable: a confirmed clean ancestor
    covers the whole value, backslash keys included."""
    hybrid = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "hybrid", "confirmed_fields": ["x_vendor"]},
        "x_vendor": {literal_key: "whole-confirmed"}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"},
        "x_vendor": {literal_key: "dev"}}})
    eff, _ = ConflictResolver().resolve(
        "light.k", [Layer("entity", hybrid), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {literal_key: "whole-confirmed"}


def test_backslash_and_dotted_keys_render_unique_explanation_paths() -> None:
    """A literal 'a\\b', a literal 'a.b', and nested a.b coexist with three
    distinct field_path renderings."""
    entity = SemanticProfile.from_dict("light.k", {"semantic_profile": {
        "metadata_origin": {"source": "user"},
        "x_vendor": {"a\\b": 1, "a.b": 2}}})
    domain = SemanticProfile.from_dict("light", {"semantic_profile": {
        "metadata_origin": {"source": "developer"}, "x_vendor": {"a": {"b": 3}}}})
    eff, res = ConflictResolver().resolve(
        "light.k", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert eff.raw["semantic_profile"]["x_vendor"] == {"a\\b": 1, "a.b": 2, "a": {"b": 3}}
    paths = sorted(e.field_path for e in res.explanations if "x_vendor" in e.field_path)
    assert paths == ["x_vendor.a.b", "x_vendor.a\\.b", "x_vendor.a\\\\b"]
    assert len(set(paths)) == 3
