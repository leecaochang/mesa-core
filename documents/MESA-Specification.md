# MESA Specification
**Version:** 1.0
**Document Type:** Formal Schema Reference

---

## Abstract

This document is the authoritative technical reference for MESA (Metadata and Environment Semantics for Agents). It defines all schemas, normative rules, conformance levels, and governance processes that constitute the standard.

This document is the MESA **Core** specification: the minimum viable semantic kernel and the schemas most critical to safe AI orchestration, ready for implementation today (Sections 1-9), together with vendor namespace rules, governance, and related work (Sections 22-24). The twelve enrichment domains that improve agent reasoning but are not required for conformance are specified in the companion **MESA Enrichment** document (Sections 10-21). Section numbering is continuous across the two documents. Both documents are normative.

For practical implementation guidance, worked examples, and AI-assisted authoring workflows, see the MESA Getting Started Guide.

---

## Table of Contents

### Core (Sections 1-9)

1. [Conventions](#1-conventions)
2. [Conformance Levels](#2-conformance-levels)
3. [Security Considerations](#3-security-considerations)
4. [The MESA Core Kernel](#4-the-mesa-core-kernel)
5. [Global Profile Metadata](#5-global-profile-metadata)
   - 5.1 [Root Object](#51-root-object)
   - 5.2 [Profile Metadata Schema](#52-profile-metadata-schema)
   - 5.3 [Metadata Origin Schema](#53-metadata-origin-schema)
   - 5.4 [Inferred AI Profile Rules](#54-inferred-ai-profile-rules)
   - 5.5 [Profile Freshness and Invalidation](#55-profile-freshness-and-invalidation)
   - 5.6 [Profile Inheritance](#56-profile-inheritance)
   - 5.7 [Global Profile Conflict Resolution](#57-global-profile-conflict-resolution)
   - 5.8 [Deployment Defaults for Unprofiled Entities](#58-deployment-defaults-for-unprofiled-entities)
6. [Operational Boundaries](#6-operational-boundaries)
   - 6.1 [Boundary Schema](#61-boundary-schema)
   - 6.2 [Side Effect Scope](#62-side-effect-scope)
   - 6.3 [Predicate Operators](#63-predicate-operators)
   - 6.4 [Declared Limits Schema](#64-declared-limits-schema)
   - 6.5 [Temporal Constraints Schema](#65-temporal-constraints-schema)
   - 6.6 [Confirmation Protocol](#66-confirmation-protocol)
7. [Privacy and Sensitivity Classification](#7-privacy-and-sensitivity-classification)
   - 7.1 [Privacy Classification Schema](#71-privacy-classification-schema)
   - 7.2 [Role-Based Access](#72-role-based-access)
8. [Integration Semantics](#8-integration-semantics)
   - 8.1 [Category Traits](#81-category-traits)
   - 8.2 [Capability Semantics](#82-capability-semantics)
   - 8.3 [Semantic Routing](#83-semantic-routing)
   - 8.4 [Complete Integration Profile Example](#84-complete-integration-profile-example)
9. [Semantic Retrieval API](#9-semantic-retrieval-api)
   - 9.1 [Overview](#91-overview)
   - 9.2 [Query Request Schema](#92-query-request-schema)
   - 9.3 [Query Response Schema](#93-query-response-schema)
   - 9.4 [Caller Context Schema](#94-caller-context-schema)
   - 9.5 [MCP Tool Definitions](#95-mcp-tool-definitions)
   - 9.6 [Error Responses](#96-error-responses)

### Enrichment (Sections 10-21) - separate document

Sections 10-21 (Spatial Semantics, Automation and Blueprint Semantics, Scene Semantics, Diagnostic Semantics, Event Semantics, Helper Entity Semantics, Zone Semantics, People Semantics, Assist Pipeline Semantics, Dashboard and UI Semantics, Resource and Cost Awareness, State Lease Protocol) are specified in the companion **MESA Enrichment** document.

### Core, continued (Sections 22-24)

22. [Vendor Namespace Extensions](#22-vendor-namespace-extensions)
23. [Governance](#23-governance)
24. [Related Work](#24-related-work)

### Appendices

- [Appendix A: Seed Vocabulary](#appendix-a-seed-vocabulary)
- [Appendix B: Conformance Summary](#appendix-b-conformance-summary)

---

## 1. Conventions

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, RECOMMENDED, MAY, and OPTIONAL in this document are to be interpreted as described in RFC 2119.

**Schema notation.** All schemas are presented in JSON. Where a schema applies in a Home Assistant configuration context, an equivalent YAML representation is provided immediately following. JSON is the canonical format for API responses and MCP tool payloads. YAML is the natural format for HA configuration files including automations, blueprints, and area registry entries. Both are equally valid representations of the same data; use the format appropriate to your context. Developers working exclusively in one context need only read that format.

**Field types.** Types are specified as: `string`, `number`, `boolean`, `array<type>`, `object`, `enum(value1 | value2)`. Optional fields carry a trailing `?`.

**Normative vs. illustrative examples.** Examples marked `[NORMATIVE]` define required structure. Examples marked `[ILLUSTRATIVE]` demonstrate real-world usage and are not themselves normative.

**Predicate operators.** All predicate operators throughout this specification use canonical short-form tokens defined in Section 6.3. Native Home Assistant condition syntax is also accepted by host implementations and is documented in Section 6.3.

**Agent behaviour and schema scope.** This specification contains two categories of normative statement. Schema definitions describe the structure and semantics of MESA metadata. Agent behaviour requirements describe how consuming agents SHOULD or MUST act on that metadata. These categories are intentionally combined in a single document because they are mutually dependent: the schema is meaningless without behaviour expectations, and behaviour cannot be specified without schema context. Implementors should note that agent behaviour requirements (MUST log access, MUST NOT construct behavioural profiles, etc.) are obligations on the agent implementation, not on the metadata itself.

MESA metadata describes the environment. Agents are probabilistic reasoning systems, not deterministic constraint-solvers. This specification distinguishes three categories of constraint:

- **Platform-enforced:** A conforming Level 3 MCP server in `enforced` mode will reject service calls that violate declared limits. These can be relied upon for safety.
- **Agent-respected:** A well-behaved agent SHOULD follow these. They cannot be guaranteed without enforcement infrastructure.
- **Advisory:** Informational signals the agent SHOULD consider but may override based on user instruction or context.

---

## 2. Conformance Levels

MESA defines three conformance levels. These levels describe capability tiers that any MCP server can reach by integrating the mesa-core Python module. A host server MUST declare which level it targets.

**Reference implementation.** The mesa-core Python module is the reference implementation of this specification. mesa-core v1 implements Levels 1 and 2 in full and the core of Level 3 (retrieval tools, enforcement, confirmation protocol); lease tools follow in v1.1. MCP server developers integrate mesa-core to gain MESA conformance without reimplementing the specification from scratch. See the mesa-core Module Proposal document for integration details.

**Who conformance applies to.** Conformance levels are declared by host implementations: MCP servers and the libraries they embed. Some requirements in this specification address consuming agents rather than hosts: epistemic weighting, cascade caution, refusal communication. These are normative guidance for agent developers, but they describe probabilistic reasoning behaviour that no test suite can verify. The conformance test suite verifies host behaviour only; requirements addressed to agents are identifiable by their agent-directed language ("Agents MUST...").

### Level 1: Profile Consumer

Reads and respects MESA profiles. Minimum viable integration.

**Requirements:**
- MUST parse `semantic_profile` root objects without error.
- MUST surface `metadata_origin` to decision-making logic.
- MUST apply lower epistemic weight to `inferred_ai` profiles than `developer` or `user` profiles.
- MUST treat `control_mode: confirm` as the safe default when the field is absent.
- MUST NOT expose entities to callers whose role appears in `deny_for`.
- SHOULD respect declared limits and temporal constraints.
- SHOULD surface privacy classification to access control logic.

### Level 2: Profile Author

Generates, stores, and manages MESA profiles in addition to consuming them.

**Requirements:** All Level 1 requirements, plus:
- MUST include `metadata_origin` in all generated profiles.
- MUST mark AI-inferred profiles `source: inferred_ai`.
- MUST include `confidence` and `generated_at` in all `inferred_ai` profiles.
- MUST NOT generate inference chains deeper than depth 1.
- MUST expose `inferred_ai` profiles separately from authoritative profiles in API responses.
- SHOULD provide a human review and confirmation path for inferred profiles.

### Level 3: Profile Server

Full MESA implementation including semantic retrieval API, enforcement, and optional lease protocol.

**Requirements:** All Level 1 and Level 2 requirements, plus:
- MUST implement the following MCP tools defined in Section 9.5: `mesa_query_profiles`, `mesa_get_profile`, `mesa_get_caller_context`, `mesa_explain_profile`.
- SHOULD implement lease tools (`mesa_request_lease`, `mesa_release_lease`) when the deployment requires multi-agent coordination. Full lease support is expected in a future revision of this specification. A Level 3 server that omits lease tools is conformant but cannot participate in the coordination protocol defined in Section 21 (MESA Enrichment).
- MUST support domain, tag, area, intent, and origin filtering.
- MUST support pagination.
- MUST require authentication equivalent to the host platform's API authentication.
- SHOULD capture pre-execution snapshots for `snapshot_restorable` automations before they fire. Full snapshot support is expected in a future revision.
- SHOULD deny lease requests for entities under `protected` or `critical` automation control. This requirement becomes MUST when lease tools are implemented.
- SHOULD support `enforced` mode. When supported, the server MUST reject service calls that violate `control_mode: prohibited` or active `declared_limits`. A Level 3 server that does not implement `enforced` mode is still conformant but cannot make the safety guarantees described in Section 3.

---

## 3. Security Considerations

**Profile exposure.** A complete semantic profile maps a deployment's constraints, boundaries, and spatial topology. This information SHOULD NOT be exposed over unauthenticated channels.

**Inferred profile poisoning.** A malicious actor could craft inputs to an AI inference system that cause it to generate dangerous profiles (e.g., marking a lock as `control_mode: autonomous`). Mitigation: inferred profiles affecting security-sensitive domains (`lock`, `alarm_control_panel`, `camera`, `binary_sensor` with security tags) MUST default to `control_mode: confirm` regardless of inference output. Human review MUST be required before such profiles become operational.

**Tightening abuse and the removal path.** Because tightening always wins (Rule A) and privacy is most-restrictive-wins (Rule C), a poisoned or erroneous profile can also deny service by over-restricting: marking entities `prohibited` or `restricted` that should not be. Conflict resolution applies only to extant profiles; the remedy is removal. Operators locate the offending profile with `mesa_explain_profile`, which names the level and origin contributing each effective value, and delete or correct it through the host server's configuration interface. Host servers MUST allow operators to delete any profile of any origin, at any scope: entity, area, or domain.

**Declared limit bypass.** Operational boundaries in `advisory` enforcement mode are semantic descriptions that a well-behaved agent should follow. They do not replace HA's native access control. Use `enforced` mode for safety-critical limits.

**The goodwill dependency.** Without a Level 3 MCP server operating in `enforced` mode, the safety properties of MESA rest entirely on agent goodwill. A buggy, misconfigured, or malicious agent may ignore `control_mode: prohibited`, `declared_limits`, `temporal_constraints`, and privacy classifications. MESA cannot prevent this at the metadata layer. Operators who require hard safety guarantees MUST use a Level 3 host server in `enforced` mode AND HA's native access control in combination. Neither alone is sufficient. Advisory mode provides signal; enforced mode provides enforcement; native HA permissions provide the final backstop.

**Threat model: what MESA does and does not prevent.**

| Scenario | MESA prevents this | Notes |
|---|---|---|
| Well-behaved agent acting on incomplete information | Yes | Core use case. MESA provides the missing context. |
| Agent making spatially naive decisions | Yes, with spatial profiles | Requires enrichment profiles (MESA Enrichment). |
| Agent ignoring automation conflicts | Yes, with automation profiles | Requires enrichment profiles (MESA Enrichment). |
| Agent misunderstanding custom integration states | Yes, with diagnostic profiles | Requires diagnostic profile authoring. |
| Buggy agent ignoring `control_mode: prohibited` | Only in enforced mode | Requires Level 3 server with `enforcement_mode: enforced`. |
| Agent accidentally skipping confirmation (hallucinated approval, lost state, parameter drift) | Yes, in enforced mode | Confirmation protocol (Section 6.6) forces the round-trip and binds parameters. |
| Agent fabricating confirmation approval | No | The protocol verifies the round-trip, not the human. Deceptive agents are out of scope; operator controls and HA native permissions apply. |
| Malicious agent with valid credentials | No | MESA is not an access control system. Use HA native permissions. |
| Native YAML automations conflicting with agent | Partially | Lease protocol is advisory. Native automations remain unaware unless they check `binary_sensor.mesa_lease_active`. |
| Agent acting on stale profiles | Partially | Staleness warnings help. Profile freshness is the operator's responsibility. |
| Agent bypassing HA native permissions | No | MESA does not replace HA's authentication and authorisation layer. |

HA native permissions remain the final backstop for all scenarios. MESA is designed to protect against well-behaved but under-informed agents, not against adversarial access.

**Caller identity realism.** The role-based access model (Section 7.2) is only as strong as the caller identity the host server can establish. In deployments where the MCP server authenticates to HA with a single long-lived access token and exposes no per-caller authentication of its own, every caller shares one identity and `access_roles` provides no isolation: `deny_for: [child]` restricts nothing if children and adults reach the server through the same channel. Operators relying on role-based privacy MUST ensure the host server authenticates callers individually; otherwise only base privacy levels apply, to everyone equally.

**Profile staleness.** Profiles that drift out of sync with deployment reality cause agents to reason incorrectly. See Section 5.5 for invalidation mechanisms.

**Privacy side channels.** When an agent receives no response for an entity because of `deny_for` role restrictions, the absence itself may signal that the entity exists. Use `deny_response_mode` (Section 7.2) to control this behaviour.

---

## 4. The MESA Core Kernel

The kernel is the recommended starting set for any MESA profile. Seven fields that give agents the most value for the least authoring effort. No fields beyond these seven are needed for a complete kernel profile. Individual kernel fields are marked RECOMMENDED in their respective schema tables because a profile missing any single field is still valid and useful, but a profile containing all seven provides the fullest agent reasoning context. A kernel profile shipped in an integration's `mesa_profile.json` needs no `metadata_origin`: it defaults to `source: developer` (Section 5.3). Profiles stored anywhere else SHOULD declare `metadata_origin` explicitly.

```json
{
  "semantic_profile": {
    "semantic_tags": ["lighting.ambient"],
    "operational_boundaries": {
      "control_mode": "autonomous",
      "triggers_automations": "none",
      "reversible": true,
      "reversibility_cost": "none",
      "side_effect_scope": "entity_only"
    }
  },
  "privacy_classification": {
    "level": "normal"
  }
}
```

**`semantic_tags`** - What this component is for. One tag from Appendix A is sufficient. Enables intent-based context retrieval.

**`control_mode`** - How an agent should treat write operations on this entity. Four values with normative definitions:

- `autonomous`: The agent MAY act without requesting user approval. Appropriate for low-risk, easily reversible entities such as lights and media volume.
- `confirm`: The agent MUST NOT execute a write operation without explicit human approval in the current session. When no interaction channel exists, approval cannot be obtained: the agent MUST treat the entity as `prohibited` for the duration of the session, regardless of domain, and SHOULD surface a configuration warning. An explicit `confirm` is never silently downgraded by the built-in baseline or `deployment_defaults`. Operators who want autonomous behaviour in non-interactive deployments declare it explicitly: via `deployment_defaults` for unprofiled entities, or via the operator loosening override (Section 5.7 Rule A) for profiled ones.
- `read_only`: This entity is inherently non-writable by its nature, not by policy. Agents MUST NOT attempt write operations. Distinct from `prohibited`: `read_only` reflects the entity's fundamental purpose (diagnostic sensors, read-only metrics), while `prohibited` reflects an operator policy decision.
- `prohibited`: The agent MUST NOT write to this entity under MESA-declared policy.

When absent, agents MUST default to `confirm`. There is no silent autonomous default. The built-in domain safety baseline (Section 5.8) applies for domains where `confirm` would be unnecessarily restrictive.

**Precedence rule:** A developer may declare any `control_mode` in the integration's distributed profile. An operator may always tighten the restriction. An operator may loosen a developer-declared `confirm` to `autonomous` only through the explicit loosening override defined in Section 5.7 Rule A: `override_control_mode: true` in an entity-level `user`-origin profile, with a `control_reason`. No profile at any level may loosen a developer-declared `prohibited` or `read_only`. Tightening hierarchy: `autonomous` -> `confirm` -> `prohibited`. `read_only` is treated as equivalent to `prohibited` in the tightening hierarchy. When both `read_only` and `prohibited` are declared at different inheritance levels, `read_only` takes precedence in the effective profile because it describes entity nature rather than operator policy. The enforcement behaviour is identical; the distinction is semantic and affects how agents communicate refusals to users.

**`control_mode` field precedence across profile layers.** When `control_mode` is declared in multiple locations, the following precedence order applies from lowest to highest:

1. `capability_semantics.control_mode` in integration profile (integration-level default, lowest authority)
2. `operational_boundaries.control_mode` in domain-level profile distributed with the integration (`mesa_profile.json` sidecar)
3. `operational_boundaries.control_mode` in area-level profile
4. `operational_boundaries.control_mode` in entity-level profile (highest authority)

Within each level, tightening-only rules apply: a higher-level declaration may only change `control_mode` to a more restrictive value, following the tightening hierarchy and `read_only` handling defined in the precedence rule above. At no level may a less restrictive value override a more restrictive one declared at any level, with a single exception: the operator loosening override (Section 5.7 Rule A) allows an entity-level `user`-origin profile to loosen an inherited `confirm` to `autonomous`.

**`triggers_automations`** - Whether changing this entity is likely to trigger one or more automations. This is a critical field for mode flags, coordination signals, and helper entities. Agents SHOULD apply cascade caution when the value is `likely`, or `deployment_defined` with a non-empty `affected_automations` list, regardless of `side_effect_scope`. When absent, agents SHOULD treat the value as `unknown` and apply caution for helper domains.

The field acknowledges a fundamental knowledge boundary: a developer writing an integration profile cannot know what automations an operator has built. Use `likely` when the integration is designed to drive downstream behaviour. Use `unknown` when it genuinely cannot be determined. Operators authoring entity-level profiles who know their specific deployment SHOULD use `deployment_defined`.

**`reversible`** - Can the effect be undone? Turning a light off is reversible. Sending a notification is not. Locking a door is reversible only if the agent can unlock it.

**`reversibility_cost`** (RECOMMENDED) - The cost or impact of reversing the action. `none` for lights and simple switches. `trivial` for actions that take a few seconds. `moderate` for actions with minor side effects (waking a pet, brief disruption). `high` for actions that are technically reversible but carry significant consequences. Without this field agents treat all reversible actions as equally safe, which they are not.

**`reversibility_note`** (OPTIONAL) - A short human-readable string explaining the reversal cost in deployment-specific terms. Examples: "unlocking wakes dog", "re-arming takes 30 seconds", "restoring state requires snapshot".

**`side_effect_scope`** - How far does the **direct hardware impact** spread? See Section 6.2. This field describes physical footprint only, not software cascade. Use `triggers_automations` to signal cascade risk.

**`privacy_classification.level`** - Does this component contain personal data? Four values:
- `public`: no personal data, no privacy expectations. Weather stations, utility meters, entrance sensors.
- `normal`: standard residential devices. Motion sensors, light states, temperature readings.
- `sensitive`: personal data present. Cameras, microphones, presence sensors, sleep trackers. Agents SHOULD log access and avoid exposing raw data without confirmation.
- `restricted`: highly personal or safety-critical. Medical devices, children's monitors, intimate spaces. Agents MUST log access and MUST NOT act autonomously.

Every additional field beyond the kernel improves agent reasoning. None is required for the kernel to deliver value. See the Getting Started Guide for the enrichment continuum.

---

## 5. Global Profile Metadata

### 5.1 Root Object

All MESA metadata SHALL be exposed under the root key `semantic_profile`. A separate `diagnostic_profile` root key covers diagnostic semantics (Section 13, MESA Enrichment).

```json
{
  "semantic_profile": {},
  "diagnostic_profile": {}
}
```

The `semantic_profile` key MAY appear in: a `mesa_profile.json` sidecar file in an integration directory (the developer distribution path, Section 8), entity registry extra state attributes, automation and blueprint metadata blocks, area and floor registry entries, helper entity registry entries, native HA API responses, and MCP server context payloads.

MESA is additive. Systems that do not expose `semantic_profile` remain fully conformant with HA's operational layer. MCP servers may expose `semantic_profile` data by integrating the mesa-core module, which handles profile storage, retrieval, inheritance resolution, and enforcement.

### 5.2 Profile Metadata Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `string` | SHOULD | MESA schema version. Currently `1.0`. |
| `profile_version` | `string` | SHOULD | Version of this specific profile. Implementor-defined. |
| `metadata_origin` | `object` | RECOMMENDED | Profile provenance. See Section 5.3. When absent, the default depends on the profile's location: profiles loaded from an integration's `mesa_profile.json` default to `source: developer`; profiles from any other location default to `source: unknown`. See Section 5.3. |
| `semantic_tags` | `array<string>` | RECOMMENDED | Namespaced tags classifying this component. See Appendix A. |
| `last_updated` | `string` | SHOULD | ISO 8601 timestamp of most recent modification. |
| `inheritance_scope` | `enum` | RECOMMENDED | How this profile applies in the inheritance hierarchy. `entity` (applies to this entity only, default), `domain` (applies to all entities from this integration), `area` (applies to all entities assigned to this area). See Section 5.6. |
| `profile_valid_for` | `object` | MAY | Conditions under which this profile should be reviewed. See Section 5.5. |

### 5.3 Metadata Origin Schema

Provenance determines how much epistemic weight an agent assigns to a profile.

| Field | Type | Required | Description |
|---|---|---|---|
| `source` | `enum` | REQUIRED | Origin class. See table below. |
| `confidence` | `number` | REQUIRED for `inferred_ai` | 0.0 to 1.0. Base confidence at time of inference. |
| `generated_at` | `string` | REQUIRED for `inferred_ai` | ISO 8601 timestamp of inference. |
| `staleness_window_days` | `number` | OPTIONAL | Days before profile is flagged for review. Default: 60. |
| `confirmed_fields` | `array<string>` | REQUIRED for `hybrid` | Field paths confirmed by a human. |

**Origin classes (highest to lowest authority):**

| Value | Description |
|---|---|
| `developer` | Authored by the integration developer. Distributed with the integration. |
| `user` | Authored by the deployment operator. Explicitly written. |
| `hybrid` | Partially human-confirmed. `confirmed_fields` lists authoritative paths. |
| `inferred_ai` | Generated by AI inference. Subject to rules in Section 5.4. |
| `unknown` | Provenance cannot be determined. Used for legacy imports, migrated profiles, or profiles where `metadata_origin` is absent and no location default applies (see below). Agents MUST treat `unknown` profiles with the same caution as `inferred_ai` for trust decisions. |

```json
{
  "metadata_origin": {
    "source": "user",
    "confidence": 1.0
  }
}
```

**Provenance defaults when `metadata_origin` is absent.** A profile read from an integration's `mesa_profile.json` sidecar defaults to `source: developer`: the file is distributed inside the integration directory and is under the integration developer's control, so developer provenance is the honest default reading. A profile from any other location (the operator profile store, migrated or imported data, API payloads) defaults to `source: unknown` and receives `inferred_ai`-level caution. The asymmetry is deliberate: profiles outside the sidecar are written by Level 2 servers, which MUST stamp `metadata_origin` on everything they generate (Section 2), so an absent origin there indicates a fault rather than an authoring choice. Developers SHOULD still declare `metadata_origin` explicitly. In particular, an AI-generated profile shipped in `mesa_profile.json` without an explicit `inferred_ai` or `hybrid` origin misrepresents its provenance; see the trust-laundering guidance in the Getting Started Guide.

### 5.4 Inferred AI Profile Rules

**Rule 1.** `inferred_ai` profiles MUST include `confidence` and `generated_at`. Missing either field makes the profile malformed and unusable.

**Rule 2.** Conforming agents SHOULD apply lower epistemic weight to `inferred_ai` profiles. When profiles of different origin classes conflict, the higher-authority profile MUST take precedence.

**Rule 3.** Agents MAY use `inferred_ai` profiles with `confidence >= 0.7` for non-safety-critical reasoning decisions. The 0.7 threshold is a convention, not a calibration guarantee; confidence scores are self-reported by the inference system and are not comparable across systems. The threshold serves as a minimum bar: it prevents very low-confidence inferences from being acted upon, but does not imply that 0.7 from one system is equivalent to 0.7 from another. For `control_mode` specifically, agents MAY act on an unconfirmed inferred value only when doing so represents a tightening action: an inferred `confirm` may override a baseline of `autonomous`, and an inferred `prohibited` may override either. Agents MUST NOT use an unconfirmed inferred `control_mode` to loosen or establish an initial baseline permission (i.e. an inferred `autonomous` MUST NOT take effect without human confirmation). For privacy classification, agents MUST NOT use unconfirmed inferred values for access decisions without human confirmation of those specific fields.

**Rule 4.** Agents MUST NOT use `inferred_ai` profiles as source material for further inference. Inference chain depth is limited to 1.

**Rule 5.** Conforming Level 3 MCP servers MUST expose inferred profiles separately from authoritative profiles in API responses. Agents MUST explicitly opt-in to receive inferred profiles using `include_inferred: true` in query requests (Section 9.2). By default, queries return only `developer`, `user`, and `hybrid` profiles.

**Rule 6.** Human confirmation of fields in an `inferred_ai` profile promotes those fields to `hybrid`. Unconfirmed fields remain inferred.

**Rule 7.** A `developer` or `user` profile for an entity supersedes any `inferred_ai` or `hybrid` profile for that entity for all fields it explicitly declares. Exception: field-level tightening of `control_mode` by any lower-authority profile is always preserved, even when a higher-authority profile would otherwise supersede it. A `developer` profile declaring `control_mode: autonomous` does not undo a lower-authority `inferred_ai` or `hybrid` profile that declares `control_mode: prohibited`, because tightening is always safe regardless of origin authority.

**Rule 8.** All inferred profiles MUST default `control_mode` to `confirm` regardless of inference output and regardless of domain. An inferred profile MUST NOT assert `control_mode: autonomous` without human confirmation of that specific field. This applies to all domains, not only security-sensitive ones.

**Rule 9.** For helper domains (`input_boolean`, `input_select`, `input_number`, `input_text`, `input_datetime`, `counter`, `timer`), inferred profiles MUST default `triggers_automations` to `likely` regardless of inference output. An inferred profile for a helper entity MUST NOT assert `triggers_automations: none` without human confirmation. This rule exists because helpers are the most common cause of automation cascade effects and inference systems cannot reliably determine which automations a given helper controls.

**Staleness.** Rather than a hard cutoff, Level 2 and Level 3 host servers surface a `staleness_status` field alongside inferred profiles:

| Value | Meaning |
|---|---|
| `current` | Within `staleness_window_days` with no invalidation triggers. |
| `stale` | Age has exceeded `staleness_window_days` or an invalidation trigger has fired. |
| `unknown` | Age or generation timestamp cannot be determined. |

A stale profile MUST NOT be silently discarded. It MUST be surfaced with a `staleness_status: stale` flag so agents can apply appropriate skepticism. Even a stale inferred profile may be the only available context for a legacy device.

### 5.5 Profile Freshness and Invalidation

Human-authored profiles do not decay but can become stale when the deployment changes around them. The `profile_valid_for` object declares invalidation triggers.

| Field | Type | Description |
|---|---|---|
| `integration_version` | `string` | Integration version this profile was authored against. |
| `ha_version` | `string` | HA version at time of authoring. |
| `review_after_days` | `number` | Flag for review after this many days regardless of other conditions. |
| `invalidated_by_entities` | `array<string>` | Entity IDs whose removal or renaming triggers invalidation. |

```json
{
  "profile_valid_for": {
    "integration_version": "2.4.1",
    "ha_version": "2026.5",
    "review_after_days": 180,
    "invalidated_by_entities": ["light.living_room_ceiling"]
  }
}
```

When an invalidation trigger fires, a host MCP server SHOULD surface a warning. It MUST NOT silently discard the profile.

**Live validation of `triggers_automations`.** Automation configurations change frequently. A static `triggers_automations: none` declaration can become stale the moment an operator adds a new automation referencing that entity. Level 2 and Level 3 host implementations SHOULD periodically run a live cross-reference of declared `none` profiles against the actual HA automation registry. Any entity declared `none` that is found in an automation trigger or condition block SHOULD generate a staleness warning surfaced to the operator. The mesa-core module provides `TriggerValidator` for this purpose.

**Entity renames.** Profiles are keyed by entity ID, and operators rename entities freely. A profile whose entity ID no longer exists in the HA registry is orphaned: it applies to nothing, and the renamed entity silently loses its profile, falling back to domain and area inheritance and deployment defaults. Host servers SHOULD detect orphaned profiles by checking stored keys against the entity registry, at startup and on `entity_registry_updated` events, surface them to the operator, and offer re-keying. Host servers MAY additionally record HA registry unique IDs alongside entity IDs to survive renames automatically.

### 5.6 Profile Inheritance

MESA profiles follow a three-level inheritance hierarchy. This reduces per-entity authoring burden significantly: an operator or developer can declare defaults that apply to many entities at once, and override only where needed.

**Hierarchy (lowest to highest precedence):**

1. **Domain-level defaults** - declared in an integration's distributed profile (`mesa_profile.json` sidecar, Section 8). Apply to all entities created by that integration unless overridden.
2. **Area-level defaults** - declared in an area's spatial profile `operational_boundaries`. Apply to all entities assigned to that area unless overridden.
3. **Entity-level profile** - declared directly on an entity. Takes full precedence over domain and area defaults for all fields present, subject to the trust-tier rule (Rule D, Section 5.7) and the field-specific Rules A through C.

**Inheritance rules:**

- Fields present in a lower-level profile are used when the same field is absent from all higher-level profiles.
- Fields present in a higher-level profile take precedence among profiles of `developer`, `user`, or `hybrid` origin. `inferred_ai` and `unknown` profiles never override trusted-tier declarations regardless of level (Rule D, Section 5.7).
- `control_mode` follows the additional tightening rule: a higher-level profile may tighten freely but may loosen an inherited `confirm` only via the operator loosening override (Rule A, Section 5.7). `prohibited` and `read_only` MUST NOT be loosened at any level.
- `triggers_automations: likely` is sticky upward: if any profile at any level declares `likely`, the effective value is `likely` regardless of lower-level declarations. `none` is not sticky: a lower-level `likely` overrides a higher-level `none` because the presence of any known automation trigger is more informative than an assertion of absence. `deployment_defined` at entity scope may override `likely` from higher levels when accompanied by `override_triggers_automations: true`, representing the operator's precise knowledge of their specific deployment. To override a sticky `likely` from a higher level, an entity-level profile may declare `triggers_automations: none` alongside `override_triggers_automations: true` with a `human_reason` string explaining the exception.
- `privacy_classification.level` follows the more-restrictive-wins rule from Section 7.

**Practical example:** An integration declares `control_mode: autonomous` in its distributed profile for all its light entities. An operator assigns all bedroom lights to the bedroom area. The bedroom area profile declares `control_mode: confirm`. All bedroom lights now require confirmation, even though the integration declared them autonomous. The operator has tightened the restriction at the area level. No per-entity profiles are needed.

**JSON example [ILLUSTRATIVE]:**

```json
{
  "semantic_profile": {
    "schema_version": "1.0",
    "metadata_origin": {"source": "developer", "confidence": 1.0},
    "inheritance_scope": "domain",
    "semantic_tags": ["lighting.ambient"],
    "operational_boundaries": {
      "control_mode": "autonomous",
      "triggers_automations": "none",
      "reversible": true,
      "side_effect_scope": "entity_only"
    }
  },
  "privacy_classification": {"level": "normal"}
}
```

The `inheritance_scope` field tells host implementations how to apply this profile. Valid values: `entity` (applies to this entity only, default), `domain` (applies to all entities from this integration), `area` (applies to all entities assigned to this area).

### 5.7 Global Profile Conflict Resolution

When profiles from different origins, levels, or inheritance tiers declare conflicting values for the same field, the following global resolution rules apply. These rules are stated here as a single authoritative reference to prevent implementor ambiguity.

**Rule A: `control_mode` follows tightening-only authority.**
The most restrictive `control_mode` value wins at the field level, regardless of origin authority. `read_only` and `prohibited` are equally restrictive and beat `confirm` beats `autonomous`. An `inferred_ai` profile declaring `prohibited` is preserved even when a higher-authority `developer` profile declares `autonomous`, because tightening is always safe. This is a field-level rule that operates independently of profile-level origin authority (Rule D). No profile at any authority level may loosen a `prohibited` or `read_only` declaration.

**Rule A exception: the operator loosening override.** An entity-level profile with `metadata_origin.source: user` MAY loosen an inherited `confirm` to `autonomous` by declaring `control_mode: autonomous` together with `override_control_mode: true` and a `control_reason` explaining why autonomous control is safe in this deployment. This is the only permitted loosening of `control_mode`. It exists because a developer's `confirm` is a context-free conservative default, while the operator has deployment knowledge the developer cannot have. Constraints: the override is valid only at entity scope; it is valid only in `user`-origin profiles (`inferred_ai`, `hybrid`, and `unknown` profiles MUST NOT loosen); it can loosen only `confirm`, never `prohibited` or `read_only`; and `override_control_mode: true` without an accompanying `control_reason` is malformed and MUST be ignored. Host servers MUST surface active loosening overrides in `mesa_explain_profile` output.

**Rule B: `triggers_automations: likely` is sticky upward.**
If any profile at any level declares `triggers_automations: likely` for an entity, the effective value is `likely`. `none` is not sticky: a lower-level `likely` overrides a higher-level `none`, because the presence of a known trigger is more informative than an assertion of absence. `deployment_defined` at entity scope overrides `likely` from any higher level only when accompanied by `override_triggers_automations: true`. This reflects the deployment reality: if any profiler knows automations are likely triggered, that knowledge is preserved unless the operator explicitly overrides it with precise local knowledge.

**Rule C: Privacy classification uses most-restrictive-wins.**
When multiple profiles declare `privacy_classification.level` for the same entity, the most restrictive level applies. `restricted` beats `sensitive` beats `normal` beats `public` regardless of origin authority.

**Rule D: Scope precedence with origin tiebreak for all other fields.**
For all fields not covered by Rules A, B, or C, resolution proceeds in two tiers. Within the trusted tier (`developer`, `user`, `hybrid`), the most specific scope wins: `entity` > `area` > `domain`. Where scope is equal, origin authority decides: `developer` > `user` > `hybrid`. Profiles of `inferred_ai` or `unknown` origin form a lower tier: they never override a field explicitly declared by any trusted-tier profile at any scope, consistent with Rule 7 (Section 5.4). When a field is declared only in the lower tier, the same scope-then-origin rule applies within it (`inferred_ai` > `unknown`). This preserves operator sovereignty (an operator's entity-level declaration beats a developer's domain-level default) while ensuring inferred and unattributed profiles can fill gaps but never displace explicit human or developer declarations.

**Rule E: Absence is not a conflict.**
A field absent from a higher-authority profile is inherited from lower-authority profiles in scope. Absence means "not specified here," not "set to default." Defaults only apply when no profile at any level specifies the field.

### 5.8 Deployment Defaults for Unprofiled Entities

When an entity has no MESA profile at any inheritance level, agents have no semantic guidance beyond HA's operational layer. The safe fallback is `control_mode: confirm` for all writes, but this may be overly restrictive or overly permissive depending on the domain.

An MCP server integrating mesa-core MAY expose a `deployment_defaults` configuration object that operators use to set domain-level defaults for all unprofiled entities in their deployment. This reduces the risk of incorrect assumptions without requiring per-entity profiling.

**`deployment_defaults` schema:**

| Field | Type | Description |
|---|---|---|
| `default_control_mode` | `enum` | Default `control_mode` for all unprofiled entities. Overridden by any profile at any level. Default: `confirm`. |
| `domain_overrides` | `object` | Per-domain defaults. Keys are HA domain strings. Values are objects with `control_mode` and `triggers_automations` fields. |
| `triggers_automations_domains` | `array<string>` | Domains for which unprofiled entities should default `triggers_automations: likely`. Recommended: include `input_boolean`, `input_select`, `input_number`, `counter`, `timer`. |

```json
{
  "deployment_defaults": {
    "default_control_mode": "confirm",
    "triggers_automations_domains": [
      "input_boolean",
      "input_select",
      "input_number",
      "counter",
      "timer"
    ],
    "domain_overrides": {
      "light": {"control_mode": "autonomous", "triggers_automations": "none"},
      "lock": {"control_mode": "prohibited", "triggers_automations": "none"},
      "alarm_control_panel": {"control_mode": "prohibited", "triggers_automations": "likely"}
    }
  }
}
```

When `deployment_defaults` is configured, it acts as a floor below all MESA profile inheritance levels. Any profile at any level takes precedence. Tightening-only rules apply: domain overrides cannot loosen a profile-declared `prohibited`.

**Built-in domain safety baseline.** When no `deployment_defaults` are configured and an entity has no profile at any inheritance level, host implementations SHOULD apply the following built-in baseline rather than defaulting everything to `confirm`. This prevents non-interactive agents from being completely locked out of well-understood low-risk domains before any profiles have been authored.

| Domain | Built-in default `control_mode` | Rationale |
|---|---|---|
| `light` | `autonomous` | Low risk, easily reversible, no personal data. |
| `media_player` | `confirm` | Effects vary by service call. Operators may loosen to `autonomous` via `deployment_defaults`. |
| `input_select` | `confirm` | May trigger automations. |
| `switch` | `confirm` | Scope of effects varies too widely for a blanket autonomous default. |
| `cover` | `confirm` | Physical consequences vary significantly by deployment. |
| `climate` | `confirm` | Comfort and energy implications vary by deployment. |
| `lock` | `prohibited` | Physical security. Never autonomous without explicit operator declaration. |
| `alarm_control_panel` | `prohibited` | Safety-critical. Never autonomous without explicit operator declaration. |
| `input_boolean` | `confirm` | High automation cascade risk in typical deployments. |
| `script` | `confirm` | Side effects are deployment-defined and unknown to the baseline. |
| `scene` | `confirm` | Multi-entity effects are deployment-defined. |
| All other domains | `confirm` | Conservative fallback. |

For `triggers_automations`, the built-in baseline applies the same logic as `deployment_defaults.triggers_automations_domains`: helper domains default to `likely`, all others default to `unknown`.

This baseline is not a substitute for explicit `deployment_defaults` or entity-level profiles. Operators SHOULD configure `deployment_defaults` as early as possible to replace the baseline with deployment-specific knowledge.


---

## 6. Operational Boundaries

Operational boundaries are machine-readable policy declarations. They describe how an entity should be treated by AI agents. A conforming agent SHOULD respect them. A Level 3 server in `enforced` mode MUST reject service calls that violate them.

### 6.1 Boundary Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `control_mode` | `enum` | RECOMMENDED | `autonomous`, `confirm`, `read_only`, or `prohibited`. See Section 4 for normative definitions. Default when absent: `confirm`. |
| `triggers_automations` | `enum` | RECOMMENDED | Whether this entity is likely to trigger automations. See values below. Default when absent: `unknown`. |
| `reversible` | `boolean` | RECOMMENDED | Can the effect be undone. |
| `reversibility_cost` | `enum` | RECOMMENDED | Cost of reversing: `none`, `trivial`, `moderate`, `high`. |
| `reversibility_note` | `string` | MAY | Short human-readable description of reversal cost in deployment context. |
| `reversibility_window_seconds` | `number` | MAY | Time window within which reversal is possible. After this window, treat as permanent. |
| `idempotent` | `boolean` | MAY | Do repeated identical calls produce the same result. |
| `state_persistence` | `enum` | MAY | How long written state persists: `permanent`, `temporary`, `session`, `transient`. |
| `expected_latency_ms` | `number` | MAY | Typical ms from service call to state change. |
| `side_effect_scope` | `enum` | MAY | Direct physical footprint of writes. See Section 6.2. |
| `state_volatility` | `enum` | MAY | How rapidly state changes. See volatility classes below. |
| `override_triggers_automations` | `boolean` | MAY | Entity-level only. Set `true` alongside `triggers_automations: none` or `deployment_defined` to override a sticky `likely` from domain or area level. Requires `human_reason`. |
| `override_control_mode` | `boolean` | MAY | Entity-level, `user`-origin profiles only. Set `true` alongside `control_mode: autonomous` to loosen an inherited `confirm`. Requires `control_reason`. Cannot loosen `prohibited` or `read_only`. See Section 5.7 Rule A. |
| `human_reason` | `string` | CONDITIONAL | Required when `override_triggers_automations` is `true`. Short explanation of why the override is correct for this specific deployment. |

**`triggers_automations` enum values:**

| Value | Meaning | Typical author |
|---|---|---|
| `likely` | This entity is designed to act as an automation trigger, or commonly does so in typical deployments. Mode flags, coordination signals, and most helper entities. Agents MUST apply cascade caution before acting. | Developer (by design) or operator (known fact) |
| `none` | A positive assertion that this entity does not trigger automations. Diagnostic sensors, read-only metrics, display-only entities. Agents MAY act without cascade reasoning. | Developer or operator |
| `unknown` | The author cannot determine whether this entity triggers automations in the consuming deployment. Agents MUST apply caution and assume possible cascade. | Developer (integration-level default) |
| `deployment_defined` | The operator knows precisely whether this entity triggers automations and has declared it. SHOULD be accompanied by `affected_automations` in helper traits. When `affected_automations` is absent or empty, agents MUST treat this as equivalent to `none`. Overrides all inherited values at entity scope. | Operator (entity-level only) |

**Boundary schema fields (continued):**

| Field | Type | Req | Description |
|---|---|---|---|
| `enforcement_mode` | `enum` | MAY | `advisory` (default) or `enforced`. In `enforced` mode a Level 3 server rejects violating calls. |
| `control_reason` | `string` | RECOMMENDED for `confirm` and `prohibited` | A short human-readable explanation of why this `control_mode` was chosen. Helps agents communicate refusals meaningfully. Examples: "triggers alarm automation", "medical device - operator review required", "physically dangerous if reversed". |
| `declared_limits` | `array<object>` | MAY | Conditional value constraints. See Section 6.4. |
| `temporal_constraints` | `array<object>` | MAY | Time-based boundary modifications. See Section 6.5. |

**State volatility classes:**

| Value | Typical change frequency | Agent implication |
|---|---|---|
| `static` | Rarely or never. | Safe to cache. Lease conflicts unlikely. |
| `low` | Hours or days. | Cache with caution. |
| `medium` | Minutes. | Do not cache. Verify before acting. |
| `high` | Seconds. | State may change during reasoning. Request lease. |
| `realtime` | Sub-second. | Treat reads as approximate. Lease strongly recommended. |

```json
{
  "semantic_profile": {
    "operational_boundaries": {
      "control_mode": "autonomous",
      "triggers_automations": "none",
      "reversible": true,
      "reversibility_cost": "none",
      "side_effect_scope": "entity_only",
      "state_volatility": "low",
      "enforcement_mode": "advisory"
    }
  }
}
```

### 6.2 Side Effect Scope

`side_effect_scope` describes the **direct physical footprint** of a write operation. It refers strictly to hardware-level consequences, not downstream automation cascades. Automation cascade effects are the responsibility of the automation conflict system (Section 11, MESA Enrichment).

For domain-specific propagation (acoustic, thermal, visual), agents SHOULD consult the area's `spatial_leakage` array in the spatial profile (Section 10.3, MESA Enrichment). `side_effect_scope` alone does not capture that a kitchen speaker at high volume affects adjacent rooms acoustically. `spatial_leakage` provides that domain-specific reasoning.

| Value | Description |
|---|---|
| `entity_only` | Direct effects confined to the target entity. |
| `device_localized` | May extend to other entities on the same physical device. |
| `room_localized` | May extend to other entities in the same area via hardware coupling. |
| `zone_wide` | May extend across a logical zone via hardware coupling. |
| `deployment_wide` | May extend across the entire deployment. |

### 6.3 Predicate Operators

All predicate operators in MESA profiles SHOULD use the following canonical short-form tokens. Conforming implementations MUST also accept native Home Assistant condition syntax to avoid requiring operators to learn a separate language.

| Token | Meaning | Applicable types |
|---|---|---|
| `eq` | Equal to | `string`, `number`, `boolean` |
| `neq` | Not equal to | `string`, `number`, `boolean` |
| `gt` | Greater than | `number` |
| `gte` | Greater than or equal to | `number` |
| `lt` | Less than | `number` |
| `lte` | Less than or equal to | `number` |
| `in` | Member of a list | `string`, `number` |
| `contains` | String contains substring | `string` |

**Predicate object schema:**

| Field | Type | Required | Description |
|---|---|---|---|
| `entity` | `string` | REQUIRED | Entity ID to evaluate. |
| `operator` | `enum` | REQUIRED | Canonical operator token from the table above. |
| `value` | `any` | REQUIRED | Value to compare against. Type must match the operator's applicable types. |
| `type` | `string` | CONDITIONAL | Set to `ha_condition` when using native HA condition syntax instead of canonical operators. When present, `entity`, `operator`, and `value` are replaced by `condition`. |
| `condition` | `object` | CONDITIONAL | Required when `type` is `ha_condition`. Must contain a valid HA condition object. |

Native HA condition syntax (e.g. `condition: state`, `condition: template` with Jinja2 expressions) is also accepted in predicate fields. When a predicate uses native HA syntax, the `type` field MUST be set to `ha_condition` and the `condition` field MUST contain a valid HA condition object.

```yaml
predicate:
  type: ha_condition
  condition:
    condition: state
    entity_id: input_boolean.cinema_mode
    state: "on"
```

Implementations MUST reject unrecognised non-HA operator tokens rather than guessing their meaning.

### 6.4 Declared Limits Schema

Declared limits express conditional value constraints. An agent SHOULD treat them as advisory unless `enforcement_mode` is `enforced`.

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | `string` | REQUIRED | Stable unique identifier for this limit. |
| `predicate` | `object` | REQUIRED | Condition under which the limit applies. See Section 6.3. |
| `limit` | `object` | REQUIRED | Value constraint when predicate is true. |
| `human_reason` | `string` | RECOMMENDED | Why this limit exists. |

**Limit schema:**

| Field | Type | Required | Description |
|---|---|---|---|
| `service` | `string` | REQUIRED | Service call to which this limit applies. |
| `parameter` | `string` | REQUIRED | Parameter being limited. |
| `max_value` | `number` | CONDITIONAL | Maximum permitted value. |
| `min_value` | `number` | CONDITIONAL | Minimum permitted value. |
| `permitted_values` | `array` | CONDITIONAL | Explicit list for discrete parameters. |

```json
{
  "declared_limits": [
    {
      "id": "night_mode_volume_cap",
      "predicate": {
        "entity": "input_boolean.night_mode",
        "operator": "eq",
        "value": true
      },
      "limit": {
        "service": "media_player.volume_set",
        "parameter": "volume_level",
        "max_value": 0.4
      },
      "human_reason": "Household occupants are sleeping."
    }
  ]
}
```

### 6.5 Temporal Constraints Schema

Temporal constraints allow boundary rules to be conditioned on time, day, or calendar state. They extend declared limits to handle time-based conditions.

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | `string` | REQUIRED | Stable unique identifier. |
| `condition` | `object` | REQUIRED | Temporal condition. |
| `effect` | `object` | REQUIRED | Boundary modification when condition is true. |
| `human_reason` | `string` | RECOMMENDED | Why this constraint exists. |

**Condition types:**

| `type` | Required fields | Description |
|---|---|---|
| `time_range` | `start_time`, `end_time` | HH:MM 24-hour. Midnight-crossing supported. |
| `day_of_week` | `days` | Array of: `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`. |
| `calendar_entity` | `calendar_entity` | HA calendar entity ID. True when calendar has active event. |
| `solar_angle` | `solar_event` | `sunrise`, `sunset`, `civil_twilight_start`, `civil_twilight_end`, `nautical_twilight_start`, `nautical_twilight_end`. Optional `solar_offset_minutes`. |
| `duration` | `duration_seconds` | True for this many seconds after the triggering condition. Supports "wait N minutes after event" patterns. |
| `relative_to_event` | `anchor_event`, `offset_seconds` | True from `offset_seconds` after `anchor_event`. Supports presence-departure patterns. |

In addition to its type-specific fields, any condition MAY include `negate` (`boolean`, default `false`), which inverts the condition's result. Negation makes the complement of any condition expressible: "outside the away calendar", "before the departure window", "on weekdays" as the negation of a weekend list.

When a temporal condition cannot be evaluated (the referenced entity does not exist, is `unavailable`, or is in an `unknown` state), conforming implementations MUST treat the constraint as active and apply the effect. This applies regardless of any `negate` flag. An unevaluable constraint is treated as active, not ignored. Because effects are tightening-only, this rule is fail-closed: no evaluation failure can ever grant a permission the base profile does not.

**Effect schema:**

| Field | Type | Required | Description |
|---|---|---|---|
| `control_mode` | `enum` | CONDITIONAL | Temporary `control_mode` override while the condition is active. Tightening-only: MUST NOT loosen the entity's effective base `control_mode` (the resolved value after inheritance and conflict resolution, Section 5.7). |
| `service` | `string` | CONDITIONAL | Service call this value constraint applies to. Required when `max_value`, `min_value`, or `permitted_values` is present. |
| `parameter` | `string` | CONDITIONAL | Service parameter being constrained. Required when `service` is present. |
| `max_value` | `number` | CONDITIONAL | Maximum permitted value while condition is true. |
| `min_value` | `number` | CONDITIONAL | Minimum permitted value while condition is true. |
| `permitted_values` | `array` | CONDITIONAL | Explicit list of permitted values while condition is true. |

An effect MUST contain at least one field. An effect MAY contain both a `control_mode` modification and a value constraint simultaneously.

**Effects are tightening-only.** A temporal effect may restrict an entity beyond its base boundaries; it MUST NOT relax them. An effect declaring a `control_mode` less restrictive than the effective base is invalid: conforming implementations MUST ignore it and SHOULD surface a validation warning. This invariant is what keeps the subsystem analyzable: multiple active constraints can be applied in any order because the most restrictive value wins, unevaluable conditions fail closed rather than open, and a manipulated clock or poisoned calendar entity can never grant permissions. To express "autonomous only while condition X holds", do not loosen with a temporal effect: set the base `control_mode` to `autonomous` (using the operator loosening override of Section 5.7 Rule A where the inherited value is `confirm`) and declare a tightening constraint whose condition is the negation of X. The third example below shows this pattern.

```yaml
temporal_constraints:
  - id: quiet_hours_volume
    condition:
      type: time_range
      start_time: "22:00"
      end_time: "07:00"
    effect:
      service: media_player.volume_set
      parameter: volume_level
      max_value: 0.3
    human_reason: Quiet hours. Volume above 30% is inappropriate between 10pm and 7am.
  - id: wfh_no_vacuum
    condition:
      type: calendar_entity
      calendar_entity: calendar.work_from_home
    effect:
      control_mode: confirm
    human_reason: Do not run the vacuum autonomously during work-from-home events.
  - id: vacuum_away_blocks_only
    condition:
      type: calendar_entity
      calendar_entity: calendar.away_schedule
      negate: true
    effect:
      control_mode: confirm
    human_reason: >
      Base control_mode is autonomous. Autonomous operation is permitted only
      while the away calendar is active; outside scheduled away blocks the
      vacuum must ask first.
```

### 6.6 Confirmation Protocol

When `control_mode` is `confirm` and `enforcement_mode` is `enforced`, a Level 3 server MUST require the confirmation round-trip defined below before allowing the service call.

**What this protocol is for.** MESA's threat model (Section 3) assumes cooperative agents; deliberately deceptive agents are out of scope and are the operator's responsibility, with HA's native access control as the backstop. Within that model, this protocol protects against the accidental confirmation failures that cooperative agents actually exhibit: an agent that believes it already asked the user when it did not, an agent that loses conversational state mid-task, or an agent that obtains approval for one set of parameters and submits another. Because the first call always fails and returns a challenge, confirmation cannot be skipped by accident. Because the token is bound to the exact entity, service, and parameters, what executes is exactly what was approved. The protocol also produces an audit trail (`approved_by`, `approved_at`).

**What this protocol is not.** The server cannot verify that a human actually approved: the agent reports the approval, and a deliberately misbehaving agent could fabricate it. This is a scope decision, not an oversight. Host servers MAY additionally route approval through an out-of-band channel the agent does not mediate (an HA companion app actionable notification, a dashboard approval card) for deployments that want approval verification independent of the agent. Such channels are outside the scope of this specification.

**Confirmation flow:**

1. Agent calls a service on an entity with `control_mode: confirm`.
2. Enforcer denies the call and returns a `confirmation_challenge`: an opaque, single-use token bound to the specific entity, service, and parameters of the denied request.
3. Agent presents the action to the user and obtains explicit approval.
4. Agent re-submits the service call with a `confirmation_token` referencing the challenge and recording the approval.
5. Enforcer verifies the token is valid, matches the original request, and has not expired. If valid, the call proceeds.

**Confirmation challenge schema:**

| Field | Type | Description |
|---|---|---|
| `challenge_id` | `string` | Opaque single-use token. |
| `entity_id` | `string` | Entity the challenge applies to. |
| `service` | `string` | Service call that was denied. |
| `parameters` | `object` | Parameters of the denied call. |
| `expires_at` | `string` | ISO 8601 expiry. Challenges SHOULD expire within 120 seconds. |

**Confirmation token schema (returned with re-submitted call):**

| Field | Type | Description |
|---|---|---|
| `challenge_id` | `string` | The challenge being responded to. |
| `approved_by` | `string` | Caller ID of the approving user. |
| `approved_at` | `string` | ISO 8601 timestamp of approval. |

A confirmation token is valid only for the exact entity, service, and parameters in the original challenge. Changing any parameter requires a new challenge. Expired or reused tokens MUST be rejected.

In `advisory` enforcement mode, this protocol is not required. Agents SHOULD still obtain user confirmation for `confirm` entities, but the server does not verify it.

---

## 7. Privacy and Sensitivity Classification

Privacy classification is cross-cutting. The canonical location is as a sibling key of `semantic_profile`, not nested within it. Implementations that encounter `privacy_classification` nested inside `semantic_profile` SHOULD treat it as equivalent, but profile authors SHOULD place it as a sibling. During inheritance resolution, `privacy_classification` is resolved from a single canonical location regardless of where individual profiles placed it. Where classifications conflict between levels, the more restrictive MUST take precedence.

### 7.1 Privacy Classification Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `level` | `enum` | REQUIRED | `public`, `normal`, `sensitive`, or `restricted`. |
| `contains_presence_data` | `boolean` | RECOMMENDED | Exposes occupancy or location of individuals. |
| `contains_audio_capture` | `boolean` | RECOMMENDED | Captures or exposes audio. |
| `contains_visual_capture` | `boolean` | RECOMMENDED | Captures or exposes visual data. |
| `contains_biometric_data` | `boolean` | RECOMMENDED | Sleep patterns, heart rate, etc. |
| `contains_behavioural_data` | `boolean` | MAY | Patterns of individual behaviour over time. |
| `data_retention_local` | `boolean` | MAY | No cloud transmission. |
| `access_logging_recommended` | `boolean` | MAY | Default: `true` for `sensitive` and `restricted`. |
| `access_roles` | `object` | MAY | Role-based access. See Section 7.2. |
| `deny_response_mode` | `enum` | MAY | How to respond when access is denied. Default: `omit`. See below. |
| `privacy_note` | `string` | MAY | Short human-readable note capturing privacy nuance that the classification level cannot express. Example: "sensitive at night when occupants are sleeping, normal during daytime." |

**Privacy levels:**

| Value | Default agent behaviour |
|---|---|
| `public` | No restrictions. |
| `normal` | No restrictions. |
| `sensitive` | Agent SHOULD log access. SHOULD NOT expose raw data without operator confirmation. |
| `restricted` | Agent MUST log access. MUST NOT act autonomously. Operator confirmation REQUIRED. |

A standardised audit event schema for access logging is planned for a future revision. In v1.0, implementations MUST log the required events but MAY use any structured format. See the mesa-core Module Proposal for the planned `mesa_audit_event` schema.

**Approximate mapping to regulatory frameworks (informational, non-normative):**

| MESA level | GDPR approximate equivalent | CCPA approximate equivalent |
|---|---|---|
| `public` | Not personal data | Not personal information |
| `normal` | Personal data (Art. 4) | Personal information |
| `sensitive` | Personal data with higher risk (location, behavioural) | Sensitive personal information |
| `restricted` | Special category data (Art. 9: health, biometric) or data about minors | Sensitive personal information (Cal. Civ. Code 1798.121) |

This mapping is approximate. Regulatory compliance requirements vary by jurisdiction and context and are not determined solely by MESA privacy levels.

**`deny_response_mode` values:**

| Value | Description |
|---|---|
| `omit` | Entity absent from response. Absence may signal existence to aware callers. |
| `redact` | Return placeholder indicating denial without revealing entity details. |
| `error` | Return authorisation error. Caller knows they were denied. |

### 7.2 Role-Based Access

The `access_roles` object conditions privacy restrictions on caller role. Actual caller identity resolution is the responsibility of the MCP server via the caller context schema (Section 9.4).

| Field | Type | Description |
|---|---|---|
| `unrestricted_for` | `array<string>` | Roles for which base privacy level is relaxed to `normal`. |
| `restricted_for` | `array<string>` | Roles for which base level is escalated to `restricted`. |
| `deny_for` | `array<string>` | Roles for which access is denied entirely. |

Canonical role identifiers: `primary_resident`, `secondary_resident`, `child`, `guest`, `temporary_guest`, `caregiver`, `admin`.

A conforming agent with caller context MUST apply `access_roles` before acting on or surfacing data. Without caller context, apply the base privacy level.

```json
{
  "privacy_classification": {
    "level": "sensitive",
    "contains_presence_data": true,
    "contains_visual_capture": true,
    "access_logging_recommended": true,
    "deny_response_mode": "redact",
    "access_roles": {
      "unrestricted_for": ["primary_resident", "admin"],
      "deny_for": ["guest", "child"]
    }
  }
}
```

---

## 8. Integration Semantics

Integration profiles are authored by developers and distributed with the integration as a sidecar file named `mesa_profile.json`, placed in the integration directory. The file contains the `semantic_profile` and `privacy_classification` root objects, and optionally a `diagnostic_profile`. Because it travels inside the integration directory, it ships through normal distribution channels (HACS, manual install) without modifying any file that HA tooling validates.

**Data flow:** the host MCP server is responsible for extracting integration profiles at startup and writing them to the `ProfileStore` with `inheritance_scope: domain`. mesa-core provides `import_from_integration(integration_path)` to automate this: it reads the integration's `mesa_profile.json`. Profiles in `mesa_profile.json` that omit `metadata_origin` default to `source: developer` (Section 5.3).

**Why not `manifest.json`?** Earlier drafts of this specification distributed integration profiles as a top-level key in `manifest.json`. That path is rejected for two reasons: hassfest (the manifest validator run in most custom integration CI pipelines) rejects unknown keys with `extra keys not allowed`, and embedding foreign keys in a file validated by HA tooling couples MESA's schema evolution to HA's. MESA does not use `manifest.json`.

**Filesystem access requirement.** Reading sidecar files requires the host server to have filesystem access to the integration directories (for example, running as an HA add-on or with the HA config directory mounted). Hosts without filesystem access cannot import developer sidecar profiles directly; they rely on the `extra_state_attributes` path (profiles populated by the integration at setup time, at the cost of integration code and recorder overhead) or on operator-authored profiles.

### 8.1 Category Traits

| Field | Type | Required | Description |
|---|---|---|---|
| `functional_domain` | `string` | REQUIRED | Primary HA domain: `media_player`, `light`, `climate`, `tts`, etc. |
| `specialization` | `array<string>` | RECOMMENDED | Tags distinguishing this integration within its domain. |
| `performance_characteristics` | `array<string>` | MAY | Performance tags. See Appendix A. |

### 8.2 Capability Semantics

| Field | Type | Required | Description |
|---|---|---|---|
| `control_mode` | `enum` | RECOMMENDED | Default control mode for entities in this integration. Operator may tighten, or loosen `confirm` via the Rule A override (Section 5.7). |
| `triggers_automations` | `enum` | RECOMMENDED | Whether entities in this integration commonly trigger automations. Values: `likely`, `none`, `unknown`. See Section 4. |
| `reversible` | `boolean` | RECOMMENDED | Effects generally reversible. |
| `idempotent` | `boolean` | MAY | Repeated identical calls produce same result. |
| `state_persistence` | `enum` | MAY | Default persistence class. |
| `expected_latency_ms` | `number` | MAY | Typical latency from call to state change. |
| `network_dependency` | `enum` | RECOMMENDED | `local_only`, `local_preferred`, `cloud_required`, `cloud_optional`. |

### 8.3 Semantic Routing

| Field | Type | Required | Description |
|---|---|---|---|
| `enhances_domains` | `array<string>` | MAY | HA domains this integration enhances. |
| `intent_tags` | `array<string>` | RECOMMENDED | Tags describing agent intents this integration serves. |

Agents MUST prioritise integrations with MESA profiles over unprofiled alternatives when routing semantic queries, all else being equal. This provides a concrete adoption incentive: profiled integrations are preferred by MESA-aware agents.

### 8.4 Complete Integration Profile Example

```json
{
  "semantic_profile": {
    "schema_version": "1.0",
    "profile_version": "1.0",
    "metadata_origin": {"source": "developer", "confidence": 1.0},
    "semantic_tags": ["media.multiroom", "media.lossless"],
    "last_updated": "2026-05-27T00:00:00Z",
    "category_traits": {
      "functional_domain": "media_player",
      "specialization": ["media.multiroom", "media.lossless", "media.hardware_sync"],
      "performance_characteristics": ["latency.low", "sync.hardware_precise"]
    },
    "capability_semantics": {
      "control_mode": "autonomous",
      "reversible": true,
      "network_dependency": "local_only",
      "expected_latency_ms": 80
    },
    "operational_boundaries": {
      "control_mode": "autonomous",
      "triggers_automations": "none",
      "reversible": true,
      "reversibility_cost": "none",
      "side_effect_scope": "zone_wide",
      "state_volatility": "medium",
      "enforcement_mode": "advisory",
      "declared_limits": [
        {
          "id": "night_mode_volume",
          "predicate": {"entity": "input_boolean.night_mode", "operator": "eq", "value": true},
          "limit": {"service": "media_player.volume_set", "parameter": "volume_level", "max_value": 0.4},
          "human_reason": "Household occupants are sleeping."
        }
      ]
    },
    "semantic_routing": {
      "enhances_domains": ["media_player"],
      "intent_tags": ["audio.high_fidelity", "audio.multiroom"]
    }
  },
  "privacy_classification": {"level": "normal"}
}
```

---

## 9. Semantic Retrieval API

The retrieval API allows agents to query only the semantic context relevant to a given task rather than receiving full deployment snapshots. This is the primary mechanism by which MESA reduces context window consumption. The mesa-core module implements all retrieval API tools; host MCP servers register them with one function call.

### 9.1 Overview

A conforming Level 3 implementation exposes four core MCP tools (MUST) and two lease coordination tools (SHOULD).

| Tool | Purpose |
|---|---|
| `mesa_query_profiles` | Query profiles by domain, tag, area, intent, or origin with pagination. |
| `mesa_get_profile` | Retrieve a single complete profile by entity ID. |
| `mesa_request_lease` | Request a temporary coordination lease on entities. |
| `mesa_release_lease` | Release a held lease early. |
| `mesa_get_caller_context` | Retrieve caller identity and role for the current session. |
| `mesa_explain_profile` | Return the full inheritance resolution path for an entity. |

All endpoints MUST require authentication equivalent to HA's API authentication.

### 9.2 Query Request Schema

All filter fields are optional and combinable. An empty query returns all available profiles subject to pagination.

| Field | Type | Default | Description |
|---|---|---|---|
| `domains` | `array<string>` | - | Filter by HA domain. |
| `tags` | `array<string>` | - | Filter by semantic tags. |
| `tags_match` | `enum` | `any` | `any` or `all`. |
| `areas` | `array<string>` | - | Filter by area identifier. |
| `intents` | `array<string>` | - | Filter by intent dot-notation. |
| `min_origin_authority` | `enum` | - | `inferred_ai`, `hybrid`, `user`, or `developer`. |
| `include_inferred` | `boolean` | `false` | Include `inferred_ai` profiles. Opt-in required. |
| `include_fields` | `array<string>` | all | Limit returned sub-objects. `metadata_origin` always included. |
| `limit` | `number` | 50 | Maximum results per page. Maximum: 200. |
| `cursor` | `string` | - | Opaque pagination cursor from previous response. Cursors are valid for the session duration. A cursor MAY be invalidated by profile changes on the server; callers MUST handle `invalid_cursor` errors by restarting pagination from the beginning. |

```json
{
  "domains": ["light"],
  "areas": ["area.living_room"],
  "tags": ["lighting.ambient"],
  "include_inferred": false,
  "include_fields": ["semantic_tags", "operational_boundaries"],
  "limit": 50
}
```

**Implementation clarifications:**

- **`include_fields` with absent fields:** When a requested field is not present in a profile, that field is silently omitted from the result object. Servers MUST NOT return an error for absent fields. `metadata_origin` and `schema_version` are always included regardless of `include_fields`.
- **`tags_match: all` across inheritance levels:** Tag matching is evaluated against the effective resolved tag set for each entity, after inheritance rules have been applied. A tag present at any inheritance level is included in the effective set.
- **`tags_match: any` vs `all`:** `any` returns profiles containing at least one of the listed tags. `all` returns only profiles containing every listed tag. Both evaluate against the same effective resolved tag set.
- **Cursor invalidation:** Cursors become invalid when the server's profile data changes significantly (integration reload, bulk profile update). Servers MUST return `invalid_cursor` in this case. Clients MUST handle this error by restarting pagination from offset zero.
- **Confidence values:** Confidence scores in `inferred_ai` profiles are self-reported by the inference system that generated them. They are relative within a single deployment and MUST NOT be compared as absolute values across different deployments or inference systems.

### 9.3 Query Response Schema

**Response envelope:**

| Field | Always present | Description |
|---|---|---|
| `mesa_version` | Yes | MESA schema version of the responding server. |
| `caller_context` | Yes (when authenticated) | Caller identity and roles. See Section 9.4. |
| `results` | Yes | Array of profile result objects. |
| `total_matched` | Yes | Total matching profiles before pagination. |
| `pagination` | Yes | `limit`, `returned`, `has_more`, `next_cursor`. |
| `warnings` | No | Non-fatal warnings, e.g. stale profiles in result set. |

**Profile result object:**

| Field | Always present | Description |
|---|---|---|
| `entity_id` | Yes | HA entity ID or component identifier. |
| `component_type` | Yes | `entity`, `integration`, `automation`, `scene`, `area`, `helper`, `zone`, `person`. |
| `staleness_status` | Yes for `inferred_ai` | `current`, `stale`, or `unknown`. |
| `semantic_profile` | Yes | Profile object, filtered by `include_fields`. |
| `diagnostic_profile` | No | Included when available and `diagnostic_profile` in `include_fields`. |

### 9.4 Caller Context Schema

Surfaced by the MCP server from the authenticated session. Not authored by the agent.

| Field | Required | Description |
|---|---|---|
| `caller_id` | REQUIRED | Stable deployment-unique caller identifier. |
| `display_name` | RECOMMENDED | Human-readable name for audit logs. |
| `roles` | REQUIRED | Roles assigned to this caller. Used to evaluate `access_roles`. |
| `is_authenticated` | REQUIRED | Whether positively identified by HA authentication. |
| `session_id` | REQUIRED | Stable session identifier. Scopes leases. |
| `session_started_at` | REQUIRED | ISO 8601 session start timestamp. |

When `is_authenticated` is `false`, agents MUST treat the caller as having no roles and apply base privacy levels.

**Voice satellite identity.** Physical shared voice devices may not provide reliable individual identity. When biometric identification is unavailable, conforming servers MUST apply a least-privilege fallback: shared ambient devices operate under `guest` role by default, requiring explicit confirmation to elevate privileges.

### 9.5 MCP Tool Definitions

**`mesa_query_profiles`** - Query profiles with filtering and pagination. Input schema matches Section 9.2.

**`mesa_get_profile`** - Retrieve complete profile for one entity.
```json
{"entity_id": "string", "include_diagnostic": "boolean (default true)"}
```

**`mesa_request_lease`** - Request coordination lease. See Section 21.2 (MESA Enrichment).

**`mesa_release_lease`** - Release held lease.
```json
{"lease_id": "string"}
```

**`mesa_get_caller_context`** - Retrieve caller context for current session. No input required.

**`mesa_explain_profile`** - Return the full inheritance resolution path for an entity, showing which profile level contributed each effective field value and why. Essential for debugging unexpected agent behaviour.
```json
{
  "entity_id": "string",
  "show_conflicts": "boolean (default true - highlight fields where multiple levels declared values)"
}
```

**Response schema:**

| Field | Type | Always present | Description |
|---|---|---|---|
| `entity_id` | `string` | Yes | The queried entity ID. |
| `effective_profile` | `object` | Yes | The fully resolved profile as an agent would see it. |
| `explanation` | `array<object>` | Yes | Per-field resolution entries. See table below. |
| `conflicts_detected` | `boolean` | Yes | Whether any field had competing declarations across levels. |

**Explanation entry schema:**

| Field | Type | Always present | Description |
|---|---|---|---|
| `field_path` | `string` | Yes | Dot-notation path to the resolved field (e.g. `operational_boundaries.control_mode`, `privacy_classification.level`). |
| `effective_value` | `any` | Yes | The resolved value after inheritance and conflict resolution. |
| `provided_by_level` | `enum` | Yes | The profile level that contributed this value: `entity`, `area`, `domain`, `deployment_default`, or `built_in_baseline`. |
| `provided_by_origin` | `enum` | Yes | The origin authority of the contributing profile: `developer`, `user`, `hybrid`, `inferred_ai`, or `unknown`. |
| `conflict` | `boolean` | Yes | Whether multiple levels declared values for this field. |
| `conflict_resolution` | `string` | No | Present when `conflict` is true. Human-readable description of which rule resolved the conflict (e.g. "Rule A: tightening applied - area declared confirm over domain autonomous"). |
| `competing_values` | `array<object>` | No | Present when `conflict` is true and `show_conflicts` was requested. Each entry: `level`, `origin`, `value`. |

### 9.6 Error Responses

```json
{"error": "error_code", "message": "human-readable description", "details": {}}
```

| Code | Description |
|---|---|
| `unauthorized` | Missing or invalid authentication. |
| `forbidden` | Authenticated caller lacks permission. |
| `not_found` | Entity has no MESA profile. |
| `invalid_cursor` | Pagination cursor is invalid or expired. |
| `invalid_query` | Query contains invalid fields or operator tokens. |
| `lease_conflict` | Lease denied due to `protected` or `critical` automation. |
| `lease_not_found` | Lease ID does not exist or has expired. |
| `rate_limited` | Too many requests. `details.retry_after_seconds` provided. |
| `server_error` | Internal server error. |

---

# Sections 10-21: Enrichment Domains

Sections 10 through 21 are specified in the companion **MESA Enrichment** document: spatial semantics (10), automation and blueprint semantics (11), scene semantics (12), diagnostic semantics (13), event semantics (14), helper entity semantics (15), zone semantics (16), people semantics (17), Assist pipeline semantics (18), dashboard and UI semantics (19), resource and cost awareness (20), and the state lease protocol (21). Section numbering is continuous across the two documents, so cross-references remain stable.

Nothing in the Enrichment document is required for Level 1 or Level 2 conformance. A complete, valid, useful MESA implementation consists of this Core document alone. Behavioural rules the Enrichment document defines for person entities (Section 17) bind any implementation that processes person profiles; they are summarised in Appendix B.

---

## 22. Vendor Namespace Extensions

Vendor-specific tags MUST follow: `vendorname.custom_qualifier`. All lowercase. No hyphens in namespace root.

**Valid:** `myintegration.audio.spatial`, `mycommunity.lighting.circadian_advanced`
**Invalid:** `MyIntegration.Audio` (uppercase), `my-integration.audio` (hyphen in root)

Vendor namespaces MUST NOT use canonical MESA namespace roots (see Appendix A). Vendor tags extending a canonical domain MUST prefix: `myvendor.lighting.custom_feature`, not `lighting.myvendor_feature`.

Agents encountering unknown vendor namespace tags MUST treat them as opaque. The agent MAY surface them to the operator but MUST NOT infer their meaning.

Canonical MESA tags take precedence over vendor tags in semantic routing. Profiled integrations are preferred over unprofiled alternatives.

---

## 23. Governance

No formal governance body exists at the time of this writing. This section documents the intended governance model.

**Temporary governance (first year).** Canonical tags are added by consensus of implementors with at least three independent deployments. The proposal author maintains a public registry and change log. This is explicitly provisional. Components shipped by the proposal author (the reference module, MCP server, tools, and integrations) count as a single implementation for all consensus and graduation thresholds; independence means independent authorship.

**Namespace stewardship.** Canonical namespace roots are stewarded by the community working group. New canonical namespaces require community review and a reference implementation.

**Extension graduation.** Vendor tags with three or more independent implementations and consistent semantics are eligible for fast-track canonical promotion without full community review.

**Deprecation.** Deprecated canonical tags remain parseable for a minimum of two major schema versions.

**Schema versioning.** Patch versions (1.0.x) fix errors. Minor versions (1.x.0) add optional fields. Major versions (x.0.0) may introduce breaking changes with a documented migration path.

**Forward and backward compatibility.** When mesa-core encounters a profile with a `schema_version` higher than its own, it MUST parse all fields it recognises and silently ignore unknown fields. When it encounters a profile with a lower `schema_version`, it MUST parse it as-is without attempting migration. The mesa-core `migrate_profile()` utility (see mesa-core Module Proposal) handles explicit version migration when the operator requests it. Profiles are never silently migrated or rewritten.

**Reference implementation.** mesa-core is the reference implementation of the MESA Specification. When the specification and mesa-core behaviour diverge, the specification takes precedence. Discrepancies should be reported as issues in the mesa-core repository. mesa-core ships a canonical JSON Schema file (`mesa_profile.schema.json`) that is the machine-readable equivalent of the schema tables in this document. Third-party implementations MAY use this schema file for validation rather than reimplementing from prose.

**Seed vocabulary freeze.** The seed vocabulary defined in Appendix A is frozen for 90 days following initial publication. No new canonical tags are added during this period. This allows the community to stabilise implementations before the vocabulary evolves.

**Tag proposal process.** After the initial freeze, new canonical tags are proposed through the following process:

1. **Propose.** Open a GitHub Issue with the proposed tag, its dot-notation name, a clear definition, and the namespace it belongs to. State which existing vendor namespace tag (if any) this proposal would canonicalise.
2. **Reference implementations.** Provide links to at least two independent integrations or deployments using this tag (or the equivalent vendor namespace tag) in production. Both must be publicly accessible.
3. **Comment window.** A 14-day comment window opens. Any implementor may object with a technical reason. Objections without technical basis do not block progression.
4. **Acceptance.** If no unresolved technical objection exists after 14 days, the tag is accepted into the next minor version of the seed vocabulary.

Tags that receive no reference implementations within 90 days of proposal are closed without prejudice and may be resubmitted.

---

## 24. Related Work

**W3C WoT Thing Description.** WoT TD is device-centric; MESA is deployment-centric. WoT TD describes a single device in isolation. MESA describes a device's operational meaning within a specific deployment, including its relationships to spaces, automations, and user expectations. MESA addresses spatial topology, automation conflict semantics, and AI agent operational boundaries that WoT TD does not.

**Matter Device Type Model.** Matter defines what a device is at the protocol level. MESA defines what it means within a deployment and how agents should reason about it. Complementary, not competing.

**schema.org IoT Extensions.** Aimed at web-scale discovery and search indexing. Does not address operational boundaries, spatial topology, automation conflict, or agent context management.

---

## Appendix A: Seed Vocabulary

Tags follow `domain.qualifier` dot notation. All lowercase.

### Lighting
`lighting.ambient`, `lighting.task`, `lighting.accent`, `lighting.security`, `lighting.circadian`, `lighting.dimming`, `lighting.colour`, `lighting.scene`

### Climate
`climate.heating`, `climate.cooling`, `climate.humidity_control`, `climate.energy_optimization`, `climate.comfort_optimization`, `climate.zone_control`, `climate.air_quality`

### Media
`media.multiroom`, `media.lossless`, `media.hardware_sync`, `media.voice_control`, `media.casting`, `media.local_only`

### Security
`security.entry_monitoring`, `security.motion_detection`, `security.perimeter`, `security.alarm`, `security.access_control`, `security.camera`

### Presence and Occupancy
`presence.occupancy`, `presence.person_identification`, `presence.sleep_tracking`, `presence.arrival_departure`

### Energy and Power
`energy.monitoring`, `energy.high_consumption`, `energy.solar`, `energy.battery`, `energy.grid_aware`

### Space
`space.sleeping`, `space.working`, `space.media`, `space.entertainment`, `space.utility`, `space.transition`, `space.outdoor`

### Diagnostics and Causality
`diagnostic.causality`, `diagnostic.confidence_scored`, `diagnostic.history_log`, `diagnostic.read_only`, `diagnostic.drift_prone`

### Performance
`latency.low`, `latency.medium`, `latency.high`, `sync.hardware_precise`, `reliability.high`, `reliability.poll_dependent`

### Audio
`audio.high_fidelity`, `audio.multiroom`, `audio.synchronised_playback`, `audio.voice_optimised`

### TTS and Speech
`tts.multilingual`, `tts.expressive_voices`, `tts.auto_chunking`

### Automation Intent
`automation.lighting`, `automation.climate`, `automation.security`, `automation.energy_conservation`, `automation.presence_response`, `automation.schedule_based`, `automation.notification`, `automation.media`, `automation.maintenance`

### Scene Intent
`scene.lighting`, `scene.climate`, `scene.media`, `scene.security`, `scene.away`, `scene.sleep`, `scene.arrival`, `scene.guest`

### Helpers
`helper.mode_flag`, `helper.config_parameter`, `helper.coordination_signal`, `helper.counter_metric`, `helper.timer_control`, `helper.user_preference`, `helper.dashboard_only`, `helper.high_impact`

### Zones
`zone.home`, `zone.workplace`, `zone.school`, `zone.healthcare`, `zone.child_associated`, `zone.high_sensitivity`

### People
`person.primary_resident`, `person.secondary_resident`, `person.child`, `person.guest`, `person.caregiver`

### Assist
`assist.local`, `assist.cloud`, `assist.satellite`, `assist.always_on`, `assist.announcement_capable`

### UI Structural Tags
`ui.glanceable` (optimised for rapid comprehension), `ui.accessible` (accessibility-focused design)

### Resource
`resource.high_power`, `resource.cloud_dependent`, `resource.local_only`, `resource.grid_aware`, `resource.battery_powered`

---

## Appendix B: Conformance Summary

Conformance levels are declared by host implementations (Section 2). Table B.1 lists host requirements; these are what the conformance test suite verifies. Table B.2 lists agent behaviour requirements: normative guidance for agent developers that is not machine-verifiable. Rows citing Sections 10-21 refer to the MESA Enrichment document.

### B.1 Host Implementation Requirements

| Requirement | Section | Level |
|---|---|---|
| Parse `semantic_profile` without error | 5.1 | L1 MUST |
| Default `control_mode` to `confirm` when absent | 4 | L1 MUST |
| `read_only` treated as equivalent to `prohibited` in tightening hierarchy | 4 | L1 MUST |
| Operator MUST NOT loosen a `prohibited` or `read_only` declaration | 4 | L2 MUST |
| Loosening inherited `confirm` to `autonomous` requires entity-level `user`-origin profile with `override_control_mode: true` and `control_reason` | 5.7 | L1 MUST |
| `triggers_automations: likely` is sticky upward; `none` is not sticky | 5.6 | L1 MUST |
| Sidecar profiles without `metadata_origin` default to `source: developer`; all other locations default to `source: unknown` | 5.3 | L1 MUST |
| Orphaned profiles (entity ID no longer in registry) detected and surfaced | 5.5 | L2 SHOULD |
| Rule D: scope precedence among trusted origins; `inferred_ai`/`unknown` never override trusted-tier declarations | 5.7 | L1 MUST |
| Operators can delete any profile of any origin, at any scope (entity, area, domain) | 3 | L2 MUST |
| Inferred profiles require opt-in in retrieval API | 5.4 | L2 MUST |
| All inferred profiles default `control_mode: confirm` | 5.4 | L2 MUST |
| Helper-domain inferred profiles default `triggers_automations: likely`; MUST NOT assert `none` | 5.4 | L2 MUST |
| `side_effect_scope` refers to direct hardware footprint only | 6.2 | L1 MUST |
| Canonical predicate operators used; HA native syntax also accepted | 6.3 | L1 SHOULD |
| Unrecognised non-HA operator tokens rejected | 6.3 | L1 MUST |
| Temporal effects are tightening-only; loosening effects ignored with warning | 6.5 | L1 MUST |
| Unevaluable temporal conditions treated as active (fail-closed) | 6.5 | L1 MUST |
| `enforced` mode: server SHOULD support it; when supported MUST reject violating calls | 6.1 | L3 SHOULD/MUST |
| `confirm` in enforced mode requires confirmation challenge/token round-trip | 6.6 | L3 MUST (when enforced) |
| More restrictive privacy classification takes precedence | 7.1 | L1 MUST |
| Person entities treated as `sensitive` by default | 17 | L1 MUST |
| `is_minor: true` triggers `restricted` regardless of declared level | 17 | L1 MUST |
| Four core retrieval API tools registered and available (`mesa_query_profiles`, `mesa_get_profile`, `mesa_get_caller_context`, `mesa_explain_profile`) | 9.1 | L3 MUST |
| Lease tools registered (`mesa_request_lease`, `mesa_release_lease`) | 9.1 | L3 SHOULD |
| `include_inferred: false` is the default for retrieval queries | 9.2 | L3 MUST |
| Unauthenticated requests rejected | 9.1 | L3 MUST |
| Voice satellite shared devices use `guest` role as least-privilege default | 9.4 | L3 MUST |
| Snapshot captured for `snapshot_restorable` automations before firing | 11.5 | L3 SHOULD |
| `binary_sensor.mesa_lease_active` sensor exposed for native automation awareness | 21.1 | L3 SHOULD |
| Lease denied for `protected` or `critical` automation entities (when lease tools implemented) | 21.5 | L3 SHOULD |
| Preempted agent notified before lease is taken (when lease tools implemented) | 21.6 | L3 SHOULD |
| Vendor namespaces MUST NOT reuse canonical roots | 22 | L1 MUST |

### B.2 Agent Behaviour Requirements

| Requirement | Section | Keyword |
|---|---|---|
| Treat `confirm` as `prohibited` when no interaction channel exists, for all domains | 4 | MUST |
| Surface configuration warning when non-interactive and `deployment_defaults` not configured | 4 | SHOULD |
| Apply lower epistemic weight to `inferred_ai` profiles | 5.4 | MUST |
| MAY use `inferred_ai` profiles with confidence >= 0.7 for non-safety decisions | 5.4 | MAY |
| Safety-critical fields require human confirmation regardless of confidence | 5.4 | MUST |
| Use `triggers_automations` alongside `side_effect_scope` for cascade awareness | 4 | SHOULD |
| Log all person entity accesses | 17 | MUST |
| Treat unknown vendor tags as opaque | 22 | MUST |
| Prefer profiled integrations over unprofiled in routing | 8.3 | SHOULD |

---

*MESA - Metadata and Environment Semantics for Agents. Version 1.0. Core specification. See also: MESA Overview, MESA Enrichment, MESA Getting Started Guide, and mesa-core Module Proposal. Discussion and contributions are welcome via GitHub Issues.*
