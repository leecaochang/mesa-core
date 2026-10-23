"""Parent-device inheritance for HA child devices (Spec 5.6, 5.7, 9.2, 9.5).

Home Assistant registers a multi-part product as a main device plus one child
device per part. The fixture models a power strip: each outlet's switch sits on
its own child device, and the strip's power sensor sits on the main device.
"""

from __future__ import annotations

import gc
import warnings
from datetime import datetime, timedelta
from typing import Any

import pytest

from mesa_core.backends import MemoryBackend
from mesa_core.enforcer import MesaEnforcer
from mesa_core.exceptions import HostCallbackError, InvalidCursorError
from mesa_core.profile import ControlMode, PrivacyLevel, TriggersAutomations
from mesa_core.store import ProfileStore

from .test_conflict import make_profile

NOON = datetime(2026, 6, 13, 12, 0)
OUTLET = "switch.strip_outlet_3"
DEVICES = {
    "switch.strip_outlet_1": "outlet_1",
    "switch.strip_outlet_3": "outlet_3",
    "sensor.strip_power": "strip",
    "switch.lamp": "lamp",
}
PARENTS = {"outlet_1": "strip", "outlet_3": "strip"}


def make_store(**kwargs: Any) -> ProfileStore:
    callbacks: dict[str, Any] = {
        "get_entity_device": DEVICES.get,
        "get_device_parent": PARENTS.get,
    }
    callbacks.update(kwargs)
    return ProfileStore(backend=MemoryBackend(), **callbacks)


def levels(store: ProfileStore, entity_id: str) -> dict[str, str]:
    explanation = store.resolver.explain(entity_id)
    return {e.field_path: e.provided_by_level for e in explanation.explanation}


# ------------------------------------------------------------- resolution


def test_parent_prohibition_reaches_child_without_profile() -> None:
    store = make_store()
    store.set_device_profile(
        "strip", make_profile("strip", boundaries={"control_mode": "prohibited"})
    )
    effective = store.get_effective(OUTLET)
    assert effective.operational_boundaries.control_mode == ControlMode.PROHIBITED
    assert levels(store, OUTLET)["operational_boundaries.control_mode"] == "parent_device"


def test_parent_prohibition_is_not_loosened_by_child_confirm() -> None:
    store = make_store()
    store.set_device_profile(
        "strip", make_profile("strip", boundaries={"control_mode": "prohibited"})
    )
    store.set_device_profile(
        "outlet_3", make_profile("outlet_3", boundaries={"control_mode": "confirm"})
    )
    effective = store.get_effective(OUTLET)
    assert effective.operational_boundaries.control_mode == ControlMode.PROHIBITED


def test_parent_confirm_beats_child_autonomous() -> None:
    store = make_store()
    store.set_device_profile("strip", make_profile("strip", boundaries={"control_mode": "confirm"}))
    store.set_device_profile(
        "outlet_3", make_profile("outlet_3", boundaries={"control_mode": "autonomous"})
    )
    effective = store.get_effective(OUTLET)
    assert effective.operational_boundaries.control_mode == ControlMode.CONFIRM


def test_parent_privacy_restriction_reaches_child() -> None:
    store = make_store()
    store.set_device_profile("strip", make_profile("strip", privacy={"level": "restricted"}))
    store.set_device_profile("outlet_3", make_profile("outlet_3", privacy={"level": "normal"}))
    effective = store.get_effective(OUTLET)
    assert effective.privacy_classification.level == PrivacyLevel.RESTRICTED


def test_parent_likely_triggers_are_sticky() -> None:
    store = make_store()
    store.set_device_profile(
        "strip", make_profile("strip", boundaries={"triggers_automations": "likely"})
    )
    store.set_device_profile(
        "outlet_3", make_profile("outlet_3", boundaries={"triggers_automations": "none"})
    )
    effective = store.get_effective(OUTLET)
    assert effective.operational_boundaries.triggers_automations == TriggersAutomations.LIKELY


def test_child_device_value_beats_parent_for_rule_d_fields() -> None:
    store = make_store()
    store.set_device_profile(
        "strip", make_profile("strip", boundaries={"reversibility_cost": "high"})
    )
    store.set_device_profile(
        "outlet_3", make_profile("outlet_3", boundaries={"reversibility_cost": "trivial"})
    )
    assert store.get_effective(OUTLET).operational_boundaries.reversibility_cost == "trivial"
    assert levels(store, OUTLET)["operational_boundaries.reversibility_cost"] == "device"


def test_parent_value_beats_area_for_rule_d_fields() -> None:
    store = make_store(get_entity_area=lambda _eid: "office")
    store.set_area_profile(
        "office", make_profile("office", boundaries={"reversibility_cost": "none"})
    )
    store.set_device_profile(
        "strip", make_profile("strip", boundaries={"reversibility_cost": "high"})
    )
    assert store.get_effective(OUTLET).operational_boundaries.reversibility_cost == "high"
    assert levels(store, OUTLET)["operational_boundaries.reversibility_cost"] == "parent_device"


