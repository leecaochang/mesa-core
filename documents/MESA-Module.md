# mesa-core: MESA Reference Module Proposal
**Version:** 1.1
**Describes:** MESA 1.1, mesa-core 1.3.x
**Document Type:** Technical Implementation Specification
**Companion Documents:**
- MESA Overview
- MESA Specification (Core)
- MESA Enrichment
- MESA Getting Started Guide

---

## Abstract

mesa-core is a standalone Python package that implements the MESA (Metadata and Environment Semantics for Agents) specification. Any MCP server that handles Home Assistant AI orchestration can integrate mesa-core to gain MESA profile management, semantic enforcement, retrieval API tools, and privacy controls without reimplementing the specification from scratch.

This document describes what mesa-core does, how it is structured, how MCP server developers integrate it, and what the first version implements versus what is deferred to future versions. It is written with sufficient technical detail to serve as a starting point for implementation.

---

## Table of Contents

1. [What mesa-core Does](#1-what-mesa-core-does)
2. [Architecture Overview](#2-architecture-overview)
3. [Package Structure](#3-package-structure)
4. [Core Components](#4-core-components)
   - 4.1 [SemanticProfile Dataclass](#41-semanticprofile-dataclass)
   - 4.2 [ProfileStore](#42-profilestore)
   - 4.3 [Storage Backends](#43-storage-backends)
   - 4.4 [MesaEnforcer](#44-mesaenforcer)
   - 4.5 [InheritanceResolver](#45-inheritanceresolver)
   - 4.6 [ConflictResolver](#46-conflictresolver)
   - 4.7 [TemporalEvaluator](#47-temporalevaluator)
   - 4.8 [TriggerValidator](#48-triggervalidator)
   - 4.9 [PrivacyEnforcer](#49-privacyenforcer)
   - 4.10 [LeaseManager](#410-leasemanager)
   - 4.11 [Audit Events](#411-audit-events)
   - 4.12 [Profile Export and Import](#412-profile-export-and-import)
5. [MCP Tool Registration](#5-mcp-tool-registration)
   - 5.1 [register_mesa_tools()](#51-register_mesa_tools)
   - 5.2 [Tool Implementations](#52-tool-implementations)
6. [Integration Guide](#6-integration-guide)
   - 6.1 [Minimal Integration (Level 1)](#61-minimal-integration-level-1)
   - 6.2 [Full Integration (Level 3)](#62-full-integration-level-3)
   - 6.3 [Framework Adapters](#63-framework-adapters)
   - 6.4 [Host Callback Reference](#64-host-callback-reference)
7. [Conformance Test Suite](#7-conformance-test-suite)
8. [Version Scope](#8-version-scope)
9. [Future Versions](#9-future-versions)
10. [Distribution and Installation](#10-distribution-and-installation)
11. [Dependencies](#11-dependencies)

---

## 1. What mesa-core Does

mesa-core provides five capabilities that any MCP server can use independently or together.

**Profile storage.** Read and write MESA profiles keyed by entity ID, automation ID, area ID, or any other HA component identifier. Profiles are stored in a pluggable backend (JSON file, SQLite, or in-memory). The host MCP server provides the storage path; mesa-core handles schema validation, inheritance resolution, and conflict detection.

**Enforcement.** Before a service call reaches HA, mesa-core evaluates the relevant entity profiles and returns an allowed/blocked decision with a reason. Evaluates `control_mode`, `declared_limits`, `temporal_constraints`, and privacy classification. The host server calls one function and receives a binary decision.

**Semantic retrieval API.** A set of MCP tools (mesa_query_profiles, mesa_get_profile, mesa_explain_profile, and others) that agents can call to query semantic context before acting. These tools are registered into the host server's tool registry with one function call. The host server does not need to implement them.

**Privacy enforcement.** Given a caller context (identity and roles) and an entity's privacy classification, mesa-core determines whether the caller may access the entity and what restrictions apply. The host server provides the caller context; mesa-core applies the MESA role resolution rules.

**Profile inheritance and conflict resolution.** When a single entity has profiles at multiple levels (domain, integration, area, device, entity), mesa-core resolves them into a single effective profile following the rules defined in the MESA Specification (Sections 5.6 and 5.7). The host server receives a fully resolved profile without needing to understand the inheritance logic.

---

## 2. Architecture Overview

```
Host MCP Server (any MCP server integrating mesa-core)
    |
    imports mesa-core
    |
    +--> ProfileStore (read/write profiles)
    |        |
    |        +--> Backend (JsonFile / SQLite / Memory)
    |
    +--> MesaEnforcer (evaluate service calls)
    |        |
    |        +--> InheritanceResolver (resolve profile hierarchy)
    |        +--> ConflictResolver (apply Rules A-E)
    |        +--> TemporalEvaluator (time-based constraints)
    |        +--> PrivacyEnforcer (caller role evaluation)
    |
    +--> register_mesa_tools() (adds MESA MCP tools to server)
             |
             +--> mesa_query_profiles
             +--> mesa_get_profile
             +--> mesa_explain_profile
             +--> mesa_request_lease
             +--> mesa_release_lease
             +--> mesa_get_caller_context
```

mesa-core has no opinion about the host server's internal architecture. It does not know about HA's REST API. It does not know which MCP framework the host uses. It receives structured data in and returns structured decisions out.

---

## 3. Package Structure

```
mesa-core/
    pyproject.toml
    README.md
    mesa_core/
        __init__.py              # Public API exports
        schemas/
            mesa_profile.schema.json   # Canonical JSON Schema for MESA profiles (v1.1)
            mesa_tools.schema.json     # JSON Schema for MCP tool inputs and outputs
        profile.py               # SemanticProfile, DiagnosticProfile dataclasses
        store.py                 # ProfileStore interface
        enforcer.py              # MesaEnforcer, DOMAIN_SAFETY_BASELINE
        inheritance.py           # InheritanceResolver
        conflict.py              # ConflictResolver (Rules A-E)
        temporal.py              # TemporalEvaluator
        privacy.py               # PrivacyEnforcer, CallerContext
        validation.py            # Profile schema validation
        trigger_validator.py     # TriggerValidator: validate triggers_automations declarations
        migration.py             # migrate_profile(): schema version migration
        integration_import.py    # import_from_integration(): load mesa_profile.json developer profiles
        vocabulary.py            # Canonical tag registry and validation
        exceptions.py            # MesaError, MesaEnforcementError, MesaValidationError
        mcp/
            __init__.py
            tools.py             # register_mesa_tools(), all tool handler functions
            schemas.py           # JSON schemas for all tool inputs and outputs
            adapters/
                __init__.py
                fastmcp.py       # Adapter for FastMCP framework
                raw_sdk.py       # Adapter for raw MCP Python SDK
        backends/
            __init__.py
            jsonfile.py          # JSON file backend
            sqlite.py            # SQLite backend
            memory.py            # In-memory backend (testing and development)
        lease/
            __init__.py
            manager.py           # LeaseManager: request, release, expire (mesa-core 1.1+)
            registry.py          # Active lease registry
    tests/
        __init__.py
        conformance/
            __init__.py
            test_kernel.py       # Kernel field validation tests
            test_control_mode.py # control_mode precedence and enforcement
            test_inheritance.py  # Profile inheritance resolution
            test_conflict.py     # Rules A-E conflict resolution
            test_temporal.py     # Temporal constraint evaluation
            test_privacy.py      # Privacy classification and role resolution
            test_inferred.py     # Inferred profile rules (Rules 1-9)
            malformed/
                missing_confidence.json
                missing_generated_at.json
                invalid_operator.json
                invalid_control_mode.json
                trust_laundering.json   # source: developer on AI-generated content
        integration/
            test_fastmcp_adapter.py
            test_raw_sdk_adapter.py
        fixtures/
            profiles/            # Valid and invalid profile JSON fixtures
```

**Why the import package is `mesa_core` and not `mesa`.** The `mesa` import name is already provided by the Mesa agent-based modeling framework on PyPI. Installing two distributions that share a top-level package silently corrupts whichever was installed first. The distribution name is `mesa-core`; the import package is `mesa_core`, following the standard naming convention.

---

## 4. Core Components

### 4.1 SemanticProfile Dataclass

The canonical Python representation of a MESA profile. All internal components work with this dataclass rather than raw dictionaries.

```python
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

class ControlMode(str, Enum):
    AUTONOMOUS = "autonomous"
    CONFIRM = "confirm"
    READ_ONLY = "read_only"
    PROHIBITED = "prohibited"

class TriggersAutomations(str, Enum):
    LIKELY = "likely"
    NONE = "none"
    UNKNOWN = "unknown"
    DEPLOYMENT_DEFINED = "deployment_defined"

class PrivacyLevel(str, Enum):
    PUBLIC = "public"
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"

class MetadataOrigin(str, Enum):
    DEVELOPER = "developer"
    USER = "user"
    HYBRID = "hybrid"
    INFERRED_AI = "inferred_ai"
    UNKNOWN = "unknown"

@dataclass
class PrivacyClassification:
    level: PrivacyLevel = PrivacyLevel.NORMAL
    contains_presence_data: bool = False
    contains_audio_capture: bool = False
    contains_visual_capture: bool = False
    contains_biometric_data: bool = False
    access_roles: Optional[Dict[str, List[str]]] = None
    deny_response_mode: str = "omit"
    privacy_note: Optional[str] = None

@dataclass
class OperationalBoundaries:
    control_mode: ControlMode = ControlMode.CONFIRM
    triggers_automations: TriggersAutomations = TriggersAutomations.UNKNOWN
    reversible: Optional[bool] = None
    reversibility_cost: Optional[str] = None
    reversibility_note: Optional[str] = None
    side_effect_scope: Optional[str] = None
    state_volatility: Optional[str] = None
    enforcement_mode: str = "advisory"
    control_reason: Optional[str] = None
    declared_limits: List[Dict[str, Any]] = field(default_factory=list)
    temporal_constraints: List[Dict[str, Any]] = field(default_factory=list)
    override_triggers_automations: bool = False
    override_control_mode: bool = False

@dataclass
class ProfileMetadata:
    schema_version: str = "1.1"
    profile_version: Optional[str] = None
    source: MetadataOrigin = MetadataOrigin.UNKNOWN
    confidence: Optional[float] = None
    generated_at: Optional[str] = None
    staleness_window_days: float = 60  # number per Spec 5.4; int or float preserved
    confirmed_fields: List[str] = field(default_factory=list)
    last_updated: Optional[str] = None
    profile_valid_for: Optional[Dict[str, Any]] = None

@dataclass
class PersonTraits:
    # People semantics (Enrichment Section 17); None / empty list = not declared.
    household_role: Optional[str] = None
    display_name: Optional[str] = None
    is_minor: Optional[bool] = None
    associated_zones: List[str] = field(default_factory=list)
    associated_automations: List[str] = field(default_factory=list)
    presence_entity: Optional[str] = None

@dataclass
class SemanticProfile:
    entity_id: str
    semantic_tags: List[str] = field(default_factory=list)
    metadata: ProfileMetadata = field(default_factory=ProfileMetadata)
    operational_boundaries: OperationalBoundaries = field(default_factory=OperationalBoundaries)
    privacy_classification: PrivacyClassification = field(default_factory=PrivacyClassification)
    person_traits: PersonTraits = field(default_factory=PersonTraits)
    inheritance_scope: str = "entity"
    diagnostic_profile: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    parse_warnings: List[str] = field(default_factory=list)
    # Dotted paths the source document explicitly declared, so Rule E can tell
    # "absent" from "set to the default value" on reserialisation.
    declared_paths: set = field(default_factory=set)

    @classmethod
    def from_dict(cls, entity_id: str, data: dict) -> "SemanticProfile":
        """Parse a profile from raw JSON/dict representation."""
        ...

    def to_dict(self) -> dict:
        """Serialise to JSON-compatible dict."""
        ...

    def is_inferred(self) -> bool:
        return self.metadata.source == MetadataOrigin.INFERRED_AI

    def effective_confidence(self) -> float:
        """Declared confidence, or 1.0 for trusted origins and 0.0 otherwise."""
        ...

    # known_entity_ids is a Collection, not an Iterable: these methods can each
    # be called with the same value (and freshness() evaluates once for both),
    # so a one-shot iterable would be exhausted by the first call and read as
    # an empty registry afterwards, inventing removal warnings. The host
    # callback carries the same requirement: it runs once per entity, so one
    # generator reused across those calls is drained by the first row of a
    # query. (A freshly built generator each call would survive, but nothing
    # can distinguish the two, so a one-shot value is refused either way.)
    def freshness(self, now: Optional[datetime] = None, *,
                  known_entity_ids: Optional[Collection[str]] = None,
                  integration_version: Optional[str] = None,
                  ha_version: Optional[str] = None) -> FreshnessReport:
        """Staleness status and invalidation warnings from ONE evaluation."""
        ...

    def staleness_status(self, now: Optional[datetime] = None, *,
                         known_entity_ids: Optional[Collection[str]] = None,
                         integration_version: Optional[str] = None,
                         ha_version: Optional[str] = None) -> str:
        """current / stale / unknown (Spec 5.4), including fired
        profile_valid_for invalidation triggers."""
        ...

    def validity_warnings(self, *, now: Optional[datetime] = None,
                          known_entity_ids: Optional[Collection[str]] = None,
                          integration_version: Optional[str] = None,
                          ha_version: Optional[str] = None) -> List[str]:
        """Advisory warnings from the profile_valid_for triggers (Spec 5.5)."""
        ...

@dataclass
class FreshnessReport:
    status: str                                  # current / stale / unknown
    warnings: List[str] = field(default_factory=list)
```

**Freshness evaluation.** `staleness_status()` and `validity_warnings()` read
the same `profile_valid_for` triggers, so a caller wanting both should call
`freshness()` rather than each in turn: one evaluation cannot report a status
and a warning set that disagree, two can. `FreshnessReport` is exported from
the package root.

### 4.2 ProfileStore

The central interface for profile storage. Host servers instantiate this with a backend and use it for all profile operations.

```python
from mesa_core import ProfileStore
from mesa_core.backends import JsonFileBackend

store = ProfileStore(backend=JsonFileBackend("/config/mesa/"))

# Get a profile (returns None if not found)
profile = store.get("light.living_room_ceiling")

# Get effective profile after inheritance resolution
effective = store.get_effective("light.living_room_ceiling")

# Store a profile
store.set("light.living_room_ceiling", profile)

# Delete a profile
store.delete("light.living_room_ceiling")

# Query profiles with optional filtering (matches effective resolved tags)
result = store.query(domains=["light"], tags=["lighting.ambient"])

# Get deployment defaults
defaults = store.get_deployment_defaults()

# Set deployment defaults
store.set_deployment_defaults(defaults_dict)
```

**ProfileStore public API:**

```python
class ProfileStore:
    def __init__(
        self,
        backend: StorageBackend,
        get_entity_area: Optional[Callable[[str], Optional[str]]] = None,
        get_entity_integration: Optional[Callable[[str], Optional[str]]] = None,
        get_entity_device: Optional[Callable[[str], Optional[str]]] = None
    ): ...
    def get(self, entity_id: str) -> Optional[SemanticProfile]: ...
    def get_effective(self, entity_id: str) -> SemanticProfile: ...
    def set(self, entity_id: str, profile: SemanticProfile) -> None: ...
    def delete(self, entity_id: str) -> None: ...
    # Scope profiles (domain-, integration-, area-, and device-level) have
    # symmetric get/set/delete.
    def get_domain_profile(self, domain: str) -> Optional[SemanticProfile]: ...
    def set_domain_profile(self, domain: str, profile: SemanticProfile) -> None: ...
    def delete_domain_profile(self, domain: str) -> None: ...
    def get_integration_profile(self, integration: str) -> Optional[SemanticProfile]: ...
    def set_integration_profile(self, integration: str, profile: SemanticProfile) -> None: ...
    def delete_integration_profile(self, integration: str) -> None: ...
    def get_area_profile(self, area_id: str) -> Optional[SemanticProfile]: ...
    def set_area_profile(self, area_id: str, profile: SemanticProfile) -> None: ...
    def delete_area_profile(self, area_id: str) -> None: ...
    def get_device_profile(self, device_id: str) -> Optional[SemanticProfile]: ...
    def set_device_profile(self, device_id: str, profile: SemanticProfile) -> None: ...
    def delete_device_profile(self, device_id: str) -> None: ...
    # Key enumeration: stored identifiers per scope, as bare names.
    def entity_keys(self) -> List[str]: ...
    def domain_keys(self) -> List[str]: ...
    def integration_keys(self) -> List[str]: ...
    def area_keys(self) -> List[str]: ...
    def device_keys(self) -> List[str]: ...
    def query(self, *,
              domains: Optional[List[str]] = None,
              tags: Optional[List[str]] = None,
              tags_match: str = "any",
              areas: Optional[List[str]] = None,
              devices: Optional[List[str]] = None,
              integrations: Optional[List[str]] = None,
              intents: Optional[List[str]] = None,
              include_inferred: bool = False,
              origin: Optional[str] = None,
              min_origin_authority: Optional[str] = None,
              limit: int = 50,
              cursor: Optional[str] = None,
              resolver: Optional[InheritanceResolver] = None) -> ProfileQueryResult: ...
    # None when the operator has configured no deployment defaults.
    def get_deployment_defaults(self) -> Optional[DeploymentDefaults]: ...
    def set_deployment_defaults(self, defaults: dict) -> None: ...
    def explain(self, entity_id: str) -> ProfileExplanation: ...
    def find_orphans(self, known_entity_ids: Iterable[str], *,
                     known_domains: Optional[Iterable[str]] = None,
                     known_integrations: Optional[Iterable[str]] = None,
                     known_areas: Optional[Iterable[str]] = None,
                     known_devices: Optional[Iterable[str]] = None) -> List[str]: ...

    # Every method above also has an `a`-prefixed async variant, e.g.:
    async def aget(self, entity_id: str) -> Optional[SemanticProfile]: ...
    async def aset_domain_profile(self, domain: str, profile: SemanticProfile) -> None: ...
    async def aquery(self, **kwargs) -> ProfileQueryResult: ...
    async def aexplain(self, entity_id: str) -> ProfileExplanation: ...
```

The only exception is `attach_resolver()`, which is synchronous-only configuration wiring with no I/O.

**Sync and async APIs.** All public methods on `ProfileStore`, `MesaEnforcer`, and `TriggerValidator` are available in both synchronous and asynchronous variants, prefixed with `a` (e.g. `get()` / `aget()`, `evaluate()` / `aevaluate()`). `LeaseManager`'s lifecycle methods have async variants (`arequest()`, `arelease()`, `arelease_session()`, `aexpire()`); its `active_leases()` and `sensor_state()` are synchronous-only reads of in-memory state. Async resolution goes through the store: `aget_effective()` and `aexplain()` wrap the `InheritanceResolver`. `PrivacyEnforcer.evaluate()` is synchronous-only by design: it is pure computation with no I/O, so it cannot block the event loop. MCP servers are typically async; host servers SHOULD use the async variants for anything that touches storage.

**Bulk operations.** `set_many()` and `delete_many()` (and their async variants `aset_many()`, `adelete_many()`) accept dictionaries and lists respectively, allowing operators to import or remove profiles for many entities in a single operation. These are essential for deployments with hundreds of entities.

**Scope enumeration.** `domain_keys()`, `integration_keys()`, `area_keys()`, and `device_keys()` return the domain names, integration names, area IDs, and device IDs that have a scope-level profile stored, as bare identifiers, mirroring `entity_keys()` for entity profiles. The reserved key scheme that separates the scopes internally is never exposed. Pair them with the matching `get_*_profile()` to walk every stored scope profile, for instance to surface the domain and area defaults an operator has configured.

**Orphan detection.** `find_orphans(known_entity_ids)` returns stored profile keys absent from the provided entity ID list, so hosts can detect profiles orphaned by entity renames (Specification Section 5.5). Hosts SHOULD run it at startup and on `entity_registry_updated` events and surface results to the operator. The keyword arguments extend the check to scoped profiles: each supplied registry (`known_domains`, `known_integrations`, `known_areas`, `known_devices`) enables that scope, and scoped orphans are returned as their full reserved key (for example `__device__:abc123` for a device that was removed from HA), so callers can distinguish scopes. Omitted keywords leave that scope unchecked, and the plain one-argument call behaves exactly as before.

### 4.3 Storage Backends

All backends implement the `StorageBackend` abstract base class. Host servers can implement their own.

```python
from abc import ABC, abstractmethod

class StorageBackend(ABC):
    @abstractmethod
    def read(self, key: str) -> Optional[dict]: ...

    @abstractmethod
    def write(self, key: str, data: dict) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def list_keys(self, prefix: Optional[str] = None) -> List[str]: ...
```

**JsonFileBackend.** Stores each profile as a separate JSON file in a directory. File names are the URL-quoted storage key, keeping the filename-to-key mapping reversible so `list_keys()` reconstructs keys exactly. Suitable for small to medium deployments.

```python
JsonFileBackend(base_path: str, create_if_missing: bool = True)
```

**SqliteBackend.** Stores all profiles as JSON documents in a single SQLite database file, using the standard library `sqlite3` (no extra dependency). Filtering and pagination are evaluated by `ProfileStore` in Python, which is comfortably fast at home-deployment scale. Suitable for larger profile sets than one-file-per-profile storage.

```python
SqliteBackend(db_path: str)
```

**MemoryBackend.** In-memory storage. Not persistent. For testing and development only.

```python
MemoryBackend(initial_data: Optional[dict] = None)
```

### 4.4 MesaEnforcer

Evaluates whether a proposed service call is permitted under the entity's MESA profile. The host server calls this before forwarding any service call to HA.

```python
from mesa_core import MesaEnforcer, CallerContext
from datetime import datetime

enforcer = MesaEnforcer(store=store)

result = enforcer.evaluate(
    entity_id="lock.front_door",
    service="lock.lock",
    service_params={"entity_id": "lock.front_door"},
    caller_context=CallerContext(
        caller_id="user.abc123",
        roles=["primary_resident"],
        is_authenticated=True,
        session_id="sess_xyz"
    ),
    current_time=datetime.now()
)

if result.allowed:
    # forward to HA
    pass
else:
    raise MesaEnforcementError(result.reason, result.rule_applied)
```

**EnforcementResult:**

```python
@dataclass
class EnforcementResult:
    allowed: bool
    reason: str
    rule_applied: Optional[str]       # e.g. "control_mode:prohibited"
    entity_id: str
    effective_profile: SemanticProfile
    warnings: List[str]               # non-blocking advisory messages
```

**Built-in domain safety baseline.** When resolving effective profiles, `MesaEnforcer` applies the built-in domain safety baseline for entities that have no profile at any inheritance level and no `deployment_defaults` configured. This prevents non-interactive agents from being completely locked out before any profiles have been authored. The baseline matches the domain table defined in Specification Section 5.8. Host servers MAY override the baseline by configuring `deployment_defaults`.

```python
# Built-in baseline is applied automatically by MesaEnforcer
# when no profile exists at any level and no deployment_defaults are set.
# Hosts can inspect the baseline:
from mesa_core.enforcer import DOMAIN_SAFETY_BASELINE

print(DOMAIN_SAFETY_BASELINE["light"])   # ControlMode.AUTONOMOUS
print(DOMAIN_SAFETY_BASELINE["lock"])    # ControlMode.PROHIBITED
```

**Fail-closed (deny-by-default) deployments.** Some hosts delegate all per-entity gating to MESA rather than maintaining their own permission layer (for example a single pass-through credential whose entire policy is "whatever MESA says"). The built-in baseline is permissive for some domains (`light` is `autonomous`; unknown domains are `confirm`), so a forgotten entity could be controllable. To invert the posture so unprofiled entities fail closed, configure `deployment_defaults` with a restrictive global default and open up only the domains (or individual entity/area/domain profiles) you intend to be controllable:

```python
from mesa_core import ControlMode
from mesa_core.store import DeploymentDefaults

store.set_deployment_defaults(DeploymentDefaults(
    default_control_mode=ControlMode.PROHIBITED,   # fallback for unprofiled entities
    domain_overrides={
        "light": {"control_mode": "autonomous"},   # domains to leave controllable
    },
))
```

This default applies **only to unprofiled entities**: it fills `control_mode` solely for an entity that has no profile at any level (entity, device, area, integration, or domain), matching Specification 5.8 and the control_mode precedence note in Section 4 (operators loosen an unprofiled entity via `deployment_defaults`, a profiled one via the Section 5.7 Rule A override). A profiled entity that simply omits `control_mode` defaults to `confirm`, never to the deployment default, so the default can never loosen a profiled entity below `confirm`. It does not participate in the Rule A most-restrictive comparison either, so a declared `autonomous` stays `autonomous`. Two practical notes for fail-closed operators:

- `prohibited` hard-blocks only when the call is evaluated in enforced mode; in advisory mode it passes with a warning. Pair a `prohibited` default with enforced evaluation. (`read_only` blocks regardless of enforcement mode, but it asserts entity nature rather than policy, so `prohibited` is the better fit for "not yet granted.")
- `control_mode` gates control (writes/service calls) only; it never gates reads. mesa-core has no blanket read-deny default, and privacy denial is role-based (`access_roles.deny_for`), not a configurable default. Read/visibility fail-closed remains the host's responsibility.

**Evaluation order:**

1. Resolve effective profile via InheritanceResolver.
2. Apply temporal constraints via TemporalEvaluator first, so a temporally tightened `control_mode` is what the following steps evaluate.
3. Apply privacy enforcement via PrivacyEnforcer. If caller is in `deny_for`, block immediately; a `restricted` effective level coerces `autonomous` to `confirm`.
4. Evaluate `control_mode`:
   - `read_only`: block with reason "Entity is read-only by nature: {control_reason or entity_id}".
   - `prohibited`: block with reason "Entity is prohibited by policy: {control_reason or entity_id}".
   - `confirm`: in advisory mode, add confirmation warning and surface `control_reason`. In enforced mode, deny the call and return a `confirmation_challenge`, or allow it when a valid `confirmation_token` accompanies the call (Specification Section 6.6). If no interaction channel exists, block as `prohibited`.
   - `autonomous`: proceed.
5. Evaluate declared limits (profile limits plus active temporal value constraints) against service params.
6. Return result with any warnings.

### 4.5 InheritanceResolver

Resolves the effective profile for an entity by merging domain-level, integration-level, area-level, and entity-level profiles following the MESA inheritance rules (Specification Section 5.6).

```python
from mesa_core.inheritance import InheritanceResolver

resolver = InheritanceResolver(store=store)

# Returns fully resolved SemanticProfile
effective = resolver.resolve("light.bedroom_ceiling")

# Returns explanation of resolution steps
explanation = resolver.explain("light.bedroom_ceiling")
```

**Resolution algorithm:**

1. Load entity-level profile if it exists.
2. Load device-level profile for the physical device that owns this entity (requires the host's `get_entity_device` callback; without it, device-scope profiles stay inert).
3. Load area-level profile for the entity's assigned area (requires the host's `get_entity_area` callback).
4. Load integration-level profile for the integration that created this entity (requires the host's `get_entity_integration` callback; without it, only integrations whose name equals the entity's HA domain resolve, and hub/device integration profiles stay inert).
5. Load domain-level profile for the entity's HA domain.
6. Load deployment defaults.
7. Merge from lowest to highest precedence: defaults, then domain, integration, area, device, entity.
8. Apply conflict resolution rules (Section 5.7) for fields present at multiple levels.
9. Apply `triggers_automations` stickiness: if any level is `likely`, effective is `likely` unless entity-level overrides with `override_triggers_automations: true`.
10. Apply `control_mode` tightening: most restrictive value wins.
11. Apply privacy most-restrictive-wins.
12. Return merged SemanticProfile.

**Host callback for area/domain lookup:**

```python
# Host provides these lookups at initialisation
resolver = InheritanceResolver(
    store=store,
    get_entity_area=lambda entity_id: "bedroom",        # HA area registry ID
    get_entity_domain=lambda entity_id: "light"          # return integration domain
)
```

### 4.6 ConflictResolver

Implements the five global conflict resolution rules from Specification Section 5.7. Called internally by InheritanceResolver; also available directly.

```python
from mesa_core.conflict import ConflictResolver

resolver = ConflictResolver()

# Merge two profiles, applying Rules A-E
merged = resolver.merge(higher_authority_profile, lower_authority_profile)
```

**Rules implemented:**

- **Rule A:** `control_mode` tightening-only. `prohibited` > `confirm` > `autonomous` regardless of authority. Sole exception: an entity-level `user`-origin profile may loosen an inherited `confirm` to `autonomous` via `override_control_mode: true` with `control_reason`. `prohibited` and `read_only` never loosen.
- **Rule B:** `triggers_automations: likely` sticky upward. `deployment_defined` at entity scope overrides.
- **Rule C:** Privacy level most-restrictive-wins. `restricted` > `sensitive` > `normal` > `public`.
- **Rule D:** Scope-then-origin for all other fields. Most specific scope wins (`entity` > `device` > `area` > `integration` > `domain`) among trusted origins (`developer`, `user`, `hybrid`); origin breaks scope ties. Hybrid trust is per field: a `hybrid` profile is trusted-tier only for the field paths in its `confirmed_fields`; its unconfirmed fields resolve in the lower tier as inferred (Rule 6). `inferred_ai` and `unknown`, and unconfirmed hybrid fields, never override trusted-tier declarations at any scope; among themselves the same scope-then-origin rule applies, with `inferred_ai` > `unknown`.
- **Rule E:** Absence is not a conflict. Missing fields are inherited, not defaulted.

### 4.7 TemporalEvaluator

Evaluates temporal constraints against the current time, calendar state, and solar elevation, supplied through host callbacks. Returns whether any constraint modifies the effective boundary.

```python
from mesa_core.temporal import TemporalEvaluator

evaluator = TemporalEvaluator(
    get_state=lambda entity_id: "on",       # callback: get current HA entity state
    get_calendar_events=lambda cal_id: [],  # callback: get active calendar events
    get_solar_elevation=lambda at: -4.2,    # callback: sun elevation in degrees at `at`
)

# Returns a TemporalResult; the tightened boundaries are on .boundaries
result = evaluator.apply(
    boundaries=profile.operational_boundaries,
    current_time=datetime.now()
)
modified_boundaries = result.boundaries
result.active_constraint_ids  # constraints that applied
result.active_limits          # limits contributed by those constraints
result.warnings               # unevaluable conditions, treated as active
```

**Condition types implemented:** `time_range`, `day_of_week`, `calendar_entity`, and (since 1.2) `solar_angle`. All condition types support the `negate` flag. `duration` and `relative_to_event` are v2 and fail closed.

**Solar evaluation.** mesa-core computes no astronomy. `get_solar_elevation(at)` returns the sun's elevation in degrees at the given time, or None (fail-closed). In Home Assistant the current elevation is the `sun.sun` entity's `elevation` attribute; hosts that can compute elevation at arbitrary times (the `astral` library ships with HA core) also get exact `solar_offset_minutes` handling, because a condition offset by N minutes samples the elevation N minutes in the past.

### 4.8 TriggerValidator

Cross-references declared `triggers_automations: none` profiles against the actual HA automation registry. Identifies entities declared `none` that appear in automation trigger or condition blocks, allowing operators to correct stale declarations before agents act on incorrect assumptions.

```python
from mesa_core import TriggerValidator

validator = TriggerValidator(store=store)

# Host provides automation configs via callback
issues = validator.validate(
    get_automation_configs=lambda: [
        {
            "id": "automation.occupancy_lights",
            "trigger": [{"platform": "state", "entity_id": "input_boolean.guest_mode"}],
            "condition": [],
            "action": []
        }
    ]
)

for issue in issues:
    print(f"Entity {issue.entity_id} declared triggers_automations: none")
    print(f"  but found in automation: {issue.automation_id}")
    print(f"  role: {issue.role}")  # "trigger", "condition", or "action"
    print(f"  recommendation: {issue.recommendation}")
```

**ValidationIssue dataclass:**

```python
@dataclass
class ValidationIssue:
    entity_id: str
    declared_value: str          # the current triggers_automations value
    automation_id: str           # the automation referencing this entity
    role: str                    # "trigger", "condition", or "action"
    severity: str                # "warning" or "error"
    recommendation: str          # human-readable corrective action
```

**TriggerValidator public API:**

```python
class TriggerValidator:
    def __init__(
        self,
        store: ProfileStore,
        expand_target: Optional[Callable[[str, str], List[str]]] = None
    ): ...

    def validate(
        self,
        get_automation_configs: Callable[[], List[dict]]
    ) -> List[ValidationIssue]:
        """
        Cross-reference all profiles declaring triggers_automations: none
        against the provided automation configurations. Returns a list of
        ValidationIssue for each entity found in an automation trigger or
        condition block despite being declared none.
        """
        ...

    def validate_entity(
        self,
        entity_id: str,
        get_automation_configs: Callable[[], List[dict]]
    ) -> List[ValidationIssue]:
        """
        Validate a single entity against the automation registry.
        """
        ...
```

The host server provides `get_automation_configs` as a callback that returns HA automation configurations in standard HA dict format. mesa-core never calls HA directly. The callback may return automations from any source: the HA REST API, a local `automations.yaml` parse, or a test fixture.

**Automation traversal primitive.** The same entity-reference walk that `TriggerValidator` uses internally is exposed as a public, stateless function:

```python
from mesa_core import entities_by_role

entities_by_role(config: dict, expand_target=None) -> dict[str, set[str]]
# Returns {"trigger": {...}, "condition": {...}, "action": {...}}
```

Given a single automation config dict, it returns the entity IDs referenced in each block, handling the singular/plural HA section keys (`trigger`/`triggers`, etc.) transparently. This is the canonical traversal for automation configs. Hosts building reverse-reference indexes (entity -> automations that reference it) SHOULD call `entities_by_role` over their own automation configs rather than reimplementing the entity-ID walk, so that HA-config-format knowledge stays in one place. mesa-core deliberately does not provide the reverse index, relationship graph, or script/scene traversal itself; those remain host concerns layered on this primitive.

**Indirect entity references.** Automations can reference entities without naming them: device triggers and conditions carry a `device_id`, and purpose-specific triggers (HA 2026.7+) take `target` blocks with `area_id`, `floor_id`, `label_id`, or `device_id` selectors. Only the host can resolve these against the HA registries. Both `TriggerValidator` and `entities_by_role` accept an optional `expand_target(kind, ref)` callback, called once per selector found, that returns the entity IDs the selector covers in the deployment. Without the callback, indirectly referenced entities are invisible to validation, and a stale `none` declaration on such an entity will pass unflagged. Hosts SHOULD provide the callback (Specification Section 5.5).

**When to run validation:** Level 2 and Level 3 host servers SHOULD run `TriggerValidator.validate()` (or `avalidate()`) at startup and whenever the automation registry changes (detected via the `automation_reloaded` HA event). Validation results SHOULD be surfaced to operators through the server's configuration interface and included in `mesa_explain_profile` output.

### 4.9 PrivacyEnforcer

Evaluates privacy classification against caller context and returns an access decision. Response shaping is the host's responsibility: mesa-core returns the decision together with `deny_response_mode`, and applying `omit`, `redact`, or `error` to the actual response payload happens in the host server, which owns the response.

```python
from mesa_core.privacy import PrivacyEnforcer, CallerContext

enforcer = PrivacyEnforcer()

decision = enforcer.evaluate(
    privacy=profile.privacy_classification,
    caller=CallerContext(
        caller_id="user.guest_01",
        roles=["guest"],
        is_authenticated=True,
        session_id="sess_abc"
    )
)

# decision.allowed: bool
# decision.effective_level: PrivacyLevel
# decision.deny_response_mode: str
# decision.reason: str
```

**CallerContext:**

```python
@dataclass
class CallerContext:
    caller_id: str
    roles: List[str]
    is_authenticated: bool
    session_id: str
    display_name: Optional[str] = None
    session_started_at: Optional[str] = None
```

### 4.10 LeaseManager

Advisory coordination leases (Enrichment Section 21). Shipped in mesa-core v1.1. The lease protocol is a signal between MESA-aware components, not a concurrency lock; read Enrichment 21.1 before integrating.

```python
from mesa_core.lease import LeaseManager

lease_manager = LeaseManager(
    store,                        # optional: enables protected/critical denial (21.5)
    get_state=my_ha_state_lookup, # optional: protected "while active" test
    on_lease_event=fire_ha_event, # optional: receives mesa_lease_expired payloads
)

response = lease_manager.request(
    ["light.living_room", "light.hall"], 15,
    session_id=ctx.session_id, caller_id=ctx.caller_id,
    intent="movie night scene transition",
)
# response: lease_id, granted, entities_granted, entities_denied,
#           denial_reasons, expires_at, granted_duration_seconds,
#           active_conflicts, warnings (Enrichment 21.3)

lease_manager.release(response.lease_id, session_id=ctx.session_id)
lease_manager.release_session(ctx.session_id)   # host session-teardown hook
lease_manager.expire()                          # periodic sweep for timely events
lease_manager.sensor_state()                    # binary_sensor.mesa_lease_active data
```

**Design properties:**

- **In-memory only.** Leases (max 30 seconds, session-scoped) are never persisted; a restart terminates all sessions and therefore all leases. Persistence would resurrect stale locks.
- **Lazy expiry.** An expired lease never grants anything, so correctness never depends on a background task, but removal and the `mesa_lease_expired` event happen only when a lifecycle operation sweeps: `request()`, `release()`, `release_session()`, `expire()`, and `sensor_state()` sweep, while `active_leases()` filters expired entries out of its result without removing them or emitting, so it stays a side-effect-free read. Hosts SHOULD therefore call `expire()` (or `aexpire()`) periodically so events fire close to `expires_at` rather than relying on reads to produce them, and SHOULD call `release_session()` on session termination (Enrichment 21.4).
- **Existing holder wins.** Overlapping requests from another session are denied per entity (partial grants are valid). Multi-agent priority preemption (Enrichment 21.6) ships in v2; `caller_priority` is accepted but unused.
- **Fail-closed automation checks.** Entities monitored by `protected` automations are denied while the automation is active; without a `get_state` callback the automation is treated as active. `critical` automation scope (trigger, condition, and affected entities) is denied unconditionally. `cooperative` and `assertive` automations surface in `active_conflicts`.
- **Events via callback.** `on_lease_event` receives the Enrichment 21.4 payload (`lease_id`, `entities`, `reason`, `timestamp`) for every ended lease; the host bridges it onto the HA event bus as `mesa_lease_expired`.

Async variants: `arequest()`, `arelease()`, `arelease_session()`, `aexpire()`.

### 4.11 Audit Events

Shipped in mesa-core v1.1. Every audit record mesa-core emits on the `mesa_core.audit` logger carries a `mesa_audit_event` attribute holding the standard event dict; the record message stays human-readable. Hosts attach a logging handler and read `record.mesa_audit_event` for structured consumption, and MAY emit their own events into the same stream with `emit_audit_event(MesaAuditEvent(...))`.

```python
@dataclass
class MesaAuditEvent:
    event_type: str    # "privacy_access" | "enforcement_decision" | "lease"
    action: str        # "access", the service called, or the lease operation
    decision: str      # "allowed" | "denied" | "blocked" | "granted" | expiry reason
    entity_id: Optional[str] = None
    caller_id: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    profile_version: Optional[str] = None
    rule_applied: Optional[str] = None
    redaction_mode: Optional[str] = None
    timestamp: str = ""                  # ISO 8601; stamped at emission
    details: Dict[str, Any] = field(default_factory=dict)
```

**Emission points.** `PrivacyEnforcer` emits `privacy_access` for sensitive/restricted entity access and all person entity access (Specification 7.1/17), with `effective_level` and `is_person` in `details`. `MesaEnforcer` emits `enforcement_decision` for every blocked call at INFO; allowed calls are emitted at DEBUG, so full trails are opt-in via log level. `LeaseManager` emits `lease` events for requests (`granted`/`denied`) and every lease end (with the Section 21.4 reason as the decision).

The standard schema is the RECOMMENDED shape for host implementations; the Specification requires the logging itself, not this exact structure (Specification 7.1).

### 4.12 Profile Export and Import

Shipped in mesa-core 1.2. Moves complete profile sets between deployments, backends, and host servers as a single JSON archive: backup and restore, JsonFile-to-SQLite migration, cloning a test deployment to production, or an Export button in one MCP server feeding an Import button in another.

```python
from mesa_core import export_profiles, import_profiles

archive = export_profiles(store)            # one JSON-serialisable dict
result = import_profiles(other_store, archive, on_conflict="skip")
# result: imported, overwritten, skipped_existing, invalid (key -> error), ok
```

The archive envelope (`mesa_export`) carries `format_version`, `exported_at`, `mesa_core_version`, and the profile documents grouped by scope: `entities`, `domains`, `integrations`, `areas`, `devices`, plus `deployment_defaults`. The archive `format_version` is `1.1` as of mesa-core 1.3; import accepts both `1.0` and `1.1` archives, while older mesa-core versions reject a `1.1` archive outright rather than silently dropping the `devices` section. The documents are the canonical profile JSON form, so the archive is storage-backend-agnostic by construction: any host that exposes its profiles through the ProfileStore API can exchange archives with any other, regardless of how either stores profiles internally.

**Design properties:**

- **Export is faithful.** It reads raw stored documents through the backend with no validation and drops nothing; a backup is a backup, malformed entries included.
- **Import validates.** Every document passes profile validation before writing; failures are quarantined in `ImportResult.invalid` and never written, so a corrupted or hostile archive cannot silently poison a store.
- **Conflicts are explicit.** `on_conflict="skip"` (default) preserves existing profiles, `"overwrite"` replaces them, and `"error"` raises before anything is written (all-or-nothing).

Async variants: `aexport_profiles()`, `aimport_profiles()`.

---

## 5. MCP Tool Registration

### 5.1 register_mesa_tools()

The primary integration point for host MCP servers. Registers all MESA MCP tools into the host server's tool registry.

```python
from mesa_core.mcp import register_mesa_tools
from mesa_core import ProfileStore
from mesa_core.backends import SqliteBackend

store = ProfileStore(backend=SqliteBackend("/config/mesa/mesa.db"))

register_mesa_tools(
    store=store,
    adapter="fastmcp",          # "fastmcp" or "raw_sdk"
    server=mcp_app,             # the host MCP server instance
    enforcer=enforcer,          # accepted for API stability; registers no tools
    lease_manager=lease_mgr,    # optional: enable lease tools (mesa-core 1.1+)
    caller_context_fn=get_ctx   # optional: function returning CallerContext for current session
)
```

Enforcement is not exposed as MCP tools: `MesaEnforcer` wraps the host's service-call path directly (Section 6.2), where it can actually block execution; an agent-callable permission check would be advisory only. The `enforcer` parameter is accepted for API stability and registers nothing. If `lease_manager` is not provided, the lease tools are not registered. This allows incremental adoption: a host server can start with just the query tools and wire enforcement into its service-call path later.

### 5.2 Tool Implementations

**mesa_query_profiles**

Input: domain filter, tag filter, area filter, device filter, integration filter, intents, min_origin_authority, include_inferred flag, include_fields, limit, cursor.
Action: calls `store.query()` (passing the resolver), which applies filters against effective resolved profiles and returns paginated results; formats them into the response envelope.
Output: results array, total_matched, pagination metadata, caller_context if available.

**mesa_get_profile**

Input: entity_id, include_diagnostic flag, include_semantic_moments flag.
Action: calls `store.get_effective()`, optionally fetches diagnostic profile; when `include_semantic_moments` is requested and the host supplies the `get_semantic_moments` callback, attaches the purpose-specific triggers and conditions (HA 2026.7+) the entity participates in.
Output: complete resolved profile for the entity, staleness_status for inferred profiles, optional `semantic_moments` array (live HA introspection for agent context; never stored, never consulted by enforcement, and no more trustworthy than the integration that defined the moment).

**mesa_explain_profile**

Input: entity_id, show_conflicts flag.
Action: calls `resolver.explain()`, returns full inheritance resolution path.
Output: explanation array showing which level contributed each field, origin, and whether any conflict rule was applied.

**mesa_request_lease**

Input: entities array, duration_seconds, intent string, priority_level, caller_priority, preemption_handling.
Action: calls `lease_manager.request()`, checks for conflicts with protected/critical automations, returns lease or denial.
Output: lease_id, granted, entities_granted, entities_denied, denial_reasons, expires_at, active_conflicts.

**mesa_release_lease**

Input: lease_id.
Action: calls `lease_manager.release()`.
Output: confirmation.

**mesa_get_caller_context**

Input: none.
Action: calls `caller_context_fn()` to retrieve session context.
Output: CallerContext as dict.

---

## 6. Integration Guide

### 6.1 Minimal Integration (Level 1)

Minimum code to reach MESA Level 1 conformance. Profiles are read from JSON files and the host server surfaces them to agents in its existing context payloads. No enforcement, no MESA-specific MCP tools required.

```python
from mesa_core import ProfileStore
from mesa_core.backends import JsonFileBackend

store = ProfileStore(backend=JsonFileBackend("/config/mesa/"))

# In your existing tool handlers, enrich context with MESA profiles:
profile = store.get_effective("light.living_room_ceiling")
if profile:
    # Include profile data in your tool response context
    context["mesa_profile"] = profile.to_dict()
```

Level 1 does not require registering MESA MCP tools. It requires reading and respecting MESA profiles. To also expose MESA query tools to agents (enabling them to search profiles by tag, domain, or area), register the retrieval tools. This is recommended but not required for Level 1:

```python
from mesa_core.mcp import register_mesa_tools

register_mesa_tools(store=store, adapter="fastmcp", server=app)
# Agents can now call mesa_query_profiles, mesa_get_profile, mesa_explain_profile.
# These are Level 3 tools exposed early for convenience.
```

### 6.2 Full Integration (Level 3)

Full Level 3 integration with enforcement, leases, and caller context.

```python
from mesa_core import ProfileStore, MesaEnforcer
from mesa_core.backends import SqliteBackend
from mesa_core.inheritance import InheritanceResolver
from mesa_core.lease import LeaseManager  # mesa-core 1.1+
from mesa_core.mcp import register_mesa_tools
from mesa_core.exceptions import MesaEnforcementError
from mesa_core.privacy import CallerContext
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from typing import Any, Optional
from datetime import datetime

# Authentication is YOUR job, not mesa-core's: Specification 9.1 requires a
# Level 3 server to reject unauthenticated requests with HA-equivalent
# authentication, and mesa-core never sees your transport. Gate it at the
# transport, so an unauthenticated request never reaches a MESA tool. Raising
# from the caller-context callback instead does not work: the handlers catch
# exceptions and answer server_error, not Specification 9.6's unauthorized.
class HomeAssistantTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> Optional[AccessToken]:
        # Home Assistant issues bearer access tokens and answers 401 for an
        # invalid one. Return None on rejection; the SDK turns that into an
        # unauthorized response before dispatch.
        user = await hass_client.verify_bearer_token(token)
        if user is None:
            return None
        return AccessToken(token=token, client_id=user.id, scopes=user.scopes)

app = FastMCP(
    "my-ha-mcp-server",
    token_verifier=HomeAssistantTokenVerifier(),
    auth=AuthSettings(
        issuer_url="https://ha.example.org",
        resource_server_url="https://ha.example.org/mcp",
    ),
)
# This path secures an HTTP transport. `FastMCP.run()` defaults to stdio, where
# there is no bearer token to verify and the trust boundary is the process
# itself, so serve over HTTP when you rely on it: `app.run("streamable-http")`.
# On standalone FastMCP the equivalent is middleware: `app.add_middleware(...)`.
# Its `middleware` attribute is a list, not a decorator.

# Initialise storage
store = ProfileStore(backend=SqliteBackend("/config/mesa/mesa.db"))

# Initialise resolver with HA lookup callbacks. These callbacks let mesa-core
# query HA for area and domain information. They are called synchronously, from
# inside a worker thread on the async paths, so they must not be coroutines: a
# coroutine object is not None, so an `async def` callback here would be used as
# the lookup result itself and silently skip the device, area, integration, and
# domain inheritance levels rather than raising. Cache the registry, or bridge with
# asyncio.run_coroutine_threadsafe against your server's loop.
def get_entity_area(entity_id: str) -> Optional[str]:
    # EFFECTIVE area, not just the entity's own: an entity with no area_id of
    # its own inherits the area of the device that owns it, so check the
    # entity registry entry first and fall back to the device registry entry.
    # Returning only the entity's own area_id silently skips area inheritance
    # for the many entities that are placed by their device.
    entry = entity_registry.get(entity_id)
    if entry is None:
        return None
    if entry.area_id is not None:
        return entry.area_id
    device = device_registry.get(entry.device_id) if entry.device_id else None
    return device.area_id if device else None

def get_entity_domain(entity_id: str) -> str:
    return entity_id.split(".")[0]

def get_entity_device(entity_id: str) -> Optional[str]:
    # entity registry entry -> device_id; None for entities owning no device
    ...

def get_entity_integration(entity_id: str) -> Optional[str]:
    # entity registry entry -> config entry -> integration domain
    ...

resolver = InheritanceResolver(
    store=store,
    get_entity_area=get_entity_area,
    get_entity_domain=get_entity_domain,
    # Supply both, or the levels they resolve are inert: device-scope profiles
    # apply to nothing without get_entity_device, and without
    # get_entity_integration only integrations whose name equals an entity
    # domain resolve, leaving hub and device integration sidecars unused
    # (Specification 5.6). Both are also required by query(devices=...) and
    # query(integrations=...), which raise ValueError when they are absent.
    get_entity_device=get_entity_device,
    get_entity_integration=get_entity_integration
)

# Initialise enforcer
enforcer = MesaEnforcer(store=store, resolver=resolver)

# Initialise lease manager. Pass the store: without it there are no automation
# profiles to read, so the protected/critical denial check (Spec 21.5) silently
# grants leases it should deny.
lease_manager = LeaseManager(store)

# Caller context function (host server provides this). mesa-core applies
# access_roles before surfacing any profile, so without this the base privacy
# level applies to every caller equally (Spec 7.2). By the time it runs the
# request is already authenticated, so it only reads the session; a server
# that always returns an anonymous context is conformant for base privacy
# levels but gives access_roles nothing to isolate (Spec 3, caller identity
# realism).
def get_caller_context() -> CallerContext:
    session = current_session()          # your transport's authenticated session
    return CallerContext(
        caller_id=session.user_id,
        roles=session.roles,
        is_authenticated=True,
        session_id=session.id,
    )

# Deployment facts the Spec 5.5 invalidation triggers are evaluated against.
# Called once per entity, because integration_version means the version of the
# integration that created THAT entity: a deployment runs many integrations at
# different versions, so returning one version for the whole request would
# compare profiles against a version they were never authored against.
# Without this callback these triggers cannot be evaluated and an invalidated
# profile keeps reporting staleness_status: current (Spec 5.4).
# review_after_days needs nothing from the host.
def get_validity_context(entity_id: str) -> dict:      # synchronous, like the resolver callbacks
    context = {
        # Must be COMPLETE: anything missing reads as a removed entity and
        # produces a false invalidation. Neither source alone is complete, so
        # union them: the entity registry omits entities that have no unique
        # ID (they exist only as states), while current states omit disabled
        # entities (they exist only in the registry). Do not use the
        # display/UI registry endpoint, which also drops disabled entities.
        "known_entity_ids": set(registry_entity_ids()) | set(state_entity_ids()),
        "ha_version": hass_version(),
    }
    # Core integrations do not carry manifest.version (Home Assistant requires
    # it only for custom integrations), so integration_version is available for
    # custom integrations alone. Omit it rather than inventing one: an omitted
    # key leaves that trigger unevaluated, while a wrong value invalidates
    # correct profiles. Profiles for core-integration entities should pin
    # ha_version instead.
    version = manifest_version(integration_of(entity_id))
    if version is not None:
        context["integration_version"] = version
    return context

# Register all MESA tools
register_mesa_tools(
    store=store,
    adapter="fastmcp",
    server=app,
    enforcer=enforcer,
    lease_manager=lease_manager,
    caller_context_fn=get_caller_context,
    get_validity_context=get_validity_context
)

# Register the MESA-enforced service tool (see "The service tool" below).
app.tool()(build_call_ha_service(enforcer, get_caller_context, perform_ha_call))
```

**The service tool.** This is `examples/ha_service_tool.py` in full, embedded
verbatim. The test suite imports that file, registers the tool against both
supported FastMCP lineages, asserts its published schema, exercises the guard
against every reserved target key, and covers the allowed, confirm, and
prohibited paths; a further test executes the block below in an empty namespace
and asserts this document matches the file. Copyable text that no test runs is
how several enforcement gaps reached this project, so the two are one object.

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from mesa_core import HA_TARGET_SELECTOR_KEYS, MesaEnforcer
from mesa_core.exceptions import MesaEnforcementError
from mesa_core.privacy import CallerContext

# Every way a Home Assistant action can name what it acts on. An entity-targeted
# tool accepts none of them in its service data: each can reach entities this
# call never evaluated, and only the host can resolve one.
#
# This guard belongs to the entity-targeted path. A few entityless services take
# an ordinary data field named `target` (`notify.notify` names its recipients
# with it), so a tool spanning both shapes must route on the service's schema
# and apply this only where an entity is the target.
RESERVED_TARGET_KEYS: frozenset[str] = frozenset(
    {"entity_id", "target", *HA_TARGET_SELECTOR_KEYS}
)


def build_call_ha_service(
    enforcer: MesaEnforcer,
    get_caller_context: Callable[[], CallerContext],
    perform_ha_call: Callable[[str, str, dict[str, Any]], Awaitable[Any]],
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build the MESA-enforced service tool to register with your server."""

    async def call_ha_service(
        domain: str,
        service: str,
        entity_id: str,
        service_data: dict[str, Any] | None = None,
        confirmation_token: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Snapshot the caller's data ONCE, before validating it. Everything
        # below reads this copy: the dict belongs to the caller, evaluation
        # suspends at an await, and re-reading the original afterwards would
        # let a concurrent mutation forward a call that was never the one
        # evaluated. Check, evaluate, and execute must all see the same bytes.
        data = dict(service_data or {})

        # This tool is entity-targeted, so service data carries service data
        # only. Home Assistant also lets an action name its target as a device,
        # area, floor, label, or config entry, or in a nested `target` block,
        # and any of those can reach entities this call never evaluated. Reject
        # them rather than forward them: a decision covers exactly the entity it
        # was made for. See "Multi-target calls" for the multi-entity path.
        stray = RESERVED_TARGET_KEYS & set(data)
        if stray:
            raise MesaEnforcementError(
                f"service_data must not carry target fields {sorted(stray)}; "
                "this tool acts on the entity_id argument"
            )

        # Pass the REAL parameters: a declared limit whose parameter is absent
        # from service_params is skipped, so dropping service_data here would
        # silently drop volume, brightness, and temperature caps (Spec 6.4).
        # The validated target goes last so nothing a caller sends displaces it.
        result = await enforcer.aevaluate(
            entity_id=entity_id,
            service=f"{domain}.{service}",
            service_params={**data, "entity_id": entity_id},
            caller_context=get_caller_context(),
            current_time=datetime.now(),
            # On resubmission, the token the user approved. The enforcer
            # verifies the round-trip and that the parameters still match the
            # approved ones (Spec 6.6).
            confirmation_token=confirmation_token,
        )
        if not result.allowed:
            if result.confirmation_challenge is not None:
                # control_mode: confirm. Not a refusal: hand the challenge back
                # to the agent, which shows the user what is about to happen and
                # resubmits this call with the approved token. Raising here
                # instead turns every confirm entity into a prohibited one.
                return {"requires_confirmation": result.confirmation_challenge}
            raise MesaEnforcementError(result.reason)

        # The same snapshot, and the validated target last here too: the call
        # that executes must be the call that was approved.
        call_data = {**data, "entity_id": entity_id}
        return {"ok": True, "result": await perform_ha_call(domain, service, call_data)}

    return call_ha_service


# Your Home Assistant client. mesa-core never calls HA itself.
async def perform_ha_call(domain: str, service: str, data: dict[str, Any]) -> Any:
    ...
```

**Multi-target calls.** A MESA decision covers exactly the entity it was
evaluated for. Home Assistant actions routinely target more than one, and
Home Assistant itself recommends `device_id` for device-level actions and
`config_entry_id` for config-entry-level ones, so this is ordinary integration
work rather than an exotic case. `MesaEnforcer` refuses a call whose parameters
carry an alternate target, because it cannot resolve a selector and must not
approve a decision that would reach entities it never considered. The host owns
that expansion:

1. **Separate target from data.** Take `entity_id`, `device_id`, `area_id`,
   `floor_id`, `label_id`, `config_entry_id`, and any nested `target` block out
   of the service data. What remains is service data, and it is what carries the
   parameters declared limits are written against.
2. **Expand every selector to entities** through the HA registries, the same
   knowledge `expand_target` supplies to `TriggerValidator`. Remember that an
   entity inherits its device's area, so an area selector reaches entities whose
   own `area_id` is unset.
3. **Require the expansion to be complete, and deny otherwise.** Home
   Assistant's target extraction reports what it could not resolve alongside
   what it could. Treat a failed expansion, an unknown device, area, floor,
   label, or config entry, or an empty resolved set as a denial. An empty set is
   the trap: "every decision allowed" is vacuously true of no decisions, so an
   unresolvable target would otherwise read as approval.
4. **Evaluate each resolved entity** with the shared service data. Policy
   differs per entity: a `light.turn_on` across an area may be autonomous for
   most lights and `confirm` or `prohibited` for one.
5. **Require every decision to allow before acting.** A partial call is the
   dangerous outcome: it executes against the permitted entities and leaves the
   agent believing the whole action succeeded. Deny the action and report which
   entities blocked it.
6. **Execute against the frozen set you evaluated,** listing those entity IDs
   explicitly. Forwarding the original area or label selector to Home Assistant
   reopens the gap between check and execution: membership can change in
   between, and the call would reach entities no decision covered.
7. **Confirm per entity.** Each `confirm` entity produces its own challenge
   bound to its own parameters, and each token is single-use and matched against
   exactly the entity, service, and parameters challenged. Present them together
   if you like, but resubmit each with its own token; there is no token that
   approves a group.

**Actions with no entity representation.** Some device-level and
config-entry-level actions genuinely address no entity, and enforcement has no
answer for them. Be precise about why, because MESA 1.1 does have device-scoped
profiles: a device profile is resolved through inheritance and governs the
entities that device owns, so it already shapes enforcement for every one of
them. What it does not do is give `MesaEnforcer` a way to decide a call that
names a device or config entry and no entity at all. Enforcement evaluates one
entity, and there is no entity here to evaluate.

Deny such calls at the MESA boundary and gate them with your own authorisation,
rather than expanding them to an empty entity set and reading that as approval.
Direct enforcement of entityless targets may come in a later version; until it
does, silence is not permission.

### 6.3 Framework Adapters

mesa-core provides adapters for the two most common MCP Python frameworks.

**FastMCP adapter.** Used when the host server uses the FastMCP framework. `register_mesa_tools()` with `adapter="fastmcp"` registers tools as FastMCP tool functions. FastMCP derives a tool's published `inputSchema` by introspecting the registered function, so the adapter builds each function's signature from that tool's declared schema (Section 9): the schema a client is shown and the schema the server enforces are the same artifact, and the input shapes documented in Specification 9.5 are what the tools accept.

**Raw MCP Python SDK adapter.** Used when the host server uses the raw `mcp` Python SDK. `register_mesa_tools()` with `adapter="raw_sdk"` registers tools as raw MCP tool handlers.

**Custom adapter.** Host servers using other frameworks implement the `ToolRegistry` protocol:

```python
from mesa_core.mcp.adapters import ToolHandler, ToolRegistry

class MyFrameworkRegistry:
    def register_tool(
        self, name: str, handler: ToolHandler, schema: dict, description: str
    ) -> None:
        # register into your framework's tool system
        ...

register_mesa_tools(store=store, adapter=MyFrameworkRegistry(), server=app)
```

Import both names. Python evaluates annotations eagerly before 3.14, so
annotating `handler` with a `ToolHandler` you did not import raises
`NameError` at class definition time on the 3.12 and 3.13 interpreters this
package supports (3.14 defers annotation evaluation, so it does not raise
there: an example that works on your interpreter can still break a user's).

All four parameters are required: `register_mesa_tools` passes the tool's
description positionally alongside its schema, so a `register_tool` accepting
only three raises `TypeError`. `handler` is a `ToolHandler`, an async callable
taking the parsed parameter dict and returning the response dict.

---

### 6.4 Host Callback Reference

mesa-core never talks to Home Assistant. Every piece of HA registry or state knowledge arrives through a host-supplied callback, and every absent callback degrades conservatively: unevaluable always tightens, never loosens. This table is the single reference for what each callback feeds and what you lose without it.

| Callback | Consumed by | Without it |
|---|---|---|
| `get_entity_area` | `ProfileStore` / `InheritanceResolver` | Area-level inheritance is skipped; `query(areas=...)` raises `ValueError`. |
| `get_entity_integration` | `InheritanceResolver` | Integration sidecar profiles resolve only where the integration name equals the entity's HA domain; hub and device integration profiles stay inert (Specification 5.6). `query(integrations=...)` raises `ValueError`. |
| `get_entity_device` | `ProfileStore` / `InheritanceResolver` | Device-level inheritance is skipped entirely; device-scope profiles are inert (Specification 5.6); `query(devices=...)` raises `ValueError`. |
| `get_state` | `MesaEnforcer`, `LeaseManager` (accepted by `TemporalEvaluator` for future entity-state condition types; unused there in 1.x) | Declared-limit predicates are treated as active (fail-closed), so limits may block unexpectedly; protected automations deny leases unconditionally. |
| `get_calendar_events` | `TemporalEvaluator` | `calendar_entity` conditions are unevaluable and treated as active (fail-closed). Note `duration` and `relative_to_event` conditions validate but are unevaluable in 1.x regardless, and also fail closed. |
| `get_solar_elevation` | `TemporalEvaluator` (via `MesaEnforcer`) | `solar_angle` conditions are unevaluable and treated as active (fail-closed). |
| `get_automation_configs` | `TriggerValidator` (per call) | No automation cross-reference is possible. |
| `expand_target` | `TriggerValidator`, `entities_by_role` | Indirect references (device triggers, purpose-specific trigger target selectors) are invisible; a stale `none` declaration behind them passes unflagged. |
| `caller_context_fn` | `register_mesa_tools` | Tools respond as an anonymous, role-less caller; lease session scoping degrades. |
| `get_semantic_moments` | `register_mesa_tools` / `MesaToolHandlers` | `mesa_get_profile` never includes the `semantic_moments` block; agents fall back to profile-declared automation semantics. |
| `get_validity_context` | `register_mesa_tools` / `MesaToolHandlers` | The `profile_valid_for` registry and version triggers cannot be evaluated, so an invalidated profile keeps reporting `staleness_status: current` and no invalidation warning is surfaced (Specification 5.4, 5.5). `review_after_days` is evaluated either way. Called once per entity, with that entity's ID. Must be synchronous, like the resolver callbacks: an `async def` returns a coroutine rather than a context, which mesa-core refuses with a logged warning rather than reading as an empty context. Values are type-checked, and a wrong-typed one is dropped with a warning; `known_entity_ids` must be a reusable collection of entity IDs (a set, list, tuple, or any other `Collection[str]`): a generator or a bare string is refused, because the callback runs once per entity and a one-shot value reused across those calls would be drained by the first row of a query. |
| `on_lease_event` | `LeaseManager` | `mesa_lease_expired` events are not bridged to the HA event bus. |

---

## 7. Conformance Test Suite

The mesa-core package ships a conformance test suite that any MESA implementation can run against itself. Tests are written with pytest and can be run independently of the host server.

### 7.1 Running the Suite

```bash
git clone https://github.com/leecaochang/mesa-core
cd mesa-core
pip install -e ".[test]"
pytest tests/conformance/ -v
```

The conformance suite runs from a source checkout. The `tests/` directory is not shipped inside the installed package.

### 7.2 Test Categories

**Kernel field validation (`test_kernel.py`).** Verifies that profiles missing required kernel fields are correctly identified. Tests that absent `control_mode` defaults to `confirm`. Tests that absent `triggers_automations` defaults to `unknown`. Tests that absent `metadata_origin` defaults to `source: unknown`, and to `source: developer` when loaded via `import_from_integration()`. Tests each valid enum value for each kernel field.

**Control mode (`test_control_mode.py`).** Tests that `prohibited` blocks service calls in enforced mode. Tests that `read_only` blocks write calls regardless of enforcement mode. Tests that `confirm` generates a warning but does not block in advisory mode. Tests that `confirm` is treated as `prohibited` when no interaction channel is present. Tests the tightening-only precedence rule. Tests the operator loosening override: an entity-level `user`-origin profile with `override_control_mode: true` loosens an inherited `confirm`; the override is rejected from `inferred_ai` origin, rejected without `control_reason`, and rejected against `prohibited` or `read_only`. Tests that `control_reason` is surfaced in enforcement error messages. Tests the confirmation round-trip in enforced mode: first call denied with a challenge; re-submission with a valid token allowed; expired, reused, or parameter-mismatched tokens rejected.

**Profile inheritance (`test_inheritance.py`).** Tests multi-level inheritance with no conflicts. Tests domain-level default applied to entity with no entity-level profile. Tests area-level override of domain-level default. Tests entity-level override of area-level profile. Tests `triggers_automations: likely` stickiness across levels (a lower-level `none` does not override a higher-level `likely`). Tests `deployment_defined` entity-level override. Tests `none` is overridden by `likely` from any level.

**Trigger validation (`test_trigger_validator.py`).** Tests that an entity declared `triggers_automations: none` is flagged when found in an automation trigger block. Tests that an entity declared `none` is flagged when found in an automation condition block. Tests that an entity declared `likely` generates no issue even when found in automations. Tests that an entity with no profile generates no false positive. Tests that validation results include correct `automation_id`, `role`, and `recommendation` fields. Tests the single-entity validation path via `validate_entity()`.

**Conflict resolution (`test_conflict.py`).** Tests Rules A through E from Specification Section 5.7. Each rule has at least three test cases: basic application, edge case, and conflict with another rule. Rule D cases include: a `user` entity-level profile overriding a `developer` domain-level default; an `inferred_ai` entity-level profile failing to override a `developer` domain-level declaration; and resolution among lower-tier profiles when no trusted-tier profile declares the field.

**Temporal constraints (`test_temporal.py`).** Tests `time_range` condition across midnight boundary. Tests `day_of_week` with single day and multiple days. Tests `calendar_entity` with active and inactive calendar events. Tests `negate: true` inversion for each condition type. Tests that temporal constraints correctly modify `control_mode` and `max_value`. Tests that an effect attempting to loosen `control_mode` below the effective base is ignored and surfaces a warning. Tests that unevaluable conditions (missing or `unavailable` entity) apply the effect, with and without `negate`.

**Privacy enforcement (`test_privacy.py`).** Tests `deny_for` role blocks access. Tests `unrestricted_for` role bypasses sensitive level restrictions. Tests unauthenticated caller treated as no-role. Tests `is_minor: true` triggers `restricted` regardless of declared level. Tests that denials surface `deny_response_mode` so the host can apply `omit`, `redact`, or `error` response shaping.

**Inferred profile rules (`test_inferred.py`).** Tests that `inferred_ai` profiles missing `confidence` are malformed. Tests that `inferred_ai` profiles missing `generated_at` are malformed. Tests that `confidence >= 0.7` allows use for non-safety decisions. Tests that `control_mode` from inferred profiles only applies when it tightens. Tests that helper-domain inferred profiles default `triggers_automations` to `likely`. Tests staleness status computation at day 0, day 30, and day 61.

### 7.3 Malformed Profile Fixtures

The test suite ships five malformed profile JSON files that MUST be rejected by any conforming Level 1 implementation.

**missing_confidence.json.** An `inferred_ai` profile without a `confidence` field.

**missing_generated_at.json.** An `inferred_ai` profile without a `generated_at` field.

**invalid_operator.json.** A declared limit using `equals` instead of `eq` as the predicate operator.

**invalid_control_mode.json.** A profile with `control_mode: yolo` (not a valid enum value). Also verifies that `read_only` and `prohibited` values are accepted and that `read_only` cannot be loosened by an operator override.

**trust_laundering.json.** A profile with `source: developer` on what is clearly AI-generated content (contains `inferred_ai` indicators in the raw data). This tests whether the host implementation surfaces a warning.

---

## 8. Version Scope

mesa-core 1.x implements the MESA Specification at Levels 1 and 2 in full and at Level 3 including the retrieval API, enforcement, and the lease coordination tools; multi-agent lease preemption is the one Level 3 capability that waits for Version 2. The focus is on correctness and simplicity over completeness.

### Included in Version 1.0

**Profile storage.** JsonFileBackend, SqliteBackend, MemoryBackend. Full CRUD operations. Deployment defaults. Orphan detection via `find_orphans()`.

**SemanticProfile dataclass.** All kernel fields. All fields from Specification Sections 5 through 8. Serialisation and deserialisation from JSON/dict.

**Canonical JSON Schema.** A machine-readable JSON Schema file (`mesa_core/schemas/mesa_profile.schema.json`) defining the complete MESA profile structure as specified in the Specification. This is the canonical artifact for third parties, who can consume it directly without reimplementing validation from prose tables. A separate `mesa_tools.schema.json` defines the input schemas for all MCP tools.

**Profile validation.** Kernel field presence checks. Enum value validation for `control_mode`, `triggers_automations`, `privacy_classification.level`. Predicate operator validation (canonical tokens and `ha_condition` type). Tag format validation (canonical or `vendorname.qualifier`). Malformed inferred profile detection. Validation is hand-rolled to keep the core dependency-free; a dedicated test asserts it stays in agreement with the canonical JSON Schema on every fixture.

**TriggerValidator.** Live cross-reference of declared `triggers_automations: none` profiles against actual HA automation configurations. Uses host-provided callback for automation data. Returns `ValidationIssue` list. Runs at startup and on automation reload.

**Profile migration.** `migrate_profile(profile, target_version)` utility and migration framework. Documents without a `schema_version` are treated as 1.0-era and stamped through the migration path. The 1.0-to-1.1 step (mesa-core 1.3) restamps the version; the 1.1 format is purely additive, so no field conversions apply. Field renames, enum value changes, and structural reorganisations land here when a schema revision first requires them.

**Integration profile import.** `import_from_integration(integration_path)` loads a developer profile from an integration directory's `mesa_profile.json`. Returns a `SemanticProfile` with `inheritance_scope: integration`. Profiles that omit `metadata_origin` are stamped `source: developer`, per Specification Section 5.3; profiles loaded from any other source default to `source: unknown`. Host servers call this at startup for each installed integration to populate the `ProfileStore`. Requires filesystem access to the integration directories; hosts running on a separate machine from HA cannot use this import path and rely on operator-authored profiles instead.

**InheritanceResolver.** Four-level inheritance (domain, integration, area, entity; the device level arrived in 1.3). Deployment defaults as floor. Conflict resolution Rules A through E. `triggers_automations` stickiness and override. `control_mode` tightening.

**MesaEnforcer.** `control_mode` evaluation (advisory and enforced modes). Confirmation challenge/token round-trip for `confirm` entities in enforced mode (Specification Section 6.6): challenge issuance, token validation, parameter binding, single-use and expiry handling. Declared limits evaluation. Privacy enforcement. Caller context role resolution. Inferred profile confidence checking (Rules 3 and 8).

**TemporalEvaluator.** `time_range` condition (including midnight boundary). `day_of_week` condition. `calendar_entity` condition (requires host callback).

**PrivacyEnforcer.** All four privacy levels. Role-based access (`unrestricted_for`, `restricted_for`, `deny_for`). `is_minor` mandatory restricted override. `deny_response_mode` all three values.

**MCP tools.** `mesa_query_profiles` with full filtering and pagination. `mesa_get_profile`. `mesa_explain_profile`. `mesa_get_caller_context` (returns the host-provided caller context; required for Level 3). Adapters for FastMCP and raw MCP Python SDK.

**Conformance test suite.** All seven test categories. All five malformed profile fixtures.

### Added in Version 1.1

**Typed person traits.** `PersonTraits` (Enrichment Section 17) on `SemanticProfile`, resolved per-field under Rule D, so `is_minor` declared at any inheritance scope reaches privacy enforcement. Validation covers the `household_role` enum and boolean `is_minor` (mirrored in the canonical JSON Schema); `household_role` is RECOMMENDED, not required.

**ProfileStore async parity.** Async variants for domain-, integration-, and area-scope profile get/set, deployment defaults, and key enumeration, plus `explain()` / `aexplain()` delegation, completing the "every public method has an async variant" contract of Section 4.2.

**Indirect automation references.** The `expand_target` callback on `TriggerValidator` and `entities_by_role` resolves `area_id` / `floor_id` / `label_id` / `device_id` selectors (device triggers, and the target blocks of HA 2026.7+ purpose-specific triggers) so stale `triggers_automations: none` declarations behind indirect references are caught. See Section 4.8.

**Lease protocol.** `LeaseManager` with request, release, session release, and automatic (lazy) expiry; `mesa_lease_expired` events via the `on_lease_event` callback; protected/critical automation denial (fail-closed); `binary_sensor.mesa_lease_active` state via `sensor_state()`; and the `mesa_request_lease` / `mesa_release_lease` MCP tools, registered when `register_mesa_tools` receives a `lease_manager`. Overlapping requests are resolved existing-holder-wins; priority preemption (Enrichment 21.6) remains v2. See Section 4.10.

**Audit event schema.** The standardised `mesa_audit_event` structure for access to sensitive/restricted entities, enforcement decisions, and lease/coordination events, emitted by `PrivacyEnforcer`, `MesaEnforcer`, and `LeaseManager` on the `mesa_core.audit` logger. Fields: `timestamp`, `caller_id`, `roles`, `entity_id`, `action`, `decision`, `profile_version`, `rule_applied`, `redaction_mode`, plus `event_type` and an extensible `details` object. See Section 4.11.

### Added in Version 1.2

**Profile export and import.** `export_profiles()` / `import_profiles()` and their async variants: the portable archive format for moving complete profile sets between deployments, backends, and host servers. Faithful export, validated import, explicit conflict policy. See Section 4.12. The `mesa-lint` CLI also shipped in this cycle as a separate package (https://github.com/leecaochang/mesa-lint).

**Solar-angle temporal conditions.** The `solar_angle` condition type evaluates through the `get_solar_elevation` host callback: each `solar_event` is an elevation-boundary crossing, and `solar_offset_minutes` shifts the transition by sampling the elevation in the past. No astronomy dependency; without the callback the condition stays fail-closed as in 1.1. See Section 4.7.

**Semantic moments (HA 2026.7+ purpose-specific triggers).** `mesa_get_profile` accepts `include_semantic_moments` and, when the host supplies the `get_semantic_moments` callback, returns the purpose-specific triggers and conditions the entity participates in. Consumed live from HA at request time, never stored in profiles (so it cannot go stale), never consulted by enforcement, and documented as carrying no MESA authority.

The callback returns `list[dict]`, one entry per moment, each carrying at least a string `id`; entries without one are dropped. This is not the shape Home Assistant hands you. The WebSocket registry operations return the triggers and the conditions an entity participates in as separate arrays of identifiers, so the host writes the adapter: fetch both, tag each identifier with which kind it came from, and emit the merged list. For example, `[{"id": t, "kind": "trigger"} for t in triggers] + [{"id": c, "kind": "condition"} for c in conditions]`. mesa-core deliberately does not do this itself, because the operation names and payload shapes are HA version territory and would date the library.

### Added in Version 1.3

**Device inheritance scope (MESA 1.1).** The fifth inheritance level, keyed by HA device registry ID and ranked between entity and area: `get/set/delete_device_profile`, `device_keys()`, the `get_entity_device` host callback on `ProfileStore` and `InheritanceResolver`, the `__device__:` reserved namespace, a `devices` archive section, and `device` in the `inheritance_scope` enum and explanation `provided_by_level`. Profile format `schema_version` is now `1.1`; the 1.0-to-1.1 migration step restamps documents on request. The Rule A and Rule B loosening overrides remain entity-only.

**Query filters.** `query(devices=...)` and `query(integrations=...)` (and the matching `mesa_query_profiles` parameters), each requiring its host mapping callback and raising `ValueError` without it, mirroring `areas`.

**Capability hint resolution.** `capability_semantics.control_mode` on an integration-scoped profile participates in Rule A as that profile's contribution when `operational_boundaries.control_mode` is absent, attributed below every operational_boundaries declaration (Specification Section 4). The enum is now validated in both the validator and the canonical JSON Schema.

**Profile validity evaluation.** `SemanticProfile.validity_warnings(now=..., known_entity_ids=..., integration_version=..., ha_version=...)` evaluates the `profile_valid_for` invalidation triggers (Specification 5.5) and returns advisory warnings. Each check runs only when the host supplies the corresponding input.

**Scoped orphan detection.** `find_orphans` keyword arguments extend orphan detection to domain, integration, area, and device profiles.

**Fail-closed lease profile parsing.** Malformed Enrichment Section 11 fields on automation profiles (`cooperative_priority.level`, `trigger_entities`, `condition_entities`, `affected_entities`) now deny leases with a surfaced warning instead of silently losing protection. Lease timestamps are timezone-aware UTC.

**MCP corrections.** `mesa_version` reports `1.1`; `component_type` is derived from the entity ID's domain (previously always `entity`); the raw SDK adapter returns an `unknown_tool` error envelope instead of raising for unregistered tool names.

### Deferred to Version 2

**Temporal evaluator: relative_to_event and duration conditions.** Require HA event bus integration. Architecture is defined; implementation deferred.

**Multi-agent lease collision resolution.** `caller_priority` field, role-to-priority mapping, preemption notification. Deferred until multiple agents in a single deployment is a common real-world scenario.

**Snapshot management for `snapshot_restorable` automations.** Requires integration with HA state history. Architecture is defined; implementation deferred.

**`binary_sensor.mesa_lease_active` HA entity.** Requires the host server to write to HA's entity registry. Implementation deferred to allow host servers to implement it natively.


---

## 9. Future Versions

**Version 2.0.** Multi-agent lease collision resolution. Snapshot management for reversible automations. `binary_sensor.mesa_lease_active` entity support. Additional framework adapters (Node.js MCP SDK if demand exists).

**Version 3.0.** Semantic graph queries (find all entities connected to an automation via environmental dependencies). Graph-based conflict detection. Spatial leakage traversal queries. These require Version 2 to be stable in production first.

**Version 3.0 (continued): Native HA service interceptor.** A `custom_components/mesa` Home Assistant custom component that integrates MESA enforcement at the HA core level, allowing MESA boundaries to apply regardless of which client (MCP, WebSocket, REST, or script) issues a service call. This requires upstream HA cooperation or a stable HA internal hook API that does not currently exist. The approach of patching `hass.services.async_register` from a custom component is fragile and unsupported in HA 2025+; this item is deferred until HA exposes a formal service interceptor middleware API or until the MESA community has sufficient standing to propose it as an upstream HA feature.

---

## 10. Distribution and Installation

mesa-core is a Python library for MCP server developers. It is distributed via PyPI. End users never install mesa-core directly. They install the MCP server that bundles it as a dependency.

**For MCP server developers:**

```bash
# Install in your development environment
pip install mesa-core           # SQLite backend included (stdlib sqlite3)
pip install mesa-core[test]     # with test suite

# Add as a dependency in your server's pyproject.toml
# [project]
# dependencies = ["mesa-core>=1.0"]
```

MCP server developers import mesa-core as a library dependency, integrate it into their server, and ship their server through whatever mechanism they use. mesa-core is bundled as a transitive dependency, invisible to end users.

Do not fork mesa-core to customise it. Subclass or extend the relevant components instead. This ensures your server continues to receive specification updates as mesa-core versions advance.

**From source:**

```bash
git clone https://github.com/leecaochang/mesa-core
cd mesa-core
pip install -e ".[test]"
pytest
```

---

## 11. Dependencies

**Required (core):**

- Python 3.12 or later
- No external dependencies for the core package. All profile parsing, inheritance resolution, conflict resolution, temporal evaluation, and privacy enforcement use only the Python standard library.

**Optional:**

- `fastmcp` (for the FastMCP adapter)
- `mcp` (for the raw MCP Python SDK adapter)
- `pytest` and `jsonschema` (for the conformance test suite)

SqliteBackend uses the standard library `sqlite3` module; async access is provided by thread offload, so no `aiosqlite` dependency is required.

**Explicitly excluded:**

- No HA Python library dependency. mesa-core does not import `homeassistant`. It receives HA data through callbacks provided by the host server. This keeps mesa-core usable in any Python environment, not only inside a running HA instance.
- No HTTP client dependency. mesa-core does not make network calls. All HA API interactions go through host-provided callbacks.

---

*mesa-core is the reference implementation of the MESA Specification. It is designed to be the lowest-friction path to MESA conformance for any MCP server developer. Issues, pull requests, and conformance test contributions are welcome via GitHub.*
