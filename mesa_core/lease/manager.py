"""LeaseManager: advisory coordination leases (Enrichment Section 21).

The lease protocol is an advisory signal between MESA-aware components, not a
concurrency lock (Section 21.1). mesa-core owns no event loop, so automatic
expiry is lazy: every operation ignores and sweeps expired leases, and hosts
SHOULD call ``expire()`` periodically for timely ``mesa_lease_expired``
events. Events are delivered through the ``on_lease_event`` callback with the
Section 21.4 payload (``lease_id``, ``entities``, ``reason``, ``timestamp``);
the host bridges them onto the HA event bus.

Multi-agent priority preemption (Section 21.6) ships in v2. For overlapping
requests the existing holder takes precedence, which is 21.6 Rule 3, the
no-priority baseline; ``caller_priority`` is accepted but unused.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from mesa_core.exceptions import LeaseNotFoundError, MesaValidationError
from mesa_core.lease.registry import Lease, LeaseRegistry
from mesa_core.store import ProfileStore

audit_logger = logging.getLogger("mesa_core.audit")

MAX_LEASE_DURATION_SECONDS = 30.0

_PRIORITY_LEVELS = ("deferential", "cooperative", "assertive")
_PREEMPTION_HANDLING = ("rollback_abort", "continue_ignore")
# Automation cooperative_priority levels that deny leases (Spec 21.5).
_DENYING_LEVELS = ("protected", "critical")
_CONFLICT_LEVELS = ("cooperative", "assertive")


@dataclass
class LeaseResponse:
    """The Section 21.3 lease response. ``lease_id`` and ``expires_at`` are
    always present, even for full denials (the lease is simply never
    registered)."""

    lease_id: str
    granted: bool
    entities_granted: list[str]
    entities_denied: list[str]
    expires_at: str
    granted_duration_seconds: float
    denial_reasons: dict[str, str] = field(default_factory=dict)
    active_conflicts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Entities denied because of protected/critical automations, so the tool
    # layer can distinguish the lease_conflict envelope (Spec 9.6) from a
    # plain existing-holder denial.
    automation_denials: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "lease_id": self.lease_id,
            "granted": self.granted,
            "entities_granted": list(self.entities_granted),
            "entities_denied": list(self.entities_denied),
            "expires_at": self.expires_at,
            "granted_duration_seconds": self.granted_duration_seconds,
        }
        if self.denial_reasons:
            out["denial_reasons"] = dict(self.denial_reasons)
        if self.active_conflicts:
            out["active_conflicts"] = list(self.active_conflicts)
        if self.warnings:
            out["warnings"] = list(self.warnings)
        return out


class LeaseManager:
    """Grant, track, and expire advisory coordination leases."""

    def __init__(
        self,
        store: ProfileStore | None = None,
        *,
        get_state: Callable[[str], str | None] | None = None,
        on_lease_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """``store`` supplies automation profiles for the protected/critical
        denial check (Spec 21.5); without it no automation profiles exist to
        check. ``get_state`` reports automation entity state for the
        protected "while active" test; absent, protected automations are
        treated as active (fail-closed). ``on_lease_event`` receives the
        ``mesa_lease_expired`` payload for every ended lease.
        """
        self.store = store
        self.get_state = get_state
        self.on_lease_event = on_lease_event
        self._registry = LeaseRegistry()

    # -- events ------------------------------------------------------------------

    def _emit(self, lease: Lease, reason: str, now: datetime) -> None:
        audit_logger.info(
            "mesa lease ended: lease=%s reason=%s entities=%s",
            lease.lease_id,
            reason,
            lease.entities,
            extra={
                "mesa_lease_id": lease.lease_id,
                "mesa_caller_id": lease.caller_id,
                "mesa_entities": list(lease.entities),
                "mesa_decision": reason,
            },
        )
        if self.on_lease_event is not None:
            self.on_lease_event(
                {
                    "event_type": "mesa_lease_expired",
                    "lease_id": lease.lease_id,
                    "entities": list(lease.entities),
                    "reason": reason,
                    "timestamp": now.isoformat(),
                }
            )

    def _sweep(self, now: datetime) -> None:
        for lease in self._registry.sweep_expired(now):
            self._emit(lease, "natural_expiry", now)

    # -- automation interaction (Spec 21.5) ----------------------------------------

    def _automation_active(self, automation_id: str, warnings: list[str]) -> bool:
        if self.get_state is None:
            warnings.append(
                f"protected automation {automation_id}: no get_state callback; "
                "treated as active (fail-closed)"
            )
            return True
        state = self.get_state(automation_id)
        if state is None or state in ("unavailable", "unknown"):
            warnings.append(
                f"protected automation {automation_id}: state unavailable; "
                "treated as active (fail-closed)"
            )
            return True
        return state == "on"

    def _automation_conflicts(
        self, requested: set[str], warnings: list[str]
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        """Denials and advisory conflicts from stored automation profiles.

        Reads the unmodeled Section 11 fields from ``raw``: monitored entities
        are trigger + condition entities (11.3); for ``critical`` the scope
        additionally includes ``intent_archetype.affected_entities``, since
        21.5 denies for "entities in this automation's scope".
        """
        denials: dict[str, str] = {}
        conflicts: list[dict[str, Any]] = []
        if self.store is None:
            return denials, conflicts
        for key in self.store.entity_keys():
            if not key.startswith("automation."):
                continue
            try:
                profile = self.store.get(key)
            except MesaValidationError as err:
                warnings.append(f"skipped malformed automation profile {key}: {err}")
                continue
            if profile is None:
                continue
            sp = profile.raw.get("semantic_profile", {})
            level = (sp.get("cooperative_priority") or {}).get("level")
            if level not in _DENYING_LEVELS and level not in _CONFLICT_LEVELS:
                continue
            env = sp.get("environmental_dependencies") or {}
            monitored = set(env.get("trigger_entities") or [])
            monitored |= set(env.get("condition_entities") or [])
            scope = set(monitored)
            if level == "critical":
                scope |= set((sp.get("intent_archetype") or {}).get("affected_entities") or [])
            overlap = requested & (scope if level == "critical" else monitored)
            if not overlap:
                continue
            if level == "critical":
                for entity in overlap:
                    denials.setdefault(
                        entity, f"entity is in the scope of critical automation {key} (Spec 21.5)"
                    )
            elif level == "protected":
                if self._automation_active(key, warnings):
                    for entity in overlap:
                        denials.setdefault(
                            entity,
                            f"entity is monitored by active protected automation {key} "
                            "(Spec 21.5)",
                        )
            else:
                conflicts.append(
                    {"automation_id": key, "level": level, "entities": sorted(overlap)}
                )
                if level == "assertive":
                    warnings.append(
                        f"assertive automation {key} may counteract actions on "
                        f"{sorted(overlap)} (Spec 21.5)"
                    )
        return denials, conflicts

    # -- lifecycle (Spec 21.4) ------------------------------------------------------

    def request(
        self,
        entities: list[str],
        duration_seconds: float,
        *,
        session_id: str,
        caller_id: str = "unknown",
        intent: str | None = None,
        priority_level: str = "cooperative",
        preemption_handling: str = "rollback_abort",
        caller_priority: float | None = None,
        now: datetime | None = None,
    ) -> LeaseResponse:
        now = now or datetime.now()
        self._sweep(now)
        if not entities:
            raise ValueError("entities must be a non-empty list")
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if priority_level not in _PRIORITY_LEVELS:
            raise ValueError(f"invalid priority_level: {priority_level!r}")
        if preemption_handling not in _PREEMPTION_HANDLING:
            raise ValueError(f"invalid preemption_handling: {preemption_handling!r}")

        warnings: list[str] = []
        granted_duration = min(duration_seconds, MAX_LEASE_DURATION_SECONDS)
        if granted_duration < duration_seconds:
            warnings.append(
                f"duration_seconds clamped to the {MAX_LEASE_DURATION_SECONDS:.0f}s "
                "maximum (Spec 21.2)"
            )
        if caller_priority is not None:
            warnings.append(
                "caller_priority is accepted but unused: multi-agent priority "
                "preemption (Spec 21.6) ships in a future version; existing "
                "holders take precedence"
            )

        denial_reasons, active_conflicts = self._automation_conflicts(set(entities), warnings)
        automation_denials = sorted(denial_reasons)

        # Existing holder takes precedence (21.6 Rule 3 baseline). Same-session
        # overlap is a refresh and is granted.
        for entity in entities:
            if entity in denial_reasons:
                continue
            holder = self._registry.holding(entity, now)
            if holder is not None and holder.session_id != session_id:
                denial_reasons[entity] = (
                    "entity is under an active lease held by another session"
                )

        entities_granted = [e for e in entities if e not in denial_reasons]
        entities_denied = [e for e in entities if e in denial_reasons]
        lease_id = uuid.uuid4().hex
        expires_at = now + timedelta(seconds=granted_duration)

        if entities_granted:
            self._registry.add(
                Lease(
                    lease_id=lease_id,
                    session_id=session_id,
                    caller_id=caller_id,
                    entities=list(entities_granted),
                    granted_at=now,
                    expires_at=expires_at,
                    intent=intent,
                    priority_level=priority_level,
                    preemption_handling=preemption_handling,
                )
            )
        audit_logger.info(
            "mesa lease request: lease=%s caller=%s granted=%s denied=%s",
            lease_id,
            caller_id,
            entities_granted,
            entities_denied,
            extra={
                "mesa_lease_id": lease_id,
                "mesa_caller_id": caller_id,
                "mesa_entities": list(entities),
                "mesa_decision": "granted" if entities_granted else "denied",
                "mesa_intent": intent,
            },
        )
        return LeaseResponse(
            lease_id=lease_id,
            granted=bool(entities_granted),
            entities_granted=entities_granted,
            entities_denied=entities_denied,
            expires_at=expires_at.isoformat(),
            granted_duration_seconds=granted_duration,
            denial_reasons=denial_reasons,
            active_conflicts=active_conflicts,
            warnings=warnings,
            automation_denials=automation_denials,
        )

    def release(
        self, lease_id: str, *, session_id: str | None = None, now: datetime | None = None
    ) -> Lease:
        """Release a lease early. ``session_id``, when provided, must match the
        holder's; a mismatch reads as not-found so other sessions' leases are
        never disclosed (Spec 21.6)."""
        now = now or datetime.now()
        self._sweep(now)
        lease = self._registry.get(lease_id)
        if lease is None or (session_id is not None and lease.session_id != session_id):
            raise LeaseNotFoundError(f"lease {lease_id!r} does not exist or has expired")
        self._registry.remove(lease_id)
        self._emit(lease, "early_release", now)
        return lease

    def release_session(self, session_id: str, *, now: datetime | None = None) -> int:
        """Release all leases of a terminated session (Spec 21.4). Returns count."""
        now = now or datetime.now()
        self._sweep(now)
        leases = self._registry.by_session(session_id)
        for lease in leases:
            self._registry.remove(lease.lease_id)
            self._emit(lease, "session_terminated", now)
        return len(leases)

    def expire(self, now: datetime | None = None) -> None:
        """Sweep expired leases, emitting their events. Hosts SHOULD call this
        periodically for timely events; correctness does not depend on it."""
        self._sweep(now or datetime.now())

    def active_leases(self, now: datetime | None = None) -> list[Lease]:
        return self._registry.active(now or datetime.now())

    def sensor_state(self, now: datetime | None = None) -> dict[str, Any]:
        """The ``binary_sensor.mesa_lease_active`` state and attributes
        (Spec 21.4), for hosts that expose the sensor natively."""
        now = now or datetime.now()
        self._sweep(now)
        active = self._registry.active(now)
        leased: set[str] = set()
        for lease in active:
            leased.update(lease.entities)
        earliest = min((lease.expires_at for lease in active), default=None)
        return {
            "state": "on" if active else "off",
            "active_lease_count": len(active),
            "leased_entities": sorted(leased),
            "earliest_expiry": earliest.isoformat() if earliest else None,
            "last_lease_holder": self._registry.last_lease_holder,
        }

    # -- async variants ---------------------------------------------------------------

    async def arequest(
        self, entities: list[str], duration_seconds: float, **kwargs: Any
    ) -> LeaseResponse:
        return await asyncio.to_thread(
            lambda: self.request(entities, duration_seconds, **kwargs)
        )

    async def arelease(self, lease_id: str, **kwargs: Any) -> Lease:
        return await asyncio.to_thread(lambda: self.release(lease_id, **kwargs))

    async def arelease_session(self, session_id: str, **kwargs: Any) -> int:
        return await asyncio.to_thread(lambda: self.release_session(session_id, **kwargs))

    async def aexpire(self, now: datetime | None = None) -> None:
        await asyncio.to_thread(self.expire, now)