def test_parent_without_profile_falls_through_to_area() -> None:
    store = make_store(get_entity_area=lambda _eid: "office")
    store.set_area_profile(
        "office", make_profile("office", boundaries={"reversibility_cost": "none"})
    )
    assert levels(store, OUTLET)["operational_boundaries.reversibility_cost"] == "area"


def test_parent_layer_makes_the_entity_profiled() -> None:
    store = make_store()
    assert not store.resolver.has_profile(OUTLET)
    store.set_device_profile("strip", make_profile("strip"))
    assert store.resolver.has_profile(OUTLET)


def test_parent_level_cannot_use_the_loosening_override() -> None:
    # Rule A: the loosening override is valid at entity scope only, so a parent
    # device profile declaring it cannot loosen an inherited confirm.
    store = make_store()
    store.set_domain_profile(
        "switch", make_profile("switch", origin="developer", boundaries={"control_mode": "confirm"})
    )
    store.set_device_profile(
        "strip",
        make_profile(
            "strip",
            boundaries={
                "control_mode": "autonomous",
                "override_control_mode": True,
                "control_reason": "bench supply",
            },
        ),
    )
    assert store.get_effective(OUTLET).operational_boundaries.control_mode == ControlMode.CONFIRM


def test_parent_trusted_control_replaces_the_baseline_like_a_device_profile() -> None:
    # A trusted parent declaration is the product-wide operator intent, so it
    # replaces the lock baseline exactly as a device profile does for the
    # device's own entities (Spec 5.8). Hosts enabling the callback inherit
    # this for every existing main-device profile.
    store = make_store(get_entity_device={"lock.door_bolt": "bolt"}.get)
    store.set_device_profile(
        "bolt", make_profile("bolt", boundaries={"control_mode": "autonomous"})
    )
    device_level = store.get_effective("lock.door_bolt").operational_boundaries.control_mode

    store = make_store(
        get_entity_device={"lock.door_bolt": "bolt"}.get,
        get_device_parent={"bolt": "door"}.get,
    )
    store.set_device_profile(
        "door", make_profile("door", boundaries={"control_mode": "autonomous"})
    )
    parent_level = store.get_effective("lock.door_bolt").operational_boundaries.control_mode
    assert parent_level == device_level == ControlMode.AUTONOMOUS


def test_main_device_entities_get_one_device_layer() -> None:
    # The strip's own sensor sits on the main device: its profile is the
    # device level, and a main device has no parent level.
    store = make_store()
    store.set_device_profile(
        "strip", make_profile("strip", boundaries={"reversibility_cost": "high"})
    )
    layers = store.resolver._gather_layers("sensor.strip_power")
    assert [layer.level for layer in layers] == ["device"]


def test_callback_naming_the_device_itself_is_no_parent() -> None:
    store = make_store(get_device_parent=lambda device_id: device_id)
    store.set_device_profile(
        "outlet_3", make_profile("outlet_3", boundaries={"reversibility_cost": "high"})
    )
    layers = store.resolver._gather_layers(OUTLET)
    assert [layer.level for layer in layers] == ["device"]


def test_parent_lookup_is_one_level_only() -> None:
    # A host returning a parent for the parent too is never asked about it.
    calls: list[str] = []

    def parent(device_id: str) -> str | None:
        calls.append(device_id)
        return {"outlet_3": "strip", "strip": "rack"}.get(device_id)

    store = make_store(get_device_parent=parent)
    store.set_device_profile(
        "rack", make_profile("rack", boundaries={"control_mode": "prohibited"})
    )
    store.set_device_profile("strip", make_profile("strip"))
    layers = store.resolver._gather_layers(OUTLET)
    assert calls == ["outlet_3"]
    assert [layer.level for layer in layers] == ["parent_device"]
    assert store.get_effective(OUTLET).operational_boundaries.control_mode != ControlMode.PROHIBITED


def test_parent_callback_unused_for_entities_without_device() -> None:
    calls: list[str] = []
    store = make_store(get_device_parent=lambda device_id: calls.append(device_id))
    store.get_effective("input_boolean.flag")
    assert calls == []


def test_parent_callback_inert_without_entity_device_mapping() -> None:
    store = ProfileStore(backend=MemoryBackend(), get_device_parent=PARENTS.get)
    store.set_device_profile(
        "strip", make_profile("strip", boundaries={"control_mode": "prohibited"})
    )
    assert store.resolver._gather_layers(OUTLET) == []


