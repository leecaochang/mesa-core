"""import_from_integration: sidecar developer profiles (Spec Sections 5.3, 8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mesa_core import MesaValidationError, MetadataOrigin
from mesa_core.backends import MemoryBackend
from mesa_core.integration_import import import_from_integration
from mesa_core.profile import ControlMode
from mesa_core.store import ProfileStore

SIDECAR = {
    "semantic_profile": {
        "schema_version": "1.0",
        "semantic_tags": ["lighting.colour"],
        "operational_boundaries": {
            "control_mode": "autonomous",
            "triggers_automations": "none",
            "reversible": True,
            "side_effect_scope": "entity_only",
        },
    },
    "privacy_classification": {"level": "normal"},
}


def write_integration(tmp_path: Path, domain: str, doc: dict) -> Path:
    integration = tmp_path / domain
    integration.mkdir()
    (integration / "manifest.json").write_text(json.dumps({"domain": domain}))
    (integration / "mesa_profile.json").write_text(json.dumps(doc))
    return integration


def test_sidecar_defaults_to_developer_origin(tmp_path: Path) -> None:
    path = write_integration(tmp_path, "my_lights", SIDECAR)
    profile = import_from_integration(path)
    assert profile is not None
    assert profile.entity_id == "my_lights"
    assert profile.metadata.source == MetadataOrigin.DEVELOPER
    assert profile.inheritance_scope == "domain"


def test_explicit_origin_in_sidecar_wins(tmp_path: Path) -> None:
    doc = json.loads(json.dumps(SIDECAR))
    doc["semantic_profile"]["metadata_origin"] = {
        "source": "hybrid",
        "confidence": 1.0,
        "confirmed_fields": ["operational_boundaries.control_mode"],
    }
    profile = import_from_integration(write_integration(tmp_path, "my_lights", doc))
    assert profile is not None
    assert profile.metadata.source == MetadataOrigin.HYBRID


def test_missing_sidecar_returns_none(tmp_path: Path) -> None:
    integration = tmp_path / "bare"
    integration.mkdir()
    assert import_from_integration(integration) is None


def test_malformed_sidecar_raises(tmp_path: Path) -> None:
    doc = json.loads(json.dumps(SIDECAR))
    doc["semantic_profile"]["operational_boundaries"]["control_mode"] = "yolo"
    path = write_integration(tmp_path, "broken", doc)
    with pytest.raises(MesaValidationError):
        import_from_integration(path)


def test_imported_profile_feeds_domain_inheritance(tmp_path: Path) -> None:
    path = write_integration(tmp_path, "light", SIDECAR)
    profile = import_from_integration(path)
    assert profile is not None
    store = ProfileStore(backend=MemoryBackend())
    store.set_domain_profile(profile.entity_id, profile)
    effective = store.get_effective("light.from_this_integration")
    # Developer-declared autonomous flows through domain inheritance.
    assert effective.operational_boundaries.control_mode == ControlMode.AUTONOMOUS
