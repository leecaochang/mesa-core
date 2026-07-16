"""The hand-rolled validator and the canonical JSON Schema must agree.

mesa_core/schemas/mesa_profile.schema.json is the machine-readable artifact third
parties consume; mesa_core/validation.py is the zero-dependency implementation.
Hard-rejection parity is asserted across every fixture: a document is schema-invalid
iff validate_document reports errors. (Warnings are validator-only by design.)
"""

from __future__ import annotations

import contextlib
import copy
import json
import random
from pathlib import Path
from typing import Any

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


@pytest.mark.parametrize("path", VALID_FIXTURES, ids=lambda p: p.name)
def test_bare_form_body_agrees_with_the_schema(path: Path) -> None:
    """Parsers accept a bare semantic_profile body, so the schema must judge one.

    Without this the schema matches nothing at the root of a bare document and
    passes it vacuously, so a third party validating with the canonical artifact
    would accept what mesa-core rejects.
    """
    data = json.loads(path.read_text())
    bare = data.get("semantic_profile")
    if not isinstance(bare, dict):
        pytest.skip(f"{path.name} has no semantic_profile body")
    assert validate_document(bare).ok
    assert _schema_valid(bare)


@pytest.mark.parametrize(
    "bare",
    [
        pytest.param({"operational_boundaries": {"control_mode": "bogus"}}, id="invalid_enum"),
        pytest.param({"metadata_origin": {"source": "nonsense"}}, id="invalid_origin"),
        pytest.param({"operational_boundaries": {"reversible": "false"}}, id="wrong_type"),
        pytest.param(
            {"metadata_origin": {"source": "inferred_ai"}}, id="inferred_missing_fields"
        ),
    ],
)
def test_malformed_bare_form_body_rejected_by_both(bare: dict) -> None:
    assert not validate_document(bare).ok
    assert not _schema_valid(bare)


# ---------------------------------------------------------------------------
# Committed differential property test.
#
# The validator and schema must agree on EVERY document, not only the fixtures.
# A prior session asserted this over a throwaway fuzzer that missed classes a
# later audit found: the validator never type-checked profile_valid_for or
# diagnostic_profile, the schema validated the nested privacy_classification
# location even when a canonical sibling made mesa-core's parser ignore it, and
# both accepted time_range bounds in any string shape. The search below is
# regenerated deterministically (fixed seed) so the agreement is reproducible
# from the repo rather than resting on a discarded run.
# ---------------------------------------------------------------------------

_RICH_ROOT: dict[str, Any] = {
    "semantic_profile": {
        "schema_version": "1.0",
        "profile_version": "3",
        "metadata_origin": {
            "source": "hybrid",
            "confidence": 0.8,
            "generated_at": "2026-06-01T12:00:00+00:00",
            "staleness_window_days": 45,
            "confirmed_fields": ["operational_boundaries.control_mode"],
        },
        "semantic_tags": ["lighting.ambient", "vendorx.custom"],
        "last_updated": "2026-01-01",
        "inheritance_scope": "domain",
        "profile_valid_for": {"conditions": []},
        "operational_boundaries": {
            "control_mode": "confirm",
            "triggers_automations": "unknown",
            "reversible": True,
            "reversibility_cost": "moderate",
            "reversibility_window_seconds": 30,
            "idempotent": True,
            "state_persistence": "session",
            "expected_latency_ms": 100,
            "side_effect_scope": "room_localized",
            "state_volatility": "low",
            "enforcement_mode": "enforced",
            "control_reason": "reason",
            "declared_limits": [
                {
                    "id": "lim1",
                    "predicate": {"entity": "sensor.x", "operator": "eq", "value": "on"},
                    "limit": {
                        "service": "light.turn_on",
                        "parameter": "brightness",
                        "max_value": 200,
                        "min_value": 10,
                        "permitted_values": [1, 2],
                    },
                    "human_reason": "dim",
                }
            ],
            "temporal_constraints": [
                {
                    "id": "tc1",
                    "condition": {
                        "type": "time_range",
                        "start_time": "23:00",
                        "end_time": "06:00",
                        "negate": False,
                    },
                    "effect": {"control_mode": "prohibited"},
                    "human_reason": "night",
                }
            ],
        },
        "person_traits": {
            "household_role": "primary_resident",
            "display_name": "Name",
            "is_minor": False,
            "associated_zones": ["zone.home"],
            "associated_automations": ["automation.x"],
            "presence_entity": "person.me",
        },
    },
    "privacy_classification": {
        "level": "sensitive",
        "deny_response_mode": "redact",
        "access_roles": {"unrestricted_for": ["a"], "deny_for": ["b"]},
        "contains_presence_data": True,
        "data_retention_local": True,
        "access_logging_recommended": True,
        "privacy_note": "note",
    },
    "diagnostic_profile": {"detail": "x"},
}


def _nested_only(root: dict[str, Any]) -> dict[str, Any]:
    """Root form with no sibling privacy_classification, only a nested copy."""
    doc = copy.deepcopy(root)
    doc["semantic_profile"]["privacy_classification"] = doc.pop("privacy_classification")
    return doc


def _mutation_bases() -> list[dict[str, Any]]:
    bases = [copy.deepcopy(_RICH_ROOT), _nested_only(_RICH_ROOT)]
    bases += [json.loads(p.read_text()) for p in VALID_FIXTURES]
    return bases


_MUTATION_VALUES: list[Any] = [
    None, "x", "25:99", "noon", "12:00:00", "9:00", "24:00", 7, 0, -3, 3.14,
    True, False, [], ["a", "b"], ["a", 1], {}, {"k": "v"}, [["x"]], "bogus_enum",
]
_DELETE = object()


