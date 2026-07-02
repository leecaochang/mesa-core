"""Standard mesa_audit_event schema across all three emitters (Module Section 8)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from mesa_core import CallerContext, MesaEnforcer, ProfileStore
from mesa_core.backends import MemoryBackend
from mesa_core.lease import LeaseManager

DOCUMENTED_FIELDS = {
    "timestamp",
    "caller_id",
    "roles",
    "entity_id",
    "action",
    "decision",
    "profile_version",
    "rule_applied",
    "redaction_mode",
}


def audit_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        r.mesa_audit_event
        for r in caplog.records
        if r.name == "mesa_core.audit" and hasattr(r, "mesa_audit_event")
    ]


def caller() -> CallerContext:
    return CallerContext(
        caller_id="user.alice", roles=["primary_resident"], is_authenticated=True,
        session_id="sess-1",
    )


def test_enforcement_block_emits_standard_event(caplog: pytest.LogCaptureFixture) -> None:
    enforcer = MesaEnforcer(ProfileStore(backend=MemoryBackend()), mode="enforced")
    with caplog.at_level(logging.INFO, logger="mesa_core.audit"):
        result = enforcer.evaluate("lock.front_door", "lock.unlock", caller_context=caller())
    assert not result.allowed

    events = audit_events(caplog)
    blocked = [e for e in events if e["event_type"] == "enforcement_decision"]
    assert len(blocked) == 1
    event = blocked[0]
    # Every documented field is present, even when null.
    assert set(event) >= DOCUMENTED_FIELDS
    assert event["action"] == "lock.unlock"
    assert event["decision"] == "blocked"
    assert event["rule_applied"] == "control_mode:prohibited"
    assert event["entity_id"] == "lock.front_door"
    assert event["caller_id"] == "user.alice"
    assert event["roles"] == ["primary_resident"]
    assert event["timestamp"]


def test_enforcement_allow_is_debug_level(caplog: pytest.LogCaptureFixture) -> None:
    enforcer = MesaEnforcer(ProfileStore(backend=MemoryBackend()), mode="enforced")
    with caplog.at_level(logging.INFO, logger="mesa_core.audit"):
        assert enforcer.evaluate("light.x", "light.turn_on").allowed
    assert [e for e in audit_events(caplog) if e["event_type"] == "enforcement_decision"] == []

    with caplog.at_level(logging.DEBUG, logger="mesa_core.audit"):
        assert enforcer.evaluate("light.x", "light.turn_on").allowed
    allowed = [e for e in audit_events(caplog) if e["event_type"] == "enforcement_decision"]
    assert len(allowed) == 1 and allowed[0]["decision"] == "allowed"


def test_lease_events_carry_standard_shape(caplog: pytest.LogCaptureFixture) -> None:
    manager = LeaseManager()
    with caplog.at_level(logging.INFO, logger="mesa_core.audit"):
        response = manager.request(
            ["light.x"], 10, session_id="s1", caller_id="agent.a", intent="test"
        )
        manager.release(response.lease_id, session_id="s1")

    events = audit_events(caplog)
    assert [e["action"] for e in events] == ["lease_request", "lease_ended"]
    request, ended = events
    assert set(request) >= DOCUMENTED_FIELDS
    assert request["event_type"] == "lease"
    assert request["decision"] == "granted"
    assert request["details"]["lease_id"] == response.lease_id
    assert request["details"]["entities_granted"] == ["light.x"]
    assert ended["decision"] == "early_release"
    assert ended["details"]["entities"] == ["light.x"]
