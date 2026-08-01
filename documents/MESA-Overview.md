# MESA: Metadata and Environment Semantics for Agents
**A semantic safety and coordination layer for AI-operated smart environments**
**Version:** 1.0

---

## The Problem in One Paragraph

When an AI agent connects to your smart home, it sees a list of entities, their states, and the services it can call. It does not know which devices are safe to control automatically. It does not know that your `input_boolean.cinema_mode` governs a dozen automations. It does not know that `unavailable` on your cloud thermostat means something completely different from `unavailable` on your local Zigbee sensor. It does not know that turning up the kitchen speakers at 11pm will wake the baby two rooms away. It reasons from names and guesses. Sometimes it guesses wrong.

MESA is a small, optional, machine-readable annotation you add to your integrations, entities, and automations. It tells agents the things they cannot figure out on their own.

---

## What MESA Looks Like

This is a complete, valid MESA profile for a smart light:

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

Seven fields. That is the complete kernel. An agent that reads this knows: this is ambient lighting, it is safe to control automatically, it does not trigger any automations, mistakes can be undone, it only affects itself, and it contains no personal data.

Now compare that to a door lock:

```json
{
  "semantic_profile": {
    "semantic_tags": ["security.access_control"],
    "operational_boundaries": {
      "control_mode": "confirm",
      "triggers_automations": "none",
      "reversible": true,
      "reversibility_cost": "moderate",
      "side_effect_scope": "room_localized"
    }
  },
  "privacy_classification": {
    "level": "normal"
  }
}
```

The agent now knows: ask before touching this. And a mode flag helper that controls a dozen automations:

```json
{
  "semantic_profile": {
    "semantic_tags": ["helper.mode_flag", "helper.high_impact"],
    "operational_boundaries": {
      "control_mode": "confirm",
      "triggers_automations": "likely",
      "reversible": true,
      "reversibility_cost": "trivial",
      "side_effect_scope": "deployment_wide"
    }
  },
  "privacy_classification": {
    "level": "normal"
  }
}
```

The agent now knows: ask before touching this, and be aware that changing it will trigger automations across the deployment. Same seven fields. Three very different answers. This is what the agent was missing.

---

## The Seven Kernel Fields

Every MESA profile starts with these seven fields. Nothing else is required.

| Field | What it tells the agent |
|---|---|
| `semantic_tags` | What this component is for. Picked from a shared vocabulary so agents understand without guessing. |
| `control_mode` | How the agent should treat writes. `autonomous`: act freely. `confirm`: ask first. `read_only`: not writable by nature. `prohibited`: do not act, by operator policy. |
| `triggers_automations` | Whether changing this entity is likely to trigger automations. `likely`, `none`, `unknown`, or `deployment_defined`. Agents apply cascade caution when `likely` or `deployment_defined`. |
| `reversible` | Can the action be undone? Turning a light off is reversible. Sending a notification is not. |
| `reversibility_cost` | How costly is undoing this action? `none`, `trivial`, `moderate`, or `high`. |
| `side_effect_scope` | How far does the direct hardware impact spread? `entity_only`, `device_localized`, `room_localized`, `zone_wide`, or `deployment_wide`. |
| `privacy_classification.level` | Does this contain personal data? `public`, `normal`, `sensitive`, or `restricted`. |

---

## What Happens When You Add More

The seven fields are the floor. Every additional field you add improves agent reasoning in a specific, measurable way.

**Add `metadata_origin`** and agents know how much to trust the profile.

**Add `control_reason`** and agents can explain a refusal in plain language instead of "access denied".

**Add `state_volatility`** and agents know whether to grab a coordination lock before acting.

**Add `temporal_constraints`** and agents know not to vacuum during work-from-home calendar events, or not to raise volume after 10pm.

**Add a `diagnostic_profile`** and agents understand what `unavailable` actually means for your specific integration, and what to do about it.

**Add `cooperative_priority` to automations** and agents know which automations they can work alongside and which ones take precedence.

**Add `spatial_traits` to areas** and agents understand that the open-plan kitchen and living room share acoustic space, and that raising the kitchen speaker volume affects a study two metres away.

None of these are required. All of them are useful. You add them when you have time, when you see agent behaviour that could be better, or when a specific failure mode matters to your deployment.

---

## Who MESA Is For

