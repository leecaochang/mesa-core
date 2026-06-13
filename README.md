# mesa-core v1.0

Reference implementation of the [MESA specification](documents/MESA-Specification.md) (Metadata and Environment Semantics for Agents), a semantic safety and coordination layer for AI-operated smart environments.

Any MCP server that handles Home Assistant AI orchestration can integrate mesa-core to gain MESA profile management, semantic enforcement, retrieval API tools, and privacy controls without reimplementing the specification.

- **Zero runtime dependencies.** All HA data arrives through host callbacks; mesa-core never imports `homeassistant` and makes no network calls.
- **Distribution:** `mesa-core` on PyPI; **import name:** `mesa_core` (the `mesa` import name belongs to the Mesa agent-based modeling framework).

```bash
pip install mesa-core
```

> ### See [MESA Overview](documents/MESA-Overview.md) for an introduction to MESA

## Minimal integration (Level 1)

```python
from mesa_core import ProfileStore
from mesa_core.backends import JsonFileBackend

store = ProfileStore(backend=JsonFileBackend("/config/mesa/"))

# Effective profile after inheritance, conflict rules, and safety baselines:
profile = store.get_effective("light.living_room_ceiling")
print(profile.operational_boundaries.control_mode)  # e.g. ControlMode.AUTONOMOUS
```

## Enforcement

```python
from datetime import datetime
from mesa_core import MesaEnforcer, CallerContext

enforcer = MesaEnforcer(store, get_state=my_ha_state_lookup)

result = enforcer.evaluate(
    entity_id="lock.front_door",
    service="lock.unlock",
    service_params={"entity_id": "lock.front_door"},
    caller_context=CallerContext(
        caller_id="user.abc", roles=["primary_resident"],
        is_authenticated=True, session_id="sess-1",
    ),
    current_time=datetime.now(),
)
if not result.allowed:
    if result.confirmation_challenge:
        # control_mode: confirm in enforced mode -- present the action to the
        # user, then re-submit with confirmation_token (Spec 6.6).
        ...
    else:
        raise PermissionError(result.reason)
```

Unprofiled entities get the built-in domain safety baseline (Spec 5.8): lights are autonomous, locks and alarm panels are prohibited, everything else asks first. Temporal constraints are fail-closed, loosening effects are ignored, and declared limits with unevaluable predicates stay active.

## MCP tools (Level 3 retrieval API)

```python
from mesa_core.mcp import register_mesa_tools

register_mesa_tools(store, adapter="fastmcp", server=app)
# Registers: mesa_query_profiles, mesa_get_profile,
#            mesa_explain_profile, mesa_get_caller_context
```

Adapters ship for FastMCP and the raw MCP Python SDK (`pip install mesa-core[fastmcp]` / `[mcp]`); any other framework implements the small `ToolRegistry` protocol.

## Developer profiles from integrations

```python
from mesa_core import import_from_integration

profile = import_from_integration("/config/custom_components/my_integration")
if profile is not None:
    store.set_domain_profile(profile.entity_id, profile)
```

Sidecar `mesa_profile.json` files default to `source: developer` (Spec 5.3).

## Documentation

- [MESA Overview](documents/MESA-Overview.md) - the problem and the seven-field kernel
- [MESA Specification (Core)](documents/MESA-Specification.md) - normative schemas, Sections 1-9 and 22-24
- [MESA Enrichment](documents/MESA-Enrichment.md) - advanced domains, Sections 10-21
- [Getting Started Guide](documents/MESA-Getting-Started.md) - add your first profile today
- [Module Proposal](documents/MESA-Module.md) - architecture and integration guide for this library

The canonical machine-readable schemas ship in the package: `mesa_core/schemas/mesa_profile.schema.json` and `mesa_core/schemas/mesa_tools.schema.json`.

## Conformance

mesa-core v1.0 implements MESA Levels 1 and 2 in full and the core of Level 3: the retrieval API tools, enforcement (including the Spec 6.6 confirmation challenge/token round-trip), inheritance and conflict resolution (Rules A-E), privacy enforcement with audit logging, the TriggerValidator, and profile migration. The lease protocol ships in v1.1.

```bash
git clone https://github.com/sfox38/mesa-core
cd mesa-core
pip install -e ".[dev]"
pytest tests/ -v       # conformance suite
ruff check . && mypy   # quality gates
```

