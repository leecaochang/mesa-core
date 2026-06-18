
# mesa-core.

[![CI](https://github.com/sfox38/mesa-core/actions/workflows/ci.yml/badge.svg)](https://github.com/sfox38/mesa-core/actions/workflows/ci.yml)

mesa-core decides whether an AI agent should be allowed to act on a smart-home device, and how cautious it should be about it.

When an assistant tries to turn on a light, unlock the front door, or change the thermostat, mesa-core answers three questions: is this allowed, should the user confirm it first, and why. It ships with safe defaults (a light is fine to control automatically; unlike a lock) that you refine for each home.

It is the reference implementation of the [MESA specification](documents/MESA-Specification.md). It has no runtime dependencies and never talks to Home Assistant directly: you hand it device state through callback functions, and it hands you decisions.

```bash
pip install mesa-core
```

## Quick look

```python
from mesa_core import MesaEnforcer, ProfileStore
from mesa_core.backends import MemoryBackend

enforcer = MesaEnforcer(ProfileStore(backend=MemoryBackend()))

# An AI agent wants to unlock the front door. Should it?
result = enforcer.evaluate("lock.front_door", "lock.unlock")

result.allowed   # False
result.reason    # "Entity is prohibited by policy: lock.front_door"
```

## How decisions work

- Every device has a control mode: act freely, ask the user first, read-only, or never act.
- Devices you have not configured fall back to safe defaults: lights act freely, locks and alarm panels are off-limits, everything else asks first.
- Rules can be set for a single device, an area, or a whole device type, and are combined with a bias toward caution: the more restrictive rule wins, and anything that cannot be checked blocks rather than allows.
- You can add finer limits (cap the speaker volume after 10pm) and time-based rules (no blinds before sunrise).

## Asking the user to confirm

When a device is set to confirm first, `evaluate` returns a challenge instead of a yes. Show the action to the user, then call again with the token from the approved challenge.

```python
result = enforcer.evaluate("cover.garage", "cover.open_cover")
if result.confirmation_challenge:
    # present result.confirmation_challenge to the user; once approved,
    # build a confirmation_token from it and re-submit the same call:
    result = enforcer.evaluate(
        "cover.garage", "cover.open_cover",
        confirmation_token=approved_token,
    )
```

## Reading a device's profile

`ProfileStore` resolves the effective profile after inheritance and defaults. Use a file backend to persist profiles under your HA config:

```python
from mesa_core import ProfileStore
from mesa_core.backends import JsonFileBackend

store = ProfileStore(backend=JsonFileBackend("/config/mesa/"))
profile = store.get_effective("light.living_room_ceiling")
profile.operational_boundaries.control_mode   # ControlMode.AUTONOMOUS
```

## Exposing it to an AI agent (MCP)

Register MESA's tools into an MCP server so the agent can look up profiles and caller context for itself.

```python
from mesa_core.mcp import register_mesa_tools

register_mesa_tools(store, adapter="fastmcp", server=app)
```

Adapters ship for FastMCP and the MCP Python SDK (`pip install "mesa-core[fastmcp]"` or `"mesa-core[mcp]"`). Any other framework can implement a small registration protocol.

## Loading profiles shipped by integrations

An HA integration can ship a `mesa_profile.json` describing its own devices. Load it with:

```python
from mesa_core import import_from_integration

profile = import_from_integration("/config/custom_components/my_integration")
if profile is not None:
    store.set_domain_profile(profile.entity_id, profile)
```

## Documentation

- [MESA Overview](documents/MESA-Overview.md) - the problem MESA solves, in plain terms
- [Getting Started](documents/MESA-Getting-Started.md) - write your first profile
- [Specification](documents/MESA-Specification.md) - the full normative reference
- [Enrichment](documents/MESA-Enrichment.md) - optional advanced domains
- [Module Proposal](documents/MESA-Module.md) - how this library is built

## Status

mesa-core v1.0 is ready for use: profile storage and inheritance, enforcement with confirmation, the MCP retrieval tools, and privacy controls are all implemented.

```bash
git clone https://github.com/sfox38/mesa-core
cd mesa-core
pip install -e ".[dev]"
pytest tests/ -v       # test suite
ruff check . && mypy   # lint and type check
```