def _all_paths(obj: Any, prefix: tuple = ()) -> list[tuple]:
    """Every path into obj (dict keys and list indices), intermediate nodes included."""
    out: list[tuple] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            p = (*prefix, key)
            out.append(p)
            out.extend(_all_paths(value, p))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            p = (*prefix, i)
            out.append(p)
            out.extend(_all_paths(value, p))
    return out


def _apply(doc: Any, path: tuple, value: Any) -> None:
    cur = doc
    for key in path[:-1]:
        cur = cur[key]
    if value is _DELETE:
        del cur[path[-1]]
    else:
        cur[path[-1]] = value


def test_mutation_fuzz_validator_and_schema_agree() -> None:
    """Deterministically mutate rich base documents (delete / null / retype /
    enum-corrupt / bad time strings, one or two edits at a time) and assert the
    validator and schema reach the same verdict on each."""
    rng = random.Random(1234)
    checked = 0
    for base in _mutation_bases():
        paths = _all_paths(base)
        if not paths:
            continue
        for _ in range(220):
            doc = copy.deepcopy(base)
            for _ in range(rng.choice((1, 1, 2))):
                path = rng.choice(paths)
                value = rng.choice([*_MUTATION_VALUES, _DELETE])
                # A prior mutation may have removed or retyped this path; skip it.
                with contextlib.suppress(KeyError, IndexError, TypeError):
                    _apply(doc, path, value)
            checked += 1
            assert validate_document(doc).ok == _schema_valid(doc), (
                "validator/schema divergence on mutated document: "
                + json.dumps(doc, default=str)
            )
    # Guaranteed by the two rich bases alone (2 x 220), independent of how many
    # valid fixtures happen to be on disk.
    assert checked >= 400


# Explicit regression cases: each fixed divergence class, with the acceptance
# both validators must reach. These pin the intent even if the fuzz distribution
# shifts. _GOOD_PC / _BAD_PC are a well-formed and an enum-invalid privacy body.
_GOOD_PC: dict[str, Any] = {"level": "normal"}
_BAD_PC: dict[str, Any] = {"level": "bogus_level"}


def _with_sp(key: str, value: Any) -> dict[str, Any]:
    doc = copy.deepcopy(_RICH_ROOT)
    doc["semantic_profile"][key] = value
    return doc


def _with_root(key: str, value: Any) -> dict[str, Any]:
    doc = copy.deepcopy(_RICH_ROOT)
    doc[key] = value
    return doc


def _with_time_range(start: Any, end: Any) -> dict[str, Any]:
    doc = copy.deepcopy(_RICH_ROOT)
    cond = doc["semantic_profile"]["operational_boundaries"]["temporal_constraints"][0][
        "condition"
    ]
    cond["start_time"] = start
    cond["end_time"] = end
    return doc


def _privacy(sibling: Any, nested: Any, *, has_sibling: bool) -> dict[str, Any]:
    doc = copy.deepcopy(_RICH_ROOT)
    doc["semantic_profile"]["privacy_classification"] = nested
    if has_sibling:
        doc["privacy_classification"] = sibling
    else:
        doc.pop("privacy_classification", None)
    return doc


_REGRESSION_CASES: list[tuple[str, dict[str, Any], bool]] = [
    # Fix 1: profile_valid_for must be an object.
    ("profile_valid_for_object", _with_sp("profile_valid_for", {"after": "2026"}), True),
    ("profile_valid_for_string", _with_sp("profile_valid_for", "2026-12-31"), False),
    ("profile_valid_for_null", _with_sp("profile_valid_for", None), False),
    ("profile_valid_for_list", _with_sp("profile_valid_for", []), False),
    # Fix 2: diagnostic_profile must be an object.
    ("diagnostic_profile_object", _with_root("diagnostic_profile", {"d": 1}), True),
    ("diagnostic_profile_string", _with_root("diagnostic_profile", "d"), False),
    ("diagnostic_profile_list", _with_root("diagnostic_profile", [1]), False),
    ("diagnostic_profile_null", _with_root("diagnostic_profile", None), False),
    # Fix 4: time_range bounds are 24-hour HH:MM.
    ("time_range_valid", _with_time_range("23:00", "06:00"), True),
    ("time_range_seconds", _with_time_range("12:00:00", "06:00"), False),
    ("time_range_out_of_range", _with_time_range("25:99", "06:00"), False),
    ("time_range_word", _with_time_range("noon", "06:00"), False),
    ("time_range_no_leading_zero", _with_time_range("9:00", "06:00"), False),
    ("time_range_hour_24", _with_time_range("24:00", "06:00"), False),
    ("time_range_end_bad", _with_time_range("06:00", "23:60"), False),
    # Fix 3: nested privacy_classification resolves the way the parser does.
    ("sibling_valid_nested_malformed", _privacy(_GOOD_PC, _BAD_PC, has_sibling=True), True),
    ("sibling_valid_nested_nonobject", _privacy(_GOOD_PC, "x", has_sibling=True), True),
    ("no_sibling_nested_valid", _privacy(None, _GOOD_PC, has_sibling=False), True),
    ("no_sibling_nested_malformed", _privacy(None, _BAD_PC, has_sibling=False), False),
    ("no_sibling_nested_nonobject", _privacy(None, "x", has_sibling=False), False),
    ("no_sibling_nested_null", _privacy(None, None, has_sibling=False), True),
    ("sibling_null_nested_valid", _privacy(None, _GOOD_PC, has_sibling=True), False),
]


@pytest.mark.parametrize(
    "doc,expected_ok",
    [pytest.param(d, e, id=i) for i, d, e in _REGRESSION_CASES],
)
def test_specific_agreement_regressions(doc: dict, expected_ok: bool) -> None:
    assert validate_document(doc).ok == expected_ok
    assert _schema_valid(doc) == expected_ok
