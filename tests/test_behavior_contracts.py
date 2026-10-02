"""Behavior contracts derived from the October audit mutation witnesses."""

import asyncio
import logging
import threading
from datetime import datetime, timedelta

import pytest

from mesa_core import MesaEnforcer, ProfileStore, SemanticProfile, validate_document
from mesa_core.backends import MemoryBackend
from mesa_core.conflict import ConflictResolver, Layer
from mesa_core.enforcer import ConfirmationManager
from mesa_core.exceptions import InvalidCursorError, LeaseNotFoundError
from mesa_core.lease import LeaseManager
from mesa_core.mcp.tools import MesaToolHandlers
from mesa_core.privacy import CallerContext, PrivacyEnforcer
from mesa_core.profile import (
    ControlMode,
    OperationalBoundaries,
    PrivacyClassification,
    PrivacyLevel,
    TriggersAutomations,
)
from mesa_core.store import DeploymentDefaults, _encode_cursor
from mesa_core.temporal import TemporalEvaluator

NOON = datetime(2026, 6, 13, 12, 0)
NOW = datetime(2026, 7, 2, 12, 0, 0)


def doc(ob=None, source="user", privacy=None, **sp_extra):
    mo = {"source": source}
    if source == "inferred_ai":
        mo |= {"confidence": 0.9, "generated_at": "2026-06-01T00:00:00+00:00"}
    if source == "hybrid":
        mo["confirmed_fields"] = []
    sp = {"metadata_origin": mo}
    if ob is not None:
        sp["operational_boundaries"] = ob
    sp.update(sp_extra)
    d = {"semantic_profile": sp}
    if privacy is not None:
        d["privacy_classification"] = privacy
    return d


def put(store, key, d):
    store.set(key, SemanticProfile.from_dict(key, d))


def prof(key, d):
    return SemanticProfile.from_dict(key, d)


def limit(
    max_value=None,
    min_value=None,
    permitted=None,
    service="light.turn_on",
    parameter="brightness",
    predicate=None,
    id="cap",
):
    spec = {"service": service, "parameter": parameter}
    if max_value is not None:
        spec["max_value"] = max_value
    if min_value is not None:
        spec["min_value"] = min_value
    if permitted is not None:
        spec["permitted_values"] = permitted
    entry = {
        "id": id,
        "limit": spec,
        "human_reason": "witness",
        "predicate": predicate or {"entity": "sensor.on", "operator": "eq", "value": "on"},
    }
    return entry


def enforcer_for(entity, ob, store=None, **kw):
    store = store or ProfileStore(MemoryBackend())
    put(store, entity, doc(ob))
    kw.setdefault("get_state", lambda eid: "on")
    return MesaEnforcer(store, **kw)


# ============================================================ baseline table (profile.py)
BASELINE = {
    "light": ControlMode.AUTONOMOUS,
    "media_player": ControlMode.CONFIRM,
    "input_select": ControlMode.CONFIRM,
    "switch": ControlMode.CONFIRM,
    "cover": ControlMode.CONFIRM,
    "climate": ControlMode.CONFIRM,
    "lock": ControlMode.PROHIBITED,
    "alarm_control_panel": ControlMode.PROHIBITED,
    "input_boolean": ControlMode.CONFIRM,
    "script": ControlMode.CONFIRM,
    "scene": ControlMode.CONFIRM,
    "vacuum": ControlMode.CONFIRM,  # not in the table: unknown domains must default to confirm (Spec 4)
}


@pytest.mark.parametrize("domain", sorted(BASELINE))
def test_w_B_baseline(domain):
    enforcer = MesaEnforcer(ProfileStore(MemoryBackend()))
    result = enforcer.evaluate(f"{domain}.x", f"{domain}.act", current_time=NOON)
    expected = BASELINE[domain]
    if expected == ControlMode.AUTONOMOUS:
        assert result.allowed
    else:
        assert not result.allowed
        assert result.rule_applied == f"control_mode:{expected.value}"


