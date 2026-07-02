"""TriggerValidator: live cross-reference of none declarations (Module Proposal 7.2)."""

from __future__ import annotations

from typing import Any

from mesa_core.backends import MemoryBackend
from mesa_core.store import ProfileStore
from mesa_core.trigger_validator import TriggerValidator, entities_by_role

from .test_conflict import make_profile

AUTOMATIONS: list[dict[str, Any]] = [
    {
        "id": "automation.occupancy_lights",
        "trigger": [{"platform": "state", "entity_id": "input_boolean.guest_mode"}],
        "condition": [{"condition": "state", "entity_id": "binary_sensor.occupied", "state": "on"}],
        "action": [{"service": "light.turn_off", "entity_id": "light.hallway"}],
    },
    {
        "id": "automation.plural_keys",
        "triggers": [{"platform": "state", "entity_id": ["sensor.multi_a", "sensor.multi_b"]}],
        "actions": [],
    },
]


def store_with_none(*entity_ids: str) -> ProfileStore:
    store = ProfileStore(backend=MemoryBackend())
    for entity_id in entity_ids:
        store.set(
            entity_id,
            make_profile(entity_id, boundaries={"triggers_automations": "none"}),
        )
    return store


def test_none_in_trigger_block_flagged_as_error() -> None:
    validator = TriggerValidator(store=store_with_none("input_boolean.guest_mode"))
    issues = validator.validate(lambda: AUTOMATIONS)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.entity_id == "input_boolean.guest_mode"
    assert issue.automation_id == "automation.occupancy_lights"
    assert issue.role == "trigger"
    assert issue.severity == "error"
    assert issue.declared_value == "none"
    assert "likely" in issue.recommendation


def test_none_in_condition_block_flagged_as_warning() -> None:
    validator = TriggerValidator(store=store_with_none("binary_sensor.occupied"))
    issues = validator.validate(lambda: AUTOMATIONS)
    assert len(issues) == 1
    assert issues[0].role == "condition"
    assert issues[0].severity == "warning"


def test_action_only_reference_not_flagged() -> None:
    # An entity written by an automation action does not trigger automations.
    validator = TriggerValidator(store=store_with_none("light.hallway"))
    assert validator.validate(lambda: AUTOMATIONS) == []


def test_likely_declaration_generates_no_issue() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "input_boolean.guest_mode",
        make_profile("input_boolean.guest_mode", boundaries={"triggers_automations": "likely"}),
    )
    assert TriggerValidator(store=store).validate(lambda: AUTOMATIONS) == []


def test_unprofiled_entity_no_false_positive() -> None:
    store = ProfileStore(backend=MemoryBackend())
    assert TriggerValidator(store=store).validate(lambda: AUTOMATIONS) == []


def test_undeclared_default_not_treated_as_none() -> None:
    # A profile that never declared triggers_automations must not be flagged.
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "input_boolean.guest_mode",
        make_profile("input_boolean.guest_mode", boundaries={"control_mode": "confirm"}),
    )
    assert TriggerValidator(store=store).validate(lambda: AUTOMATIONS) == []


def test_entity_id_lists_and_plural_keys() -> None:
    validator = TriggerValidator(store=store_with_none("sensor.multi_b"))
    issues = validator.validate(lambda: AUTOMATIONS)
    assert len(issues) == 1
    assert issues[0].automation_id == "automation.plural_keys"


# Named triggers (HA 2026.7+) reference entities through target selectors;
# device conditions reference them through device_id. Neither names an entity.
TARGETED_AUTOMATIONS: list[dict[str, Any]] = [
    {
        "id": "automation.movie_mode",
        "triggers": [
            {"trigger": "occupancy.detected", "target": {"area_id": "area.living_room"}}
        ],
        "conditions": [{"condition": "device", "device_id": "washer-device-1"}],
        "actions": [],
    },
]


def expand(kind: str, ref: str) -> list[str]:
    registry = {
        ("area_id", "area.living_room"): ["binary_sensor.lr_motion"],
        ("device_id", "washer-device-1"): ["sensor.washer_status"],
    }
    return registry.get((kind, ref), [])


def test_target_selector_reference_flagged_with_expand_target() -> None:
    validator = TriggerValidator(
        store=store_with_none("binary_sensor.lr_motion"), expand_target=expand
    )
    issues = validator.validate(lambda: TARGETED_AUTOMATIONS)
    assert len(issues) == 1
    assert issues[0].role == "trigger"
    assert issues[0].severity == "error"
    assert issues[0].automation_id == "automation.movie_mode"


def test_device_condition_reference_flagged_with_expand_target() -> None:
    validator = TriggerValidator(
        store=store_with_none("sensor.washer_status"), expand_target=expand
    )
    issues = validator.validate(lambda: TARGETED_AUTOMATIONS)
    assert len(issues) == 1
    assert issues[0].role == "condition"
    assert issues[0].severity == "warning"


def test_target_selector_invisible_without_expand_target() -> None:
    # Documented limitation: without the callback, only explicit entity_id
    # references are seen, so indirect references produce no issues.
    validator = TriggerValidator(store=store_with_none("binary_sensor.lr_motion"))
    assert validator.validate(lambda: TARGETED_AUTOMATIONS) == []


def test_entities_by_role_expands_targets() -> None:
    by_role = entities_by_role(TARGETED_AUTOMATIONS[0], expand_target=expand)
    assert by_role["trigger"] == {"binary_sensor.lr_motion"}
    assert by_role["condition"] == {"sensor.washer_status"}
    assert by_role["action"] == set()


def test_async_variants_match_sync() -> None:
    import asyncio

    validator = TriggerValidator(
        store=store_with_none("input_boolean.guest_mode", "binary_sensor.occupied")
    )

    async def run() -> None:
        issues = await validator.avalidate(lambda: AUTOMATIONS)
        assert {i.entity_id for i in issues} == {"input_boolean.guest_mode", "binary_sensor.occupied"}
        single = await validator.avalidate_entity("input_boolean.guest_mode", lambda: AUTOMATIONS)
        assert len(single) == 1 and single[0].role == "trigger"

    asyncio.run(run())


def test_validate_entity_single_path() -> None:
    validator = TriggerValidator(
        store=store_with_none("input_boolean.guest_mode", "binary_sensor.occupied")
    )
    issues = validator.validate_entity("input_boolean.guest_mode", lambda: AUTOMATIONS)
    assert len(issues) == 1
    assert issues[0].entity_id == "input_boolean.guest_mode"
    assert validator.validate_entity("light.unrelated", lambda: AUTOMATIONS) == []