def _layered_store(**kwargs: Any) -> ProfileStore:
    store = make_store(
        get_entity_area=lambda _eid: "office",
        get_entity_integration=lambda _eid: "strips",
        **kwargs,
    )
    store.set_domain_profile(
        "switch", make_profile("switch", origin="developer", boundaries={"idempotent": True})
    )
    store.set_integration_profile(
        "strips", make_profile("strips", origin="developer", boundaries={"control_mode": "confirm"})
    )
    store.set_area_profile(
        "office", make_profile("office", boundaries={"reversibility_cost": "none"})
    )
    store.set_device_profile(
        "outlet_3", make_profile("outlet_3", boundaries={"reversibility_cost": "trivial"})
    )
    store.set(OUTLET, make_profile(OUTLET, tags=["power.outlet"]))
    return store


@pytest.mark.parametrize("parent_callback", [None, lambda _device_id: None])
def test_resolution_unchanged_without_a_parent(parent_callback: Any) -> None:
    # With no parent mapping, a stored parent profile is inert: the explanation
    # is exactly what a store without that profile produces.
    baseline = _layered_store(get_device_parent=None).resolver.explain(OUTLET).to_dict()
    store = _layered_store(get_device_parent=parent_callback)
    store.set_device_profile(
        "strip", make_profile("strip", boundaries={"control_mode": "prohibited"})
    )
    assert store.resolver.explain(OUTLET).to_dict() == baseline


# --------------------------------------------------------- callback contract


def _raises(_device_id: str) -> str:
    raise RuntimeError("device registry unavailable")


async def _async_parent(_device_id: str) -> str:
    return "strip"


@pytest.mark.parametrize(
    ("callback", "message"),
    [
        (_raises, "get_device_parent callback failed"),
        (lambda _device_id: "", "non-empty identifier"),
        (lambda _device_id: "   ", "non-empty identifier"),
        (lambda _device_id: 7, "non-empty identifier"),
        (_async_parent, "must be synchronous"),
    ],
)
def test_malformed_parent_callback_fails_closed(callback: Any, message: str) -> None:
    store = make_store(get_device_parent=callback)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        with pytest.raises(HostCallbackError, match=message):
            store.get_effective(OUTLET)
        gc.collect()


# ------------------------------------------------------------------- query


def test_query_by_main_device_finds_its_parts() -> None:
    store = make_store()
    for entity_id in DEVICES:
        store.set(entity_id, make_profile(entity_id))
    assert {r.entity_id for r in store.query(devices=["strip"]).rows} == {
        "switch.strip_outlet_1",
        "switch.strip_outlet_3",
        "sensor.strip_power",
    }
    assert {r.entity_id for r in store.query(devices=["outlet_3"]).rows} == {OUTLET}


def test_query_by_main_device_without_parent_mapping_finds_own_entities() -> None:
    store = make_store(get_device_parent=None)
    for entity_id in DEVICES:
        store.set(entity_id, make_profile(entity_id))
    assert {r.entity_id for r in store.query(devices=["strip"]).rows} == {"sensor.strip_power"}


def test_query_skips_rows_whose_parent_lookup_fails() -> None:
    store = make_store(get_device_parent=_raises)
    store.set(OUTLET, make_profile(OUTLET))
    result = store.query(devices=["strip"])
    assert result.total_matched == 0
    assert "skipped an unevaluable profile" in result.warnings


def test_query_cursor_invalidated_by_parent_profile_change() -> None:
    store = make_store()
    store.set("switch.strip_outlet_1", make_profile("switch.strip_outlet_1"))
    store.set(OUTLET, make_profile(OUTLET))
    first = store.query(devices=["strip"], limit=1)
    assert first.next_cursor is not None
    store.set_device_profile(
        "strip", make_profile("strip", boundaries={"reversibility_cost": "high"})
    )
    with pytest.raises(InvalidCursorError):
        store.query(devices=["strip"], limit=1, cursor=first.next_cursor)


# ------------------------------------------------------------- enforcement


def test_parent_tightened_after_challenge_denies_the_approval() -> None:
    # A confirmation approves one call; it never outlives a policy change.
    store = make_store()
    store.set_device_profile("strip", make_profile("strip", boundaries={"control_mode": "confirm"}))
    enforcer = MesaEnforcer(store)
    first = enforcer.evaluate(OUTLET, "switch.turn_on", current_time=NOON)
    assert not first.allowed and first.confirmation_challenge is not None

    store.set_device_profile(
        "strip", make_profile("strip", boundaries={"control_mode": "prohibited"})
    )
    token = {
        "challenge_id": first.confirmation_challenge["challenge_id"],
        "approved_by": "user.alice",
        "approved_at": NOON.isoformat(),
    }
    second = enforcer.evaluate(
        OUTLET,
        "switch.turn_on",
        current_time=NOON + timedelta(seconds=5),
        confirmation_token=token,
    )
    assert not second.allowed
    assert second.rule_applied == "control_mode:prohibited"
