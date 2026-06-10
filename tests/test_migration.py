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


def test_same_version_returns_equal_copy() -> None:
    migrated = migrate_profile(DOC)
    assert migrated == DOC
    assert migrated is not DOC
    assert migrated["semantic_profile"] is not DOC["semantic_profile"]


def test_missing_schema_version_is_stamped() -> None:
    doc = {"semantic_profile": {"operational_boundaries": {"control_mode": "confirm"}}}
    migrated = migrate_profile(doc)
    assert migrated["semantic_profile"]["schema_version"] == "1.0"
    assert "schema_version" not in doc["semantic_profile"]  # original untouched


def test_unknown_version_raises() -> None:
    doc = {"semantic_profile": {"schema_version": "2.0"}}
    with pytest.raises(MesaError):
        migrate_profile(doc)


def test_unparseable_version_raises() -> None:
    doc = {"semantic_profile": {"schema_version": "latest"}}
    with pytest.raises(MesaError):
        migrate_profile(doc)


def test_document_without_semantic_profile_raises() -> None:
    with pytest.raises(MesaError):
        migrate_profile({"privacy_classification": {"level": "normal"}})
