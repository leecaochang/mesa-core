"""Every profile-shaped example in the documents must validate.

An invalid example is a defect: readers copy examples verbatim, and an example
the validator rejects teaches a value that cannot be stored. This sweeps the
fenced JSON and YAML blocks in documents/ and runs each profile-shaped one
through the same validator mesa-core applies on write.

The audit that prompted this found a camera example declaring
``deny_response_mode: silent``, which is not one of the three valid values. The
JSON examples were being checked by hand; the YAML ones were not checked at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from mesa_core.validation import validate_document

yaml = pytest.importorskip("yaml")

DOCUMENTS = sorted((Path(__file__).parent.parent / "documents").glob("*.md"))

# Fenced blocks, capturing the language tag and the body.
_FENCE = re.compile(r"^```(json|yaml|yml)\n(.*?)^```", re.MULTILINE | re.DOTALL)

# A block is profile-shaped when it carries one of the root keys the validator
# judges. Blocks illustrating other things (tool payloads, query requests,
# archive envelopes, deployment_defaults) are parsed but not validated.
_PROFILE_KEYS = ("semantic_profile", "privacy_classification", "diagnostic_profile")


def _blocks() -> list[tuple[str, int, str, Any]]:
    """(document, block number, language, parsed body) for every fenced block."""
    found: list[tuple[str, int, str, Any]] = []
    for path in DOCUMENTS:
        text = path.read_text()
        for index, match in enumerate(_FENCE.finditer(text), start=1):
            language, body = match.group(1), match.group(2)
            # Illustrative fragments use ... placeholders and elisions that no
            # parser accepts; they are not copy-paste examples.
            if "..." in body:
                continue
            try:
                parsed = json.loads(body) if language == "json" else yaml.safe_load(body)
            except (json.JSONDecodeError, yaml.YAMLError) as err:
                pytest.fail(f"{path.name} block {index} ({language}) does not parse: {err}")
            found.append((path.name, index, language, parsed))
    return found


ALL_BLOCKS = _blocks()
PROFILE_BLOCKS = [
    pytest.param(doc, index, parsed, id=f"{doc}-block{index}")
    for doc, index, _lang, parsed in ALL_BLOCKS
    if isinstance(parsed, dict) and any(key in parsed for key in _PROFILE_KEYS)
]


def test_documents_contain_parseable_examples() -> None:
    # Guards the sweep itself: a refactor that stopped finding blocks would
    # otherwise make every test below vacuously pass.
    assert len(ALL_BLOCKS) > 20
    assert len(PROFILE_BLOCKS) > 10


@pytest.mark.parametrize("document,index,parsed", PROFILE_BLOCKS)
def test_documented_profile_examples_validate(
    document: str, index: int, parsed: dict[str, Any]
) -> None:
    report = validate_document(parsed)
    assert report.ok, f"{document} block {index} is invalid: {'; '.join(report.errors)}"
