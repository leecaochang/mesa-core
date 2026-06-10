# MESA Enrichment Specification
**Version:** 1.0
**Document Type:** Formal Schema Reference (companion to the MESA Specification)

---

## Abstract

This document specifies the twelve MESA enrichment domains: schemas that improve agent reasoning significantly but are not required for conformance. It is the companion to the MESA Specification (the Core document). Section numbering is continuous across the two documents: the Core document defines Sections 1 through 9 and 22 through 24; this document defines Sections 10 through 21. References to sections outside that range refer to the Core document.

**Nothing in this document is required.** Implementing none of it leaves a complete, valid, useful MESA implementation. Implementing any subset delivers proportional benefit. All schemas are additive, and fields here that conflict with Core fields follow the global conflict resolution rules defined in Core Section 5.7.

One qualification: where this document defines behavioural rules for specific component types — person entities (Section 17) are the significant case — those rules bind any implementation that processes profiles for those component types, regardless of which other enrichment domains it implements. These rules are summarised in the Core document's Appendix B.

Read a section when you have a specific problem it solves: spatial leakage when agents make spatially naive decisions, diagnostic semantics when agents cannot distinguish failure modes, automation cooperative priority when race conditions are occurring. Each section is self-contained. You do not need to read this document in order or in full.

---

## Table of Contents

