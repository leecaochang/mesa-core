"""migrate_profile: explicit schema version migration (Spec Section 23)."""

from __future__ import annotations

import pytest

from mesa_core.exceptions import MesaError
from mesa_core.migration import migrate_profile

DOC = {
    "semantic_profile": {
        "schema_version": "1.0",
        "operational_boundaries": {"control_mode": "confirm"},
    },
    "privacy_classification": {"level": "normal"},
}


def test_1_0_migrates_to_1_1(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="mesa_core.migration"):
        migrated = migrate_profile(DOC)
    assert migrated["semantic_profile"]["schema_version"] == "1.1"
    # The 1.1 format is additive: nothing but the version stamp changes.
    unstamped = {k: v for k, v in migrated["semantic_profile"].items() if k != "schema_version"}
    assert unstamped == {"operational_boundaries": {"control_mode": "confirm"}}
    assert DOC["semantic_profile"]["schema_version"] == "1.0"  # original untouched
    assert any("1.1" in record.message for record in caplog.records)


def test_same_version_returns_equal_copy() -> None:
    doc = {"semantic_profile": {"schema_version": "1.1"}}
    migrated = migrate_profile(doc)
    assert migrated == doc
    assert migrated is not doc
    assert migrated["semantic_profile"] is not doc["semantic_profile"]


def test_missing_schema_version_reads_as_1_0_and_migrates() -> None:
    # An unversioned document is 1.0-era; defaulting it to the current version
    # would silently skip the migration step.
    doc = {"semantic_profile": {"operational_boundaries": {"control_mode": "confirm"}}}
    migrated = migrate_profile(doc)
    assert migrated["semantic_profile"]["schema_version"] == "1.1"
    assert "schema_version" not in doc["semantic_profile"]  # original untouched


def test_missing_schema_version_with_1_0_target_is_stamped() -> None:
    doc = {"semantic_profile": {"operational_boundaries": {"control_mode": "confirm"}}}
    migrated = migrate_profile(doc, target_version="1.0")
    assert migrated["semantic_profile"]["schema_version"] == "1.0"


def test_downgrade_raises() -> None:
    doc = {"semantic_profile": {"schema_version": "1.1"}}
    with pytest.raises(MesaError):
        migrate_profile(doc, target_version="1.0")


def test_unknown_version_raises() -> None:
    for version in ("0.9", "1.2", "2.0"):
        doc = {"semantic_profile": {"schema_version": version}}
        with pytest.raises(MesaError):
            migrate_profile(doc)


def test_unparseable_version_raises() -> None:
    doc = {"semantic_profile": {"schema_version": "latest"}}
    with pytest.raises(MesaError):
        migrate_profile(doc)


def test_document_without_semantic_profile_raises() -> None:
    with pytest.raises(MesaError):
        migrate_profile({"privacy_classification": {"level": "normal"}})
