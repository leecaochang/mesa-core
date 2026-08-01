"""Lease protocol conformance (Enrichment Section 21; Module Proposal 4.10)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from mesa_core.backends import MemoryBackend
from mesa_core.exceptions import LeaseNotFoundError
from mesa_core.lease import LeaseManager
from mesa_core.profile import SemanticProfile
from mesa_core.store import ProfileStore

NOW = datetime(2026, 7, 2, 12, 0, 0)


def automation_profile(
    automation_id: str,
    level: str,
    trigger: list[str] | None = None,
    condition: list[str] | None = None,
    affected: list[str] | None = None,
) -> SemanticProfile:
    doc: dict[str, Any] = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "cooperative_priority": {"level": level},
            "environmental_dependencies": {
                "trigger_entities": trigger or [],
                "condition_entities": condition or [],
            },
            "intent_archetype": {"affected_entities": affected or []},
        }
    }
    return SemanticProfile.from_dict(automation_id, doc)


def manager_with(*profiles: SemanticProfile, **kwargs: Any) -> LeaseManager:
    store = ProfileStore(backend=MemoryBackend())
    for profile in profiles:
        store.set(profile.entity_id, profile)
    return LeaseManager(store, **kwargs)


# ---------------------------------------------------------------- lifecycle (21.4)


def test_grant_release_lifecycle_with_events() -> None:
    events: list[dict[str, Any]] = []
    manager = LeaseManager(on_lease_event=events.append)
    response = manager.request(
        ["light.x", "light.y"], 10, session_id="s1", caller_id="agent.a", now=NOW
    )
    assert response.granted
    assert response.entities_granted == ["light.x", "light.y"]
    assert response.entities_denied == []
    assert response.granted_duration_seconds == 10
    assert response.expires_at == (NOW + timedelta(seconds=10)).isoformat()
    assert len(manager.active_leases(NOW)) == 1

    released = manager.release(response.lease_id, session_id="s1", now=NOW)
    assert released.entities == ["light.x", "light.y"]
    assert manager.active_leases(NOW) == []
    assert events == [
        {
            "event_type": "mesa_lease_expired",
            "lease_id": response.lease_id,
            "entities": ["light.x", "light.y"],
            "reason": "early_release",
            "timestamp": NOW.isoformat(),
        }
    ]


def test_natural_expiry_terminates_and_emits() -> None:
    events: list[dict[str, Any]] = []
    manager = LeaseManager(on_lease_event=events.append)
    response = manager.request(["light.x"], 10, session_id="s1", now=NOW)
    later = NOW + timedelta(seconds=11)
    assert manager.active_leases(later) == []
    manager.expire(later)
    assert [e["reason"] for e in events] == ["natural_expiry"]
    # The expired lease ID no longer releases.
    with pytest.raises(LeaseNotFoundError):
        manager.release(response.lease_id, now=later)


def test_duration_clamped_to_maximum() -> None:
    manager = LeaseManager()
    response = manager.request(["light.x"], 300, session_id="s1", now=NOW)
    assert response.granted_duration_seconds == 30
    assert response.expires_at == (NOW + timedelta(seconds=30)).isoformat()
    assert any("clamped" in w for w in response.warnings)


def test_invalid_request_arguments_raise() -> None:
    manager = LeaseManager()
    with pytest.raises(ValueError):
        manager.request([], 10, session_id="s1", now=NOW)
    with pytest.raises(ValueError):
        manager.request(["light.x"], 0, session_id="s1", now=NOW)
    with pytest.raises(ValueError):
        manager.request(["light.x"], 10, session_id="s1", priority_level="bossy", now=NOW)
    with pytest.raises(ValueError):
        manager.request(
            ["light.x"], 10, session_id="s1", preemption_handling="retry", now=NOW
        )


def test_caller_priority_accepted_but_unused_with_warning() -> None:
    manager = LeaseManager()
    response = manager.request(
        ["light.x"], 10, session_id="s1", caller_priority=0.9, now=NOW
    )
    assert response.granted
    assert any("caller_priority" in w for w in response.warnings)


def test_session_termination_releases_all() -> None:
    events: list[dict[str, Any]] = []
    manager = LeaseManager(on_lease_event=events.append)
    manager.request(["light.x"], 10, session_id="s1", now=NOW)
    manager.request(["light.y"], 10, session_id="s1", now=NOW)
    manager.request(["light.z"], 10, session_id="s2", now=NOW)
    assert manager.release_session("s1", now=NOW) == 2
    assert [e["reason"] for e in events] == ["session_terminated", "session_terminated"]
    remaining = manager.active_leases(NOW)
    assert len(remaining) == 1 and remaining[0].session_id == "s2"


# ---------------------------------------------------- overlap (21.6 Rule 3 baseline)


def test_existing_holder_takes_precedence_partial_grant() -> None:
    manager = LeaseManager()
    manager.request(["light.x"], 10, session_id="s1", now=NOW)
    response = manager.request(["light.x", "light.y"], 10, session_id="s2", now=NOW)
    assert response.granted  # partial grants are valid (21.4)
    assert response.entities_granted == ["light.y"]
    assert response.entities_denied == ["light.x"]
    assert "another session" in response.denial_reasons["light.x"]


def test_full_overlap_is_denied() -> None:
    manager = LeaseManager()
    manager.request(["light.x"], 10, session_id="s1", now=NOW)
    response = manager.request(["light.x"], 10, session_id="s2", now=NOW)
    assert not response.granted
    assert response.entities_granted == []


def test_same_session_rerequest_is_granted() -> None:
    manager = LeaseManager()
    manager.request(["light.x"], 10, session_id="s1", now=NOW)
    response = manager.request(["light.x"], 10, session_id="s1", now=NOW)
    assert response.granted


def test_expired_holder_does_not_block() -> None:
    manager = LeaseManager()
    manager.request(["light.x"], 10, session_id="s1", now=NOW)
    later = NOW + timedelta(seconds=31)
    response = manager.request(["light.x"], 10, session_id="s2", now=later)
    assert response.granted


def test_release_wrong_session_reads_as_not_found() -> None:
    manager = LeaseManager()
    response = manager.request(["light.x"], 10, session_id="s1", now=NOW)
    with pytest.raises(LeaseNotFoundError):
        manager.release(response.lease_id, session_id="s2", now=NOW)
    # Still held by s1.
    assert len(manager.active_leases(NOW)) == 1


# -------------------------------------------------- automation interaction (21.5)


def test_critical_automation_denies_unconditionally_including_affected() -> None:
    manager = manager_with(
        automation_profile(
            "automation.smoke",
            "critical",
            trigger=["binary_sensor.smoke"],
            affected=["switch.siren"],
        ),
        # get_state deliberately absent: critical never consults state.
    )
    response = manager.request(
        ["binary_sensor.smoke", "switch.siren"], 10, session_id="s1", now=NOW
    )
    assert not response.granted
    assert set(response.automation_denials) == {"binary_sensor.smoke", "switch.siren"}
    assert all("critical" in r for r in response.denial_reasons.values())


def test_protected_fails_closed_without_get_state() -> None:
    manager = manager_with(
        automation_profile("automation.meds", "protected", condition=["switch.dispenser"])
    )
    response = manager.request(["switch.dispenser"], 10, session_id="s1", now=NOW)
    assert not response.granted
    assert any("fail-closed" in w for w in response.warnings)


def test_protected_active_denies_inactive_grants() -> None:
    profile = automation_profile(
        "automation.meds", "protected", trigger=["switch.dispenser"]
    )
    active = manager_with(profile, get_state=lambda eid: "on")
    assert not active.request(["switch.dispenser"], 10, session_id="s1", now=NOW).granted

    inactive = manager_with(profile, get_state=lambda eid: "off")
    assert inactive.request(["switch.dispenser"], 10, session_id="s1", now=NOW).granted


def test_cooperative_surfaces_conflict_and_grants() -> None:
    manager = manager_with(
        automation_profile("automation.lights", "cooperative", trigger=["light.x"])
    )
    response = manager.request(["light.x"], 10, session_id="s1", now=NOW)
    assert response.granted
    assert response.active_conflicts == [
        {"automation_id": "automation.lights", "level": "cooperative", "entities": ["light.x"]}
    ]


def test_assertive_grants_with_warning() -> None:
    manager = manager_with(
        automation_profile("automation.energy", "assertive", trigger=["climate.hvac"])
    )
    response = manager.request(["climate.hvac"], 10, session_id="s1", now=NOW)
    assert response.granted
    assert any("assertive" in w for w in response.warnings)
    assert response.active_conflicts[0]["level"] == "assertive"


def test_deferential_automation_is_silent() -> None:
    manager = manager_with(
        automation_profile("automation.blinds", "deferential", trigger=["cover.blind"])
    )
    response = manager.request(["cover.blind"], 10, session_id="s1", now=NOW)
    assert response.granted
    assert response.active_conflicts == []


# ------------------------------------------------------------- sensor state (21.4)


def test_sensor_state_reflects_active_leases() -> None:
    manager = LeaseManager()
    assert manager.sensor_state(NOW) == {
        "state": "off",
        "active_lease_count": 0,
        "leased_entities": [],
        "earliest_expiry": None,
        "last_lease_holder": None,
    }
    manager.request(["light.x"], 10, session_id="s1", caller_id="agent.a", now=NOW)
    manager.request(["light.y"], 20, session_id="s2", caller_id="agent.b", now=NOW)
    state = manager.sensor_state(NOW)
    assert state["state"] == "on"
    assert state["active_lease_count"] == 2
    assert state["leased_entities"] == ["light.x", "light.y"]
    assert state["earliest_expiry"] == (NOW + timedelta(seconds=10)).isoformat()
    assert state["last_lease_holder"] == "agent.b"

    after = manager.sensor_state(NOW + timedelta(seconds=31))
    assert after["state"] == "off"
    assert after["last_lease_holder"] == "agent.b"  # audit context survives expiry


# --------------------------- fail-closed Section 11 parsing (mesa-core 1.3)


def test_default_clock_is_timezone_aware() -> None:
    manager = LeaseManager()
    response = manager.request(["light.x"], 5, session_id="s1")
    assert datetime.fromisoformat(response.expires_at).tzinfo is not None
    assert manager.sensor_state()["state"] == "on"


def test_malformed_priority_object_fails_closed() -> None:
    # cooperative_priority as a string previously crashed or slipped through;
    # it must read as protected and (state unavailable, fail-closed) deny.
    doc: dict[str, Any] = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "cooperative_priority": "protected",
            "environmental_dependencies": {"trigger_entities": ["lock.front"]},
        }
    }
    manager = manager_with(SemanticProfile.from_dict("automation.guard", doc))
    response = manager.request(["lock.front"], 5, session_id="s1", now=NOW)
    assert not response.granted
    assert response.entities_denied == ["lock.front"]
    assert any("not an object" in w and "automation.guard" in w for w in response.warnings)


def test_unknown_priority_level_treated_as_protected() -> None:
    # A typo'd level previously lost the protection entirely (silent grant).
    manager = manager_with(
        automation_profile("automation.guard", "protectedd", trigger=["lock.front"])
    )
    response = manager.request(["lock.front"], 5, session_id="s1", now=NOW)
    assert not response.granted
    assert any("unrecognized cooperative_priority.level" in w for w in response.warnings)

    # Protected is state-checked: with the automation off, the lease grants.
    manager = manager_with(
        automation_profile("automation.guard", "protectedd", trigger=["lock.front"]),
        get_state=lambda eid: "off",
    )
    response = manager.request(["lock.front"], 5, session_id="s1", now=NOW)
    assert response.granted
    assert any("unrecognized cooperative_priority.level" in w for w in response.warnings)


def test_malformed_trigger_entities_fails_closed() -> None:
    # A wrong-typed entity list previously narrowed the protection scope to
    # garbage; it must be unevaluable and cover every requested entity.
    doc: dict[str, Any] = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "cooperative_priority": {"level": "protected"},
            "environmental_dependencies": {"trigger_entities": "lock.front"},
        }
    }
    manager = manager_with(SemanticProfile.from_dict("automation.guard", doc))
    response = manager.request(["light.unrelated"], 5, session_id="s1", now=NOW)
    assert not response.granted
    assert any(
        "trigger_entities" in w and "automation.guard" in w for w in response.warnings
    )


def test_malformed_affected_entities_on_critical_fails_closed() -> None:
    doc: dict[str, Any] = {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "cooperative_priority": {"level": "critical"},
            "environmental_dependencies": {},
            "intent_archetype": {"affected_entities": 5},
        }
    }
    manager = manager_with(SemanticProfile.from_dict("automation.crit", doc))
    response = manager.request(["light.any"], 5, session_id="s1", now=NOW)
    assert not response.granted
    assert response.entities_denied == ["light.any"]
    assert any("affected_entities" in w for w in response.warnings)


def test_deferential_level_is_inert() -> None:
    manager = manager_with(
        automation_profile("automation.soft", "deferential", trigger=["light.x"])
    )
    response = manager.request(["light.x"], 5, session_id="s1", now=NOW)
    assert response.granted and response.warnings == []