10. [Spatial Semantics](#10-spatial-semantics)
11. [Automation and Blueprint Semantics](#11-automation-and-blueprint-semantics)
12. [Scene Semantics](#12-scene-semantics)
13. [Diagnostic Semantics](#13-diagnostic-semantics)
14. [Event Semantics](#14-event-semantics)
15. [Helper Entity Semantics](#15-helper-entity-semantics)
16. [Zone Semantics](#16-zone-semantics)
17. [People Semantics](#17-people-semantics)
18. [Assist Pipeline Semantics](#18-assist-pipeline-semantics)
19. [Dashboard and UI Semantics](#19-dashboard-and-ui-semantics)
20. [Resource and Cost Awareness](#20-resource-and-cost-awareness)
21. [State Lease Protocol](#21-state-lease-protocol)

---

## 10. Spatial Semantics

Spatial profiles allow agents to reason about the physical structure of a deployment rather than treating it as a flat entity list. They are authored by operators and attached to area and floor registry entries.

### 10.1 Spatial Traits Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `activity_profile` | `enum` | RECOMMENDED | `sleeping`, `working`, `social`, `media`, `utility`, `transition`, `mixed`. |
| `occupancy_pattern` | `enum` | MAY | `continuous`, `intermittent`, `scheduled`, `rare`, `variable`. |
| `natural_light_exposure` | `enum` | MAY | `full`, `partial`, `minimal`, `none`. |
| `acoustic_profile` | `enum` | MAY | `isolated`, `semi_isolated`, `open`, `shared`. |
| `thermal_zone` | `string` | MAY | Identifier linking to a shared HVAC zone. |
| `privacy_sensitivity` | `enum` | MAY | `public`, `normal`, `elevated`, `restricted`. |
| `spatial_leakage` | `array<object>` | MAY | Explicit leakage relationships. See Section 10.3. |

### 10.2 Logical Groupings Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `floor` | `string` | RECOMMENDED | Floor identifier matching HA floor registry. |
| `adjacent_areas` | `array<string>` | RECOMMENDED | Areas sharing a physical boundary. |
| `shared_thermal_areas` | `array<string>` | MAY | Areas sharing a thermal zone. |
| `shared_acoustic_areas` | `array<string>` | MAY | Areas sharing acoustic environment. |
| `logical_zone` | `string` | MAY | Operator-defined cluster: `guest_wing`, `entertainment_zone`, etc. |

### 10.3 Spatial Leakage Schema

Describes how effects in this area propagate to other areas through physical channels. Distinct from `adjacent_areas` which describes structural adjacency. Leakage describes directional effect propagation.

| Field | Type | Required | Description |
|---|---|---|---|
| `target_area` | `string` | REQUIRED | Area receiving leakage from this area. |
| `leakage_type` | `enum` | REQUIRED | `acoustic`, `thermal`, `visual`, `airflow`, `electromagnetic`. |
| `severity` | `enum` | REQUIRED | `negligible`, `minor`, `moderate`, `significant`, `full`. |
| `conditions` | `string` | MAY | When leakage is most pronounced. |

```json
{
  "spatial_leakage": [
    {
      "target_area": "area.study",
      "leakage_type": "acoustic",
      "severity": "significant",
      "conditions": "Open plan. Sound carries clearly at all volume levels."
    }
  ]
}
```

---

## 11. Automation and Blueprint Semantics

Automation profiles allow agents to reason about the automation landscape before taking action, avoiding conflicts and race conditions.

**Storage note.** The HA UI editor rewrites automation YAML on save and removes unrecognised keys including `semantic_profile`. Automation profiles embedded directly in automation YAML will be lost when edited through the UI. The recommended approach is to store automation profiles in an MCP server integrating mesa-core's configuration interface, keyed by automation ID. YAML embedding is suitable only for automations managed exclusively through direct YAML editing. Native HA UI support for MESA profile editing is a planned capability.

### 11.1 Intent Archetype

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | `string` | REQUIRED | Namespaced dot-notation intent identifier. |
| `description` | `string` | RECOMMENDED | What this automation does and why. |
| `primary_domain` | `string` | RECOMMENDED | HA domain primarily operated in. |
| `affected_areas` | `array<string>` | RECOMMENDED | Areas this automation affects. |
| `affected_entities` | `array<string>` | MAY | Specific entity IDs read or written. |

### 11.2 Cooperative Priority

| Field | Type | Required | Description |
|---|---|---|---|
| `level` | `enum` | REQUIRED | Preemption level. See table below. |
| `conflict_notification` | `boolean` | RECOMMENDED | Notify agent when automation fires concurrently. Default: `true`. |
| `scope` | `enum` | MAY | `entity`, `area`, `domain`, `deployment`. |

**Preemption levels:**

| Value | Agent can interrupt | Can interrupt agent | Typical use |
|---|---|---|---|
| `deferential` | Yes, freely | No | Convenience, non-essential routines. |
| `cooperative` | Yes, with notification | Only if lower priority | Most household automations. Recommended default. |
| `assertive` | Only with user confirmation | Yes, notifies agent | Energy rules, scheduled household-wide routines. |
| `protected` | No | Yes, notifies agent | Security, safety-adjacent, medication. |
| `critical` | No | Yes, immediately | Smoke, CO, flood, intrusion. |

### 11.3 Environmental Dependencies

Agents that need to reason about cascade effects from a proposed action SHOULD query `environmental_dependencies` across automation profiles and compute the cascade graph, rather than relying on `side_effect_scope` of individual entities.

| Field | Type | Description |
|---|---|---|
| `trigger_entities` | `array<string>` | Entity IDs that can trigger this automation. |
| `condition_entities` | `array<string>` | Entity IDs evaluated in conditions. |
| `monitored_semantic_tags` | `array<string>` | Tag categories this automation is sensitive to. |

### 11.4 Blocking Indicators

| Field | Type | Description |
|---|---|---|
| `suppression_entities` | `array<object>` | Predicate objects (Section 6.3) whose state suppresses this automation. |
| `pause_on_agent_active` | `boolean` | Pause when agent is actively orchestrating entities in scope. Default: `false`. |

### 11.5 Reversibility

Home Assistant state changes are not transactional. MESA models this through two reversibility classes.

| Value | Description |
|---|---|
| `stateless_destructive` | Cannot be reliably reversed. Pre-trigger state is not knowable, or restoring it would itself be disruptive. |
| `snapshot_restorable` | Effects can be reversed by restoring entity state snapshots captured before the automation fired. A Level 3 host server MUST capture these snapshots. |

| Field | Type | Required | Description |
|---|---|---|---|
| `reversibility_class` | `enum` | REQUIRED | `stateless_destructive` or `snapshot_restorable`. |
| `snapshot_entities` | `array<string>` | CONDITIONAL | Required for `snapshot_restorable`. Entity IDs to snapshot. |
| `rollback_window_seconds` | `number` | MAY | Window within which rollback can be requested. Default: 300. |
| `side_effects_reversible` | `boolean` | MAY | Whether side effects beyond snapshotted entities are also reversible. |

---

## 12. Scene Semantics

Scenes are distinct from automations: they are invoked explicitly, have no triggers, and their effects span multiple entities.

| Field | Type | Required | Description |
|---|---|---|---|
| `intent` | `string` | REQUIRED | Namespaced intent: `lighting.movie_night`, `climate.away_mode`. |
| `description` | `string` | RECOMMENDED | What this scene configures and when to activate it. |
| `affected_areas` | `array<string>` | RECOMMENDED | Areas affected. |
| `affected_domains` | `array<string>` | RECOMMENDED | HA domains of entities configured. |
| `activation_context` | `array<enum>` | RECOMMENDED | `manual`, `agent`, `automation`, `scheduled`. |
| `cooperative_priority` | `enum` | RECOMMENDED | Preemption level. Inherits values from Section 11.2. Default: `cooperative`. |
| `conflict_with` | `array<string>` | MAY | Intent identifiers of known conflicting scenes or automations. |
| `reversible` | `boolean` | RECOMMENDED | Whether prior states can be restored. |
| `restore_on_deactivate` | `boolean` | MAY | Whether prior states should be restored on deactivation. |

---

## 13. Diagnostic Semantics

Diagnostic profiles map integration-specific runtime states and error conditions to machine-readable contexts and recovery information. They allow agents to move beyond opaque platform states like `unavailable`.

### 13.1 State Mapping

| Field | Type | Required | Description |
|---|---|---|---|
| `state_value` | `string` | REQUIRED | Raw state string. |
| `semantic_meaning` | `string` | REQUIRED | What this state means in this integration's context. |
| `severity` | `enum` | RECOMMENDED | `info`, `low`, `medium`, `high`, `critical`. |
| `is_normal_operation` | `boolean` | REQUIRED | Whether this represents healthy operation. |
| `agent_action_recommended` | `enum` | RECOMMENDED | `none`, `notify`, `retry`, `recover`, `escalate`. |
| `error_classes` | `array<string>` | MAY | References to error class entries. |

### 13.2 Error Classes and HA Exception Mapping

The `class` field SHOULD use the Python exception class name exactly as it appears in integration source or HA core logs.

| Field | Type | Required | Description |
|---|---|---|---|
| `class` | `string` | REQUIRED | Python exception class name. |
| `ha_base_exception` | `string` | RECOMMENDED | HA core base exception. See table below. |
| `severity` | `enum` | REQUIRED | Severity level. |
| `recoverable` | `boolean` | REQUIRED | Recoverable without operator intervention. |
| `reason` | `string` | REQUIRED | Machine-readable description of why this error occurs. |
| `user_actionable_remedy` | `string` | RECOMMENDED | What the operator can do. |
| `agent_recovery_service` | `string` | MAY | HA service call to attempt as first recovery step. |
| `retry_after_seconds` | `number` | MAY | Recommended retry delay. |

**HA core exception reference:**

| Exception | Module | Default Severity |
|---|---|---|
| `HomeAssistantError` | `homeassistant.exceptions` | `medium` |
| `ServiceNotFound` | `homeassistant.exceptions` | `high` |
| `InvalidStateError` | `homeassistant.exceptions` | `medium` |
| `Unauthorized` | `homeassistant.exceptions` | `high` |
| `ConfigEntryNotReady` | `homeassistant.exceptions` | `medium` |
| `ConfigEntryAuthFailed` | `homeassistant.exceptions` | `high` |
| `PlatformNotReady` | `homeassistant.exceptions` | `medium` |
| `TemplateError` | `homeassistant.exceptions` | `low` |
| `NoEntitySpecifiedError` | `homeassistant.exceptions` | `medium` |
| `IntegrationError` | `homeassistant.exceptions` | `medium` |

Agents MUST NOT infer severity from exception class names alone.

### 13.3 Attribute Semantics

| Field | Type | Required | Description |
|---|---|---|---|
| `attribute_name` | `string` | REQUIRED | Attribute key as in entity state attributes. |
| `semantic_meaning` | `string` | REQUIRED | Machine-readable description. |
| `value_type` | `enum` | REQUIRED | `string`, `number`, `boolean`, `array`, `object`, `enum`. |
| `machine_actionable` | `boolean` | REQUIRED | Agent SHOULD use in reasoning. |
| `value_range` | `object` | MAY | `min` and `max` for numeric attributes. |
| `value_vocabulary` | `array<string>` | MAY | Valid values for enum attributes. |
| `preferred_interface` | `enum` | MAY | `attribute_poll`, `event_preferred`, `attribute_only`. |

---

## 14. Event Semantics

For integrations communicating via the HA event bus rather than continuous state machines.

| Field | Type | Required | Description |
|---|---|---|---|
| `event_type` | `string` | REQUIRED | Event type string as fired on the HA event bus. |
| `semantic_meaning` | `string` | REQUIRED | What this event represents and when it fires. |
| `payload_structure` | `object` | RECOMMENDED | Field names mapped to `{type, description, values?}` objects. |
| `event_behavior` | `object` | RECOMMENDED | `ephemeral` (boolean), `retention_seconds`, `ordering_guaranteed`, `replayable`. |
| `relationship_to_state` | `enum` | MAY | `supplements_state`, `replaces_state_polling`, `independent`, `precedes_state`. |
| `privacy_classification` | `object` | MAY | Privacy classification for this event's payload. |

---

## 15. Helper Entity Semantics

Helpers (input_boolean, input_number, input_text, input_select, input_datetime, counter, timer) frequently act as mode flags, configuration parameters, or coordination signals.

**How to add helper profiles.** Home Assistant's helper configuration UI does not currently support adding MESA profiles directly. Helper profiles are added through one of these paths:
- Through an MCP server integrating mesa-core's configuration interface (recommended). The server stores profiles keyed by entity ID and applies them at query time.
- Through `customize.yaml` in `configuration.yaml`. Profiles added here persist through UI edits because `customize.yaml` is not rewritten by the HA UI. Requires a config reload after changes.
- Through `extra_state_attributes` populated by a small custom integration at startup.

Native HA UI support for MESA profile editing is a planned community capability. Without profiles, agents cannot distinguish a cosmetic dashboard toggle from a critical mode flag driving dozens of automations.

**Common fields for all helper types:**

| Field | Type | Required | Description |
|---|---|---|---|
| `role` | `enum` | REQUIRED | `mode_flag`, `config_parameter`, `coordination_signal`, `counter_metric`, `timer_control`, `user_preference`, `dashboard_only`. |
| `affected_automations` | `array<string>` | RECOMMENDED | Automation IDs whose behaviour changes when this helper changes. |
| `default_state` | `any` | MAY | Expected state during normal operation. |

**`mode_flag` and `coordination_signal` helpers should always declare `affected_automations`.** These are the highest-impact helpers. An agent modifying a mode flag without knowing which automations it controls may cause broad, unexpected behaviour.

**Type-specific fields:**

| Helper type | Additional required/recommended fields |
|---|---|
| `input_boolean` | `true_meaning`, `false_meaning` |
| `input_number` | `parameter_meaning`, `unit`, `safe_range` |
| `input_text` | `text_meaning`, `format_hint`, `sensitive` |
| `input_select` | `selector_meaning`, `option_meanings` |
| `input_datetime` | `datetime_meaning`, `has_date`, `has_time`, `schedule_effect` |
| `counter` | `counter_meaning`, `unit`, `write_intent` |
| `timer` | `timer_meaning`, `on_finish_effect`, `duration_seconds` |

---

## 16. Zone Semantics

Zones define geographic areas for presence detection. Without profiles, agents cannot determine whether a zone is a residential address, a workplace, a child's school, or a public location.

| Field | Type | Required | Description |
|---|---|---|---|
| `zone_type` | `enum` | REQUIRED | `home`, `workplace`, `school`, `healthcare`, `family`, `recreational`, `transit`, `custom`. |
| `description` | `string` | RECOMMENDED | What this zone represents. |
| `associated_persons` | `array<string>` | MAY | Person entity IDs relevant to this zone. |
| `arrival_automations` | `array<string>` | MAY | Automations triggered by arrival. |
| `departure_automations` | `array<string>` | MAY | Automations triggered by departure. |
| `presence_sensitivity` | `enum` | RECOMMENDED | Privacy sensitivity of knowing someone is here. |
| `location_sensitivity` | `enum` | RECOMMENDED | Privacy sensitivity of the zone's coordinates. |

---

## 17. People Semantics

Person entities carry the highest inherent privacy sensitivity of any standard HA entity type. MESA persons profiles are the only context where a default privacy level is mandated: all person entities MUST be treated as `sensitive` by default in the absence of an explicit classification.

**Person-specific rules that cannot be overridden:**

1. Agents MUST NOT expose a person's current geographic location to callers without `unrestricted_for` role for that person.
2. When `is_minor: true`, agents MUST apply `restricted` level behaviour regardless of declared privacy level.
3. Agents MUST log all accesses to person entities regardless of `access_logging_recommended`.
4. Agents MUST NOT use person data to construct behavioural profiles beyond the immediate task.

| Field | Type | Required | Description |
|---|---|---|---|
| `household_role` | `enum` | REQUIRED | `primary_resident`, `secondary_resident`, `child`, `regular_guest`, `temporary_guest`, `caregiver`. |
| `display_name` | `string` | RECOMMENDED | Human-readable name for audit logs. |
| `is_minor` | `boolean` | RECOMMENDED | Triggers mandatory `restricted` privacy. |
| `associated_zones` | `array<string>` | MAY | Significant zone IDs for this person. |
| `associated_automations` | `array<string>` | MAY | Automations responding to this person. |
| `presence_entity` | `string` | MAY | Primary device tracker entity ID. |

Privacy classification is REQUIRED for all person entities.

---

## 18. Assist Pipeline Semantics

### 18.1 Pipeline Profile

| Field | Type | Required | Description |
|---|---|---|---|
| `pipeline_name` | `string` | REQUIRED | Human-readable pipeline name. |
| `language` | `string` | REQUIRED | BCP 47 language tag. |
| `stt_engine` | `string` | RECOMMENDED | Speech-to-text engine identifier. |
| `nlu_engine` | `string` | RECOMMENDED | Natural language understanding engine. |
| `tts_engine` | `string` | RECOMMENDED | TTS entity ID for this pipeline. |
| `preferred_for_agents` | `boolean` | RECOMMENDED | Whether agents should use this pipeline for output routing. |
| `associated_satellites` | `array<string>` | RECOMMENDED | Voice satellite entity IDs. |
| `wake_word` | `string` | MAY | Configured wake word. |
| `network_dependency` | `enum` | RECOMMENDED | Cloud dependency level. |
| `concurrency_mode` | `enum` | MAY | `exclusive`, `cooperative`, `independent`. How agent output should coordinate with pipeline activity. |

### 18.2 Voice Satellite Profile

| Field | Type | Required | Description |
|---|---|---|---|
| `area` | `string` | REQUIRED | Physical area of this satellite. |
| `pipeline_id` | `string` | RECOMMENDED | Associated pipeline identifier. |
| `microphone_quality` | `enum` | MAY | `basic`, `standard`, `enhanced`, `array`. |
| `speaker_quality` | `enum` | MAY | `basic`, `standard`, `enhanced`. |
| `always_on_mic` | `boolean` | RECOMMENDED | Whether continuously listening for wake word. |
| `suitable_for_tts_output` | `boolean` | RECOMMENDED | Whether suitable for agent-generated announcements. |
| `announcement_volume_limit` | `number` | MAY | Max volume for agent announcements (0.0 to 1.0). |
| `wake_word_sensitivity` | `enum` | MAY | `low`, `medium`, `high`. Helps agents avoid false triggers from their own output. |
| `primary_users` | `array<string>` | MAY | Person entity IDs most likely to use this satellite. |

---

## 19. Dashboard and UI Semantics

**Status: schema definition only. Not queryable via the retrieval API in v1.0.**

Home Assistant Lovelace cards have no stable unique identifiers. Cards are referenced internally by positional index within their view, and these indices shift on every insert or delete operation. The HA card config type accepts arbitrary fields (`[key: string]: any`), so a custom `mesa_card_id` would survive storage round-trips, but the built-in visual card editor may strip unrecognised fields on re-save, silently breaking the profile link. Until HA provides native stable card identifiers, dashboard card profiles cannot be reliably keyed, stored, or queried. The schema below is defined for forward compatibility and MAY be used by custom tooling that manages its own card identification, but `dashboard_card` is not a valid `component_type` in retrieval API responses.

Allows agents to discover and use custom frontend components rather than defaulting to standard Lovelace cards.

| Field | Type | Required | Description |
|---|---|---|---|
| `component_type` | `enum` | REQUIRED | `custom_card`, `custom_badge`, `custom_row`, `custom_header`, `custom_panel`, `custom_renderer`. |
| `visual_aesthetic` | `array<string>` | MAY | Aesthetic descriptors. Use vendor namespace tags for aesthetics (e.g. `myvendor.aesthetic.rounded`). |
| `density` | `enum` | RECOMMENDED | `compact`, `comfortable`, `spacious`. |
| `interaction_precision` | `enum` | MAY | `binary`, `stepped`, `fine_grained`, `gesture_based`. |
| `optimized_for_devices` | `array<enum>` | RECOMMENDED | `smartphone`, `tablet`, `touchscreen`, `desktop`, `wall_panel`, `tv`. |
| `supports_theming` | `boolean` | MAY | Respects active HA theme. |
| `min_card_width_columns` | `number` | MAY | Minimum Lovelace grid columns. |
| `information_depth` | `enum` | MAY | `summary`, `equivalent`, `enhanced`, `comprehensive`. |
| `best_for` | `array<string>` | RECOMMENDED | Semantic tags of entity types this component excels at. |

---

## 20. Resource and Cost Awareness

Allows agents to prefer efficient operations when functionally equivalent options exist.

| Field | Type | Required | Description |
|---|---|---|---|
| `estimated_power_watts` | `number` | MAY | Typical power consumption. |
| `peak_power_watts` | `number` | MAY | Peak power consumption. |
| `network_dependency` | `enum` | RECOMMENDED | Cloud dependency level. |
| `cost_class` | `enum` | RECOMMENDED | `negligible`, `low`, `medium`, `high`, `variable`. |
| `local_processing` | `boolean` | MAY | Computation performed locally. |
| `data_transmission_class` | `enum` | MAY | `none`, `minimal`, `moderate`, `substantial`. |
| `grid_aware` | `boolean` | MAY | Can adjust behaviour based on grid conditions or tariff. |
| `carbon_intensity_impact` | `enum` | MAY | `low`, `medium`, `high`. |
| `tariff_aware` | `boolean` | MAY | Can adjust behaviour based on energy tariff signals. |
| `demand_response_capable` | `boolean` | MAY | Can participate in demand response programs. |

---

## 21. State Lease Protocol

### 21.1 Motivation and Honest Limitations

**Read this section before implementing.** The lease protocol does less than its name implies.

The MESA lease protocol is an **advisory coordination signal between MESA-aware components only**. It is not a concurrency lock. It does not provide exclusive access to entities. Native YAML automations, Node-RED flows, physical switches, Zigbee hardware bindings, and any other non-MESA component will continue to modify entity state without any awareness of active leases. This is a fundamental architectural limitation that cannot be resolved without upstream changes to Home Assistant core.

The practical consequence: an agent that acquires a lease on a climate entity and begins a multi-step adjustment may have its state invalidated mid-sequence by a native automation, a physical thermostat interaction, or another agent that does not participate in the lease protocol. The lease does not prevent this. It signals intent to components that are listening.

The 30-second maximum lease duration reflects this reality. Leases are suitable for short, focused action sequences. They are not suitable for long-running orchestration tasks.

The `binary_sensor.mesa_lease_active` pattern for native automation awareness has an additional limitation: an automation checking this sensor at trigger time races with the agent's lease acquisition. The check is not atomic. Automation authors who add this condition improve coordination but cannot guarantee it.

**What the lease protocol is good for:** coordinating between multiple MESA-aware agents, signalling intent to MESA-aware automations that voluntarily check lease state, and providing an audit trail of agent orchestration activity.

**What it is not good for:** guaranteeing exclusive state control, preventing native automation interference, or replacing proper concurrency mechanisms.

**Agent behaviour when external state changes are detected during an active lease.** An agent holding a lease SHOULD monitor the state of leased entities for changes it did not initiate. When such an external change is detected, the agent MUST NOT attempt to correct or override it by re-applying its intended state. Instead the agent SHOULD release the lease immediately and notify the operator that external interference occurred during the operation. Entering a correction loop against a native automation creates exactly the loop-thrashing and redundant API execution the lease protocol is designed to prevent.

**Implementation priority note.** Developers building MCP servers integrating mesa-core should implement the Core specification (kernel consumption, diagnostic profile surfacing, privacy enforcement, retrieval API) before investing in the lease protocol. The kernel and diagnostic profiles deliver immediate, demonstrable value with zero coordination dependencies. The lease protocol only delivers value in deployments where multiple MESA-aware agents operate concurrently, which is a more advanced scenario. Build and validate the Core first.

AI agents have significantly higher reasoning latency than the HA state machine. A typical agent may take 500ms to 2000ms between reading state and issuing a service call. During that window, native automations may fire and change the same entities. The lease protocol acknowledges this reality without solving it.

To expose lease status to native automations, Level 3 host servers SHOULD expose a `binary_sensor.mesa_lease_active` entity. Native automation authors MAY add a condition checking this sensor to participate voluntarily in the coordination protocol, with the race condition caveat noted above.

### 21.2 Lease Request Schema

| Field | Type | Required | Description |
|---|---|---|---|
| `entities` | `array<string>` | REQUIRED | Entity IDs for which the lease is requested. |
| `duration_seconds` | `number` | REQUIRED | Requested duration. Maximum: 30. |
| `intent` | `string` | RECOMMENDED | Human-readable description. Surfaced in audit logs. |
| `priority_level` | `enum` | RECOMMENDED | `deferential`, `cooperative`, `assertive`. Default: `cooperative`. |
| `caller_priority` | `number` | RECOMMENDED | 0.0 to 1.0. Derived from caller role. See Section 21.6. |
| `preemption_handling` | `enum` | RECOMMENDED | `rollback_abort` or `continue_ignore`. What to do if preempted. Default: `rollback_abort`. |

### 21.3 Lease Response Schema

| Field | Always present | Description |
|---|---|---|
| `lease_id` | Yes | Unique lease identifier. |
| `granted` | Yes | Whether the lease was granted. |
| `entities_granted` | Yes | Entity IDs for which lease was granted. |
| `entities_denied` | Yes | Entity IDs denied. |
| `denial_reasons` | No | Map of entity ID to denial reason. |
| `expires_at` | Yes | ISO 8601 lease expiry timestamp. |
| `granted_duration_seconds` | Yes | Actual granted duration. |
| `active_conflicts` | No | Conflicting automations or agents. |

### 21.4 Lease Lifecycle

1. Agent calls `mesa_request_lease`.
2. Server responds immediately. Partial grants are valid.
3. During the active window, `deferential` automation conflict notifications are suppressed. `cooperative` automations receive advisory notification.
4. At `expires_at`, the lease automatically terminates.
5. Agent MAY call `mesa_release_lease` early to signal completion.

Leases are scoped to `session_id`. Session termination releases all associated leases automatically.

**`binary_sensor.mesa_lease_active` schema.** Level 3 host servers SHOULD expose a `binary_sensor.mesa_lease_active` entity to allow native automations to participate voluntarily in the coordination protocol.

| Field | Value | Description |
|---|---|---|
| **State** | `on` / `off` | `on` when one or more leases are active. `off` when no leases are held. |
| **`active_lease_count`** | `number` | Number of currently active leases. |
| **`leased_entities`** | `array<string>` | Entity IDs currently under any active lease. |
| **`earliest_expiry`** | `string` | ISO 8601 timestamp of the soonest lease expiry. `null` when no leases are active. |
| **`last_lease_holder`** | `string` | `caller_id` of the most recent lease holder. For audit context only. |

Native automation authors MAY use this sensor in conditions to defer action while an agent is operating. The race condition caveat from Section 21.1 applies: the check is not atomic with the automation trigger.

**Lease expiry events.** When a lease expires naturally (at `expires_at`), is released early via `mesa_release_lease`, or is terminated by session end, a Level 3 host server SHOULD fire a `mesa_lease_expired` event on the HA event bus with payload: `lease_id`, `entities`, `reason` (`natural_expiry`, `early_release`, `session_terminated`, or `preempted`), and `timestamp`. This allows native automations monitoring lease state to resume normal operation cleanly.

### 21.5 Automation Interaction

| Automation level | Behaviour during active agent lease |
|---|---|
| `deferential` | Conflict notifications suppressed. Automation proceeds normally. |
| `cooperative` | Automation notified via conflict channel. Agent informed via `active_conflicts`. |
| `assertive` | Lease granted with warning. Automation proceeds and may counteract agent. |
| `protected` | Lease denied for any entity this automation monitors while active. |
| `critical` | Lease denied unconditionally for entities in this automation's scope. |

### 21.6 Multi-Agent Collision Resolution

When two agents request overlapping leases concurrently, the server resolves by `caller_priority`.

**Default role-to-priority mapping:**

| Role | Default `caller_priority` |
|---|---|
| `admin` | 1.0 |
| `primary_resident` | 0.9 |
| `secondary_resident` | 0.7 |
| `caregiver` | 0.6 |
| `guest` | 0.4 |
| `child` | 0.3 |
| Unauthenticated | 0.1 |

**Resolution rules:**

1. Higher `caller_priority` MAY preempt existing lease. Server MUST notify existing holder before preemption.
2. Equal or lower priority: lease denied for conflicting entities. Denied agent informed (but not of other agent's identity).
3. No `caller_priority` supplied: existing holder takes precedence.
4. `protected` or `critical` automation leases always take precedence.

Upon receiving a preemption notification, the preempted agent MUST follow its declared `preemption_handling` behaviour: `rollback_abort` aborts and attempts rollback, `continue_ignore` accepts possible conflict.

---

*MESA - Metadata and Environment Semantics for Agents. Version 1.0. Enrichment specification. See also: MESA Overview, MESA Specification (Core), MESA Getting Started Guide, and mesa-core Module Proposal. Discussion and contributions are welcome via GitHub Issues.*
