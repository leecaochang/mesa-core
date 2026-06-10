"""Privacy classification and role resolution (Spec 7, 17; Module Proposal 7.2)."""

from __future__ import annotations

import logging

import pytest

from mesa_core.privacy import CallerContext, PrivacyEnforcer
from mesa_core.profile import PrivacyClassification, PrivacyLevel


def caller(*roles: str, authenticated: bool = True) -> CallerContext:
    return CallerContext(
        caller_id="user.test",
        roles=list(roles),
        is_authenticated=authenticated,
        session_id="sess",
    )


def sensitive_with_roles() -> PrivacyClassification:
    return PrivacyClassification(
        level=PrivacyLevel.SENSITIVE,
        access_roles={
            "unrestricted_for": ["primary_resident", "admin"],
            "restricted_for": ["temporary_guest"],
            "deny_for": ["guest", "child"],
        },
        deny_response_mode="redact",
    )


def test_deny_for_role_blocks_access() -> None:
    decision = PrivacyEnforcer().evaluate(sensitive_with_roles(), caller("guest"))
    assert not decision.allowed
    assert decision.deny_response_mode == "redact"


def test_unrestricted_for_relaxes_to_normal() -> None:
    decision = PrivacyEnforcer().evaluate(sensitive_with_roles(), caller("primary_resident"))
    assert decision.allowed
    assert decision.effective_level == PrivacyLevel.NORMAL


def test_restricted_for_escalates() -> None:
    decision = PrivacyEnforcer().evaluate(sensitive_with_roles(), caller("temporary_guest"))
    assert decision.allowed
    assert decision.effective_level == PrivacyLevel.RESTRICTED


def test_unauthenticated_caller_has_no_roles() -> None:
    # An unauthenticated caller with a denied role string is not matched against
    # access_roles: base privacy level applies (Spec 9.4).
    decision = PrivacyEnforcer().evaluate(
        sensitive_with_roles(), caller("guest", authenticated=False)
    )
    assert decision.allowed
    assert decision.effective_level == PrivacyLevel.SENSITIVE


def test_no_caller_context_applies_base_level() -> None:
    decision = PrivacyEnforcer().evaluate(sensitive_with_roles(), None)
    assert decision.allowed
    assert decision.effective_level == PrivacyLevel.SENSITIVE


def test_is_minor_forces_restricted_regardless_of_roles() -> None:
    decision = PrivacyEnforcer().evaluate(
        sensitive_with_roles(), caller("primary_resident"), is_minor=True
    )
    assert decision.effective_level == PrivacyLevel.RESTRICTED


def test_person_entities_at_least_sensitive() -> None:
    decision = PrivacyEnforcer().evaluate(
        PrivacyClassification(level=PrivacyLevel.NORMAL), caller(), is_person=True
    )
    assert decision.effective_level == PrivacyLevel.SENSITIVE


def test_sensitive_access_is_audit_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="mesa_core.audit"):
        PrivacyEnforcer().evaluate(
            sensitive_with_roles(), caller("primary_resident"), entity_id="camera.x"
        )
        # unrestricted_for relaxed it to normal -> not logged; denied guest -> logged.
        PrivacyEnforcer().evaluate(sensitive_with_roles(), caller("guest"), entity_id="camera.x")
    records = [r for r in caplog.records if r.name == "mesa_core.audit"]
    assert records
    assert any(getattr(r, "mesa_decision", "") == "denied" for r in records)


def test_person_access_always_logged(caplog: pytest.LogCaptureFixture) -> None:
    # Spec 17: all person entity accesses are logged regardless of level/roles.
    with caplog.at_level(logging.INFO, logger="mesa_core.audit"):
        PrivacyEnforcer().evaluate(
            PrivacyClassification(
                level=PrivacyLevel.SENSITIVE, access_roles={"unrestricted_for": ["admin"]}
            ),
            caller("admin"),
            entity_id="person.alice",
            is_person=True,
        )
    records = [r for r in caplog.records if r.name == "mesa_core.audit"]
    assert any(getattr(r, "mesa_is_person", False) for r in records)


def test_normal_access_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="mesa_core.audit"):
        PrivacyEnforcer().evaluate(PrivacyClassification(), caller(), entity_id="light.x")
    assert not [r for r in caplog.records if r.name == "mesa_core.audit"]
