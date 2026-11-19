"""Which inheritance levels may replace a prohibited control_mode floor (Spec 5.8).

A trusted declaration at entity, device, or domain scope names the entity or
its domain and replaces the floor. Area, parent-device, and integration
profiles cover entities their author may not have had in mind, so against a
prohibited or read_only floor they can only tighten. A confirm floor is still
replaced by a trusted declaration at any scope.
"""

from __future__ import annotations

from typing import Any

import pytest

from mesa_core.backends import MemoryBackend
from mesa_core.enforcer import MesaEnforcer
from mesa_core.store import ProfileStore

from .test_conflict import make_profile

LOCK = "lock.front_door"
LOCK_DEVICE = "lock_dev"
LOCK_PART = "bolt"


def make_store(area: str | None = "garage") -> ProfileStore:
    return ProfileStore(
        MemoryBackend(),
        get_entity_area=lambda e: area,
        get_entity_device={LOCK: LOCK_PART, "alarm_control_panel.home": LOCK_PART}.get,
        get_device_parent={LOCK_PART: LOCK_DEVICE}.get,
        get_entity_integration=lambda e: "hub",
    )


def mode(store: ProfileStore, entity_id: str = LOCK) -> str:
    return store.get_effective(entity_id).operational_boundaries.control_mode.value


def declare(store: ProfileStore, level: str, value: str, origin: str = "user") -> None:
    p = make_profile(level, origin=origin, boundaries={"control_mode": value})
    setters: dict[str, Any] = {
        "entity": lambda: store.set(LOCK, p),
        "device": lambda: store.set_device_profile(LOCK_PART, p),
        "parent_device": lambda: store.set_device_profile(LOCK_DEVICE, p),
        "area": lambda: store.set_area_profile("garage", p),
        "integration": lambda: store.set_integration_profile("hub", p),
        "domain": lambda: store.set_domain_profile("lock", p),
    }
    setters[level]()


@pytest.mark.parametrize("level", ["area", "parent_device", "integration"])
@pytest.mark.parametrize("value", ["autonomous", "confirm"])
def test_broad_levels_cannot_lift_the_prohibited_baseline(level: str, value: str) -> None:
    store = make_store()
    declare(store, level, value, origin="developer" if level == "integration" else "user")
    assert mode(store) == "prohibited"


@pytest.mark.parametrize("level", ["entity", "device", "domain"])
def test_naming_levels_replace_the_prohibited_baseline(level: str) -> None:
    store = make_store()
    declare(store, level, "confirm")
    assert mode(store) == "confirm"


def test_naming_level_lifts_even_when_an_area_also_declares() -> None:
    # Rule A still applies among declarations once the floor is replaced.
    store = make_store()
    declare(store, "area", "autonomous")
    declare(store, "domain", "confirm")
    assert mode(store) == "confirm"


def test_alarm_panel_is_protected_like_a_lock() -> None:
    store = make_store()
    declare(store, "area", "autonomous")
    assert mode(store, "alarm_control_panel.home") == "prohibited"


def test_prohibited_deployment_default_is_protected_the_same_way() -> None:
    store = make_store()
    store.set_deployment_defaults({"domain_overrides": {"cover": {"control_mode": "prohibited"}}})
    declare(store, "area", "autonomous")
    assert mode(store, "cover.garage_door") == "prohibited"


def test_deployment_confirm_for_locks_is_liftable_by_an_area() -> None:
    # The operator relaxed the lock floor to confirm at deployment scope, so it
    # is an ordinary confirm floor.
    store = make_store()
    store.set_deployment_defaults({"domain_overrides": {"lock": {"control_mode": "confirm"}}})
    declare(store, "area", "autonomous")
    assert mode(store) == "autonomous"


def test_confirm_floor_domains_still_follow_an_area_declaration() -> None:
    # Moving an entity into an area can still loosen a confirm-floor domain.
    store = make_store()
    assert mode(store, "switch.garage_fan") == "confirm"
    declare(store, "area", "autonomous")
    assert mode(store, "switch.garage_fan") == "autonomous"


def test_explain_reports_the_floor_and_warns_about_the_held_back_declaration() -> None:
    store = make_store()
    declare(store, "area", "autonomous")
    explanation = store.resolver.explain(LOCK)
    entry = next(
        e for e in explanation.explanation if e.field_path == "operational_boundaries.control_mode"
    )
    assert entry.effective_value == "prohibited"
    assert entry.provided_by_level == "built_in_baseline"
    assert any(
        "declared at area scope does not replace the prohibited built_in_baseline floor" in w
        for w in explanation.warnings
    )


def test_no_warning_when_a_broad_level_tightens() -> None:
    store = make_store()
    declare(store, "area", "prohibited")
    explanation = store.resolver.explain(LOCK)
    assert mode(store) == "prohibited"
    assert not any("does not replace" in w for w in explanation.warnings)


# --- control_reason follows the control_mode it explains (Spec 6.1) ----------


def reasoned(key: str, ob: dict[str, Any], origin: str = "user") -> Any:
    return make_profile(key, origin=origin, boundaries=ob)


def denial_reason(store: ProfileStore, entity_id: str = LOCK) -> str:
    return MesaEnforcer(store).evaluate(entity_id, "unlock", {}).reason


def test_held_back_reason_is_not_reported_for_the_floor() -> None:
    store = make_store()
    store.set_area_profile(
        "garage",
        reasoned(
            "garage",
            {
                "control_mode": "autonomous",
                "control_reason": "smoke test area",
                "enforcement_mode": "enforced",
            },
        ),
    )
    explanation = store.resolver.explain(LOCK)
    assert explanation.effective_profile.operational_boundaries.control_reason is None
    assert not any(
        e.field_path == "operational_boundaries.control_reason" for e in explanation.explanation
    )
    assert denial_reason(store) == f"Entity is prohibited by policy: {LOCK}"


def test_reason_comes_from_the_layer_whose_mode_won() -> None:
    store = make_store()
    store.set_domain_profile(
        "lock",
        reasoned("lock", {"control_mode": "prohibited", "control_reason": "physical security"}),
    )
    store.set_area_profile(
        "garage",
        reasoned(
            "garage",
            {
                "control_mode": "confirm",
                "control_reason": "garage lights",
                "enforcement_mode": "enforced",
            },
        ),
    )
    assert store.get_effective(LOCK).operational_boundaries.control_reason == "physical security"
    assert denial_reason(store) == "Entity is prohibited by policy: physical security"


def test_losing_mode_reason_is_dropped_when_the_winner_gives_none() -> None:
    store = make_store()
    store.set_domain_profile("lock", reasoned("lock", {"control_mode": "prohibited"}))
    store.set_area_profile(
        "garage", reasoned("garage", {"control_mode": "confirm", "control_reason": "garage lights"})
    )
    assert store.get_effective(LOCK).operational_boundaries.control_reason is None


def test_reason_only_layer_still_explains_the_floor() -> None:
    # A layer that declares a reason but no mode keeps ordinary Rule D inheritance.
    store = make_store()
    store.set(LOCK, reasoned(LOCK, {"control_reason": "front door, operator only"}))
    store.set_area_profile("garage", reasoned("garage", {"control_mode": "autonomous"}))
    ob = store.get_effective(LOCK).operational_boundaries
    assert ob.control_mode.value == "prohibited"
    assert ob.control_reason == "front door, operator only"