**Hobbyist integration developers.** Ship the seven kernel fields in a `mesa_profile.json` file inside your integration's directory. Takes five minutes. Makes your integration immediately more useful to any AI agent. Use an AI assistant to generate the profile if you are unsure what values to use.

**Home Assistant operators.** Add entity-level profiles through any MCP server that supports mesa-core. Start with your highest-impact helpers, your security devices, and your mode flags. You do not need to touch integration code.

**Serious integration developers.** Add full profiles including diagnostic semantics, event semantics, and resource characteristics. Provide the information that no one else can: what your custom states mean, what your error classes indicate, and what makes your integration distinctive.

**MCP server developers.** Add MESA to your existing server by integrating mesa-core, the reference Python module that implements the MESA specification. Three lines of code register all the MESA retrieval tools into your server. Enforcement is a separate step: it lives on your service-call path, where you ask the enforcer whether an action is permitted before executing it, because only your server sees the calls agents make. Your users get MESA without switching servers.

---

## What MESA Is Not

MESA does not tell agents how to behave. It describes the environment. What an agent does with that information is the agent's concern.

MESA does not replace Home Assistant's access control. A MESA profile that says `control_mode: prohibited` is a strong signal to a well-behaved agent. An MCP server running mesa-core in `enforced` mode can reject violating calls before they reach HA. Without enforcement, MESA's safety properties rest on agent goodwill. Neither mechanism replaces HA's native permissions, which remain the final backstop.

MESA does not require anyone else to adopt it before you benefit. A single profiled integration in a deployment of a thousand entities is immediately useful to any agent that reads it. Partial adoption delivers partial benefit.

MESA is not a complete smart home ontology. It is a practical, incrementally adoptable safety and coordination layer. The goal is not to model everything. The goal is to give agents enough context to act safely.

---

## The Adoption Path

**Today.** Add the seven kernel fields to your integration or entity. Zero dependencies. Zero coordination required.

**When mesa-core is integrated into your MCP server.** Start using the retrieval API so agents can query only the context relevant to a given task, rather than receiving full state dumps. This is expected to reduce context window consumption, by how much is deployment-specific and has not yet been measured. Any MCP server can add this capability by integrating the mesa-core module.

**As the ecosystem matures.** Multi-agent coordination, spatial graph reasoning, and real-time conflict detection become possible as more of the deployment is profiled.

The design rewards every level of investment. A five-minute kernel profile is better than nothing. A complete deployment-wide profile is better still.

---

## The Canonical Vocabulary

MESA defines a shared tag vocabulary so that `lighting.ambient` means the same thing to every agent from every vendor. The vocabulary covers lighting, climate, media, security, presence, energy, space, diagnostics, performance, audio, TTS, automation, scenes, helpers, zones, people, and the Assist pipeline.

Vendor-specific capabilities that have no canonical equivalent use a namespaced format: `myintegration.custom_feature`. Unknown vendor tags are treated as opaque by agents that have not seen them before.

---

## Honest Limitations

The lease protocol that prevents automation race conditions is a cooperative agreement between MESA-aware components. Native YAML automations that do not know about MESA will continue to fire normally. This is a real limitation and we say so explicitly.

Profile freshness is the operator's responsibility. A MESA profile authored a year ago may not reflect an integration that has since been updated. The specification includes `profile_valid_for` fields and invalidation triggers to help, but there is no substitute for human review when things change.

AI-inferred profiles are explicitly marked as lower-trust. An agent that generates a profile from deployment observation MUST mark it `inferred_ai`. Human-confirmed profiles carry higher authority. The spec defines how this degrades over time.

---

## Get Started

**Read the Getting Started Guide** if you want to add your first MESA profile today. It has prompt templates for AI-assisted authoring, worked examples for common component types, and honest guidance about what good enough looks like at each stage.

**Read the Specification** if you want to understand the complete schema, integrate mesa-core into your MCP server, or contribute to the standard.

**Read the Enrichment Specification** when you need the advanced domains: spatial reasoning, diagnostics, automation coordination, people and zone semantics, or the lease protocol. None of it is required to start.

**Read the mesa-core Module Proposal** if you want to integrate MESA into an existing MCP server. It describes the Python module, its API, and what a first integration looks like in practice.

**Join the conversation** via GitHub Issues. Your deployment experience, your failure modes, and your edge cases are what will make MESA better.

---

*MESA - Metadata and Environment Semantics for Agents. Version 1.0.*
