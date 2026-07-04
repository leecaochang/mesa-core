"""Profile store export and import (Module Proposal Section 4.12).

The archive is an envelope of canonical profile documents, the same JSON form
as ``mesa_profile.json``, the JSON Schema, and ``to_dict()``. That makes it
storage-backend-agnostic: any host that exposes its profiles through the
ProfileStore API can exchange archives with any other host, regardless of how
either stores profiles internally.

Export reads raw stored documents through the backend: full fidelity, no
validation, nothing silently dropped, so a backup is a backup. Import
validates every document and applies an explicit conflict policy, so a
corrupted or hostile archive cannot silently poison a store.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from mesa_core.exceptions import MesaError, MesaValidationError
from mesa_core.profile import SemanticProfile
from mesa_core.store import (
    _AREA_PREFIX,
    _DEPLOYMENT_DEFAULTS_KEY,
    _DOMAIN_PREFIX,
    _INTEGRATION_PREFIX,
    ProfileStore,
)

ARCHIVE_FORMAT_VERSION = "1.0"

# (archive section, reserved-key prefix) in export order. Entities use the
# bare key. Unknown future reserved keys are not exported.
_SECTIONS = (
    ("domains", _DOMAIN_PREFIX),
    ("integrations", _INTEGRATION_PREFIX),
    ("areas", _AREA_PREFIX),
)


@dataclass
class ImportResult:
    """Outcome of an import: what landed, what was held back, and why."""

    imported: int = 0
    overwritten: int = 0
    skipped_existing: list[str] = field(default_factory=list)
    invalid: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.invalid


def export_profiles(store: ProfileStore) -> dict[str, Any]:
    """Export every stored profile document into a portable archive dict.

    The caller serialises the result (``json.dumps``) wherever it wants: a
    download, a backup file, another deployment.
    """
    from mesa_core import __version__

    entities: dict[str, Any] = {}
    scoped: dict[str, dict[str, Any]] = {section: {} for section, _ in _SECTIONS}
    defaults: dict[str, Any] | None = None
    for key in store.backend.list_keys():
        doc = store.backend.read(key)
        if doc is None:
            continue
        if key == _DEPLOYMENT_DEFAULTS_KEY:
            defaults = doc
            continue
        for section, prefix in _SECTIONS:
            if key.startswith(prefix):
                scoped[section][key[len(prefix) :]] = doc
                break
        else:
            if not key.startswith("__"):
                entities[key] = doc

    archive: dict[str, Any] = {
        "format_version": ARCHIVE_FORMAT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "mesa_core_version": __version__,
        "entities": entities,
        **scoped,
    }
    if defaults is not None:
        archive["deployment_defaults"] = defaults
    return {"mesa_export": archive}


def import_profiles(
    store: ProfileStore,
    archive: dict[str, Any],
    *,
    on_conflict: str = "skip",
) -> ImportResult:
    """Import an archive produced by :func:`export_profiles`.

    ``on_conflict`` decides what happens when a key already exists in the
    target store: ``"skip"`` (default) leaves the existing profile, or
    ``"overwrite"`` replaces it; ``"error"`` raises MesaError on first
    conflict, before anything else is written. Documents that fail validation
    are reported in ``ImportResult.invalid`` and never written.
    """
    if on_conflict not in ("skip", "overwrite", "error"):
        raise ValueError(f"invalid on_conflict: {on_conflict!r}")
    inner = archive.get("mesa_export")
    if not isinstance(inner, dict):
        raise MesaValidationError("not a mesa_export archive (missing 'mesa_export' root)")
    fmt = inner.get("format_version")
    if fmt != ARCHIVE_FORMAT_VERSION:
        raise MesaValidationError(f"unsupported archive format_version: {fmt!r}")

    result = ImportResult()
    sections: list[tuple[str, str, Any]] = [("entities", "", store.set)]
    sections += [
        ("domains", _DOMAIN_PREFIX, store.set_domain_profile),
        ("integrations", _INTEGRATION_PREFIX, store.set_integration_profile),
        ("areas", _AREA_PREFIX, store.set_area_profile),
    ]

    # Conflict scan first, so on_conflict="error" is all-or-nothing.
    if on_conflict == "error":
        for section, prefix, _setter in sections:
            for key in inner.get(section) or {}:
                if store.backend.read(f"{prefix}{key}") is not None:
                    raise MesaError(f"import conflict: {section} key {key!r} already exists")
        if "deployment_defaults" in inner and store.backend.read(
            _DEPLOYMENT_DEFAULTS_KEY
        ) is not None:
            raise MesaError("import conflict: deployment_defaults already exist")

    for section, prefix, setter in sections:
        docs = inner.get(section) or {}
        for key, doc in docs.items():
            label = f"{section}:{key}"
            try:
                profile = SemanticProfile.from_dict(key, doc)
            except MesaValidationError as err:
                result.invalid[label] = str(err)
                continue
            exists = store.backend.read(f"{prefix}{key}") is not None
            if exists and on_conflict == "skip":
                result.skipped_existing.append(label)
                continue
            setter(key, profile)
            if exists:
                result.overwritten += 1
            else:
                result.imported += 1

    defaults = inner.get("deployment_defaults")
    if isinstance(defaults, dict):
        exists = store.backend.read(_DEPLOYMENT_DEFAULTS_KEY) is not None
        if exists and on_conflict == "skip":
            result.skipped_existing.append("deployment_defaults")
        else:
            try:
                store.set_deployment_defaults(defaults)
            except (ValueError, TypeError) as err:
                result.invalid["deployment_defaults"] = str(err)
            else:
                if exists:
                    result.overwritten += 1
                else:
                    result.imported += 1

    return result


async def aexport_profiles(store: ProfileStore) -> dict[str, Any]:
    return await asyncio.to_thread(export_profiles, store)


async def aimport_profiles(
    store: ProfileStore, archive: dict[str, Any], *, on_conflict: str = "skip"
) -> ImportResult:
    return await asyncio.to_thread(
        lambda: import_profiles(store, archive, on_conflict=on_conflict)
    )
