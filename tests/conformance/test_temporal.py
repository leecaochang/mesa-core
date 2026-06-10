"""Temporal constraint evaluation (Spec 6.5; Module Proposal 7.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mesa_core.profile import ControlMode, OperationalBoundaries
from mesa_core.temporal import TemporalEvaluator

# 2026-06-13 is a Saturday.
SATURDAY_NOON = datetime(2026, 6, 13, 12, 0)
SATURDAY_LATE = datetime(2026, 6, 13, 23, 30)
MONDAY_EARLY = datetime(2026, 6, 15, 5, 0)


def boundaries(*constraints: dict[str, Any], control_mode: str = "confirm") -> OperationalBoundaries:
    return OperationalBoundaries(
        control_mode=ControlMode(control_mode),
        temporal_constraints=list(constraints),
    )


def night_constraint(effect: dict[str, Any], negate: bool = False) -> dict[str, Any]:
    condition: dict[str, Any] = {"type": "time_range", "start_time": "23:00", "end_time": "06:00"}
    if negate:
        condition["negate"] = True
    return {"id": "night", "condition": condition, "effect": effect}


def test_time_range_across_midnight() -> None:
    ev = TemporalEvaluator()
    b = boundaries(night_constraint({"control_mode": "prohibited"}))
    assert ev.apply(b, SATURDAY_LATE).boundaries.control_mode == ControlMode.PROHIBITED
    assert ev.apply(b, MONDAY_EARLY).boundaries.control_mode == ControlMode.PROHIBITED
    assert ev.apply(b, SATURDAY_NOON).boundaries.control_mode == ControlMode.CONFIRM


def test_time_range_negate() -> None:
    ev = TemporalEvaluator()
    b = boundaries(night_constraint({"control_mode": "prohibited"}, negate=True))
    assert ev.apply(b, SATURDAY_NOON).boundaries.control_mode == ControlMode.PROHIBITED
    assert ev.apply(b, SATURDAY_LATE).boundaries.control_mode == ControlMode.CONFIRM


def test_day_of_week_single_and_multiple() -> None:
    ev = TemporalEvaluator()
    single = boundaries(
        {
            "id": "sat",
            "condition": {"type": "day_of_week", "days": ["sat"]},
            "effect": {"control_mode": "prohibited"},
        }
    )
    assert ev.apply(single, SATURDAY_NOON).boundaries.control_mode == ControlMode.PROHIBITED
    assert ev.apply(single, MONDAY_EARLY).boundaries.control_mode == ControlMode.CONFIRM

    multiple = boundaries(
        {
            "id": "weekend",
            "condition": {"type": "day_of_week", "days": ["sat", "sun"], "negate": True},
            "effect": {"control_mode": "prohibited"},
        }
    )
    assert ev.apply(multiple, MONDAY_EARLY).boundaries.control_mode == ControlMode.PROHIBITED
    assert ev.apply(multiple, SATURDAY_NOON).boundaries.control_mode == ControlMode.CONFIRM


def test_calendar_entity_active_and_inactive() -> None:
    events: list[str] = []
    ev = TemporalEvaluator(get_calendar_events=lambda cal: events)
    b = boundaries(
        {
            "id": "wfh",
            "condition": {"type": "calendar_entity", "calendar_entity": "calendar.wfh"},
            "effect": {"control_mode": "prohibited"},
        }
    )
    assert ev.apply(b, SATURDAY_NOON).boundaries.control_mode == ControlMode.CONFIRM
    events.append("meeting")
    assert ev.apply(b, SATURDAY_NOON).boundaries.control_mode == ControlMode.PROHIBITED


def test_calendar_negate_expresses_complement() -> None:
    # The vacuum_away_blocks_only pattern: autonomous only while the calendar is active.
    events: list[str] = []
    ev = TemporalEvaluator(get_calendar_events=lambda cal: events)
    b = boundaries(
        {
            "id": "away_only",
            "condition": {
                "type": "calendar_entity",
                "calendar_entity": "calendar.away",
                "negate": True,
            },
            "effect": {"control_mode": "confirm"},
        },
        control_mode="autonomous",
    )
    # No active away block: the negated condition is true -> tightened to confirm.
    assert ev.apply(b, SATURDAY_NOON).boundaries.control_mode == ControlMode.CONFIRM
    events.append("away")
    assert ev.apply(b, SATURDAY_NOON).boundaries.control_mode == ControlMode.AUTONOMOUS


def test_unevaluable_condition_is_active_regardless_of_negate() -> None:
    ev = TemporalEvaluator()  # no calendar callback: calendar conditions are unevaluable
    for negate in (False, True):
        condition: dict[str, Any] = {
            "type": "calendar_entity",
            "calendar_entity": "calendar.gone",
        }
        if negate:
            condition["negate"] = True
        b = boundaries(
            {"id": "c", "condition": condition, "effect": {"control_mode": "prohibited"}}
        )
        result = ev.apply(b, SATURDAY_NOON)
        assert result.boundaries.control_mode == ControlMode.PROHIBITED
        assert any("fail-closed" in w for w in result.warnings)


def test_v2_condition_types_fail_closed() -> None:
    ev = TemporalEvaluator()
    b = boundaries(
        {
            "id": "solar",
            "condition": {"type": "solar_angle", "solar_event": "sunset"},
            "effect": {"control_mode": "prohibited"},
        }
    )
    result = ev.apply(b, SATURDAY_NOON)
    assert result.boundaries.control_mode == ControlMode.PROHIBITED
    assert any("fail-closed" in w for w in result.warnings)


def test_loosening_effect_ignored_with_warning() -> None:
    ev = TemporalEvaluator()
    b = boundaries(night_constraint({"control_mode": "autonomous"}))
    result = ev.apply(b, SATURDAY_LATE)
    assert result.boundaries.control_mode == ControlMode.CONFIRM  # unchanged
    assert any("tightening-only" in w for w in result.warnings)


def test_value_constraint_effect_collected() -> None:
    ev = TemporalEvaluator()
    b = boundaries(
        {
            "id": "quiet_hours_volume",
            "condition": {"type": "time_range", "start_time": "22:00", "end_time": "07:00"},
            "effect": {
                "service": "media_player.volume_set",
                "parameter": "volume_level",
                "max_value": 0.3,
            },
            "human_reason": "Quiet hours.",
        }
    )
    result = ev.apply(b, SATURDAY_LATE)
    assert result.active_limits == [
        {
            "id": "quiet_hours_volume",
            "limit": {
                "service": "media_player.volume_set",
                "parameter": "volume_level",
                "max_value": 0.3,
            },
            "human_reason": "Quiet hours.",
        }
    ]
    assert ev.apply(b, SATURDAY_NOON).active_limits == []


def test_inactive_constraints_do_not_modify_boundaries() -> None:
    ev = TemporalEvaluator()
    b = boundaries(night_constraint({"control_mode": "prohibited"}))
    result = ev.apply(b, SATURDAY_NOON)
    assert result.boundaries.control_mode == ControlMode.CONFIRM
    assert result.active_constraint_ids == []
    assert b.control_mode == ControlMode.CONFIRM  # original untouched
