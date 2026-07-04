"""Temporal constraint evaluation (Spec 6.5; Module Proposal 7.2)."""

from __future__ import annotations

from datetime import datetime, timedelta
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


# ---------------------------------------------------------------- solar_angle


def solar_constraint(
    event: str, offset: float | None = None, negate: bool = False
) -> dict[str, Any]:
    condition: dict[str, Any] = {"type": "solar_angle", "solar_event": event}
    if offset is not None:
        condition["solar_offset_minutes"] = offset
    if negate:
        condition["negate"] = True
    return {"id": "solar", "condition": condition, "effect": {"control_mode": "prohibited"}}


def solar_evaluator(elevation: float) -> TemporalEvaluator:
    return TemporalEvaluator(get_solar_elevation=lambda at: elevation)


def test_solar_boundaries_map_to_elevations() -> None:
    cases = [
        ("sunset", -1.0, True),
        ("sunset", 5.0, False),
        ("sunrise", 5.0, True),
        ("sunrise", -1.0, False),
        ("civil_twilight_end", -7.0, True),
        ("civil_twilight_end", -5.0, False),
        ("civil_twilight_start", -5.0, True),
        ("nautical_twilight_end", -13.0, True),
        ("nautical_twilight_end", -11.0, False),
        ("nautical_twilight_start", -11.0, True),
    ]
    for event, elevation, expected in cases:
        ev = solar_evaluator(elevation)
        result = ev.evaluate_condition({"type": "solar_angle", "solar_event": event}, SATURDAY_NOON)
        assert result is expected, f"{event} at {elevation}"


def test_solar_negate_inverts() -> None:
    ev = solar_evaluator(-1.0)  # after sunset
    b = boundaries(solar_constraint("sunset", negate=True))
    assert ev.apply(b, SATURDAY_LATE).boundaries.control_mode == ControlMode.CONFIRM


def test_solar_offset_samples_elevation_in_the_past() -> None:
    sunset = datetime(2026, 6, 13, 20, 0)

    def elevation_at(at: datetime) -> float:
        # Sun descends 0.2 degrees per minute, crossing zero at 20:00.
        return -(at - sunset).total_seconds() / 60 * 0.2

    ev = TemporalEvaluator(get_solar_elevation=elevation_at)
    condition = {"type": "solar_angle", "solar_event": "sunset", "solar_offset_minutes": 30}
    # 15 minutes after sunset: the shifted boundary (sunset+30) is not reached.
    assert ev.evaluate_condition(condition, sunset + timedelta(minutes=15)) is False
    # 45 minutes after sunset: past the shifted boundary.
    assert ev.evaluate_condition(condition, sunset + timedelta(minutes=45)) is True
    # Negative offset advances the transition: active before sunset itself.
    early = {"type": "solar_angle", "solar_event": "sunset", "solar_offset_minutes": -30}
    assert ev.evaluate_condition(early, sunset - timedelta(minutes=15)) is True


def test_solar_fails_closed_without_callback_or_data() -> None:
    b = boundaries(solar_constraint("sunset"))
    # No callback at all.
    no_callback = TemporalEvaluator().apply(b, SATURDAY_LATE)
    assert no_callback.boundaries.control_mode == ControlMode.PROHIBITED
    assert any("fail-closed" in w for w in no_callback.warnings)
    # Callback cannot answer.
    unknown = TemporalEvaluator(get_solar_elevation=lambda at: None).apply(b, SATURDAY_LATE)
    assert unknown.boundaries.control_mode == ControlMode.PROHIBITED
    # Unknown solar_event value.
    bad = solar_evaluator(-1.0).apply(boundaries(solar_constraint("noon")), SATURDAY_LATE)
    assert bad.boundaries.control_mode == ControlMode.PROHIBITED


def test_enforcer_passes_solar_callback_through() -> None:
    from mesa_core import MesaEnforcer, ProfileStore
    from mesa_core.backends import MemoryBackend

    enforcer = MesaEnforcer(
        ProfileStore(backend=MemoryBackend()), get_solar_elevation=lambda at: -3.0
    )
    assert enforcer.temporal.get_solar_elevation is not None
    assert enforcer.temporal.get_solar_elevation(SATURDAY_NOON) == -3.0
