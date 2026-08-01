"""control_mode precedence and enforcement (Spec 4, 6.6; Module Proposal 7.2)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mesa_core.backends import MemoryBackend
from mesa_core.enforcer import MesaEnforcer
from mesa_core.profile import SemanticProfile
from mesa_core.store import ProfileStore

from .test_conflict import make_profile

FIXTURES = Path(__file__).parent.parent / "fixtures" / "profiles"
NOON = datetime(2026, 6, 13, 12, 0)


def make_enforcer(store: ProfileStore | None = None, **kwargs: Any) -> MesaEnforcer:
    return MesaEnforcer(store or ProfileStore(backend=MemoryBackend()), **kwargs)


# -------------------------------------------------------------- baseline & modes


def test_baseline_lock_prohibited_blocks() -> None:
    result = make_enforcer().evaluate("lock.front_door", "lock.unlock", current_time=NOON)
    assert not result.allowed
    assert result.rule_applied == "control_mode:prohibited"


def test_baseline_light_autonomous_allowed() -> None:
    result = make_enforcer().evaluate("light.kitchen", "light.turn_on", current_time=NOON)
    assert result.allowed


def test_read_only_blocks_regardless_of_enforcement_mode() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "sensor.diag",
        make_profile("sensor.diag", boundaries={"control_mode": "read_only"}),
    )
    result = make_enforcer(store, mode="advisory").evaluate(
        "sensor.diag", "sensor.set", current_time=NOON
    )
    assert not result.allowed
    assert result.rule_applied == "control_mode:read_only"


def test_prohibited_in_advisory_mode_warns_but_allows() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "switch.x", make_profile("switch.x", boundaries={"control_mode": "prohibited"})
    )
    result = make_enforcer(store, mode="advisory").evaluate(
        "switch.x", "switch.turn_on", current_time=NOON
    )
    assert result.allowed
    assert any("advisory" in w for w in result.warnings)


def test_confirm_in_advisory_mode_warns_but_allows() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set("cover.x", make_profile("cover.x", boundaries={"control_mode": "confirm"}))
    result = make_enforcer(store, mode="advisory").evaluate(
        "cover.x", "cover.open_cover", current_time=NOON
    )
    assert result.allowed
    assert any("confirmation required" in w for w in result.warnings)


def test_profile_enforcement_mode_enforces_even_when_server_advisory() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "cover.x",
        make_profile(
            "cover.x", boundaries={"control_mode": "confirm", "enforcement_mode": "enforced"}
        ),
    )
    result = make_enforcer(store, mode="advisory").evaluate(
        "cover.x", "cover.open_cover", current_time=NOON
    )
    assert not result.allowed
    assert result.confirmation_challenge is not None


def test_control_reason_surfaced_in_block_reason() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "valve.gas",
        make_profile(
            "valve.gas",
            boundaries={
                "control_mode": "prohibited",
                "control_reason": "physically dangerous if reversed",
            },
        ),
    )
    result = make_enforcer(store).evaluate("valve.gas", "valve.open", current_time=NOON)
    assert "physically dangerous if reversed" in result.reason


def test_confirm_with_no_interaction_channel_blocked_for_all_domains() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set("cover.x", make_profile("cover.x", boundaries={"control_mode": "confirm"}))
    enforcer = make_enforcer(store, interactive=False)
    result = enforcer.evaluate("cover.x", "cover.open_cover", current_time=NOON)
    assert not result.allowed
    assert result.rule_applied == "control_mode:confirm_no_channel"


# -------------------------------------------------------------- confirmation protocol


def _challenge_setup() -> tuple[MesaEnforcer, dict[str, Any]]:
    store = ProfileStore(backend=MemoryBackend())
    store.set("cover.x", make_profile("cover.x", boundaries={"control_mode": "confirm"}))
    enforcer = make_enforcer(store)
    first = enforcer.evaluate(
        "cover.x", "cover.open_cover", {"position": 50}, current_time=NOON
    )
    assert not first.allowed and first.confirmation_challenge is not None
    return enforcer, first.confirmation_challenge


def _token(challenge: dict[str, Any]) -> dict[str, Any]:
    """A complete confirmation token: the token schema records the approval,
    so approved_by and approved_at are required (Spec 6.6)."""
    return {
        "challenge_id": challenge["challenge_id"],
        "approved_by": "user.alice",
        "approved_at": NOON.isoformat(),
    }


def test_confirmation_round_trip() -> None:
    enforcer, challenge = _challenge_setup()
    token = {
        "challenge_id": challenge["challenge_id"],
        "approved_by": "user.alice",
        "approved_at": NOON.isoformat(),
    }
    second = enforcer.evaluate(
        "cover.x",
        "cover.open_cover",
        {"position": 50},
        current_time=NOON + timedelta(seconds=10),
        confirmation_token=token,
    )
    assert second.allowed
    assert any("confirmation accepted" in w for w in second.warnings)


def test_confirmation_token_single_use() -> None:
    enforcer, challenge = _challenge_setup()
    token = _token(challenge)
    params = {"position": 50}
    assert enforcer.evaluate(
        "cover.x", "cover.open_cover", params, current_time=NOON, confirmation_token=token
    ).allowed
    reused = enforcer.evaluate(
        "cover.x", "cover.open_cover", params, current_time=NOON, confirmation_token=token
    )
    assert not reused.allowed
    assert "single-use" in reused.reason


def test_confirmation_token_expires() -> None:
    enforcer, challenge = _challenge_setup()
    token = _token(challenge)
    late = NOON + timedelta(seconds=121)
    result = enforcer.evaluate(
        "cover.x", "cover.open_cover", {"position": 50}, current_time=late, confirmation_token=token
    )
    assert not result.allowed
    assert "expired" in result.reason


def test_confirmation_token_bound_to_exact_parameters() -> None:
    enforcer, challenge = _challenge_setup()
    token = _token(challenge)
    drifted = enforcer.evaluate(
        "cover.x", "cover.open_cover", {"position": 100}, current_time=NOON, confirmation_token=token
    )
    assert not drifted.allowed
    assert "exact entity, service, and parameters" in drifted.reason


def test_unknown_challenge_rejected() -> None:
    enforcer, _ = _challenge_setup()
    result = enforcer.evaluate(
        "cover.x",
        "cover.open_cover",
        {"position": 50},
        current_time=NOON,
        confirmation_token={"challenge_id": "forged", "approved_by": "user.alice",
                            "approved_at": NOON.isoformat()},
    )
    assert not result.allowed


# -------------------------------------------------------------- loosening override e2e


def test_loosening_override_end_to_end() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set_domain_profile(
        "media_player",
        make_profile("media_player", origin="developer", boundaries={"control_mode": "confirm"}),
    )
    store.set(
        "media_player.kitchen",
        make_profile(
            "media_player.kitchen",
            boundaries={
                "control_mode": "autonomous",
                "override_control_mode": True,
                "control_reason": "Kitchen speaker is safe for autonomous control here.",
            },
        ),
    )
    result = make_enforcer(store).evaluate(
        "media_player.kitchen", "media_player.media_play", current_time=NOON
    )
    assert result.allowed


# -------------------------------------------------------------- declared limits


def test_declared_limit_blocks_when_predicate_active() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "media_player.kitchen",
        make_profile(
            "media_player.kitchen",
            boundaries={
                "control_mode": "autonomous",
                "declared_limits": [
                    {
                        "id": "night_volume",
                        "predicate": {
                            "entity": "input_boolean.night_mode",
                            "operator": "eq",
                            "value": True,
                        },
                        "limit": {
                            "service": "media_player.volume_set",
                            "parameter": "volume_level",
                            "max_value": 0.4,
                        },
                        "human_reason": "Household occupants are sleeping.",
                    }
                ],
            },
        ),
    )
    states = {"input_boolean.night_mode": "on"}
    enforcer = make_enforcer(store, get_state=lambda eid: states.get(eid))

    blocked = enforcer.evaluate(
        "media_player.kitchen", "media_player.volume_set", {"volume_level": 0.9}, current_time=NOON
    )
    assert not blocked.allowed
    assert blocked.rule_applied == "declared_limit:night_volume"
    assert "sleeping" in blocked.reason

    within = enforcer.evaluate(
        "media_player.kitchen", "media_player.volume_set", {"volume_level": 0.3}, current_time=NOON
    )
    assert within.allowed

    states["input_boolean.night_mode"] = "off"
    daytime = enforcer.evaluate(
        "media_player.kitchen", "media_player.volume_set", {"volume_level": 0.9}, current_time=NOON
    )
    assert daytime.allowed


def test_entity_limit_does_not_shadow_domain_safety_limit() -> None:
    # Audit regression: a domain-level developer safety cap must survive even when
    # an entity-level profile declares its own unrelated limit. Under wholesale
    # array replacement the domain cap was erased and the call would be allowed.
    store = ProfileStore(backend=MemoryBackend())
    store.set_domain_profile(
        "media_player",
        make_profile(
            "media_player",
            origin="developer",
            boundaries={
                "control_mode": "autonomous",
                "declared_limits": [
                    {
                        "id": "night_volume_cap",
                        "predicate": {
                            "entity": "input_boolean.night_mode",
                            "operator": "eq",
                            "value": True,
                        },
                        "limit": {
                            "service": "media_player.volume_set",
                            "parameter": "volume_level",
                            "max_value": 0.4,
                        },
                        "human_reason": "Household occupants are sleeping.",
                    }
                ],
            },
        ),
    )
    store.set(
        "media_player.kitchen",
        make_profile(
            "media_player.kitchen",
            boundaries={
                "declared_limits": [
                    {
                        "id": "source_allowlist",
                        "predicate": {
                            "entity": "input_boolean.guest_mode",
                            "operator": "eq",
                            "value": True,
                        },
                        "limit": {
                            "service": "media_player.select_source",
                            "parameter": "source",
                            "permitted_values": ["Spotify", "aux"],
                        },
                    }
                ],
            },
        ),
    )
    enforcer = make_enforcer(store, get_state=lambda eid: "on")  # night_mode on

    blocked = enforcer.evaluate(
        "media_player.kitchen", "media_player.volume_set", {"volume_level": 0.9}, current_time=NOON
    )
    assert not blocked.allowed
    assert blocked.rule_applied == "declared_limit:night_volume_cap"


def test_unevaluable_predicate_fails_closed() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "media_player.kitchen",
        make_profile(
            "media_player.kitchen",
            boundaries={
                "control_mode": "autonomous",
                "declared_limits": [
                    {
                        "id": "night_volume",
                        "predicate": {
                            "entity": "input_boolean.night_mode",
                            "operator": "eq",
                            "value": True,
                        },
                        "limit": {
                            "service": "media_player.volume_set",
                            "parameter": "volume_level",
                            "max_value": 0.4,
                        },
                    }
                ],
            },
        ),
    )
    # No get_state callback: the predicate is unevaluable and the limit is active.
    result = make_enforcer(store).evaluate(
        "media_player.kitchen", "media_player.volume_set", {"volume_level": 0.9}, current_time=NOON
    )
    assert not result.allowed
    assert any("fail-closed" in w for w in result.warnings)


def test_empty_permitted_values_blocks_service() -> None:
    data = json.loads((FIXTURES / "lock_full.json").read_text())
    profile = SemanticProfile.from_dict("lock.front_door", data)
    store = ProfileStore(backend=MemoryBackend())
    store.set("lock.front_door", profile)
    enforcer = make_enforcer(store, get_state=lambda eid: "on")  # door contact open

    challenge = enforcer.evaluate(
        "lock.front_door", "lock.lock", {"entity_id": "lock.front_door"}, current_time=NOON
    )
    assert not challenge.allowed and challenge.confirmation_challenge is not None
    token = _token(challenge.confirmation_challenge)
    confirmed = enforcer.evaluate(
        "lock.front_door",
        "lock.lock",
        {"entity_id": "lock.front_door"},
        current_time=NOON,
        confirmation_token=token,
    )
    # Even with confirmation, the declared limit blocks locking an open door.
    assert not confirmed.allowed
    assert confirmed.rule_applied == "declared_limit:no_lock_door_open"


# -------------------------------------------------------------- temporal integration


def test_temporal_tightening_applies_before_control_mode() -> None:
    data = json.loads((FIXTURES / "lock_full.json").read_text())
    store = ProfileStore(backend=MemoryBackend())
    store.set("lock.front_door", SemanticProfile.from_dict("lock.front_door", data))
    enforcer = make_enforcer(store, get_state=lambda eid: "off")
    night = datetime(2026, 6, 13, 23, 30)
    result = enforcer.evaluate(
        "lock.front_door", "lock.lock", {"entity_id": "lock.front_door"}, current_time=night
    )
    # The 23:00-06:00 constraint tightens confirm -> prohibited: no challenge offered.
    assert not result.allowed
    assert result.rule_applied == "control_mode:prohibited"
    assert result.confirmation_challenge is None


def test_unevaluable_calendar_negate_fails_closed_end_to_end() -> None:
    # The vacuum fixture: autonomous only during away blocks. Without a calendar
    # callback the negated condition is unevaluable -> active -> confirm required.
    data = json.loads((FIXTURES / "vacuum_negate_temporal.json").read_text())
    store = ProfileStore(backend=MemoryBackend())
    store.set("vacuum.robot", SemanticProfile.from_dict("vacuum.robot", data))
    result = make_enforcer(store).evaluate("vacuum.robot", "vacuum.start", current_time=NOON)
    assert not result.allowed
    assert result.confirmation_challenge is not None
    assert any("fail-closed" in w for w in result.warnings)


# --------------- contradictory target in service_params (audit 15 F1)


def _confirm_store() -> ProfileStore:
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "light.x",
        SemanticProfile.from_dict(
            "light.x",
            {
                "semantic_profile": {
                    "metadata_origin": {"source": "user"},
                    "operational_boundaries": {
                        "control_mode": "confirm",
                        "enforcement_mode": "enforced",
                    },
                }
            },
        ),
    )
    return store


def test_service_params_naming_another_entity_is_denied() -> None:
    # Policy is selected from entity_id while the executed call and the
    # confirmation challenge carry service_params, so a mismatch would let an
    # operator approve one entity and act on another. HA's REST API takes
    # entity_id inside the service data, so this is a reachable payload.
    enforcer = MesaEnforcer(store=_confirm_store(), mode="enforced")
    result = enforcer.evaluate(
        entity_id="light.x",
        service="light.turn_on",
        service_params={"entity_id": "lock.front_door", "brightness": 255},
    )
    assert not result.allowed
    assert result.rule_applied == "contradictory_target"
    assert "lock.front_door" in result.reason
    # No challenge: an approvable challenge is exactly what must not be issued.
    assert result.confirmation_challenge is None


def test_non_string_targets_are_denied_too() -> None:
    # Rejecting only mismatched strings left the realistic shapes open: Home
    # Assistant accepts a list of entity IDs in service data, and a list
    # naming a second entity would be evaluated for the first alone and still
    # hand back an approvable challenge covering both.
    enforcer = MesaEnforcer(store=_confirm_store(), mode="enforced")
    for params_entity in (
        ["light.x", "lock.front_door"],
        ["light.x"],
        None,
        {"entity_id": "lock.front_door"},
        123,
    ):
        result = enforcer.evaluate(
            entity_id="light.x",
            service="light.turn_on",
            service_params={"entity_id": params_entity, "brightness": 255},
        )
        assert not result.allowed, params_entity
        assert result.rule_applied == "contradictory_target", params_entity
        assert result.confirmation_challenge is None, params_entity


def test_alternate_home_assistant_targets_are_denied() -> None:
    # An action can name its target as a device, area, floor, or label, or in a
    # nested target block. Each can reach entities this evaluation never saw,
    # and only the host can resolve a selector, so a decision made here would
    # be an approval for the wrong thing.
    enforcer = MesaEnforcer(store=_confirm_store(), mode="enforced")
    for params in (
        {"device_id": "abc123"},
        {"area_id": "kitchen"},
        {"floor_id": "upstairs"},
        {"label_id": "security"},
        {"device_id": ["abc123", "def456"]},
        {"target": {"device_id": "abc123"}},
        {"target": {"area_id": "kitchen"}},
        {"target": {"entity_id": "lock.front_door"}},
        {"target": "kitchen"},
    ):
        result = enforcer.evaluate(
            entity_id="light.x", service="light.turn_on", service_params=params
        )
        assert not result.allowed, params
        assert result.rule_applied == "contradictory_target", params
        assert result.confirmation_challenge is None, params


def test_a_target_block_naming_only_the_evaluated_entity_is_allowed() -> None:
    enforcer = MesaEnforcer(store=_confirm_store(), mode="enforced")
    result = enforcer.evaluate(
        entity_id="light.x",
        service="light.turn_on",
        service_params={"target": {"entity_id": "light.x"}, "brightness": 255},
    )
    assert result.rule_applied != "contradictory_target"
    assert result.confirmation_challenge is not None


def test_matching_or_absent_entity_id_in_service_params_is_unaffected() -> None:
    enforcer = MesaEnforcer(store=_confirm_store(), mode="enforced")
    for params in (
        {"entity_id": "light.x", "brightness": 255},
        {"brightness": 255},
    ):
        result = enforcer.evaluate(
            entity_id="light.x", service="light.turn_on", service_params=params
        )
        assert result.rule_applied != "contradictory_target"
        assert result.confirmation_challenge is not None
