"""ProfileStore and storage backend tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from mesa_core import MetadataOrigin, SemanticProfile
from mesa_core.backends import JsonFileBackend, MemoryBackend, SqliteBackend, StorageBackend
from mesa_core.exceptions import InvalidCursorError
from mesa_core.profile import ControlMode, TriggersAutomations
from mesa_core.store import ProfileStore

FIXTURES = Path(__file__).parent / "fixtures" / "profiles"


def _profile(entity_id: str, **overrides: object) -> SemanticProfile:
    doc = {
        "semantic_profile": {
            "metadata_origin": {"source": "user", "confidence": 1.0},
            "semantic_tags": ["lighting.ambient"],
            "operational_boundaries": {"control_mode": "autonomous"},
        },
        "privacy_classification": {"level": "normal"},
    }
    sp = doc["semantic_profile"]
    for key, value in overrides.items():
        sp[key] = value  # type: ignore[index]
    return SemanticProfile.from_dict(entity_id, doc)


@pytest.fixture(params=["memory", "jsonfile", "sqlite"])
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> StorageBackend:
    if request.param == "memory":
        return MemoryBackend()
    if request.param == "jsonfile":
        return JsonFileBackend(tmp_path / "mesa")
    return SqliteBackend(tmp_path / "mesa.db")


def test_crud_round_trip(backend: StorageBackend) -> None:
    store = ProfileStore(backend=backend)
    assert store.get("light.x") is None
    store.set("light.x", _profile("light.x"))
    loaded = store.get("light.x")
    assert loaded is not None
    assert loaded.entity_id == "light.x"
    assert loaded.operational_boundaries.control_mode == ControlMode.AUTONOMOUS
    assert loaded.metadata.source == MetadataOrigin.USER
    store.delete("light.x")
    assert store.get("light.x") is None


def test_domain_and_area_profiles_use_reserved_keys(backend: StorageBackend) -> None:
    store = ProfileStore(backend=backend)
    store.set_domain_profile("light", _profile("light"))
    store.set_area_profile("area.bedroom", _profile("area.bedroom"))
    store.set("light.x", _profile("light.x"))
    assert store.entity_keys() == ["light.x"]
    domain = store.get_domain_profile("light")
    assert domain is not None and domain.inheritance_scope == "domain"
    area = store.get_area_profile("area.bedroom")
    assert area is not None and area.inheritance_scope == "area"


def test_delete_domain_and_area_profiles(backend: StorageBackend) -> None:
    store = ProfileStore(backend=backend)
    store.set_domain_profile("light", _profile("light"))
    store.set_area_profile("area.bedroom", _profile("area.bedroom"))
    store.set("light.x", _profile("light.x"))

    store.delete_domain_profile("light")
    assert store.get_domain_profile("light") is None
    # Deleting a scope profile leaves the area profile and entity profiles untouched.
    assert store.get_area_profile("area.bedroom") is not None
    assert store.get("light.x") is not None

    store.delete_area_profile("area.bedroom")
    assert store.get_area_profile("area.bedroom") is None
    assert store.get("light.x") is not None
    assert store.entity_keys() == ["light.x"]


def test_delete_missing_scope_profile_is_noop(backend: StorageBackend) -> None:
    store = ProfileStore(backend=backend)
    store.delete_domain_profile("nonexistent")
    store.delete_area_profile("area.nope")  # no error, mirrors delete()


def test_deployment_defaults_round_trip(backend: StorageBackend) -> None:
    store = ProfileStore(backend=backend)
    assert store.get_deployment_defaults() is None
    store.set_deployment_defaults(
        {
            "deployment_defaults": {
                "default_control_mode": "confirm",
                "triggers_automations_domains": ["input_boolean"],
                "domain_overrides": {
                    "light": {"control_mode": "autonomous"},
                    "lock": {"control_mode": "prohibited", "triggers_automations": "likely"},
                },
            }
        }
    )
    defaults = store.get_deployment_defaults()
    assert defaults is not None
    assert defaults.control_mode_for("light") == ControlMode.AUTONOMOUS
    assert defaults.control_mode_for("lock") == ControlMode.PROHIBITED
    assert defaults.control_mode_for("cover") == ControlMode.CONFIRM
    assert defaults.triggers_for("lock") == TriggersAutomations.LIKELY
    assert defaults.triggers_for("input_boolean") == TriggersAutomations.LIKELY
    assert defaults.triggers_for("sensor") == TriggersAutomations.UNKNOWN


def test_find_orphans(backend: StorageBackend) -> None:
    store = ProfileStore(backend=backend)
    store.set("light.kept", _profile("light.kept"))
    store.set("light.renamed", _profile("light.renamed"))
    store.set_domain_profile("light", _profile("light"))  # reserved keys are not orphans
    orphans = store.find_orphans(["light.kept", "light.other"])
    assert orphans == ["light.renamed"]


def test_list_filters() -> None:
    store = ProfileStore(backend=MemoryBackend(), get_entity_area=lambda eid: "area.living_room")
    store.set("light.a", _profile("light.a"))
    store.set("light.b", _profile("light.b", semantic_tags=["lighting.task"]))
    store.set("switch.c", _profile("switch.c"))

    assert {p.entity_id for p in store.list(domain="light").profiles} == {"light.a", "light.b"}
    assert {p.entity_id for p in store.list(tags=["lighting.task"]).profiles} == {"light.b"}
    assert store.list(areas=["area.living_room"]).total_matched == 3
    assert store.list(areas=["area.elsewhere"]).total_matched == 0


def test_list_excludes_untrusted_by_default() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set("light.user", _profile("light.user"))
    inferred = SemanticProfile.from_dict(
        "light.inferred",
        {
            "semantic_profile": {
                "metadata_origin": {
                    "source": "inferred_ai",
                    "confidence": 0.8,
                    "generated_at": "2026-06-01T00:00:00+00:00",
                }
            }
        },
    )
    store.set("light.inferred", inferred)
    unknown = SemanticProfile.from_dict("light.unknown", {"semantic_profile": {}})
    store.set("light.unknown", unknown)

    default = store.list()
    assert {p.entity_id for p in default.profiles} == {"light.user"}
    included = store.list(include_inferred=True)
    assert included.total_matched == 3
    # An explicit origin filter implies inclusion.
    only_inferred = store.list(origin="inferred_ai")
    assert {p.entity_id for p in only_inferred.profiles} == {"light.inferred"}


def test_pagination_cursor_round_trip() -> None:
    store = ProfileStore(backend=MemoryBackend())
    for i in range(7):
        store.set(f"light.l{i}", _profile(f"light.l{i}"))
    first = store.list(limit=3)
    assert [p.entity_id for p in first.profiles] == ["light.l0", "light.l1", "light.l2"]
    assert first.total_matched == 7 and first.has_more and first.next_cursor

    second = store.list(limit=3, cursor=first.next_cursor)
    assert [p.entity_id for p in second.profiles] == ["light.l3", "light.l4", "light.l5"]
    third = store.list(limit=3, cursor=second.next_cursor)
    assert [p.entity_id for p in third.profiles] == ["light.l6"]
    assert not third.has_more and third.next_cursor is None


def test_cursor_invalidated_by_profile_changes() -> None:
    store = ProfileStore(backend=MemoryBackend())
    for i in range(5):
        store.set(f"light.l{i}", _profile(f"light.l{i}"))
    page = store.list(limit=2)
    store.set("light.new", _profile("light.new"))  # changes the store fingerprint
    with pytest.raises(InvalidCursorError):
        store.list(limit=2, cursor=page.next_cursor)


def test_malformed_cursor_rejected() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set("light.a", _profile("light.a"))
    with pytest.raises(InvalidCursorError):
        store.list(cursor="not-a-cursor")


def test_bulk_operations() -> None:
    store = ProfileStore(backend=MemoryBackend())
    store.set_many({f"light.l{i}": _profile(f"light.l{i}") for i in range(3)})
    assert store.list().total_matched == 3
    store.delete_many(["light.l0", "light.l2"])
    assert {p.entity_id for p in store.list().profiles} == {"light.l1"}


def test_async_variants() -> None:
    async def run() -> None:
        store = ProfileStore(backend=MemoryBackend())
        await store.aset("light.x", _profile("light.x"))
        loaded = await store.aget("light.x")
        assert loaded is not None and loaded.entity_id == "light.x"
        result = await store.alist(domain="light")
        assert result.total_matched == 1
        assert await store.afind_orphans(["other.entity"]) == ["light.x"]
        await store.adelete("light.x")
        assert await store.aget("light.x") is None

        store.set_domain_profile("light", _profile("light"))
        store.set_area_profile("area.bedroom", _profile("area.bedroom"))
        await store.adelete_domain_profile("light")
        await store.adelete_area_profile("area.bedroom")
        assert store.get_domain_profile("light") is None
        assert store.get_area_profile("area.bedroom") is None

    asyncio.run(run())


def test_stored_document_matches_fixture_round_trip(tmp_path: Path) -> None:
    # A profile loaded from a fixture and stored must round-trip byte-identically
    # at the document level (unknown fields preserved).
    data = json.loads((FIXTURES / "helper_mode_flag.json").read_text())
    profile = SemanticProfile.from_dict("input_boolean.guest_mode", data)
    store = ProfileStore(backend=JsonFileBackend(tmp_path))
    store.set("input_boolean.guest_mode", profile)
    reloaded = store.get("input_boolean.guest_mode")
    assert reloaded is not None
    assert reloaded.to_dict() == data
    assert reloaded.raw["semantic_profile"]["helper_traits"]["role"] == "mode_flag"
