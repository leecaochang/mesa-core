# Changelog

All notable changes to mesa-core. The MESA specification documents carry their own version history.

## 1.2.0 - 2026-07-03

### Added

- **Portable profile export/import.** `export_profiles(store)` produces a single JSON archive of every stored profile document (entities, domain/integration/area scopes, deployment defaults); `import_profiles(store, archive, on_conflict=...)` restores it into any store with `skip`, `overwrite`, or all-or-nothing `error` conflict handling. Export is faithful (raw documents, nothing dropped); import validates every document and quarantines failures in `ImportResult.invalid`. Because the archive carries canonical profile JSON, it is storage-backend-agnostic: an export from one MESA-integrated host imports into any other, regardless of how either stores profiles internally. Async variants included.
- **Semantic moments (HA 2026.7+ purpose-specific triggers).** `mesa_get_profile` accepts `include_semantic_moments` and, when the host supplies the new `get_semantic_moments` callback, returns the purpose-specific triggers and conditions the entity participates in. Consumed live from HA at request time, never stored in profiles (so it cannot go stale), never consulted by enforcement, and documented as carrying no MESA authority beyond the integration that defined the moment.
- **`solar_angle` temporal conditions.** Evaluated through the new `get_solar_elevation(at)` host callback (in Home Assistant, the `sun.sun` entity's `elevation` attribute); mesa-core computes no astronomy. Each `solar_event` is an elevation-boundary crossing (`sunset` below 0 degrees, civil/nautical twilight at -6/-12), and `solar_offset_minutes` shifts the transition by sampling elevation in the past. Without the callback the condition stays fail-closed exactly as in 1.1, so existing profiles only gain evaluation, never lose protection. `MesaEnforcer` accepts and passes the callback through.
### Changed

- Specification 6.5 now states the `solar_angle` truth semantics explicitly (previously the fields were listed without defining when the condition is true).
- Documentation corrections: the version-scope ledger now says four inheritance levels (integration scope included), the Level 3 lease conformance row no longer defers to a future revision, profile editing UIs are documented as host-server territory rather than a MESA deliverable, and the architecture diagram is vendor-neutral.

### Related

- The `mesa-lint` CLI (0.1.0) shipped in this cycle as a separate package for CI validation of `mesa_profile.json` sidecars and profile stores.

## 1.1.0 - 2026-07-02

mesa-core 1.1 completes MESA Level 3: the advisory lease protocol and the standard audit event schema join the retrieval API, enforcement, and the confirmation protocol. It also closes every API gap reported by integrators since the 1.0.0 release.

### Added

- **Advisory lease protocol** (Enrichment Section 21). `LeaseManager` with request, early release, session release, and automatic (lazy) expiry; partial grants; the 30-second duration cap; `mesa_lease_expired` events through the `on_lease_event` callback; and `sensor_state()` for hosts exposing `binary_sensor.mesa_lease_active`. Lease requests for entities under `protected` or `critical` automation control are denied fail-closed. The `mesa_request_lease` and `mesa_release_lease` MCP tools register when `register_mesa_tools` receives a `lease_manager`. Scope is single-agent: overlapping requests resolve existing-holder-wins, and multi-agent priority preemption (Enrichment 21.6) is planned for v2.
- **Standard audit event schema.** Every record on the `mesa_core.audit` logger now carries a `mesa_audit_event` dict: `timestamp`, `caller_id`, `roles`, `entity_id`, `action`, `decision`, `profile_version`, `rule_applied`, `redaction_mode`, plus `event_type` and a `details` object. Emitted by `PrivacyEnforcer` (privacy access), `MesaEnforcer` (every blocked call at INFO; allowed calls at DEBUG), and `LeaseManager` (requests and lease endings). `MesaAuditEvent` and `emit_audit_event` are exported for hosts emitting their own events into the same stream.
- **Typed person traits.** `PersonTraits` (Enrichment Section 17) on `SemanticProfile`, resolved per-field under conflict Rule D. Fixes a privacy-enforcement gap: `is_minor: true` declared at domain or area scope now reaches enforcement instead of being read from the entity document only.
- **person_traits validation.** `household_role` is checked against the Section 17 enum and `is_minor` must be a boolean, in both the validator and the canonical JSON Schema.
- **Indirect automation references.** `TriggerValidator` and `entities_by_role` accept an `expand_target(kind, ref)` callback resolving `area_id`, `floor_id`, `label_id`, and `device_id` selectors to entity IDs, so stale `triggers_automations: none` declarations behind device triggers or the target blocks of purpose-specific triggers (Home Assistant 2026.7+) are caught. Without the callback, behaviour is unchanged.
- **ProfileStore async parity.** Async variants for domain-, integration-, and area-scope profile get/set, deployment defaults, and key enumeration, plus `explain()` and `aexplain()` delegating to the resolver. `TriggerValidator` gains `avalidate()` and `avalidate_entity()`. Async resolution goes through the store wrappers; `PrivacyEnforcer.evaluate()` stays synchronous-only as pure computation.

### Changed

- Enrichment Section 17: `household_role` relaxed from REQUIRED to RECOMMENDED, so the minimal safety-first declaration (`{"is_minor": true}`) is valid.
- Specification 5.5: hosts SHOULD expand target selectors to entities when cross-referencing automations, since raw configuration scanning sees only explicit `entity_id` references.
- Specification 7.1: the `mesa_audit_event` schema is the RECOMMENDED audit shape; the logging obligation itself remains format-flexible for third-party implementations.

### Compatibility notes

- Profiles with an invalid `household_role` or a non-boolean `is_minor` now fail validation at read; they were accepted by 1.0.0. Correctly declared profiles are unaffected. The non-boolean `is_minor` rejection is deliberate: such a value would otherwise silently disable the mandatory restricted behaviour.
- Audit log records replace the ad-hoc `mesa_*` extras of 1.0.0 (`mesa_decision`, `mesa_is_person`, and friends) with the single `mesa_audit_event` dict. Consumers parsing the old extras need a one-line change.
- `register_mesa_tools(lease_manager=...)` now registers the lease tools; in 1.0.0 the parameter was accepted and ignored with a warning.

## 1.0.0 - 2026-06-24

Initial release. Profile storage and inheritance (conflict Rules A through E), enforcement with the confirmation challenge/token protocol, temporal constraints, privacy enforcement with audit logging, the TriggerValidator, integration sidecar import, profile migration, and the four retrieval API MCP tools with FastMCP and raw MCP SDK adapters. Zero runtime dependencies.
