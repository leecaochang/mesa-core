"""Profile export/import round trips, fidelity, and conflict policies."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from mesa_core import (
    MesaError,
    MesaValidationError,
    SemanticProfile,
    aexport_profiles,
    aimport_profiles,
    export_profiles,
    import_profiles,
)
from mesa_core.backends import JsonFileBackend, MemoryBackend, SqliteBackend
from mesa_core.store import ProfileStore


def profile(entity_id: str, **sp_extra: Any) -> SemanticProfile:
    doc: dict[str, Any] = {
        "semantic_profile": {
            "metadata_origin": {"source": "developer"},
            "semantic_tags": ["lighting.ambient"],
            "operational_boundaries": {"control_mode": "confirm", "control_reason": "test"},
            # Unknown enrichment block: must survive the round trip untouched.
            "helper_traits": {"role": "mode_flag"},
            **sp_extra,
        },
        "privacy_classification": {"level": "normal"},
    }
    return SemanticProfile.from_dict(entity_id, doc)


def populated_store() -> ProfileStore:
    store = ProfileStore(backend=MemoryBackend())
    store.set("light.x", profile("light.x"))
    store.set("lock.front", profile("lock.front"))
    store.set_domain_profile("lock", profile("lock"))
    store.set_integration_profile("hue", profile("hue"))
    store.set_area_profile("area.bedroom", profile("area.bedroom"))
    store.set_deployment_defaults(
        {"deployment_defaults": {"default_control_mode": "confirm"}}
    )
    return store


def all_docs(store: ProfileStore) -> dict[str, Any]:
    return {key: store.backend.read(key) for key in store.backend.list_keys()}


@pytest.mark.parametrize("backend_kind", ["memory", "jsonfile", "sqlite"])
def test_round_trip_across_backends(backend_kind: str, tmp_path: Path) -> None:
    source = populated_store()
    archive = export_profiles(source)

    if backend_kind == "memory":
        target = ProfileStore(backend=MemoryBackend())
    elif backend_kind == "jsonfile":
        target = ProfileStore(backend=JsonFileBackend(tmp_path / "mesa"))
    else:
        target = ProfileStore(backend=SqliteBackend(tmp_path / "mesa.db"))

    result = import_profiles(target, archive)
    assert result.ok
    assert result.imported == 6  # 2 entities + 3 scopes + defaults
    # Byte-identical documents on the other side, unknown fields included.
    assert all_docs(target) == all_docs(source)
    reloaded = target.get("light.x")
    assert reloaded is not None
    assert reloaded.raw["semantic_profile"]["helper_traits"] == {"role": "mode_flag"}


def test_archive_envelope_shape() -> None:
    archive = export_profiles(populated_store())
    inner = archive["mesa_export"]
    assert inner["format_version"] == "1.0"
    assert inner["exported_at"] and inner["mesa_core_version"]
    assert set(inner["entities"]) == {"light.x", "lock.front"}
    assert set(inner["domains"]) == {"lock"}
    assert set(inner["integrations"]) == {"hue"}
    assert set(inner["areas"]) == {"area.bedroom"}
    assert "deployment_defaults" in inner


def test_export_is_faithful_import_validates() -> None:
    source = populated_store()
    # A malformed document lands in storage behind the store's back.
    source.backend.write("light.bad", {"semantic_profile": {"operational_boundaries": {"control_mode": "yolo"}}})
    archive = export_profiles(source)
    # Export drops nothing.
    assert "light.bad" in archive["mesa_export"]["entities"]

    target = ProfileStore(backend=MemoryBackend())
    result = import_profiles(target, archive)
    # Import quarantines the malformed doc and lands the rest.
    assert not result.ok
    assert "entities:light.bad" in result.invalid
    assert result.imported == 6
    assert target.backend.read("light.bad") is None


def test_conflict_skip_is_default() -> None:
    target = populated_store()
    original = target.backend.read("light.x")
    archive = export_profiles(populated_store())
    result = import_profiles(target, archive)
    assert result.imported == 0 and result.overwritten == 0
    assert len(result.skipped_existing) == 6
    assert target.backend.read("light.x") == original


def test_conflict_overwrite() -> None:
    target = ProfileStore(backend=MemoryBackend())
    target.set("light.x", profile("light.x", semantic_meaning="old"))
    archive = export_profiles(populated_store())
    result = import_profiles(target, archive, on_conflict="overwrite")
    assert result.overwritten == 1
    assert result.imported == 5
    reloaded = target.backend.read("light.x")
    assert reloaded is not None and "semantic_meaning" not in reloaded["semantic_profile"]


def test_conflict_error_is_all_or_nothing() -> None:
    target = ProfileStore(backend=MemoryBackend())
    target.set("light.x", profile("light.x"))
    archive = export_profiles(populated_store())
    with pytest.raises(MesaError):
        import_profiles(target, archive, on_conflict="error")
    # Nothing else was written before the conflict raised.
    assert target.backend.read("lock.front") is None
    assert target.backend.read("__deployment_defaults__") is None


def test_invalid_archive_and_policy_rejected() -> None:
    store = ProfileStore(backend=MemoryBackend())
    with pytest.raises(MesaValidationError):
        import_profiles(store, {})
    with pytest.raises(MesaValidationError):
        import_profiles(store, {"mesa_export": {"format_version": "9.9"}})
    with pytest.raises(ValueError):
        import_profiles(store, export_profiles(store), on_conflict="merge")


def test_non_object_archive_rejected() -> None:
    # A non-dict top-level archive must be a MesaValidationError, not a raw
    # AttributeError from reaching for .get on a list.
    store = ProfileStore(backend=MemoryBackend())
    with pytest.raises(MesaValidationError):
        import_profiles(store, [1, 2, 3])  # type: ignore[arg-type]


def test_wrong_typed_section_is_reported() -> None:
    # Falsy wrong-typed sections must be quarantined, not coerced to "no entities".
    store = ProfileStore(backend=MemoryBackend())
    for bad in ([], "", 0, False):
        archive: dict[str, Any] = {"mesa_export": {"format_version": "1.0", "entities": bad}}
        result = import_profiles(store, archive)
        assert not result.ok
        assert "entities" in result.invalid
    # A genuinely absent section is still fine.
    assert import_profiles(store, {"mesa_export": {"format_version": "1.0"}}).ok


def test_origin_survives_the_round_trip() -> None:
    source = populated_store()
    archive = export_profiles(source)
    target = ProfileStore(backend=MemoryBackend())
    import_profiles(target, archive)
    reloaded = target.get("light.x")
    assert reloaded is not None and reloaded.metadata.source.value == "developer"


def test_async_variants() -> None:
    async def run() -> None:
        source = populated_store()
        archive = await aexport_profiles(source)
        target = ProfileStore(backend=MemoryBackend())
        result = await aimport_profiles(target, archive)
        assert result.ok and result.imported == 6

    asyncio.run(run())