def test_public_vs_normal_rule_c():
    entity = prof("sensor.x", doc(source="user", privacy={"level": "public"}))
    domain = prof("sensor", doc(source="user", privacy={"level": "normal"}))
    effective, _ = ConflictResolver().resolve(
        "sensor.x", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert effective.privacy_classification.level == PrivacyLevel.NORMAL


def test_unknown_below_inferred_at_equal_scope():
    unknown = prof("light.x", doc({"control_reason": "from unknown"}, source="unknown"))
    inferred = prof("light.x", doc({"control_reason": "from inferred"}, source="inferred_ai"))
    effective, _ = ConflictResolver().resolve(
        "light.x", [Layer("entity", unknown), Layer("entity", inferred)]
    )
    assert effective.operational_boundaries.control_reason == "from inferred"


def test_timer_is_a_helper_domain():
    inferred = prof("timer.x", doc({"triggers_automations": "none"}, source="inferred_ai"))
    effective, _ = ConflictResolver().resolve("timer.x", [Layer("entity", inferred)])
    assert effective.operational_boundaries.triggers_automations == TriggersAutomations.LIKELY


# ============================================================ conflict.py
def test_equal_restrictiveness_tie_goes_to_most_specific_scope():
    entity = prof("light.x", doc({"control_mode": "confirm"}))
    domain = prof("light", doc({"control_mode": "confirm"}, source="developer"))
    _, res = ConflictResolver().resolve(
        "light.x", [Layer("entity", entity), Layer("domain", domain)]
    )
    entry = next(
        e for e in res.explanations if e.field_path == "operational_boundaries.control_mode"
    )
    assert entry.provided_by_level == "entity"


def test_override_requires_declared_autonomous():
    p = prof(
        "media_player.x",
        doc(
            {
                "control_mode": "confirm",
                "override_control_mode": True,
                "control_reason": "operator says so",
            }
        ),
    )
    effective, res = ConflictResolver().resolve("media_player.x", [Layer("entity", p)])
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM
    assert any("override_control_mode is malformed" in w for w in res.warnings)


def test_triggers_override_value_must_be_none_or_deployment_defined():
    entity = prof(
        "switch.x",
        doc(
            {
                "triggers_automations": "unknown",
                "override_triggers_automations": True,
                "human_reason": "why",
            }
        ),
    )
    domain = prof("switch", doc({"triggers_automations": "likely"}, source="developer"))
    effective, res = ConflictResolver().resolve(
        "switch.x", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert effective.operational_boundaries.triggers_automations == TriggersAutomations.LIKELY
    assert any("override_triggers_automations is malformed" in w for w in res.warnings)


def test_absent_privacy_level_does_not_compete():
    entity = prof("sensor.x", doc(source="user", privacy={"level": "public"}))
    domain = prof(
        "sensor", doc({"control_mode": "autonomous"}, source="developer")
    )  # declares no privacy
    effective, _ = ConflictResolver().resolve(
        "sensor.x", [Layer("entity", entity), Layer("domain", domain)]
    )
    assert effective.privacy_classification.level == PrivacyLevel.PUBLIC


def test_confirmed_fields_on_non_hybrid_carry_no_weight_at_layer_level():
    p = prof("lock.front", doc({"control_mode": "autonomous"}, source="inferred_ai"))
    p.metadata.confirmed_fields = [
        "operational_boundaries.control_mode"
    ]  # programmatic: bypasses validation
    effective, _ = ConflictResolver().resolve("lock.front", [Layer("entity", p)])
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM


def test_id_less_limits_are_not_collapsed():
    from mesa_core.profile import MetadataOrigin, ProfileMetadata

    def layer_profile(entity_id, source, parameter, bound):
        p = SemanticProfile(entity_id=entity_id, metadata=ProfileMetadata(source=source))
        p.operational_boundaries.declared_limits = [
            {"limit": {"service": "light.turn_on", "parameter": parameter, "max_value": bound}}
        ]
        p.declared_paths = {"operational_boundaries.declared_limits"}
        return p

    a = layer_profile("light.x", MetadataOrigin.USER, "brightness", 10)
    b = layer_profile("light", MetadataOrigin.DEVELOPER, "color_temp", 400)
    effective, _ = ConflictResolver().resolve("light.x", [Layer("entity", a), Layer("domain", b)])
    assert len(effective.operational_boundaries.declared_limits) == 2


def test_capability_hint_ranks_below_declared_domain_value():
    integration = prof(
        "hue",
        {
            "semantic_profile": {
                "metadata_origin": {"source": "developer"},
                "capability_semantics": {"control_mode": "confirm"},
            }
        },
    )
    domain = prof("light", doc({"control_mode": "confirm"}, source="developer"))
    _, res = ConflictResolver().resolve(
        "light.x", [Layer("integration", integration), Layer("domain", domain)]
    )
    entry = next(
        e for e in res.explanations if e.field_path == "operational_boundaries.control_mode"
    )
    assert entry.provided_by_level == "domain"


# ============================================================ enforcer.py: limits and predicates
def test_permitted_values_compare_as_strings():
    enf = enforcer_for(
        "light.x",
        {
            "control_mode": "autonomous",
            "enforcement_mode": "enforced",
            "declared_limits": [limit(permitted=[1, 2], parameter="effect_id")],
        },
    )
    assert enf.evaluate("light.x", "light.turn_on", {"effect_id": "1"}, current_time=NOON).allowed


def test_limit_applies_only_to_its_service():
    enf = enforcer_for(
        "light.x",
        {
            "control_mode": "autonomous",
            "enforcement_mode": "enforced",
            "declared_limits": [limit(max_value=100)],
        },
    )
    assert enf.evaluate("light.x", "light.toggle", {"brightness": 255}, current_time=NOON).allowed
    assert not enf.evaluate(
        "light.x", "light.turn_on", {"brightness": 255}, current_time=NOON
    ).allowed


def _pred(op, value):
    return {"entity": "sensor.s", "operator": op, "value": value}


def test_gt_predicate_is_inactive_at_equality():
    enf = enforcer_for(
        "light.x",
        {
            "control_mode": "autonomous",
            "enforcement_mode": "enforced",
            "declared_limits": [limit(max_value=100, predicate=_pred("gt", 5))],
        },
        get_state=lambda eid: "5",
    )
    assert enf.evaluate("light.x", "light.turn_on", {"brightness": 255}, current_time=NOON).allowed


def test_lte_predicate_is_active_at_equality():
    enf = enforcer_for(
        "light.x",
        {
            "control_mode": "autonomous",
            "enforcement_mode": "enforced",
            "declared_limits": [limit(max_value=100, predicate=_pred("lte", 5))],
        },
        get_state=lambda eid: "5",
    )
    assert not enf.evaluate(
        "light.x", "light.turn_on", {"brightness": 255}, current_time=NOON
    ).allowed


def test_non_numeric_value_fails_closed_against_min_value():
    enf = enforcer_for(
        "light.x",
        {
            "control_mode": "autonomous",
            "enforcement_mode": "enforced",
            "declared_limits": [limit(min_value=10)],
        },
    )
    result = enf.evaluate("light.x", "light.turn_on", {"brightness": "abc"}, current_time=NOON)
    assert not result.allowed
    assert "not comparable to min_value" in result.reason


def test_unavailable_state_is_normalised():
    enf = enforcer_for(
        "light.x",
        {
            "control_mode": "autonomous",
            "enforcement_mode": "enforced",
            "declared_limits": [limit(max_value=100, predicate=_pred("eq", "on"))],
        },
        get_state=lambda eid: " Unavailable ",
    )
    assert not enf.evaluate(
        "light.x", "light.turn_on", {"brightness": 255}, current_time=NOON
    ).allowed


def test_ha_condition_predicate_fails_closed():
    pred = {
        "type": "ha_condition",
        "condition": {"condition": "state", "entity_id": "sun.sun", "state": "above_horizon"},
    }
    enf = enforcer_for(
        "light.x",
        {
            "control_mode": "autonomous",
            "enforcement_mode": "enforced",
            "declared_limits": [limit(max_value=100, predicate=pred)],
        },
        get_state=lambda eid: "on",
    )
    result = enf.evaluate("light.x", "light.turn_on", {"brightness": 255}, current_time=NOON)
    assert not result.allowed
    assert any("ha_condition" in w for w in result.warnings)


def test_advisory_mode_warns_on_limit_violation():
    enf = enforcer_for(
        "light.x",
        {
            "control_mode": "autonomous",
            "enforcement_mode": "advisory",
            "declared_limits": [limit(max_value=100)],
        },
        mode="advisory",
    )
    result = enf.evaluate("light.x", "light.turn_on", {"brightness": 255}, current_time=NOON)
    assert result.allowed
    assert any(w.startswith("advisory:") for w in result.warnings)


def _inferred_enforcer(confidence):
    store = ProfileStore(MemoryBackend())
    d = doc({"control_mode": "confirm", "enforcement_mode": "advisory"}, source="inferred_ai")
    d["semantic_profile"]["metadata_origin"]["confidence"] = confidence
    put(store, "light.x", d)
    return MesaEnforcer(store, mode="advisory")


def test_confidence_below_floor_warns():
    result = _inferred_enforcer(0.65).evaluate("light.x", "light.turn_on", current_time=NOON)
    assert any("Rule 3" in w for w in result.warnings)


def test_confidence_at_floor_does_not_warn():
    result = _inferred_enforcer(0.7).evaluate("light.x", "light.turn_on", current_time=NOON)
    assert not any("Rule 3" in w for w in result.warnings)


# ============================================================ enforcer.py: privacy + confirmation
CAMERA = {
    "semantic_profile": {
        "metadata_origin": {"source": "user"},
        "operational_boundaries": {"control_mode": "confirm", "enforcement_mode": "enforced"},
    },
    "privacy_classification": {"level": "sensitive", "access_roles": {"deny_for": ["guest"]}},
}
GUEST = CallerContext("guest1", roles=["guest"], is_authenticated=True)


def test_deny_for_is_a_privacy_block_not_a_confirmation_prompt():
    store = ProfileStore(MemoryBackend())
    put(store, "camera.x", CAMERA)
    enf = MesaEnforcer(store)
    result = enf.evaluate("camera.x", "camera.turn_on", caller_context=GUEST, current_time=NOON)
    assert not result.allowed
    assert result.rule_applied == "privacy:deny_for"
    assert result.confirmation_challenge is None


def test_token_is_bound_to_the_entity():
    mgr = ConfirmationManager()
    ch = mgr.issue("light.a", "light.turn_on", {"brightness": 5}, NOW)
    token = {
        "challenge_id": ch["challenge_id"],
        "approved_by": "me",
        "approved_at": NOW.isoformat(),
    }
    ok, _ = mgr.redeem(token, "lock.front_door", "light.turn_on", {"brightness": 5}, NOW)
    assert not ok


def test_token_is_bound_to_the_service():
    mgr = ConfirmationManager()
    ch = mgr.issue("light.a", "light.turn_on", {"brightness": 5}, NOW)
    token = {
        "challenge_id": ch["challenge_id"],
        "approved_by": "me",
        "approved_at": NOW.isoformat(),
    }
    ok, _ = mgr.redeem(token, "light.a", "light.turn_off", {"brightness": 5}, NOW)
    assert not ok


def test_token_valid_at_exact_expiry_instant():
    mgr = ConfirmationManager()
    ch = mgr.issue("light.a", "light.turn_on", {}, NOW)
    token = {
        "challenge_id": ch["challenge_id"],
        "approved_by": "me",
        "approved_at": NOW.isoformat(),
    }
    ok, _ = mgr.redeem(token, "light.a", "light.turn_on", {}, NOW + timedelta(seconds=120))
    assert ok


def test_param_key_order_does_not_matter():
    mgr = ConfirmationManager()
    ch = mgr.issue("light.a", "light.turn_on", {"a": 1, "b": 2}, NOW)
    token = {
        "challenge_id": ch["challenge_id"],
        "approved_by": "me",
        "approved_at": NOW.isoformat(),
    }
    ok, _ = mgr.redeem(token, "light.a", "light.turn_on", {"b": 2, "a": 1}, NOW)
    assert ok


def test_a_live_challenge_survives_a_later_issue():
    mgr = ConfirmationManager()
    first = mgr.issue("light.a", "light.turn_on", {}, NOW)
    mgr.issue("light.b", "light.turn_on", {}, NOW + timedelta(seconds=1))
    token = {
        "challenge_id": first["challenge_id"],
        "approved_by": "me",
        "approved_at": NOW.isoformat(),
    }
    ok, msg = mgr.redeem(token, "light.a", "light.turn_on", {}, NOW + timedelta(seconds=2))
    assert ok, msg


def test_expired_challenges_are_evicted_on_next_issue():
    mgr = ConfirmationManager()
    first = mgr.issue("light.a", "light.turn_on", {}, NOW)
    mgr.issue("light.b", "light.turn_on", {}, NOW + timedelta(seconds=500))
    assert first["challenge_id"] not in mgr._challenges
    assert len(mgr._challenges) == 1


def test_rejected_token_rule_label():
    store = ProfileStore(MemoryBackend())
    put(store, "cover.x", doc({"control_mode": "confirm", "enforcement_mode": "enforced"}))
    enf = MesaEnforcer(store)
    bad = {"challenge_id": "nope", "approved_by": "me", "approved_at": NOW.isoformat()}
    result = enf.evaluate("cover.x", "cover.open_cover", confirmation_token=bad, current_time=NOON)
    assert result.rule_applied == "control_mode:confirm"


def test_person_entities_are_always_audit_logged_by_the_enforcer(caplog):
    store = ProfileStore(MemoryBackend())
    put(store, "person.alex", doc({"control_mode": "autonomous"}, privacy={"level": "normal"}))
    with caplog.at_level(logging.DEBUG, logger="mesa_core.audit"):
        MesaEnforcer(store).evaluate("person.alex", "person.set", current_time=NOON)
    events = [r.mesa_audit_event for r in caplog.records if hasattr(r, "mesa_audit_event")]
    assert any(e["event_type"] == "privacy_access" for e in events)


def test_challenge_ids_are_unique_and_unpredictable():
    mgr = ConfirmationManager()
    a = mgr.issue("light.a", "light.turn_on", {}, NOW)["challenge_id"]
    b = mgr.issue("light.b", "light.turn_on", {}, NOW)["challenge_id"]
    assert a != b
    assert len(a) == 32 and a != "0" * 32


def test_async_evaluate_applies_caller_privacy():
    store = ProfileStore(MemoryBackend())
    put(store, "camera.x", CAMERA)
    enf = MesaEnforcer(store)
    result = asyncio.run(enf.aevaluate("camera.x", "camera.turn_on", None, GUEST, NOON))
    assert not result.allowed
    assert result.rule_applied == "privacy:deny_for"


@pytest.mark.parametrize("field", ["approved_by", "approved_at"])
def test_empty_approval_fields_are_rejected(field):
    mgr = ConfirmationManager()
    ch = mgr.issue("light.a", "light.turn_on", {}, NOW)
    token = {
        "challenge_id": ch["challenge_id"],
        "approved_by": "me",
        "approved_at": NOW.isoformat(),
    }
    token[field] = ""
    ok, _ = mgr.redeem(token, "light.a", "light.turn_on", {}, NOW)
    assert not ok


def test_issue_is_thread_safe():
    import sys

    mgr = ConfirmationManager()
    errors = []

    def issuer(tag):
        try:
            for i in range(200):
                mgr.issue(f"light.{tag}", "light.turn_on", {"i": i}, NOW)
        except Exception as err:
            errors.append(err)

    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # make the unsynchronised interleaving reproducible
    try:
        threads = [threading.Thread(target=issuer, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(previous)
    assert not errors, errors[:1]


# ============================================================ temporal.py
EV = TemporalEvaluator()


def tr(start, end, h, m=0, s=0):
    return EV.evaluate_condition(
        {"type": "time_range", "start_time": start, "end_time": end}, datetime(2026, 6, 13, h, m, s)
    )


def test_time_range_is_start_inclusive_end_exclusive():
    assert tr("09:00", "17:00", 9, 0) is True
    assert tr("09:00", "17:00", 17, 0) is False
    assert tr("09:00", "17:00", 8, 59, 59) is False
    assert tr("09:00", "17:00", 12, 0) is True
    assert tr("09:00", "17:00", 20, 0) is False


def test_midnight_range_is_start_inclusive_end_exclusive():
    assert tr("22:00", "06:00", 22, 0) is True
    assert tr("22:00", "06:00", 6, 0) is False
    assert tr("22:00", "06:00", 5, 59, 59) is True


def test_start_equals_end_covers_the_full_day():
    assert tr("09:00", "09:00", 9, 0) is True
    assert tr("09:00", "09:00", 15, 0) is True


@pytest.mark.parametrize("days", [[], "mon", None])
def test_unusable_day_lists_are_unevaluable(days):
    cond = {"type": "day_of_week", "days": days}
    assert EV.evaluate_condition(cond, NOON) is None


def test_negate_requires_boolean_true():
    cond = {"type": "day_of_week", "days": ["sat"], "negate": "yes"}
    assert EV.evaluate_condition(cond, NOON) is True  # 2026-06-13 is a Saturday


def _boundaries(mode):
    ob = OperationalBoundaries()
    ob.control_mode = mode
    ob.temporal_constraints = [
        {
            "id": "t",
            "condition": {"type": "day_of_week", "days": ["sat"]},
            "effect": {"control_mode": "prohibited"},
        }
    ]
    return ob


def test_equal_rank_effect_does_not_replace_read_only():
    result = TemporalEvaluator().apply(_boundaries(ControlMode.READ_ONLY), NOON)
    assert result.boundaries.control_mode == ControlMode.READ_ONLY


def test_temporal_permitted_values_effect_is_enforced():
    ob = {
        "control_mode": "autonomous",
        "enforcement_mode": "enforced",
        "temporal_constraints": [
            {
                "id": "night",
                "condition": {"type": "day_of_week", "days": ["sat"]},
                "effect": {
                    "service": "light.turn_on",
                    "parameter": "color_name",
                    "permitted_values": ["red"],
                },
            }
        ],
    }
    enf = enforcer_for("light.x", ob)
    assert not enf.evaluate(
        "light.x", "light.turn_on", {"color_name": "blue"}, current_time=NOON
    ).allowed
    assert enf.evaluate(
        "light.x", "light.turn_on", {"color_name": "red"}, current_time=NOON
    ).allowed


def test_effect_with_service_only_creates_no_limit():
    ob = OperationalBoundaries()
    ob.temporal_constraints = [
        {
            "id": "t",
            "condition": {"type": "day_of_week", "days": ["sat"]},
            "effect": {"control_mode": "confirm", "service": "light.turn_on"},
        }
    ]
    assert TemporalEvaluator().apply(ob, NOON).active_limits == []


def test_sunrise_is_strictly_above_zero_elevation():
    ev = TemporalEvaluator(get_solar_elevation=lambda at: 0.0)
    assert ev.evaluate_condition({"type": "solar_angle", "solar_event": "sunrise"}, NOON) is False


@pytest.mark.parametrize(
    ("event", "elevation", "expected"),
    [
        ("civil_twilight_start", -5.0, True),
        ("civil_twilight_start", -7.0, False),
        ("civil_twilight_end", -7.0, True),
        ("civil_twilight_end", -5.0, False),
        ("nautical_twilight_start", -11.0, True),
        ("nautical_twilight_start", -13.0, False),
        ("nautical_twilight_end", -13.0, True),
        ("nautical_twilight_end", -11.0, False),
    ],
)
def test_twilight_thresholds(event, elevation, expected):
    ev = TemporalEvaluator(get_solar_elevation=lambda at: elevation)
    assert ev.evaluate_condition({"type": "solar_angle", "solar_event": event}, NOON) is expected


def test_raising_solar_callback_is_unevaluable():
    def boom(at):
        raise RuntimeError("sun unavailable")

    ev = TemporalEvaluator(get_solar_elevation=boom)
    assert ev.evaluate_condition({"type": "solar_angle", "solar_event": "sunset"}, NOON) is None


@pytest.mark.parametrize(
    "cond",
    [
        {"type": "time_range", "start_time": "xx", "end_time": "06:00"},
        {"type": "time_range", "end_time": "06:00"},
        {"type": "time_range", "start_time": 900, "end_time": "06:00"},
    ],
)
def test_malformed_time_range_is_unevaluable(cond):
    assert EV.evaluate_condition(cond, NOON) is None


# ============================================================ privacy.py
def _caller(*roles):
    return CallerContext("c", roles=list(roles), is_authenticated=True)


def test_restricted_for_wins_over_unrestricted_for():
    pc = PrivacyClassification(
        level=PrivacyLevel.SENSITIVE,
        access_roles={"restricted_for": ["a"], "unrestricted_for": ["b"]},
    )
    decision = PrivacyEnforcer().evaluate(pc, _caller("a", "b"), entity_id="camera.x")
    assert decision.effective_level == PrivacyLevel.RESTRICTED


def test_sensitive_access_is_audit_logged():
    records = []

    class H(logging.Handler):
        def emit(self, record):
            records.append(record)

    lg = logging.getLogger("witness.audit")
    lg.addHandler(H())
    lg.setLevel(logging.DEBUG)
    pc = PrivacyClassification(level=PrivacyLevel.SENSITIVE)
    PrivacyEnforcer(logger=lg).evaluate(pc, _caller("x"), entity_id="camera.x")
    assert len(records) == 1


# ============================================================ validation.py
def test_zero_confidence_is_valid():
    d = {
        "semantic_profile": {
            "metadata_origin": {
                "source": "inferred_ai",
                "confidence": 0.0,
                "generated_at": "2026-01-01T00:00:00Z",
            }
        }
    }
    assert validate_document(d).ok


def test_empty_limit_id_is_rejected():
    d = doc({"declared_limits": [limit(max_value=1, id="")]})
    assert not validate_document(d).ok


def test_realtime_state_volatility_is_valid():
    assert validate_document(doc({"state_volatility": "realtime"})).ok


def test_caregiver_household_role_is_valid():
    assert validate_document(doc(person_traits={"household_role": "caregiver"})).ok


def test_solar_offset_must_be_number():
    tc = {
        "id": "t",
        "condition": {"type": "solar_angle", "solar_event": "sunset", "solar_offset_minutes": "30"},
        "effect": {"control_mode": "confirm"},
    }
    assert not validate_document(doc({"temporal_constraints": [tc]})).ok


def test_duration_seconds_must_be_number():
    tc = {
        "id": "t",
        "condition": {"type": "duration", "duration_seconds": "ten"},
        "effect": {"control_mode": "confirm"},
    }
    assert not validate_document(doc({"temporal_constraints": [tc]})).ok


def test_malformed_override_is_warned_about():
    report = validate_document(doc({"control_mode": "autonomous", "override_control_mode": True}))
    assert any("override_control_mode" in w for w in report.warnings)


# ============================================================ lease
def automation(automation_id, level, trigger=None, affected=None, **extra):
    sp = {
        "metadata_origin": {"source": "user"},
        "cooperative_priority": {"level": level},
        "environmental_dependencies": {"trigger_entities": trigger or [], "condition_entities": []},
        "intent_archetype": {"affected_entities": affected or []},
    }
    sp.update(extra)
    return prof(automation_id, {"semantic_profile": sp})


def lease_manager(*profiles, **kw):
    store = ProfileStore(MemoryBackend())
    for p in profiles:
        store.set(p.entity_id, p)
    return LeaseManager(store, **kw)


@pytest.mark.parametrize("state", ["unknown", "unavailable", None])
def test_protected_automation_with_unreadable_state_denies(state):
    mgr = lease_manager(
        automation("automation.guard", "protected", trigger=["lock.front"]),
        get_state=lambda eid: state,
    )
    response = mgr.request(["lock.front"], 10, session_id="s", now=NOW)
    assert not response.granted


def test_lease_is_expired_at_exact_expiry():
    mgr = LeaseManager()
    mgr.request(["light.x"], 10, session_id="s", now=NOW)
    assert mgr.active_leases(now=NOW + timedelta(seconds=10)) == []


def test_malformed_environmental_dependencies_fail_closed():
    raw = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "cooperative_priority": {"level": "protected"},
            "environmental_dependencies": "oops",
        }
    }
    mgr = LeaseManager(ProfileStore(MemoryBackend({"automation.guard": raw})))
    assert not mgr.request(["light.x"], 10, session_id="s", now=NOW).granted


def test_malformed_intent_archetype_fails_closed_for_critical():
    p = automation("automation.guard", "critical", trigger=["sensor.x"], intent_archetype="oops")
    mgr = lease_manager(p)
    assert not mgr.request(["lock.front"], 10, session_id="s", now=NOW).granted


def test_request_sweeps_expired_leases_and_emits():
    events = []
    mgr = LeaseManager(on_lease_event=events.append)
    mgr.request(["light.x"], 10, session_id="a", now=NOW)
    mgr.request(["light.y"], 10, session_id="b", now=NOW + timedelta(seconds=20))
    assert [e["reason"] for e in events] == ["natural_expiry"]


def test_async_release_enforces_session_ownership():
    mgr = LeaseManager()
    lease_id = mgr.request(["light.x"], 10, session_id="owner", now=NOW).lease_id
    with pytest.raises(LeaseNotFoundError):
        asyncio.run(mgr.arelease(lease_id, session_id="intruder", now=NOW))


# ============================================================ mcp tools
class Who:
    def __init__(self, caller):
        self.caller = caller

    def __call__(self):
        return self.caller


def test_duration_seconds_rejects_booleans():
    handlers = MesaToolHandlers(ProfileStore(MemoryBackend()), lease_manager=LeaseManager())
    out = asyncio.run(
        handlers.mesa_request_lease({"entities": ["light.x"], "duration_seconds": True})
    )
    assert out.get("error") == "invalid_query"


@pytest.mark.parametrize("limit_value", [1, 200])
def test_limit_bounds_are_inclusive(limit_value):
    handlers = MesaToolHandlers(ProfileStore(MemoryBackend()))
    out = asyncio.run(handlers.mesa_query_profiles({"limit": limit_value}))
    assert "error" not in out, out


def test_retrieval_audit_records_minor_as_restricted(caplog):
    store = ProfileStore(MemoryBackend())
    put(
        store,
        "person.kid",
        doc(
            {"control_mode": "confirm"},
            privacy={"level": "normal"},
            person_traits={"is_minor": True},
        ),
    )
    handlers = MesaToolHandlers(store, caller_context_fn=Who(_caller("parent")))
    with caplog.at_level(logging.DEBUG, logger="mesa_core.audit"):
        asyncio.run(handlers.mesa_get_profile({"entity_id": "person.kid"}))
    levels = [
        r.mesa_audit_event["details"]["effective_level"]
        for r in caplog.records
        if hasattr(r, "mesa_audit_event") and r.mesa_audit_event["event_type"] == "privacy_access"
    ]
    assert levels == ["restricted"]


def test_retrieval_of_person_entity_is_audit_logged(caplog):
    store = ProfileStore(MemoryBackend())
    put(store, "person.alex", doc({"control_mode": "confirm"}, privacy={"level": "normal"}))
    handlers = MesaToolHandlers(store, caller_context_fn=Who(_caller("parent")))
    with caplog.at_level(logging.DEBUG, logger="mesa_core.audit"):
        asyncio.run(handlers.mesa_get_profile({"entity_id": "person.alex"}))
    assert any(
        hasattr(r, "mesa_audit_event") and r.mesa_audit_event["event_type"] == "privacy_access"
        for r in caplog.records
    )


def test_release_tool_enforces_session_ownership():
    mgr = LeaseManager()
    who = Who(CallerContext("a", is_authenticated=True, session_id="session-a"))
    handlers = MesaToolHandlers(
        ProfileStore(MemoryBackend()), lease_manager=mgr, caller_context_fn=who
    )
    granted = asyncio.run(
        handlers.mesa_request_lease({"entities": ["light.x"], "duration_seconds": 10})
    )
    who.caller = CallerContext("b", is_authenticated=True, session_id="session-b")
    out = asyncio.run(handlers.mesa_release_lease({"lease_id": granted["lease_id"]}))
    assert out.get("error") == "lease_not_found"


def test_mixed_denial_is_not_a_lease_conflict_error():
    store = ProfileStore(MemoryBackend())
    store.set(
        "automation.guard", automation("automation.guard", "critical", trigger=["lock.front"])
    )
    mgr = LeaseManager(store)
    mgr.request(["light.y"], 20, session_id="other")
    who = Who(CallerContext("a", is_authenticated=True, session_id="mine"))
    handlers = MesaToolHandlers(store, lease_manager=mgr, caller_context_fn=who)
    out = asyncio.run(
        handlers.mesa_request_lease({"entities": ["lock.front", "light.y"], "duration_seconds": 5})
    )
    assert "error" not in out
    assert out["granted"] is False


# ============================================================ store.py
def _many(n):
    store = ProfileStore(MemoryBackend())
    for i in range(n):
        put(store, f"light.l{i:03d}", doc({"control_mode": "autonomous"}))
    return store


def test_limit_lower_clamp():
    store = _many(3)
    r0 = store.query(limit=0)
    assert r0.limit == 1 and len(r0.rows) == 1
    rneg = store.query(limit=-5)
    assert rneg.limit == 1 and len(rneg.rows) == 1


def test_limit_upper_clamp():
    store = _many(205)
    r = store.query(limit=9999)
    assert r.limit == 200 and len(r.rows) == 200 and r.has_more


def test_has_more_false_when_page_ends_exactly_at_last_row():
    store = _many(4)
    first = store.query(limit=2)
    assert first.has_more and first.next_cursor
    second = store.query(limit=2, cursor=first.next_cursor)
    assert len(second.rows) == 2
    assert second.has_more is False and second.next_cursor is None


def test_negative_cursor_offset_is_rejected():
    store = _many(3)
    with pytest.raises(InvalidCursorError):
        store.query(limit=1, cursor=_encode_cursor(-1, store._fingerprint()))


def test_deployment_defaults_triggers_automations_domains():
    store = ProfileStore(MemoryBackend())
    store.set_deployment_defaults(DeploymentDefaults(triggers_automations_domains=["switch"]))
    explanation = store.explain("switch.fan")
    assert (
        explanation.effective_profile.operational_boundaries.triggers_automations
        == TriggersAutomations.LIKELY
    )


def test_invalid_tags_match_is_rejected():
    with pytest.raises(ValueError):
        _many(2).query(tags=["x"], tags_match="bogus")


# ============================================================ raw SDK v1 adapter handlers
def _raw_sdk_server():
    mcp_server = pytest.importorskip("mcp.server")
    server = mcp_server.Server("w")
    if hasattr(server, "get_request_handler"):
        pytest.skip("SDK v1 decorator handlers only")
    store = ProfileStore(MemoryBackend())
    put(store, "light.kitchen", doc({"control_mode": "autonomous"}))
    from mesa_core.mcp.tools import register_mesa_tools

    register_mesa_tools(store, adapter="raw_sdk", server=server)
    return server


def test_raw_sdk_v1_list_tools_publishes_the_declared_schemas():
    from mcp import types

    from mesa_core.mcp.schemas import TOOL_SCHEMAS

    server = _raw_sdk_server()
    result = asyncio.run(
        server.request_handlers[types.ListToolsRequest](types.ListToolsRequest(method="tools/list"))
    )
    published = {t.name: t.inputSchema for t in result.root.tools}
    assert published == {name: TOOL_SCHEMAS[name] for name in published}


def test_raw_sdk_v1_call_tool_forwards_arguments_and_returns_the_payload():
    import json

    from mcp import types

    server = _raw_sdk_server()
    call = server.request_handlers[types.CallToolRequest]

    def invoke(name, arguments):
        req = types.CallToolRequest(
            method="tools/call", params=types.CallToolRequestParams(name=name, arguments=arguments)
        )
        return json.loads(asyncio.run(call(req)).root.content[0].text)

    assert (
        invoke("mesa_get_profile", {"entity_id": "light.kitchen"})["entity_id"] == "light.kitchen"
    )
    assert invoke("mesa_frobnicate", {})["error"] == "unknown_tool"


def test_raw_sdk_dispatch_forwards_arguments():
    from mesa_core.mcp.tools import register_mesa_tools

    store = ProfileStore(MemoryBackend())
    put(store, "light.kitchen", doc({"control_mode": "autonomous"}))
    mcp_server = pytest.importorskip("mcp.server")
    registry = register_mesa_tools(store, adapter="raw_sdk", server=mcp_server.Server("w"))
    out = asyncio.run(registry.dispatch("mesa_get_profile", {"entity_id": "light.kitchen"}))
    assert out["entity_id"] == "light.kitchen"


# ============================================================ second-tier survivors
def test_staleness_window_boundary_is_not_yet_stale():
    p = prof(
        "light.x",
        {
            "semantic_profile": {
                "metadata_origin": {
                    "source": "inferred_ai",
                    "confidence": 0.9,
                    "generated_at": "2026-01-01T00:00:00",
                }
            }
        },
    )
    assert p.staleness_status(now=datetime(2026, 3, 2, 0, 0, 0)) == "current"  # exactly 60 days
    assert p.staleness_status(now=datetime(2026, 3, 2, 0, 0, 1)) == "stale"


def test_review_after_days_boundary_is_not_yet_due():
    p = prof(
        "light.x",
        {
            "semantic_profile": {
                "metadata_origin": {"source": "user"},
                "last_updated": "2026-01-01T00:00:00",
                "profile_valid_for": {"review_after_days": 30},
            }
        },
    )
    assert p.validity_warnings(now=datetime(2026, 1, 31, 0, 0, 0)) == []
    assert p.validity_warnings(now=datetime(2026, 1, 31, 0, 0, 1))


def test_trust_predicates():
    for source, trusted in (("developer", True), ("user", True), ("unknown", False)):
        p = prof("light.x", {"semantic_profile": {"metadata_origin": {"source": source}}})
        assert p.is_trusted() is trusted
        assert p.effective_confidence() == (1.0 if trusted else 0.0)
    hybrid = prof(
        "light.x",
        {"semantic_profile": {"metadata_origin": {"source": "hybrid", "confirmed_fields": []}}},
    )
    assert hybrid.is_trusted() is True
    inferred = prof(
        "light.x",
        {
            "semantic_profile": {
                "metadata_origin": {
                    "source": "inferred_ai",
                    "confidence": 0.4,
                    "generated_at": "2026-01-01T00:00:00",
                }
            }
        },
    )
    assert inferred.is_trusted() is False
    assert inferred.effective_confidence() == 0.4


def test_empty_archive_key_is_rejected():
    from mesa_core.portability import import_profiles

    store = ProfileStore(MemoryBackend())
    result = import_profiles(
        store,
        {
            "mesa_export": {
                "format_version": "1.1",
                "entities": {"": doc({"control_mode": "confirm"})},
            }
        },
    )
    assert result.imported == 0 and "entities:" in result.invalid


def test_error_policy_detects_existing_deployment_defaults():
    from mesa_core.exceptions import MesaError
    from mesa_core.portability import import_profiles

    store = ProfileStore(MemoryBackend())
    store.set_deployment_defaults(DeploymentDefaults())
    archive = {
        "mesa_export": {
            "format_version": "1.1",
            "deployment_defaults": {"deployment_defaults": {"default_control_mode": "confirm"}},
        }
    }
    with pytest.raises(MesaError):
        import_profiles(store, archive, on_conflict="error")


def test_malformed_effective_profile_does_not_abort_trigger_validation():
    from mesa_core.trigger_validator import TriggerValidator

    store = ProfileStore(
        MemoryBackend(
            {
                "switch.bad": {
                    "semantic_profile": {"operational_boundaries": {"control_mode": "yolo"}}
                }
            }
        )
    )
    assert TriggerValidator(store).validate(lambda: [], entity_ids=["switch.bad"]) == []


def test_host_entity_registry_enumerates_inherited_none():
    from mesa_core.trigger_validator import TriggerValidator

    store = ProfileStore(MemoryBackend())
    store.set_domain_profile("switch", prof("switch", doc({"triggers_automations": "none"})))
    configs = [
        {"id": "automation.a", "trigger": [{"platform": "state", "entity_id": "switch.test"}]}
    ]
    issues = TriggerValidator(store).validate(lambda: configs, entity_ids=["switch.test"])
    assert [i.entity_id for i in issues] == ["switch.test"]


# ============================================================ storage backend contract
@pytest.fixture(params=["memory", "jsonfile", "sqlite"])
def backend(request, tmp_path):
    from mesa_core.backends import JsonFileBackend, SqliteBackend

    if request.param == "memory":
        return MemoryBackend()
    if request.param == "jsonfile":
        return JsonFileBackend(tmp_path / "j")
    return SqliteBackend(tmp_path / "s.db")


def test_overwrite_replaces_the_stored_document(backend):
    backend.write("light.x", {"v": 1})
    backend.write("light.x", {"v": 2})
    assert backend.read("light.x") == {"v": 2}


def test_prefix_is_literal_and_anchored(backend):
    backend.write("__domain__:light", {"v": 1})
    backend.write("abdomaincd:light", {"v": 2})  # '_' must not act as a LIKE wildcard
    backend.write("x__domain__:light", {"v": 3})  # prefix must be anchored at the start
    assert backend.list_keys("__domain__:") == ["__domain__:light"]


def test_list_keys_is_sorted(backend):
    for key in ("light.c", "light.a", "light.b"):
        backend.write(key, {"v": 1})
    assert backend.list_keys() == ["light.a", "light.b", "light.c"]


def test_documents_are_isolated_from_callers():
    backend = MemoryBackend()
    original = {"semantic_profile": {"tags": ["a"]}}
    backend.write("light.x", original)
    original["semantic_profile"]["tags"].append("mutated-by-caller")
    first = backend.read("light.x")
    first["semantic_profile"]["tags"].append("mutated-after-read")
    assert backend.read("light.x") == {"semantic_profile": {"tags": ["a"]}}


def test_initial_data_is_copied():
    initial = {"light.x": {"v": 1}}
    backend = MemoryBackend(initial)
    initial["light.x"]["v"] = 99
    assert backend.read("light.x") == {"v": 1}


# ============================================================ never-executed enforcer and lease lines
@pytest.mark.parametrize(("state", "blocked"), [("playing", True), ("idle", False)])
def test_contains_predicate(state, blocked):
    enf = enforcer_for(
        "light.x",
        {
            "control_mode": "autonomous",
            "enforcement_mode": "enforced",
            "declared_limits": [limit(max_value=100, predicate=_pred("contains", "play"))],
        },
        get_state=lambda eid: state,
    )
    assert enf.evaluate(
        "light.x", "light.turn_on", {"brightness": 255}, current_time=NOON
    ).allowed is (not blocked)


def test_limit_is_skipped_when_the_call_does_not_carry_the_parameter():
    enf = enforcer_for(
        "light.x",
        {
            "control_mode": "autonomous",
            "enforcement_mode": "enforced",
            "declared_limits": [limit(max_value=100)],
        },
    )
    assert enf.evaluate(
        "light.x", "light.turn_on", {"color_name": "red"}, current_time=NOON
    ).allowed


def test_protected_automation_without_dependencies_fails_closed():
    p = prof(
        "automation.guard",
        {
            "semantic_profile": {
                "metadata_origin": {"source": "user"},
                "cooperative_priority": {"level": "protected"},
            }
        },
    )
    mgr = lease_manager(p, get_state=lambda eid: "on")
    assert not mgr.request(["light.x"], 10, session_id="s", now=NOW).granted


def test_async_release_session_forwards_now():
    mgr = LeaseManager()
    mgr.request(["light.x"], 10, session_id="s", now=NOW)
    assert asyncio.run(mgr.arelease_session("s", now=NOW + timedelta(seconds=1))) == 1


def test_async_expire_uses_the_supplied_clock():
    events = []
    mgr = LeaseManager(on_lease_event=events.append)
    future = datetime(2100, 1, 1)
    mgr.request(["light.x"], 10, session_id="s", now=future)
    asyncio.run(mgr.aexpire(future + timedelta(seconds=20)))
    assert [e["reason"] for e in events] == ["natural_expiry"]
