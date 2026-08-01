# MESA Getting Started Guide
**Version:** 1.1
**Describes:** MESA 1.1
**Document Type:** Practical Implementation Guide

---

## About This Guide

The MESA Specification is a complete technical reference. This guide is not that. This guide is for people who want to add their first MESA profile today, without reading a specification first.

It assumes you know what Home Assistant is. It does not assume you are a developer. It does not assume you have read any other MESA document.

By the end of this guide you will have added a valid MESA profile to at least one entity, integration, or automation. That is the goal.

---

## Table of Contents

1. [Start Here: The Seven Fields](#1-start-here-the-seven-fields)
2. [JSON or YAML: Which One Do I Use?](#2-json-or-yaml-which-one-do-i-use)
3. [Pick Your Path](#3-pick-your-path)
   - 3.1 [I want to add MESA to my MCP server](#31-i-want-to-add-mesa-to-my-mcp-server)
   - 3.2 [I have a custom integration on HACS](#32-i-have-a-custom-integration-on-hacs)
   - 3.3 [I am an operator who wants better agent behaviour](#33-i-am-an-operator-who-wants-better-agent-behaviour)
   - 3.4 [I am building a production integration](#34-i-am-building-a-production-integration)
4. [Use AI to Write Your Profile](#4-use-ai-to-write-your-profile)
   - 4.1 [For integration developers](#41-for-integration-developers)
   - 4.2 [For operators](#42-for-operators)
   - 4.3 [For diagnostic profiles](#43-for-diagnostic-profiles)
   - 4.4 [Reviewing what the AI generates](#44-reviewing-what-the-ai-generates)
5. [Worked Examples](#5-worked-examples)
   - 5.1 [A simple RGB light integration](#51-a-simple-rgb-light-integration)
   - 5.2 [A critical mode flag helper](#52-a-critical-mode-flag-helper)
   - 5.3 [A custom diagnostic sensor](#53-a-custom-diagnostic-sensor)
   - 5.4 [A cloud TTS integration with dual connection modes](#54-a-cloud-tts-integration-with-dual-connection-modes)
   - 5.5 [An operator-added entity profile](#55-an-operator-added-entity-profile)
   - 5.6 [A device-scope profile for a camera](#56-a-device-scope-profile-for-a-camera)
6. [Choosing Semantic Tags](#6-choosing-semantic-tags)
7. [What Good Enough Looks Like](#7-what-good-enough-looks-like)
8. [Common Mistakes](#8-common-mistakes)
9. [Profile Validation](#9-profile-validation)
10. [What to Build Next: The Enrichment Path](#10-what-to-build-next-the-enrichment-path)
11. [Community Tooling Roadmap](#11-community-tooling-roadmap)
12. [Common Anti-Patterns](#12-common-anti-patterns)

---

## 1. Start Here: The Seven Fields

Every MESA profile starts with the same seven fields. Nothing beyond these seven is needed for a complete kernel profile. A profile missing any single field is still valid and useful, but including all seven gives agents the fullest context.

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

In YAML:

```yaml
semantic_profile:
  semantic_tags:
    - lighting.ambient
  operational_boundaries:
    control_mode: autonomous
    triggers_automations: none
    reversible: true
    reversibility_cost: none
    side_effect_scope: entity_only
privacy_classification:
  level: normal
```

**What each field means:**

**`semantic_tags`** - What is this for? Pick one tag from the list in Section 6. One is enough to start. This tells agents what category of thing they are dealing with.

**`control_mode`** - How should the agent treat writes on this entity? Four values:
- `autonomous` - the agent may act without asking the user. Use for lights, switches, media volume.
- `confirm` - the agent MUST ask the user before acting. If the agent is running non-interactively with no way to ask, `confirm` entities are off-limits: the agent treats them as `prohibited` and reports why. Use for locks, alarms, mode flags, anything where a mistake is disruptive.
- `read_only` - this entity cannot meaningfully be written to by its nature. Use for diagnostic sensors, read-only metrics, anything that exists purely to be read. Different from `prohibited`: `read_only` is about what the entity is, not operator policy.
- `prohibited` - the agent MUST NOT write to this entity under operator policy. Use for entities you have explicitly decided should never be agent-controlled.

When this field is absent, agents default to `confirm`. There is no silent autonomous default.

**Precedence rule:** You can always tighten. If a developer sets `prohibited` or `read_only`, you as an operator cannot change that, ever. You can change `autonomous` to `confirm` or `prohibited`, and `confirm` to `prohibited`. Loosening works in exactly one case: if a developer shipped `confirm` and you know autonomous control is safe in your deployment, set `control_mode: autonomous` at the entity level together with `override_control_mode: true` and a `control_reason` explaining why. The explicit flag protects against accidental loosening of safety constraints.

**Add `control_reason`** for any `confirm` or `prohibited` entity. A short string explaining why is invaluable for debugging and for agents communicating refusals: `"triggers alarm automation"`, `"medical device"`, `"physically dangerous if reversed"`.

**`triggers_automations`** - Whether changing this entity is likely to trigger automations. Three values cover most situations:
- `likely` - use this for mode flag helpers, coordination signals, and any entity you know drives automations. The agent will reason carefully about cascade effects before acting.
- `none` - a positive assertion that this entity triggers no automations. Use for diagnostic sensors, read-only metrics, and entities you have confirmed have no automation connections.
- `unknown` - use this when you genuinely cannot tell. Agents apply caution for helper domains when this is set.

A fourth value, `deployment_defined`, is for operators who know their specific deployment precisely. When you use `deployment_defined`, also add `affected_automations` in the helper traits section to list which automations are driven by this entity.

Note: a developer writing a profile for a HACS integration cannot know what automations an operator has built around their entities. Use `likely` when the integration is designed to drive downstream behaviour. Operators authoring entity-level profiles who know their deployment should use `deployment_defined`.

**`reversible`** - Can the action be undone? Turning a light off is reversible. Sending a push notification is not. Locking a door is reversible if the agent can also unlock it.

**`reversibility_cost`** (recommended, not required) - How costly is undoing this action? Helps agents distinguish between "safe to experiment with" and "reversible but disruptive." Choose one:
- `none` - reversal has no side effects. Lights, basic switches.
- `trivial` - reversal takes a few seconds or has negligible impact.
- `moderate` - reversal has minor side effects. Unlocking may wake a pet; re-arming an alarm takes 30 seconds.
- `high` - technically reversible but carries meaningful consequences. Use `reversibility_note` to explain.

**`reversibility_note`** (optional) - A short plain-text explanation of the reversal cost specific to your deployment. Examples: "unlocking wakes dog", "restoring scene requires pre-execution snapshot", "re-arming takes 30 seconds and resets motion history."

**`side_effect_scope`** - How far does the **direct hardware impact** spread? This is about physical consequences only, not automation cascades. Use `triggers_automations` to signal cascade risk separately.
- `entity_only` - only affects this entity directly
- `device_localized` - may affect other entities on the same physical device
- `room_localized` - may affect other entities in the same area via hardware coupling
- `zone_wide` - may affect entities across a logical zone via hardware coupling
- `deployment_wide` - may affect the entire home via hardware coupling

**`privacy_classification.level`** - Does this entity contain personal data? Four values:
- `public` - no personal data, no privacy expectations. Weather stations, utility meters, entrance area sensors.
- `normal` - standard residential device. Motion sensors, light states, temperature readings.
- `sensitive` - personal data present. Cameras, microphones, presence sensors, sleep trackers.
- `restricted` - highly personal or safety-critical. Medical devices, children's monitors, intimate spaces.

You can also add a `privacy_note` string to capture nuance that the level alone cannot express: for example `"sensitive at night when occupants are sleeping, normal during daytime."` This is optional and purely for human and agent context; it does not change enforcement behaviour.

That is the complete minimum. An agent reading this profile is immediately safer and smarter around your integration.

---

## 2. JSON or YAML: Which One Do I Use?

Use whatever format fits the file you are editing.

**Use JSON when:**
- Writing a `mesa_profile.json` sidecar file for an integration
- Working with MCP server API responses
- Storing profiles in entity registry attributes

**Use YAML when:**
- Adding profiles to Home Assistant automation YAML files
- Working in the HA configuration editor
- Adding profiles via a host MCP server running mesa-core's configuration interface

Both formats represent exactly the same data. You do not need to maintain both. If you are only working in one context, only write that format. The examples in this guide show both where helpful, but you never need to provide both.

---

## 3. Pick Your Path

### 3.1 I want to add MESA to my MCP server

**Time required: 30 minutes to a few hours depending on your server's framework.**

This is the highest-leverage path. When you integrate mesa-core into your MCP server, every one of your users gets MESA immediately without changing their configuration.

**Step 1: Install mesa-core.**

```bash
pip install 'mesa-core[fastmcp]'
```

The MCP framework is an optional dependency, so install the extra matching your server: `mesa-core[fastmcp]` for the FastMCP path shown below (the default adapter), or `mesa-core[mcp]` if you use the raw MCP Python SDK with `adapter="raw_sdk"`. Plain `pip install mesa-core` gives you the library without either framework, which is what you want when you are only storing and resolving profiles.

**Step 2: Register MESA tools into your server.**

```python
from mesa_core.mcp import register_mesa_tools
from mesa_core import ProfileStore
from mesa_core.backends import JsonFileBackend

# Initialise profile storage
store = ProfileStore(backend=JsonFileBackend("config/mesa/"))

# Register all MESA MCP tools into your server
# (exact API depends on your MCP framework - see mesa-core docs)
register_mesa_tools(server=your_mcp_server, store=store)
```

**Step 3: Wrap service calls with MESA enforcement.**

```python
from datetime import datetime

from mesa_core import MesaEnforcer
from mesa_core.exceptions import MesaEnforcementError

enforcer = MesaEnforcer(store)

# Before passing any service call to HA. Two details matter:
#  - `service` is the canonical "domain.service", e.g. "media_player.volume_set".
#  - `service_params` must be the REAL parameters of the call. A declared limit
#    whose parameter is missing from service_params is skipped, so passing
#    nothing here silently drops volume, brightness, and temperature caps.
#  - the validated entity_id goes LAST in the merge. Expanded the other way, a
#    caller-supplied entity_id would replace the target policy was chosen for,
#    so the approved confirmation challenge would name a different entity than
#    the call actually executes against. mesa-core denies that mismatch, but
#    the merge order is what stops you building it.
result = enforcer.evaluate(
    entity_id=entity_id,
    service=f"{domain}.{service}",
    service_params={**service_params, "entity_id": entity_id},
    caller_context=caller_ctx,
    current_time=datetime.now()
)
if not result.allowed:
    if result.confirmation_challenge is not None:
        # control_mode: confirm. This is not a refusal: return the challenge
        # to the agent, let it show the user what is about to happen, and
        # resubmit with the token from the approved challenge. Raising here
        # instead makes confirmation impossible, which turns every confirm
        # entity into a prohibited one.
        return {"requires_confirmation": result.confirmation_challenge}
    raise MesaEnforcementError(result.reason)
# proceed with service call
```

The resubmitted call is the same call plus the approved token:

```python
result = enforcer.evaluate(
    entity_id=entity_id,
    service=f"{domain}.{service}",
    service_params={**service_params, "entity_id": entity_id},
    caller_context=caller_ctx,
    current_time=datetime.now(),
    confirmation_token=approved_token,      # the dict from the approved challenge
)
```

The enforcer verifies the round-trip and that the parameters still match the
ones the user approved, so a token cannot be replayed against a different call
(Specification 6.6). See the Module Proposal for the full challenge and token
shapes.

**Step 4: Declare your conformance level.**

Level 1 (profile consumer) is about reading profiles and respecting what they say: parse them, surface `metadata_origin` to your decision logic, weight inferred profiles lower, treat a missing `control_mode` as `confirm`, and never expose an entity to a caller its `deny_for` names. None of that requires the MCP tools, so Level 1 needs Step 1 and the storage setup, not Step 2. Level 2 adds authoring and storing profiles, including stamping `metadata_origin` on everything you generate.

The steps above are the *foundation* of Level 3, not Level 3 itself. A conforming Level 3 server also authenticates every request, supplies the resolver callbacks for device, area, and integration inheritance, supplies caller context so `access_roles` can isolate anyone, supports the full filter set and pagination, and meets the Level 2 authoring requirements underneath. The Module Proposal's Full Integration example shows all of that wired together; the checklist itself is Specification Section 2. Start at Level 1 and add capabilities incrementally, and declare the level you actually meet rather than the one you are building toward.

**Step 5: Tell your users.**

Add a MESA badge or note to your README. Users who want to author profiles will need a way to add them through your configuration interface or through `customize.yaml` in their HA configuration.

See the mesa-core Module Proposal document for complete integration details, framework-specific adapters, and the full API reference.

---

### 3.2 I have a custom integration on HACS

**Time required: 5 to 30 minutes depending on complexity.**

Simple integrations (lights, basic switches) take five minutes. Integrations with custom states, cloud dependencies, or non-obvious side effects take longer and benefit from AI-assisted authoring. You only need to add one file: `mesa_profile.json`, in your integration's directory.

Create it with `semantic_profile` and `privacy_classification` as top-level keys:

```json
{
  "semantic_profile": {
    "schema_version": "1.1",
    "metadata_origin": {"source": "developer", "confidence": 1.0},
    "semantic_tags": ["diagnostic.causality"],
    "operational_boundaries": {
      "control_mode": "confirm",
      "reversible": false,
      "side_effect_scope": "entity_only"
    }
  },
  "privacy_classification": {
    "level": "normal"
  }
}
```

**Steps:**
1. Create `mesa_profile.json` in your integration's directory (the same folder as `manifest.json`).
2. Pick your semantic tags from Section 6.
3. Answer: can an agent write to entities in this integration without asking? Set `control_mode` accordingly.
4. Answer: if the agent makes a mistake, can it be undone? Set `reversible` accordingly.
5. Answer: does this integration capture personal data? Set `privacy_classification.level` accordingly.
6. Commit and push.

`metadata_origin` is optional in `mesa_profile.json`: an absent field defaults to `source: developer`. Declare it explicitly anyway if an AI assistant helped write the profile (`source: hybrid` with your `confirmed_fields`); the default assumes you authored it yourself.

**Why a separate file instead of `manifest.json`?** The hassfest validation action used in most custom integration CI pipelines rejects unknown `manifest.json` keys (`extra keys not allowed`), so embedding MESA keys there would fail your CI. A sidecar file ships with your integration exactly the same way; it is just another file in your integration directory, and nothing in the HA toolchain touches it.

If you are not sure what values to use, go to Section 4 and use an AI assistant to generate the profile for you. It takes about two minutes.

---

### 3.3 I am an operator who wants better agent behaviour

**Time required: 10 to 30 minutes depending on how many entities you profile.**

You do not need to touch any integration code. You add entity-level profiles through a host MCP server running mesa-core's configuration interface.

**How profile storage works today.** Home Assistant's native UI does not support adding MESA profiles to entities, helpers, or automations directly. When you edit an automation through the HA UI editor and save it, HA rewrites the YAML and removes any keys it does not recognise. This means MESA profiles cannot be reliably stored in automation YAML if you use the UI editor.

The recommended path for operators is to manage all MESA profiles through your host MCP server's configuration interface.

**If you are running a background or non-interactive agent** (scheduled jobs, automated pipelines with no user-facing confirmation path), configure `deployment_defaults` before running the agent. Without it, the agent will hit `confirm` on everything outside the built-in baseline and stall. A five-minute `deployment_defaults` configuration eliminates this problem for the vast majority of entities. For safety-critical domains like locks and alarms, the `prohibited` baseline protects you automatically. The server stores profiles keyed by entity ID and automation ID, and applies them at query time without touching HA's native configuration files. Some host servers provide a profile editing UI; check yours.

**Understand the built-in baseline first.** Before configuring anything, mesa-core already applies a built-in domain safety baseline for unprofiled entities. You do not start from "everything blocked." The baseline gives lights `autonomous` control, locks and alarms `prohibited`, and everything else (including media players) `confirm`. This means a background agent on a fresh deployment can already control lights without any configuration.

**Built-in baseline (applied automatically when no profile exists):**

| Domain | Default | Notes |
|---|---|---|
| `light` | `autonomous` | Safe for immediate agent control |
| `lock` | `prohibited` | Never autonomous without explicit declaration |
| `alarm_control_panel` | `prohibited` | Never autonomous without explicit declaration |
| `input_boolean` | `confirm` | High cascade risk |
| All others | `confirm` | Conservative fallback |

**Then configure deployment defaults to go further.** Add a `deployment_defaults` configuration to your host MCP server to override the baseline with your specific knowledge.

```json
{
  "deployment_defaults": {
    "default_control_mode": "confirm",
    "triggers_automations_domains": ["input_boolean", "input_select", "input_number", "counter", "timer"],
    "domain_overrides": {
      "light": {"control_mode": "autonomous"},
      "media_player": {"control_mode": "autonomous"},
      "lock": {"control_mode": "prohibited"},
      "alarm_control_panel": {"control_mode": "prohibited"},
      "cover": {"control_mode": "confirm"}
    }
  }
}
```

This supplements the built-in baseline with your deployment-specific decisions. Then add per-entity profiles only where you need finer control.

**Then profile your highest-impact entities.** These are the ones where agent mistakes would be most disruptive or where you have already seen unexpected behaviour.

**Priority order:**
1. Mode flag helpers (`input_boolean.cinema_mode`, `input_boolean.guest_mode`, `input_boolean.vacation_mode`). These control dozens of automations. An agent that toggles one carelessly may cause broad disruption.
2. Security entities (`lock.front_door`, `alarm_control_panel.home`). Always `control_mode: confirm` or `prohibited`.
3. Multi-entity physical devices, especially cameras, microphones, and presence sensors. Profile the device once instead of its fourteen entities: a single device-scope profile covers every entity the device owns, including entities a future firmware update adds. See the device profile section below.
4. Climate entities where you have specific constraints (min/max temperatures, schedule restrictions).
5. Media players where you have volume limits at night or during certain modes.

**Adding profiles through your MCP server.** Open your host MCP server's configuration interface and add profiles by entity ID. The examples below show the YAML you would enter there.

**Example: profiling your front door lock**

```yaml
semantic_profile:
  schema_version: "1.1"
  metadata_origin:
    source: user
    confidence: 1.0
  semantic_tags:
    - security.access_control
  operational_boundaries:
    control_mode: confirm
    triggers_automations: none
    reversible: true
    reversibility_cost: trivial
    reversibility_note: "unlocking from locked state is immediate but may disturb sleeping occupants"
    side_effect_scope: room_localized
    enforcement_mode: enforced
privacy_classification:
  level: normal
```

Note `enforcement_mode: enforced`. This tells a conforming MCP server to actively reject any agent call that tries to lock or unlock the door without confirmation. This is stronger than advisory.

**Example: profiling a mode flag helper**

For `input_boolean.cinema_mode`:

```yaml
semantic_profile:
  schema_version: "1.1"
  metadata_origin:
    source: user
    confidence: 1.0
  semantic_tags:
    - helper.mode_flag
    - helper.high_impact
  helper_traits:
    role: mode_flag
    true_meaning: >
      Cinema mode is active. Living room lighting automations are suppressed.
      Volume limits are reduced to 40% on all speakers. Scene activations
      affecting the living room are blocked.
    false_meaning: Normal operation. All automations proceed without restriction.
    affected_automations:
      - automation.occupancy_lights_off
      - automation.evening_ambient_lights
    default_state: false
  operational_boundaries:
    control_mode: confirm
    triggers_automations: likely
    reversible: true
    side_effect_scope: zone_wide
privacy_classification:
  level: normal
```

This tells the agent exactly what happens when this helper changes. The `true_meaning` and `false_meaning` fields are the most valuable part of a mode flag profile.

**Profiling a whole physical device (MESA 1.1).** One physical device usually exposes several entities: a camera device might expose `camera.nursery`, `binary_sensor.nursery_motion`, and `sensor.nursery_sound_level`. When your intent is about the physical object ("everything this camera produces is sensitive", "hands off this relay"), write one device-scope profile instead of repeating it per entity. The profile is keyed by the HA device registry ID, which you can find under Settings, then Devices and Services, then the device page (the ID is in the page URL). It applies to every entity the device owns, ranks above area and below entity in inheritance, and automatically covers entities the device grows later, which per-entity profiles never do.

```yaml
semantic_profile:
  schema_version: "1.1"
  inheritance_scope: device
  metadata_origin:
    source: user
    confidence: 1.0
  semantic_tags:
    - security.camera
privacy_classification:
  level: restricted
  contains_visual_capture: true
  contains_audio_capture: true
```

Two things to know. First, your host server needs the entity-to-device mapping from the HA registries for device profiles to resolve; every maintained host provides it, but on one that does not, device profiles are simply inert (they never fail open). Second, device profiles can tighten but never loosen: `override_control_mode` works only on entity-level profiles.

---

### 3.4 I am building a production integration

Add the kernel first, then enrich incrementally.

**Phase 1 (ship with initial release):** Kernel profile in `mesa_profile.json`. Diagnostic profile covering your main state values and error classes.

**Phase 2 (first update):** Event semantics if you fire custom events. Attribute semantics for non-standard entity attributes.

**Phase 3 (ongoing):** Temporal constraints for time-sensitive entities. Vendor namespace tags for integration-specific capabilities.

**Diagnostic profiles deserve special attention.** If your integration exposes non-standard states or custom error classes, a diagnostic profile transforms opaque runtime behaviour into actionable agent context. It is often the highest-value thing you can add after the kernel. See the worked example in Section 5.4.

**Vendor namespace tags.** If your integration has capabilities that no canonical MESA tag describes, use a vendor namespace: `myintegration.custom_capability`. Publish a registry alongside your documentation listing what each vendor tag means. This allows MESA-aware agents and MCP servers to reason about your specific capabilities.

---

## 4. Use AI to Write Your Profile

AI assistants are well-suited to generating first-draft MESA profiles. They know the MESA schema, they know Home Assistant domain conventions, and they can generate plausible values in seconds. The result is never perfect but it is always a better starting point than a blank page.

### 4.1 For integration developers

Copy this prompt, fill in the brackets, and paste it into an AI assistant:

```
I am building a Home Assistant custom integration and need a MESA semantic profile.

Integration description: [describe what your integration does, what HA domain it uses,
whether it requires cloud connectivity, what makes it different from standard domain
implementations, and any custom states or error conditions it exposes]

Please generate:
1. A complete MESA kernel profile (semantic_profile + privacy_classification)
   with metadata_origin source set to "developer".
2. If the integration has custom states or error conditions, also generate a
   diagnostic_profile with state_mapping and error_classes entries.
3. Use canonical MESA tags where they fit. Use vendor namespace tags
   (prefixed with [integrationname].) for anything integration-specific.
4. Format as JSON for a mesa_profile.json sidecar file.
5. Always set metadata_origin.source to "inferred_ai" in your output.
   Never set it to "developer" or "user" - that is the human's decision after review.
6. After the profile, briefly explain your choices for control_mode,
   triggers_automations, reversible, and privacy_classification.level.
   Flag any field where you are uncertain.
```

### 4.2 For operators

```
I want to add a MESA semantic profile to a Home Assistant entity.
Please generate the profile.

Entity details:
- Entity ID: [entity_id]
- Domain: [light / lock / input_boolean / etc.]
- If my intent is really about the physical device that owns this entity
  (a camera, a multi-sensor, a power strip), suggest a device-scope profile
  instead and tell me it needs the HA device registry ID.
- What this entity does: [describe its purpose in your home]
- What automations use it or respond to it: [list them if you know]
- Should an AI agent be able to control this automatically? [yes / no / ask first]
- If the agent makes a mistake with this entity, can it be undone? [yes / no]

Please generate a semantic_profile and privacy_classification in YAML format,
suitable for adding to a host MCP server running mesa-core configuration.
Always set metadata_origin.source to "inferred_ai" - I will change it after review.
After the profile, flag any fields I should double-check, especially control_mode
and triggers_automations.
```

### 4.3 For diagnostic profiles

```
I need a MESA diagnostic_profile for a custom Home Assistant integration.

Integration details:
- Domain: [tts / sensor / binary_sensor / etc.]
- Custom state values it exposes: [list each state and what it means]
- Main failure modes: [describe what can go wrong and why]
- Recovery actions: [what should happen when each failure occurs - retry,
  reload integration, reconfigure credentials, etc.]

Please generate a diagnostic_profile with:
1. state_mapping for each custom state.
2. error_classes for each failure mode. Use HA core exception class names
   where applicable (ConfigEntryAuthFailed, HomeAssistantError, etc.)
   and include ha_base_exception references.
3. Format as JSON.
```

### 4.4 Reviewing what the AI generates

AI-generated profiles are starting points. Always review before using. Check these fields yourself because the AI cannot know your specific situation:

**Always verify manually:**
- `control_mode` - AI assistants tend to set this too permissive (autonomous) to be helpful. Especially on security entities, always set this yourself after review.
- `triggers_automations` - The AI cannot know which automations in your specific deployment are triggered by an entity. Mode flag helpers should be `likely`. If you know your deployment precisely, use `deployment_defined` and add `affected_automations` to the helper traits section. Never accept `none` for a mode flag without verifying.
- `privacy_classification.level` - The AI may under-classify presence sensors or over-classify simple switches.
- `reversible` - The AI often marks things as reversible when they are not (notifications, one-shot triggers, webhook calls, counter resets).
- `reversibility_cost` - The AI frequently sets this to `none` when it should be `moderate` or `high`. Review for any entity where reversal has real consequences.
- `side_effect_scope` - Describes hardware footprint only. Use `triggers_automations` to signal cascade risk separately.
- `affected_automations` in helper profiles - The AI will not know which automations in your deployment are affected.

**The rule you must not skip:** Never ship `control_mode: autonomous` on a security domain entity without personally verifying it. If an AI generated it, change it to `confirm` first and loosen it only if you are certain.

**Usually safe to trust:**
- `semantic_tags` - The AI is generally good at matching to canonical tags.
- `network_dependency` - Usually deterministic from the description.
- State mapping `semantic_meaning` fields - Usually accurate if your description was clear.
- `ha_base_exception` mappings - The AI knows the HA exception hierarchy.

**Mark it correctly. This is not optional.**

`source: developer` means you wrote the profile yourself from your own knowledge. `source: hybrid` means the profile was partially AI-generated and partially human-confirmed. These are different trust levels and agents treat them differently. Publishing an AI-generated profile as `source: developer` is trust laundering - it misrepresents provenance and undermines the reliability of the metadata ecosystem.

**The rule:** AI generated any part of the content -> `source: hybrid` at best. You wrote it entirely yourself -> `source: developer` or `source: user`.

If AI-generated and you have reviewed and confirmed the key fields:

```yaml
metadata_origin:
  source: hybrid
  confidence: 1.0
  confirmed_fields:
    - operational_boundaries.control_mode
    - operational_boundaries.triggers_automations
    - privacy_classification.level
    - operational_boundaries.reversible
```

Never ship an AI-generated profile with `control_mode: autonomous` on a security domain entity (`lock`, `alarm_control_panel`, `camera`) without explicit personal verification.

If you have not reviewed it yet:

```yaml
metadata_origin:
  source: inferred_ai
  confidence: 0.75
  generated_at: "2026-05-27T10:00:00+07:00"
```

---

## 5. Worked Examples

### 5.0 Three Archetype Profiles

These three profiles cover the most common footguns in smart home AI orchestration. Copy them, adjust the values for your specific entity, and you have covered 90% of the cases where agents cause unintended behaviour.

**Archetype 1: A light (safe for autonomous control)**

```json
{
  "semantic_profile": {
    "schema_version": "1.1",
    "metadata_origin": {"source": "user", "confidence": 1.0},
    "semantic_tags": ["lighting.ambient"],
    "operational_boundaries": {
      "control_mode": "autonomous",
      "control_reason": "Low-risk, easily reversible. Agent may dim or turn off freely.",
      "triggers_automations": "none",
      "reversible": true,
      "reversibility_cost": "none",
      "side_effect_scope": "entity_only"
    }
  },
  "privacy_classification": {"level": "normal"}
}
```

**Archetype 2: A lock (always confirm, never autonomous)**

```json
{
  "semantic_profile": {
    "schema_version": "1.1",
    "metadata_origin": {"source": "user", "confidence": 1.0},
    "semantic_tags": ["security.access_control"],
    "operational_boundaries": {
      "control_mode": "confirm",
      "control_reason": "Physical security. Unlocking at wrong time may trigger alarm automation.",
      "triggers_automations": "likely",
      "reversible": true,
      "reversibility_cost": "moderate",
      "reversibility_note": "Re-locking is immediate but may wake occupants if done at night.",
      "side_effect_scope": "room_localized",
      "enforcement_mode": "enforced"
    }
  },
  "privacy_classification": {"level": "normal"}
}
```

**Archetype 3: A mode flag helper (high impact, must confirm)**

```yaml
semantic_profile:
  schema_version: "1.1"
  metadata_origin:
    source: user
    confidence: 1.0
  semantic_tags:
    - helper.mode_flag
    - helper.high_impact
  helper_traits:
    role: mode_flag
    true_meaning: >
      Guest mode active. Privacy restrictions elevated on all presence
      and camera entities. Standard automations replaced with
      guest-friendly alternatives.
    false_meaning: Normal operation. Standard privacy levels apply.
    affected_automations:
      - automation.morning_routine
      - automation.occupancy_lights_off
    default_state: false
  operational_boundaries:
    control_mode: confirm
    control_reason: "Affects privacy classification of all presence entities and disables standard automations."
    triggers_automations: likely
    reversible: true
    reversibility_cost: trivial
    side_effect_scope: deployment_wide
    enforcement_mode: enforced
privacy_classification:
  level: normal
```

These three archetypes plus the `deployment_defaults` configuration in Section 3.3 cover the most common agent footguns without requiring per-entity profiling of every entity in your deployment.

---

### 5.1 A simple RGB light integration

A custom integration for a specific smart bulb brand. Supports RGB colour and smooth dimming. Local only, no cloud.

```json
{
  "semantic_profile": {
    "schema_version": "1.1",
    "metadata_origin": {"source": "developer", "confidence": 1.0},
    "semantic_tags": ["lighting.colour", "lighting.dimming", "lighting.ambient"],
    "operational_boundaries": {
      "control_mode": "autonomous",
      "triggers_automations": "none",
      "reversible": true,
      "reversibility_cost": "none",
      "side_effect_scope": "entity_only",
      "state_volatility": "low"
    },
    "capability_semantics": {
      "network_dependency": "local_only",
      "expected_latency_ms": 50
    }
  },
  "privacy_classification": {"level": "normal"}
}
```

This is the kernel plus two optional enrichment fields. Total authoring time: three minutes.

---

### 5.2 A critical mode flag helper

`input_boolean.guest_mode` - when on, privacy restrictions elevate across the deployment, guest-friendly automations replace standard routines, and the presence mode selector locks to "guest".

```yaml
semantic_profile:
  schema_version: "1.1"
  metadata_origin:
    source: user
    confidence: 1.0
  semantic_tags:
    - helper.mode_flag
    - helper.high_impact
  last_updated: "2026-05-27T10:00:00+07:00"
  helper_traits:
    role: mode_flag
    true_meaning: >
      Guest mode is active. Privacy restrictions on all presence and camera
      entities are elevated to restricted level. Guest-friendly lighting and
      climate automations replace standard routines. The presence mode
      selector is locked to "guest" and cannot be changed autonomously.
    false_meaning: >
      Normal operation. Standard privacy levels and automation routines apply.
    affected_automations:
      - automation.morning_routine
      - automation.occupancy_lights_off
      - automation.climate_schedule
      - automation.security_arm_disarm
    default_state: false
  operational_boundaries:
    control_mode: confirm
    triggers_automations: likely
    reversible: true
    side_effect_scope: deployment_wide
    enforcement_mode: enforced
privacy_classification:
  level: normal
```

The `true_meaning` and `false_meaning` fields are the most valuable part. They tell the agent exactly what it is controlling.

---

### 5.3 A custom diagnostic sensor

A sensor that tracks which entity or person last triggered a motion-sensitive light. Exposes states: `monitoring`, `device`, `ui`, `automation`, `script`, `scene`, `service`.

```json
{
  "semantic_profile": {
    "schema_version": "1.1",
    "metadata_origin": {"source": "developer", "confidence": 1.0},
    "semantic_tags": [
      "diagnostic.causality",
      "diagnostic.confidence_scored",
      "diagnostic.read_only"
    ],
    "operational_boundaries": {
      "control_mode": "read_only",
      "control_reason": "Diagnostic sensor. Inherently read-only by nature.",
      "triggers_automations": "none",
      "reversible": false,
      "reversibility_cost": "none",
      "side_effect_scope": "entity_only",
      "state_volatility": "high"
    }
  },
  "diagnostic_profile": {
    "state_mapping": [
      {
        "state_value": "monitoring",
        "semantic_meaning": "Actively monitoring. No trigger recorded since initialisation.",
        "severity": "info",
        "is_normal_operation": true,
        "agent_action_recommended": "none"
      },
      {
        "state_value": "device",
        "semantic_meaning": "Last trigger attributed to direct physical device interaction.",
        "severity": "info",
        "is_normal_operation": true,
        "agent_action_recommended": "none"
      },
      {
        "state_value": "ui",
        "semantic_meaning": "Last trigger attributed to HA frontend or companion app action.",
        "severity": "info",
        "is_normal_operation": true,
        "agent_action_recommended": "none"
      },
      {
        "state_value": "automation",
        "semantic_meaning": "Last trigger attributed to a HA automation.",
        "severity": "info",
        "is_normal_operation": true,
        "agent_action_recommended": "none"
      },
      {
        "state_value": "script",
        "semantic_meaning": "Last trigger attributed to a HA script execution.",
        "severity": "info",
        "is_normal_operation": true,
        "agent_action_recommended": "none"
      },
      {
        "state_value": "scene",
        "semantic_meaning": "Last trigger attributed to a scene activation.",
        "severity": "info",
        "is_normal_operation": true,
        "agent_action_recommended": "none"
      },
      {
        "state_value": "service",
        "semantic_meaning": "Last trigger attributed to a direct service call, including from AI agents.",
        "severity": "info",
        "is_normal_operation": true,
        "agent_action_recommended": "none"
      },
      {
        "state_value": "unavailable",
        "semantic_meaning": "Integration has lost its event bus subscription. Cannot attribute triggers.",
        "severity": "high",
        "is_normal_operation": false,
        "agent_action_recommended": "recover",
        "error_classes": ["EventBusSubscriptionLost"]
      }
    ],
    "error_classes": [
      {
        "class": "EventBusSubscriptionLost",
        "ha_base_exception": "HomeAssistantError",
        "severity": "high",
        "recoverable": true,
        "reason": "Event bus listener dropped subscription, typically after HA restart or integration reload.",
        "user_actionable_remedy": "Reload the integration via Settings -> Integrations.",
        "agent_recovery_service": "homeassistant.reload_config_entry",
        "retry_after_seconds": 30
      }
    ],
    "attribute_semantics": [
      {
        "attribute_name": "confidence",
        "semantic_meaning": "Attribution confidence 0.0 to 1.0. Values below 0.5 indicate uncertain attribution.",
        "value_type": "number",
        "machine_actionable": true,
        "value_range": {"min": 0.0, "max": 1.0}
      },
      {
        "attribute_name": "history_log",
        "semantic_meaning": "Ordered array of recent trigger events with timestamp, source, and confidence.",
        "value_type": "array",
        "machine_actionable": true,
        "preferred_interface": "attribute_poll"
      }
    ]
  },
  "privacy_classification": {"level": "normal"}
}
```

---

### 5.4 A cloud TTS integration with dual connection modes

A hypothetical custom TTS integration offering proxy mode (community-run endpoint, no credentials needed) and direct API mode (requires session credentials that expire periodically). Also supports automatic text chunking and expressive voice styles.

Note how vendor namespace tags handle the implementation-specific details while canonical tags cover broadly applicable capabilities.

```json
{
  "semantic_profile": {
    "schema_version": "1.1",
    "metadata_origin": {"source": "developer", "confidence": 1.0},
    "semantic_tags": [
      "tts.multilingual",
      "tts.expressive_voices",
      "tts.auto_chunking",
      "customtts.connectionmode.proxy",
      "customtts.connectionmode.direct",
      "customtts.auth.session_based"
    ],
    "category_traits": {
      "functional_domain": "tts",
      "specialization": ["tts.multilingual", "tts.expressive_voices", "tts.auto_chunking"]
    },
    "operational_boundaries": {
      "control_mode": "autonomous",
      "triggers_automations": "none",
      "reversible": false,
      "reversibility_cost": "none"
    },
    "capability_semantics": {
      "network_dependency": "cloud_required"
    }
  },
  "diagnostic_profile": {
    "state_mapping": [
      {
        "state_value": "unavailable",
        "semantic_meaning": "Cannot reach configured endpoint. May be proxy outage, expired session credential, or network failure. Consult error_classes for specific recovery guidance.",
        "severity": "high",
        "is_normal_operation": false,
        "agent_action_recommended": "recover",
        "error_classes": ["ProxyEndpointUnreachable", "SessionCredentialExpired", "NetworkConnectivityFailure"]
      }
    ],
    "error_classes": [
      {
        "class": "ProxyEndpointUnreachable",
        "ha_base_exception": "HomeAssistantError",
        "severity": "medium",
        "recoverable": true,
        "reason": "Community proxy endpoint unavailable. Volunteer-run service with intermittent outages.",
        "user_actionable_remedy": "Wait and retry, or switch to direct API mode in integration configuration.",
        "retry_after_seconds": 120
      },
      {
        "class": "SessionCredentialExpired",
        "ha_base_exception": "ConfigEntryAuthFailed",
        "severity": "high",
        "recoverable": false,
        "reason": "Session credential for direct API mode has expired. Must be renewed manually.",
        "user_actionable_remedy": "Reconfigure the integration via Settings -> Devices and Services with a fresh session credential."
      },
      {
        "class": "NetworkConnectivityFailure",
        "ha_base_exception": "HomeAssistantError",
        "severity": "high",
        "recoverable": true,
        "reason": "General network failure prevented reaching any configured endpoint.",
        "user_actionable_remedy": "Check network connectivity. Direct mode will attempt regional fallback automatically.",
        "retry_after_seconds": 60
      }
    ],
    "attribute_semantics": [
      {
        "attribute_name": "connection_mode",
        "semantic_meaning": "Active connection mode. 'proxy' uses community endpoint without credentials. 'direct' calls upstream API with session credential that may expire over time.",
        "value_type": "enum",
        "machine_actionable": true,
        "value_vocabulary": ["proxy", "direct"]
      },
      {
        "attribute_name": "available_voices",
        "semantic_meaning": "Voice IDs available for configured language. Includes standard, expressive, and character subclasses. Expressive and character voices may not suit all announcement contexts.",
        "value_type": "array",
        "machine_actionable": true,
        "preferred_interface": "attribute_poll"
      }
    ]
  },
  "privacy_classification": {"level": "normal"}
}
```

---

### 5.5 An operator-added entity profile

An operator adding a MESA profile to `lock.front_door` through a host MCP server running mesa-core's configuration interface, without touching any integration code.

```yaml
semantic_profile:
  schema_version: "1.1"
  metadata_origin:
    source: user
    confidence: 1.0
  semantic_tags:
    - security.access_control
  last_updated: "2026-05-27T10:00:00+07:00"
  operational_boundaries:
    control_mode: confirm
    triggers_automations: none
    reversible: true
    side_effect_scope: room_localized
    state_volatility: low
    enforcement_mode: enforced
    declared_limits:
      - id: no_lock_door_open
        predicate:
          entity: binary_sensor.front_door_contact
          operator: eq
          value: "on"
        limit:
          service: lock.lock
          parameter: entity_id
          permitted_values: []
        human_reason: >
          Do not lock when the door contact sensor shows the door is open.
          This would damage the lock mechanism.
    temporal_constraints:
      - id: no_lock_changes_at_night
        condition:
          type: time_range
          start_time: "23:00"
          end_time: "06:00"
        effect:
          control_mode: prohibited
        human_reason: >
          Lock state must not change via agent during sleeping hours at all,
          even with confirmation. Tightens the base confirm to prohibited.
privacy_classification:
  level: normal
```

This profile does not require any changes to the lock integration. It is applied at the entity level through the MCP server configuration. The declared limit prevents locking an open door. The temporal constraint adds an additional nighttime restriction.

---

### 5.6 A device-scope profile for a camera

The same operator restricts a nursery camera. The physical device exposes three entities (`camera.nursery`, `binary_sensor.nursery_motion`, `sensor.nursery_sound_level`), and the intent is about the hardware, so one device-scope profile replaces three entity profiles. The key is the HA device registry ID.

```yaml
semantic_profile:
  schema_version: "1.1"
  inheritance_scope: device
  metadata_origin:
    source: user
    confidence: 1.0
  semantic_tags:
    - security.camera
    - presence.occupancy
  last_updated: "2026-08-01T10:00:00+07:00"
  operational_boundaries:
    control_mode: confirm
    side_effect_scope: device_localized
privacy_classification:
  level: restricted
  contains_visual_capture: true
  contains_audio_capture: true
  deny_response_mode: omit
```

Every entity the camera owns now resolves `restricted` privacy and `confirm` control, including any entity a future firmware update adds. Asking the server to explain any of them (`mesa_explain_profile`) shows `provided_by_level: device` for these fields. The nursery thermostat, in the same area but a different device, is unaffected.

If one entity of the device needs different treatment, an entity-level profile on it is more specific and wins wherever the resolution rules allow one value to replace another. That is not everywhere: privacy is most-restrictive-wins, so an entity profile declaring `normal` does not undo the device's `restricted`, and an inherited `confirm` can only be loosened through the entity-scope operator override (`override_control_mode: true` with a `control_reason`). Specificity decides which value is chosen; the safety rules decide whether a looser value is allowed at all.

---

## 6. Choosing Semantic Tags

Use this quick reference to pick tags for your profile. For the full vocabulary, see the Specification Appendix A.

**Lighting:** `lighting.ambient` (general room light), `lighting.task` (desk or work light), `lighting.colour` (RGB support), `lighting.dimming` (brightness control), `lighting.security` (entry/deterrence)

**Climate:** `climate.heating`, `climate.cooling`, `climate.energy_optimization`, `climate.air_quality`

**Media:** `media.multiroom`, `media.lossless`, `media.local_only`, `media.casting`

**Security:** `security.access_control` (locks, gates), `security.camera`, `security.alarm`, `security.entry_monitoring`, `security.motion_detection`

**Presence:** `presence.occupancy`, `presence.person_identification`, `presence.sleep_tracking`

**Energy:** `energy.monitoring`, `energy.high_consumption`, `energy.solar`, `energy.grid_aware`

**Diagnostics:** `diagnostic.causality` (tracks who changed what), `diagnostic.read_only` (do not write to this), `diagnostic.history_log`, `diagnostic.confidence_scored`

**Helpers:** `helper.mode_flag` (controls broad behaviour), `helper.config_parameter` (tunes one thing), `helper.high_impact` (add alongside `mode_flag` for things that affect many automations)

**TTS:** `tts.multilingual`, `tts.expressive_voices`, `tts.auto_chunking`

**Audio:** `audio.high_fidelity`, `audio.multiroom`, `audio.voice_optimised`

**If nothing fits:** Use a vendor namespace tag: `myintegration.my_capability`. Publish what it means in your documentation.

---

## 7. What Good Enough Looks Like

The most common question: how complete does my profile need to be?

The honest answer: whatever you can maintain accurately is better than what you cannot.

A profile with six correct fields is worth more than a profile with forty fields where several are wrong. Incorrect semantics are actively harmful. An agent that trusts wrong metadata may behave worse than one with no metadata at all.

**The practical hierarchy:**

| What you add | What it prevents |
|---|---|
| Kernel with `control_mode: confirm/prohibited`, `triggers_automations: likely`, and `reversibility_cost` | Agent touching things it should not, ignoring cascade effects, and treating all reversible actions as equally safe. |
| + Diagnostic profile | Agent confusion when things fail. |
| + Temporal constraints | Agent doing the wrong thing at the wrong time. |
| + Mode flag helper profiles | Agent causing cascading effects it does not understand. |
| + Cooperative priority on automations | Race conditions between agent and automations. |
| + Spatial leakage | Spatially naive decisions affecting adjacent spaces. |

Start at the top. Add downward when you observe agent behaviour that could be better.

**One honest warning.** If you find yourself setting `control_mode: autonomous` on everything just to make the agent less annoying, stop. The agent asking for confirmation is annoying. An agent that locks the wrong door or triggers the wrong automation is worse. The correct fix is to configure the agent's confirmation threshold, not the profile.

---

## 8. Common Mistakes

**Setting `control_mode: autonomous` everywhere to avoid confirmation dialogs.**
This defeats the safety purpose. Mark entities correctly. If the agent asking for confirmation is annoying, configure the agent's confirmation threshold, not the profile.

**Marking irreversible actions as `reversible: true`.**
Sending notifications, firing webhooks, resetting counters, making one-shot API calls: none of these are reversible. Mark them `false`.

**Using subjective tags that are not in the vocabulary.**
Tags like `lighting.cozy` or `security.important` are not canonical and will not be interpreted consistently. Use canonical tags. Use vendor namespaces for specifics. Use `human_reason` prose fields for subjective descriptions.

**Writing profiles that describe what you wish were true.**
If your integration requires cloud connectivity, `network_dependency` must be `cloud_required`. Fix the integration rather than misrepresenting it.

**Omitting `metadata_origin` when it matters.**
A profile shipped in an integration's `mesa_profile.json` defaults to `source: developer` when the field is absent, which is only correct if you wrote the profile yourself. If an AI assistant generated any part of it, the default misrepresents provenance: declare `source: hybrid` or `source: inferred_ai` explicitly. Profiles stored anywhere else are treated as `unknown` without `metadata_origin` and trusted no more than an unreviewed AI guess. Include it.

**Using long-form predicate operators.**
Use `eq`, not `equals`. Use `gt`, not `greater_than`. Unrecognised tokens must be rejected by conforming implementations.

**Leaving mode flag helpers unprofiled.**
These are the highest-impact entities in most deployments. If you profile nothing else, profile your mode flags.

---

## 9. Profile Validation

Two validators exist. `mesa-lint` (`pip install mesa-lint`) checks profiles and profile stores from the command line or CI: `mesa-lint path/to/mesa_profile.json`, or `--strict` to fail on warnings. It builds on `mesa_core.validate_document`, so it reports every malformed-document error the library reports, and adds opinionated warnings of its own (a `confirm` entity with no `control_reason`, a helper declaring `triggers_automations: none`, and the like), which the library does not. Programmatically, `mesa_core.validate_document(doc)` returns the library's errors as a report, and `SemanticProfile.from_dict` raises `MesaValidationError` on a malformed document.

Both catch what a schema can catch. For the judgement a schema cannot make, whether a declaration is actually true of your home, the AI prompt below is still the fastest review:

```
Please review this MESA semantic profile for issues.

[paste your profile here]

Check for:
1. Missing required fields for the declared metadata_origin.source.
2. Non-canonical predicate operators (correct: eq, neq, gt, gte, lt, lte, in, contains).
3. Semantic tags that are not in canonical MESA vocabulary and not in vendor namespace format (vendorname.qualifier).
4. control_mode: autonomous on entities that are likely high-risk (locks, alarms, cameras).
5. reversible: true on actions that are likely irreversible (notifications, webhooks, one-shot events).
6. privacy_classification.level too low for the semantic tags declared.
7. mode_flag helpers without affected_automations declared.

Report any issues and suggest corrections.
```

**What a future linter should check:**
- All required fields present for declared `metadata_origin.source`.
- `confidence` and `generated_at` present for `inferred_ai` profiles.
- All predicate operators canonical or HA native syntax.
- All `semantic_tags` either canonical or properly namespaced.
- `control_mode: autonomous` combined with `side_effect_scope: deployment_wide` flagged as high-risk.
- `reversible: true` on notification or webhook entities flagged as potentially incorrect.
- `privacy_classification.level: normal` on presence or camera entities flagged for review.

---

## 10. What to Build Next: The Enrichment Path

Once the kernel is in place, here is a sensible order for adding enrichment based on return on investment.

**Highest return:**

1. **Diagnostic profile** for any integration with non-standard states or error conditions. Transforms `unavailable` from a mystery into an actionable signal.

2. **Mode flag helper profiles** with `true_meaning`, `false_meaning`, and `affected_automations`. Prevents the single most common class of agent-caused cascading disruption.

3. **Temporal constraints** for entities where appropriate behaviour changes by time. Night volume limits, work-from-home restrictions, outdoor light activation windows.

**Medium return:**

4. **Automation cooperative priority** for your most important automations. Tells agents which automations take precedence and which they can work alongside.

5. **Spatial profiles** for areas with acoustic or thermal leakage. Particularly useful for open-plan layouts and adjacent sleeping spaces.

6. **Event semantics** for integrations that use the HA event bus. Allows agents to subscribe to events rather than polling state.

**Lower return but valuable for complete deployments:**

7. Resource profiles for high-power or cloud-dependent integrations.

8. Person and zone profiles for deployments where agents reason about presence and location.

9. Assist pipeline and satellite profiles for voice-integrated deployments.

---

## 11. Community Tooling Roadmap

Some of these have shipped and are marked as such; the rest are what the community needs to build for MESA to achieve broad adoption. If you are a developer looking for a high-impact contribution, the unbuilt ones are where to start.

**Reference profile generator.** A tool that reads an integration's existing `strings.json`, service definitions, device classes, and entity descriptions, and emits a kernel-level MESA profile automatically. This would make Level 1 conformance a CI check rather than a manual task.

**mesa-core. Shipped.** The reference Python module implementing the MESA Specification. Provides profile storage, enforcement engine, inheritance resolution, conflict resolution, temporal constraint evaluation, privacy enforcement, and all MESA MCP tools. Install with `pip install mesa-core`. This is the primary community deliverable.

**`TriggerValidator`. Shipped.** Built into mesa-core: `TriggerValidator(store).validate(get_automation_configs)` cross-references your declared `triggers_automations: none` profiles against your actual HA automation configurations. Run it at startup and when automations change. If an entity you declared `none` is found in an automation trigger or condition block, you get a `ValidationIssue` with the automation ID, the entity's role in that automation, and a recommendation. This prevents the silent safety gap where an operator declares `none` and later adds an automation without updating the profile. One caveat: automations that reference entities indirectly (device triggers, or the `target` blocks of purpose-specific triggers in HA 2026.7+) are only visible to validation when the host supplies the `expand_target` callback; if yours does not, prefer `unknown` over `none` for entities driven that way.

```python
from mesa_core import TriggerValidator

validator = TriggerValidator(store=store)
issues = validator.validate(get_automation_configs=ha_client.get_automations)
for issue in issues:
    print(f"WARNING: {issue.entity_id} declared none but found in {issue.automation_id} as {issue.role}")
```

**`mesa-lint`. Shipped** (`pip install mesa-lint`, https://github.com/sfox38/mesa-lint). A CI-friendly CLI that validates MESA profile documents with mesa-core's own validator, so the linter and the library agree on what is malformed by construction: schema violations, invalid enum values, malformed inferred profiles (missing `confidence` or `generated_at`), non-canonical predicate operator tokens, and tag format. On top of validation it adds deployment lint rules:
- `control_mode: confirm` or `prohibited` without a `control_reason`
- person entities without a privacy classification
- `triggers_automations: none` declared on helper entities
- overly long `semantic_meaning` prose, which costs agent context on every retrieval
- missing `metadata_origin`
- orphaned profiles (stored keys absent from your entity list)
- automation cross-checks against declared `triggers_automations: none`, resolved through profile inheritance as of mesa-lint 0.2

It exits nonzero on findings, so it slots into CI directly. A GitHub Action wrapper and further rules (kernel-field completeness, `autonomous` on security domains, `reversible: true` on notification entities) are roadmap items, not shipped checks.

**Profile inheritance debugger.** The `mesa_explain_profile` tool (defined in the Specification Section 9.5) returns the full inheritance resolution path for any entity, showing which profile level contributed each effective field (including the `device` level as of MESA 1.1) and whether any conflict resolution rule was applied. When an agent refuses an action and you cannot tell why, this is the first tool to reach for. MCP servers running mesa-core implementing Level 3 SHOULD expose this tool.

**Reference profiles for common domains.** Ten well-authored example profiles covering `light`, `climate`, `lock`, `camera`, `media_player`, `cover`, `switch`, `sensor`, `binary_sensor`, and `alarm_control_panel`. Developers can copy and adapt these rather than starting from scratch.

**MESA registry.** A community-maintained registry of canonical tags and vendor namespaces, searchable by tag name. Prevents fragmentation by making the vocabulary discoverable.

**HA frontend integration.** A way to add MESA profiles through the standard HA configuration UI rather than requiring a separate tool or manual file editing. This requires upstream HA cooperation but would dramatically lower the operator authoring barrier.

The mesa-core module is the starting point for all other tooling. See the mesa-core Module Proposal document for the full roadmap and v1 scope. If you build any community tools, please share them via GitHub Issues.

---

---

## 12. Common Anti-Patterns

These are real mistakes that produce profiles that look correct but cause agents to behave unsafely. Each one has been observed in practice or is a predictable consequence of the authoring patterns described in this guide.

**Setting `reversible: true` on entities where reversal has physical consequences.**

`reversible` means the state can be returned to its prior value. It does not mean the physical consequences of the action are safe or cost-free. A garage door is technically reversible (open -> close -> open) but reversing it at the wrong moment can crush an object or a person. A hot water system is reversible but cycling it repeatedly causes wear. For these entities, set `reversible: true` but also set `reversibility_cost: high` and add a `reversibility_note` explaining the actual consequence.

**Setting `triggers_automations: none` on a helper because "I haven't written automations for it yet."**

`none` is a positive assertion, not a default. It tells every agent that uses your profile in every deployment that this entity never triggers automations. If you are unsure, use `unknown`. If you are writing a developer profile for a HACS integration, `unknown` is almost always more honest than `none` for helper entities.

**Setting `control_mode: autonomous` everywhere to reduce confirmation dialogs.**

The confirmation dialog exists because the agent is about to do something consequential. Marking everything autonomous does not make your home safer; it removes the signal that tells the agent when to be careful. If confirmation dialogs are annoying on low-risk entities, configure `deployment_defaults` to set sensible domain-level defaults. The built-in baseline already makes lights autonomous. Do not misrepresent the safety of your entities by marking high-risk ones autonomous just to reduce friction.

**Using `source: developer` for AI-generated profiles.**

If an AI assistant wrote the initial profile and you reviewed it, the source is `hybrid` with your confirmed fields listed. `source: developer` means you wrote it yourself from your own knowledge of the integration. This distinction matters because agents weight developer profiles more heavily. Misrepresenting provenance undermines the trust model.

**Marking `side_effect_scope: entity_only` on a mode flag.**

Mode flags by definition affect more than themselves. `input_boolean.guest_mode` with `side_effect_scope: entity_only` tells agents the only thing that changes is the boolean value. That is false. Use `deployment_wide` for mode flags that affect multiple automations across the deployment. The `side_effect_scope` describes hardware footprint only, but `triggers_automations: likely` plus `affected_automations` in helper traits provides the software cascade information agents need.

**Omitting `control_reason` on `confirm` and `prohibited` entities.**

When an agent is blocked from acting, it needs to communicate a reason to the user. "Access denied" is unhelpful. "This entity triggers an alarm automation and requires confirmation" is actionable. `control_reason` is a short string that costs thirty seconds to write and prevents a support request when an agent stops working.

**Declaring `triggers_automations: none` and then adding an automation without updating the profile.**

`none` is a positive assertion. Once declared, it tells every agent in every session that this entity is safe to act on without cascade caution. If you later add an automation that uses this entity as a trigger or condition, the declaration is now wrong. Use mesa-core's `TriggerValidator` to catch this automatically. Run it at startup and when automations change. If you cannot run validation, use `unknown` instead of `none` unless you are certain.

*MESA - Metadata and Environment Semantics for Agents. Version 1.1. Getting Started Guide. Discussion and contributions are welcome via GitHub Issues.*
