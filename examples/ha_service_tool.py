"""The entity-targeted service tool the Module Proposal documents (Section 6.2).

This file is the source of that example, not a copy of it: the Module embeds
the marked region below verbatim, and the test suite imports this module,
registers the tool against both supported FastMCP lineages, and exercises the
guard. Documented host code that no test runs is how several enforcement gaps
reached this project, so the copyable version and the executed version are the
same text.

It is a host's code, not part of mesa-core. It depends only on mesa-core and
the standard library, so it runs here without Home Assistant; substitute your
own HA client where `perform_ha_call` is injected.
"""

# --- docs:call_ha_service:start
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
# --- docs:call_ha_service:end
