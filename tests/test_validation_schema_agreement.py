"""The hand-rolled validator and the canonical JSON Schema must agree.

mesa_core/schemas/mesa_profile.schema.json is the machine-readable artifact third
parties consume; mesa_core/validation.py is the zero-dependency implementation.
Hard-rejection parity is asserted across every fixture: a document is schema-invalid
iff validate_document reports errors. (Warnings are validator-only by design.)
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from mesa_core import validate_document

ROOT = Path(__file__).parent
SCHEMA = json.loads(
    (ROOT.parent / "mesa_core" / "schemas" / "mesa_profile.schema.json").read_text()
)

VALID_FIXTURES = sorted((ROOT / "fixtures" / "profiles").glob("*.json"))
MALFORMED_FIXTURES = sorted((ROOT / "conformance" / "malformed").glob("*.json"))
# trust_laundering is warning-only by design: valid under both validators.
HARD_REJECTED = [p for p in MALFORMED_FIXTURES if p.name != "trust_laundering.json"]


def _schema_valid(data: dict) -> bool:
    validator = jsonschema.Draft202012Validator(SCHEMA)
    return not list(validator.iter_errors(data))


@pytest.mark.parametrize("path", VALID_FIXTURES, ids=lambda p: p.name)
def test_valid_fixture_accepted_by_both(path: Path) -> None:
    data = json.loads(path.read_text())
    assert validate_document(data).ok, f"validator rejected valid fixture {path.name}"
    assert _schema_valid(data), f"schema rejected valid fixture {path.name}"


@pytest.mark.parametrize("path", HARD_REJECTED, ids=lambda p: p.name)
def test_malformed_fixture_rejected_by_both(path: Path) -> None:
    data = json.loads(path.read_text())
    assert not validate_document(data).ok, f"validator accepted malformed {path.name}"
    assert not _schema_valid(data), f"schema accepted malformed {path.name}"


def test_trust_laundering_valid_under_both_with_warning() -> None:
    data = json.loads((ROOT / "conformance" / "malformed" / "trust_laundering.json").read_text())
    report = validate_document(data)
    assert report.ok and report.warnings
    assert _schema_valid(data)
