# mesa-core: MESA Reference Module Proposal
**Version:** 1.0
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
5. [MCP Tool Registration](#5-mcp-tool-registration)
   - 5.1 [register_mesa_tools()](#51-register_mesa_tools)
   - 5.2 [Tool Implementations](#52-tool-implementations)
6. [Integration Guide](#6-integration-guide)
   - 6.1 [Minimal Integration (Level 1)](#61-minimal-integration-level-1)
   - 6.2 [Full Integration (Level 3)](#62-full-integration-level-3)
   - 6.3 [Framework Adapters](#63-framework-adapters)
7. [Conformance Test Suite](#7-conformance-test-suite)
8. [Version 1 Scope](#8-version-1-scope)
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

**Profile inheritance and conflict resolution.** When a single entity has profiles at multiple levels (domain, area, entity), mesa-core resolves them into a single effective profile following the rules defined in the MESA Specification (Sections 5.6 and 5.7). The host server receives a fully resolved profile without needing to understand the inheritance logic.

---

## 2. Architecture Overview

```
Host MCP Server (ha-mcp, ATM, or any other)
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
            mesa_profile.schema.json   # Canonical JSON Schema for MESA profiles (v1.0)
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
            manager.py           # LeaseManager: request, release, expire (ships in v1.1)
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
    schema_version: str = "1.0"
    profile_version: Optional[str] = None
    source: MetadataOrigin = MetadataOrigin.UNKNOWN
    confidence: Optional[float] = None
    generated_at: Optional[str] = None
    staleness_window_days: int = 60
    confirmed_fields: List[str] = field(default_factory=list)
    last_updated: Optional[str] = None
    profile_valid_for: Optional[Dict[str, Any]] = None

@dataclass
class SemanticProfile:
    entity_id: str
    semantic_tags: List[str] = field(default_factory=list)
    metadata: ProfileMetadata = field(default_factory=ProfileMetadata)
    operational_boundaries: OperationalBoundaries = field(default_factory=OperationalBoundaries)
    privacy_classification: PrivacyClassification = field(default_factory=PrivacyClassification)
    inheritance_scope: str = "entity"
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, entity_id: str, data: dict) -> "SemanticProfile":
        """Parse a profile from raw JSON/dict representation."""
        ...

    def to_dict(self) -> dict:
        """Serialise to JSON-compatible dict."""
        ...

    def is_inferred(self) -> bool:
        return self.metadata.source == MetadataOrigin.INFERRED_AI

    def effective_confidence(self, current_date) -> float:
        """Compute degraded confidence for inferred profiles."""
        ...
```

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

# List all profiles with optional filtering
profiles = store.list(domain="light", tags=["lighting.ambient"])

# Get deployment defaults
defaults = store.get_deployment_defaults()

# Set deployment defaults
store.set_deployment_defaults(defaults_dict)
```

**ProfileStore public API:**

```python
class ProfileStore:
    def __init__(self, backend: StorageBackend): ...
    def get(self, entity_id: str) -> Optional[SemanticProfile]: ...
    def get_effective(self, entity_id: str) -> SemanticProfile: ...
    def set(self, entity_id: str, profile: SemanticProfile) -> None: ...
    def delete(self, entity_id: str) -> None: ...
    # Scope profiles (domain- and area-level) have symmetric get/set/delete.
    def get_domain_profile(self, domain: str) -> Optional[SemanticProfile]: ...
    def set_domain_profile(self, domain: str, profile: SemanticProfile) -> None: ...
    def delete_domain_profile(self, domain: str) -> None: ...
    def get_area_profile(self, area_id: str) -> Optional[SemanticProfile]: ...
    def set_area_profile(self, area_id: str, profile: SemanticProfile) -> None: ...
    def delete_area_profile(self, area_id: str) -> None: ...
    # Key enumeration: stored identifiers per scope, as bare names.
    def entity_keys(self) -> List[str]: ...
    def domain_keys(self) -> List[str]: ...
    def area_keys(self) -> List[str]: ...
    def list(self,
             domain: Optional[str] = None,
             tags: Optional[List[str]] = None,
             areas: Optional[List[str]] = None,
             origin: Optional[str] = None,
             include_inferred: bool = False,
             limit: int = 50,
             cursor: Optional[str] = None) -> ProfileQueryResult: ...
    def get_deployment_defaults(self) -> DeploymentDefaults: ...
    def set_deployment_defaults(self, defaults: dict) -> None: ...
    def explain(self, entity_id: str) -> ProfileExplanation: ...
    def find_orphans(self, known_entity_ids: Iterable[str]) -> List[str]: ...

    # Async variants of all public methods
    async def aget(self, entity_id: str) -> Optional[SemanticProfile]: ...
    async def aget_effective(self, entity_id: str) -> SemanticProfile: ...
    async def aset(self, entity_id: str, profile: SemanticProfile) -> None: ...
    async def adelete(self, entity_id: str) -> None: ...
    async def alist(self, **kwargs) -> ProfileQueryResult: ...
    async def aset_many(self, profiles: Dict[str, SemanticProfile]) -> None: ...
    async def adelete_many(self, entity_ids: List[str]) -> None: ...
    async def aexplain(self, entity_id: str) -> ProfileExplanation: ...
```

**Sync and async APIs.** All public methods on `ProfileStore`, `MesaEnforcer`, `InheritanceResolver`, `TriggerValidator`, and `PrivacyEnforcer` are available in both synchronous and asynchronous variants. Async methods are prefixed with `a` (e.g. `get()` / `aget()`, `evaluate()` / `aevaluate()`). MCP servers are typically async; synchronous APIs will block the event loop in async contexts. Host servers SHOULD use async variants in production.

**Bulk operations.** `set_many()` and `delete_many()` (and their async variants `aset_many()`, `adelete_many()`) accept dictionaries and lists respectively, allowing operators to import or remove profiles for many entities in a single operation. These are essential for deployments with hundreds of entities.

**Scope enumeration.** `domain_keys()` and `area_keys()` return the domain names and area IDs that have a scope-level profile stored, as bare identifiers, mirroring `entity_keys()` for entity profiles. The reserved key scheme that separates the three scopes internally is never exposed. Pair them with `get_domain_profile()` / `get_area_profile()` to walk every stored scope profile, for instance to surface the domain and area defaults an operator has configured.

**Orphan detection.** `find_orphans(known_entity_ids)` returns stored profile keys absent from the provided entity ID list, so hosts can detect profiles orphaned by entity renames (Specification Section 5.5). Hosts SHOULD run it at startup and on `entity_registry_updated` events and surface results to the operator.

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

**JsonFileBackend.** Stores each profile as a separate JSON file in a directory. File name is the entity ID with slashes replaced by underscores. Suitable for small to medium deployments.

```python
JsonFileBackend(base_path: str, create_if_missing: bool = True)
```

**SqliteBackend.** Stores all profiles in a SQLite database. Supports efficient tag-based queries and pagination. Suitable for large deployments.

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

This default applies **only as a fallback**: it fills `control_mode` solely when no profile at any level (entity, area, or domain) declares it. It does not participate in the Rule A most-restrictive comparison, so an entity (or its area/domain) that declares `autonomous` stays `autonomous`; a restrictive default never dominates a declared value. Two practical notes for fail-closed operators:

- `prohibited` hard-blocks only when the call is evaluated in enforced mode; in advisory mode it passes with a warning. Pair a `prohibited` default with enforced evaluation. (`read_only` blocks regardless of enforcement mode, but it asserts entity nature rather than policy, so `prohibited` is the better fit for "not yet granted.")
- `control_mode` gates control (writes/service calls) only; it never gates reads. mesa-core has no blanket read-deny default, and privacy denial is role-based (`access_roles.deny_for`), not a configurable default. Read/visibility fail-closed remains the host's responsibility.

**Evaluation order:**

1. Resolve effective profile via InheritanceResolver.
2. Apply privacy enforcement via PrivacyEnforcer. If caller is in `deny_for`, block immediately.
3. Evaluate `control_mode`:
   - `read_only`: block with reason "Entity is read-only by nature: {control_reason or entity_id}".
   - `prohibited`: block with reason "Entity is prohibited by policy: {control_reason or entity_id}".
   - `confirm`: in advisory mode, add confirmation warning and surface `control_reason`. In enforced mode, deny the call and return a `confirmation_challenge`, or allow it when a valid `confirmation_token` accompanies the call (Specification Section 6.6). If no interaction channel exists, block as `prohibited`.
   - `autonomous`: proceed.
4. Evaluate temporal constraints via TemporalEvaluator.
5. Evaluate declared limits against service params.
6. Return result with any warnings.

### 4.5 InheritanceResolver

Resolves the effective profile for an entity by merging domain-level, area-level, and entity-level profiles following the MESA inheritance rules (Specification Section 5.6).

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
2. Load area-level profile for the entity's assigned area (requires HA area registry lookup via a callback the host provides).
3. Load domain-level profile from the integration that owns this entity.
4. Load deployment defaults.
5. Merge from lowest to highest precedence: defaults -> domain -> area -> entity.
6. Apply conflict resolution rules (Section 5.7) for fields present at multiple levels.
7. Apply `triggers_automations` stickiness: if any level is `likely`, effective is `likely` unless entity-level overrides with `override_triggers_automations: true`.
8. Apply `control_mode` tightening: most restrictive value wins.
9. Apply privacy most-restrictive-wins.
10. Return merged SemanticProfile.

**Host callback for area/domain lookup:**

```python
# Host provides these lookups at initialisation
resolver = InheritanceResolver(
    store=store,
    get_entity_area=lambda entity_id: "area.bedroom",   # return area ID for entity
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
- **Rule D:** Scope-then-origin for all other fields. Most specific scope wins (`entity` > `area` > `domain`) among trusted origins (`developer`, `user`, `hybrid`); origin breaks scope ties. `inferred_ai` and `unknown` never override trusted-tier declarations at any scope; among themselves the same scope-then-origin rule applies, with `inferred_ai` > `unknown`.
- **Rule E:** Absence is not a conflict. Missing fields are inherited, not defaulted.

### 4.7 TemporalEvaluator

Evaluates temporal constraints against the current time and HA state. Returns whether any constraint modifies the effective boundary.

```python
from mesa_core.temporal import TemporalEvaluator

evaluator = TemporalEvaluator(
    get_state=lambda entity_id: "on",   # callback: get current HA entity state
    get_calendar_events=lambda cal_id: []  # callback: get active calendar events
)

# Returns modified OperationalBoundaries after applying active constraints
modified_boundaries = evaluator.apply(
    boundaries=profile.operational_boundaries,
    current_time=datetime.now()
)
```

**Condition types implemented in v1:** `time_range`, `day_of_week`, `calendar_entity`. All condition types support the `negate` flag. Solar angle and relative-to-event are v2.

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
    def __init__(self, store: ProfileStore): ...

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

entities_by_role(config: dict) -> dict[str, set[str]]
# Returns {"trigger": {...}, "condition": {...}, "action": {...}}
```

Given a single automation config dict, it returns the entity IDs referenced in each block, handling the singular/plural HA section keys (`trigger`/`triggers`, etc.) transparently. This is the canonical traversal for automation configs. Hosts building reverse-reference indexes (entity -> automations that reference it) SHOULD call `entities_by_role` over their own automation configs rather than reimplementing the entity-ID walk, so that HA-config-format knowledge stays in one place. mesa-core deliberately does not provide the reverse index, relationship graph, or script/scene traversal itself; those remain host concerns layered on this primitive.

**When to run validation:** Level 2 and Level 3 host servers SHOULD run `validate_triggers_automations()` at startup and whenever the automation registry changes (detected via the `automation_reloaded` HA event). Validation results SHOULD be surfaced to operators through the server's configuration interface and included in `mesa_explain_profile` output.

### 4.9 PrivacyEnforcer

Evaluates privacy classification against caller context and returns an access decision.

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
    enforcer=enforcer,          # optional: enable enforcement tools
    lease_manager=lease_mgr,    # optional: enable lease tools (mesa-core 1.1+)
    caller_context_fn=get_ctx   # optional: function returning CallerContext for current session
)
```

If `enforcer` is not provided, the enforcement-related tools are not registered. If `lease_manager` is not provided, lease tools are not registered. This allows incremental adoption: a host server can start with just the query tools and add enforcement later.

### 5.2 Tool Implementations

**mesa_query_profiles**

Input: domain filter, tag filter, area filter, origin filter, include_inferred flag, limit, cursor.
Action: calls `store.list()` with filters, resolves effective profiles, returns paginated results.
Output: results array, total_matched, pagination metadata, caller_context if available.

**mesa_get_profile**

Input: entity_id, include_diagnostic flag.
Action: calls `store.get_effective()`, optionally fetches diagnostic profile.
Output: complete resolved profile for the entity, staleness_status for inferred profiles.

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
from mesa_core.privacy import PrivacyEnforcer
from mesa_core.lease import LeaseManager  # mesa-core 1.1+
from mesa_core.mcp import register_mesa_tools
from mesa_core.exceptions import MesaEnforcementError
from mcp.server.fastmcp import FastMCP
import httpx
from datetime import datetime

app = FastMCP("my-ha-mcp-server")

# Initialise storage
store = ProfileStore(backend=SqliteBackend("/config/mesa/mesa.db"))

# Initialise resolver with HA lookup callbacks
# These callbacks let mesa-core query HA for area and domain information
async def get_entity_area(entity_id: str) -> Optional[str]:
    # Call HA REST API to get entity's area
    ...

async def get_entity_domain(entity_id: str) -> str:
    return entity_id.split(".")[0]

resolver = InheritanceResolver(
    store=store,
    get_entity_area=get_entity_area,
    get_entity_domain=get_entity_domain
)

# Initialise enforcer
enforcer = MesaEnforcer(store=store, resolver=resolver)

# Initialise lease manager
lease_manager = LeaseManager()

# Caller context function (host server provides this)
def get_caller_context() -> CallerContext:
    # Extract from current MCP session
    ...

# Register all MESA tools
register_mesa_tools(
    store=store,
    adapter="fastmcp",
    server=app,
    enforcer=enforcer,
    lease_manager=lease_manager,
    caller_context_fn=get_caller_context
)

# Wrap your service call handler with MESA enforcement
@app.tool()
async def call_ha_service(domain: str, service: str, entity_id: str, **kwargs):
    # Evaluate MESA profile before calling HA
    result = await enforcer.aevaluate(
        entity_id=entity_id,
        service=f"{domain}.{service}",
        service_params={"entity_id": entity_id, **kwargs},
        caller_context=get_caller_context(),
        current_time=datetime.now()
    )
    if not result.allowed:
        raise MesaEnforcementError(result.reason)
    # Proceed with HA API call
    ...
```

### 6.3 Framework Adapters

mesa-core provides adapters for the two most common MCP Python frameworks.

**FastMCP adapter.** Used when the host server uses the FastMCP framework. `register_mesa_tools()` with `adapter="fastmcp"` registers tools as FastMCP tool functions with proper type annotations.

**Raw MCP Python SDK adapter.** Used when the host server uses the raw `mcp` Python SDK. `register_mesa_tools()` with `adapter="raw_sdk"` registers tools as raw MCP tool handlers.

**Custom adapter.** Host servers using other frameworks implement the `ToolRegistry` protocol:

```python
from mesa_core.mcp.adapters import ToolRegistry

class MyFrameworkRegistry:
    def register_tool(self, name: str, handler: Callable, schema: dict) -> None:
        # register into your framework's tool system
        ...

register_mesa_tools(store=store, adapter=MyFrameworkRegistry(), server=app)
```

---

## 7. Conformance Test Suite

The mesa-core package ships a conformance test suite that any MESA implementation can run against itself. Tests are written with pytest and can be run independently of the host server.

### 7.1 Running the Suite

```bash
git clone https://github.com/[owner]/mesa-core
cd mesa-core
pip install -e ".[test]"
pytest tests/conformance/ -v
```

The conformance suite runs from a source checkout. The `tests/` directory is not shipped inside the installed package.

### 7.2 Test Categories

**Kernel field validation (`test_kernel.py`).** Verifies that profiles missing required kernel fields are correctly identified. Tests that absent `control_mode` defaults to `confirm`. Tests that absent `triggers_automations` defaults to `unknown`. Tests that absent `metadata_origin` defaults to `source: unknown`, and to `source: developer` when loaded via `import_from_integration()`. Tests each valid enum value for each kernel field.

**Control mode (`test_control_mode.py`).** Tests that `prohibited` blocks service calls in enforced mode. Tests that `read_only` blocks write calls regardless of enforcement mode. Tests that `confirm` generates a warning but does not block in advisory mode. Tests that `confirm` is treated as `prohibited` when no interaction channel is present. Tests the tightening-only precedence rule. Tests the operator loosening override: an entity-level `user`-origin profile with `override_control_mode: true` loosens an inherited `confirm`; the override is rejected from `inferred_ai` origin, rejected without `control_reason`, and rejected against `prohibited` or `read_only`. Tests that `control_reason` is surfaced in enforcement error messages. Tests the confirmation round-trip in enforced mode: first call denied with a challenge; re-submission with a valid token allowed; expired, reused, or parameter-mismatched tokens rejected.

**Profile inheritance (`test_inheritance.py`).** Tests three-level inheritance with no conflicts. Tests domain-level default applied to entity with no entity-level profile. Tests area-level override of domain-level default. Tests entity-level override of area-level profile. Tests `triggers_automations: likely` stickiness across levels (a lower-level `none` does not override a higher-level `likely`). Tests `deployment_defined` entity-level override. Tests `none` is overridden by `likely` from any level.

**Trigger validation (`test_trigger_validator.py`).** Tests that an entity declared `triggers_automations: none` is flagged when found in an automation trigger block. Tests that an entity declared `none` is flagged when found in an automation condition block. Tests that an entity declared `likely` generates no issue even when found in automations. Tests that an entity with no profile generates no false positive. Tests that validation results include correct `automation_id`, `role`, and `recommendation` fields. Tests the single-entity validation path via `validate_entity()`.

**Conflict resolution (`test_conflict.py`).** Tests Rules A through E from Specification Section 5.7. Each rule has at least three test cases: basic application, edge case, and conflict with another rule. Rule D cases include: a `user` entity-level profile overriding a `developer` domain-level default; an `inferred_ai` entity-level profile failing to override a `developer` domain-level declaration; and resolution among lower-tier profiles when no trusted-tier profile declares the field.

**Temporal constraints (`test_temporal.py`).** Tests `time_range` condition across midnight boundary. Tests `day_of_week` with single day and multiple days. Tests `calendar_entity` with active and inactive calendar events. Tests `negate: true` inversion for each condition type. Tests that temporal constraints correctly modify `control_mode` and `max_value`. Tests that an effect attempting to loosen `control_mode` below the effective base is ignored and surfaces a warning. Tests that unevaluable conditions (missing or `unavailable` entity) apply the effect, with and without `negate`.

**Privacy enforcement (`test_privacy.py`).** Tests `deny_for` role blocks access. Tests `unrestricted_for` role bypasses sensitive level restrictions. Tests unauthenticated caller treated as no-role. Tests `is_minor: true` triggers `restricted` regardless of declared level. Tests `deny_response_mode: redact` returns placeholder not entity data.

**Inferred profile rules (`test_inferred.py`).** Tests that `inferred_ai` profiles missing `confidence` are malformed. Tests that `inferred_ai` profiles missing `generated_at` are malformed. Tests that `confidence >= 0.7` allows use for non-safety decisions. Tests that `control_mode` from inferred profiles only applies when it tightens. Tests that helper-domain inferred profiles default `triggers_automations` to `likely`. Tests staleness status computation at day 0, day 30, and day 61.

### 7.3 Malformed Profile Fixtures

The test suite ships five malformed profile JSON files that MUST be rejected by any conforming Level 1 implementation.

**missing_confidence.json.** An `inferred_ai` profile without a `confidence` field.

**missing_generated_at.json.** An `inferred_ai` profile without a `generated_at` field.

**invalid_operator.json.** A declared limit using `equals` instead of `eq` as the predicate operator.

**invalid_control_mode.json.** A profile with `control_mode: yolo` (not a valid enum value). Also verifies that `read_only` and `prohibited` values are accepted and that `read_only` cannot be loosened by an operator override.

**trust_laundering.json.** A profile with `source: developer` on what is clearly AI-generated content (contains `inferred_ai` indicators in the raw data). This tests whether the host implementation surfaces a warning.

---

## 8. Version 1 Scope

Version 1 of mesa-core implements the MESA Specification at Level 1 and Level 2, with partial Level 3 support. The focus is on correctness and simplicity over completeness.

### Included in Version 1

**Profile storage.** JsonFileBackend, SqliteBackend, MemoryBackend. Full CRUD operations. Deployment defaults. Orphan detection via `find_orphans()`.

**SemanticProfile dataclass.** All kernel fields. All fields from Specification Sections 5 through 8. Serialisation and deserialisation from JSON/dict.

**Canonical JSON Schema.** A machine-readable JSON Schema file (`mesa_core/schemas/mesa_profile.schema.json`) defining the complete MESA profile structure as specified in the Specification. This is the authoritative validation artifact; `validation.py` uses it, and third-party tools can consume it directly without reimplementing validation from prose tables. A separate `mesa_tools.schema.json` defines the input and output schemas for all MCP tools.

**Profile validation.** Kernel field presence checks. Enum value validation for `control_mode`, `triggers_automations`, `privacy_classification.level`. Predicate operator validation (canonical tokens and `ha_condition` type). Tag format validation (canonical or `vendorname.qualifier`). Malformed inferred profile detection. All validation is driven by the canonical JSON Schema.

**TriggerValidator.** Live cross-reference of declared `triggers_automations: none` profiles against actual HA automation configurations. Uses host-provided callback for automation data. Returns `ValidationIssue` list. Runs at startup and on automation reload.

**Profile migration.** `migrate_profile(profile, target_version)` utility converts profiles from older schema versions to the current version. Handles field renames, enum value changes, and structural reorganisations. Returns a migrated copy without modifying the original. Logs all transformations applied.

**Integration profile import.** `import_from_integration(integration_path)` loads a developer profile from an integration directory's `mesa_profile.json`. Returns a `SemanticProfile` with `inheritance_scope: domain`. Profiles that omit `metadata_origin` are stamped `source: developer`, per Specification Section 5.3; profiles loaded from any other source default to `source: unknown`. Host servers call this at startup for each installed integration to populate the `ProfileStore`. Requires filesystem access to the integration directories; hosts running on a separate machine from HA cannot use this import path and rely on operator-authored profiles instead.

**InheritanceResolver.** Three-level inheritance (domain, area, entity). Deployment defaults as floor. Conflict resolution Rules A through E. `triggers_automations` stickiness and override. `control_mode` tightening.

**MesaEnforcer.** `control_mode` evaluation (advisory and enforced modes). Confirmation challenge/token round-trip for `confirm` entities in enforced mode (Specification Section 6.6): challenge issuance, token validation, parameter binding, single-use and expiry handling. Declared limits evaluation. Privacy enforcement. Caller context role resolution. Inferred profile confidence checking (Rules 3 and 8).

**TemporalEvaluator.** `time_range` condition (including midnight boundary). `day_of_week` condition. `calendar_entity` condition (requires host callback).

**PrivacyEnforcer.** All four privacy levels. Role-based access (`unrestricted_for`, `restricted_for`, `deny_for`). `is_minor` mandatory restricted override. `deny_response_mode` all three values.

**MCP tools.** `mesa_query_profiles` with full filtering and pagination. `mesa_get_profile`. `mesa_explain_profile`. `mesa_get_caller_context` (returns the host-provided caller context; required for Level 3). Adapters for FastMCP and raw MCP Python SDK.

**Conformance test suite.** All seven test categories. All five malformed profile fixtures.

### Deferred to Version 1.1

**Lease protocol.** `LeaseManager` with basic request and release. Single-agent lease management. Automatic expiry. `mesa_lease_expired` event. Deferred from v1.0 because the lease protocol is advisory-only, native automations ignore it, and the primary value of mesa-core v1.0 is the kernel, enforcement, and profile management. Lease support will be added once the Core specification has real-world validation.

**Audit event schema.** Standardised `mesa_audit_event` structure for logging access to sensitive/restricted entities, enforcement decisions, and lease/coordination events. Fields: `timestamp`, `caller_id`, `roles`, `entity_id`, `action`, `decision`, `profile_version`, `rule_applied`, `redaction_mode`. The specification requires logging for restricted entities and person entities but does not yet define a standard event shape. Deferred to v1.1 to allow real-world usage to inform the schema design.

### Deferred to Version 2

**Temporal evaluator: solar angle conditions.** Requires a solar calculation library. Deferred to avoid adding a dependency.

**Temporal evaluator: relative_to_event conditions.** Requires HA event bus integration. Architecture is defined; implementation deferred.

**Multi-agent lease collision resolution.** `caller_priority` field, role-to-priority mapping, preemption notification. Deferred until multiple agents in a single deployment is a common real-world scenario.

**Snapshot management for `snapshot_restorable` automations.** Requires integration with HA state history. Architecture is defined; implementation deferred.

**`binary_sensor.mesa_lease_active` HA entity.** Requires the host server to write to HA's entity registry. Implementation deferred to allow host servers to implement it natively.

**Profile linting CLI (`mesa-lint`).** Planned as a separate package `mesa-lint` that imports `mesa-core` for validation. Deferred to allow mesa-core to stabilise first.


---

## 9. Future Versions

**Version 1.1.** Lease protocol (`LeaseManager` with basic request, release, and expiry). `mesa-lint` CLI tool as a separate package. Solar angle temporal conditions. Profile export and import utilities.

**Version 2.0.** Multi-agent lease collision resolution. Snapshot management for reversible automations. `binary_sensor.mesa_lease_active` entity support. Additional framework adapters (Node.js MCP SDK if demand exists).

**Version 3.0.** Semantic graph queries (find all entities connected to an automation via environmental dependencies). Graph-based conflict detection. Spatial leakage traversal queries. These require Version 2 to be stable in production first.

**Version 3.0 (continued): Native HA service interceptor.** A `custom_components/mesa` Home Assistant custom component that integrates MESA enforcement at the HA core level, allowing MESA boundaries to apply regardless of which client (MCP, WebSocket, REST, or script) issues a service call. This requires upstream HA cooperation or a stable HA internal hook API that does not currently exist. The approach of patching `hass.services.async_register` from a custom component is fragile and unsupported in HA 2025+; this item is deferred until HA exposes a formal service interceptor middleware API or until the MESA community has sufficient standing to propose it as an upstream HA feature.

---

## 10. Distribution and Installation

mesa-core is a Python library for MCP server developers. It is distributed via PyPI. End users never install mesa-core directly. They install the MCP server that bundles it as a dependency.

**For MCP server developers:**

```bash
# Install in your development environment
pip install mesa-core
pip install mesa-core[sqlite]   # with SQLite backend
pip install mesa-core[test]     # with test suite

# Add as a dependency in your server's pyproject.toml
# [project]
# dependencies = ["mesa-core>=1.0"]
```

MCP server developers import mesa-core as a library dependency, integrate it into their server, and ship their server through whatever mechanism they use. mesa-core is bundled as a transitive dependency, invisible to end users.

Do not fork mesa-core to customise it. Subclass or extend the relevant components instead. This ensures your server continues to receive specification updates as mesa-core versions advance.

**From source:**

```bash
git clone https://github.com/[owner]/mesa-core
cd mesa-core
pip install -e ".[test]"
pytest
```

---

## 11. Dependencies

**Required (core):**

- Python 3.11 or later
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
