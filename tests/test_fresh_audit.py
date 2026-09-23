"""Independent expected-behavior tests from the fresh audit. Source stays unchanged."""

import asyncio
from datetime import datetime

import pytest

from mesa_core import MesaEnforcer, ProfileStore
from mesa_core.backends import MemoryBackend
from mesa_core.mcp.tools import MesaToolHandlers


def document(**boundaries):
    return {
        "semantic_profile": {
            "metadata_origin": {"source": "user"},
            "operational_boundaries": {"control_mode": "autonomous", **boundaries},
        }
    }


@pytest.mark.parametrize(
    "method", ["mesa_get_profile", "mesa_query_profiles", "mesa_explain_profile"]
)
def test_mcp_registry_callback_can_bridge_to_server_loop(method):
    async def scenario():
        loop = asyncio.get_running_loop()

        async def lookup():
            return "room"

        def get_area(_):
            future = asyncio.run_coroutine_threadsafe(lookup(), loop)
            try:
                return future.result(timeout=0.15)
            finally:
                future.cancel()

        store = ProfileStore(MemoryBackend({"light.test": document()}), get_entity_area=get_area)
        # Positive control: the documented async store path supports this bridge.
        assert (await store.aget_effective("light.test")).entity_id == "light.test"
        handler = getattr(MesaToolHandlers(store), method)
        response = await handler(
            {} if method == "mesa_query_profiles" else {"entity_id": "light.test"}
        )
        assert "error" not in response, response

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind,bound,observed",
    [
        ("max_value", 2**53, 2**53 + 1),
        ("min_value", 2**53 + 1, 2**53),
    ],
)
def test_adjacent_integer_bound_cannot_be_crossed(kind, bound, observed):
    profile = document(
        declared_limits=[
            {
                "id": "exact",
                "predicate": {"entity": "sensor.ready", "operator": "eq", "value": "on"},
                "limit": {"service": "number.set_value", "parameter": "value", kind: bound},
            }
        ]
    )
    enforcer = MesaEnforcer(
        ProfileStore(MemoryBackend({"number.test": profile})), get_state=lambda _: "on"
    )
    result = enforcer.evaluate("number.test", "number.set_value", {"value": observed})
    assert not result.allowed, result


@pytest.mark.parametrize(
    "operator,state,bound",
    [
        ("gt", str(2**53 + 1), 2**53),
        ("lt", str(2**53), 2**53 + 1),
        ("neq", str(2**53 + 1), 2**53),
    ],
)
def test_adjacent_integer_predicate_cannot_disable_limit(operator, state, bound):
    profile = document(
        declared_limits=[
            {
                "id": "exact",
                "predicate": {"entity": "sensor.counter", "operator": operator, "value": bound},
                "limit": {"service": "number.set_value", "parameter": "value", "max_value": 0},
            }
        ]
    )
    enforcer = MesaEnforcer(
        ProfileStore(MemoryBackend({"number.test": profile})), get_state=lambda _: state
    )
    result = enforcer.evaluate("number.test", "number.set_value", {"value": 1})
    assert not result.allowed, result


@pytest.mark.parametrize(
    "negate,value", [(False, None), (False, False), (True, {"error": "unavailable"})]
)
def test_unusable_calendar_result_cannot_drop_constraint(negate, value):
    profile = document(
        temporal_constraints=[
            {
                "id": "calendar",
                "condition": {
                    "type": "calendar_entity",
                    "calendar_entity": "calendar.test",
                    "negate": negate,
                },
                "effect": {"control_mode": "prohibited"},
            }
        ]
    )
    enforcer = MesaEnforcer(
        ProfileStore(MemoryBackend({"light.test": profile})), get_calendar_events=lambda _: value
    )
    result = enforcer.evaluate("light.test", "light.turn_on", current_time=datetime(2026, 9, 22))
    assert not result.allowed, result


@pytest.mark.parametrize(
    "method", ["mesa_get_profile", "mesa_query_profiles", "mesa_explain_profile"]
)
def test_retrieval_callbacks_preserve_request_context_and_loop_progress(method):
    import contextvars
    import threading

    from mesa_core.privacy import CallerContext

    async def scenario():
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()
        identity = contextvars.ContextVar("identity", default="missing")
        identity.set("resident")
        callbacks = []

        async def lookup(name):
            await asyncio.sleep(0)
            assert identity.get() == "resident"
            callbacks.append(name)

        def bridge(name, result):
            assert threading.get_ident() != loop_thread
            assert identity.get() == "resident"
            asyncio.run_coroutine_threadsafe(lookup(name), loop).result(timeout=2)
            return result

        def caller():
            assert threading.get_ident() == loop_thread
            return CallerContext(identity.get(), is_authenticated=True)

        store = ProfileStore(
            MemoryBackend({"light.test": document()}),
            get_entity_area=lambda _: bridge("area", "room"),
        )
        handler = MesaToolHandlers(
            store,
            caller_context_fn=caller,
            get_validity_context=lambda _: bridge("validity", {}),
            get_semantic_moments=lambda _: bridge("moments", [{"id": "test"}]),
        )
        params = {} if method == "mesa_query_profiles" else {"entity_id": "light.test"}
        if method == "mesa_get_profile":
            params["include_semantic_moments"] = True
        response = await getattr(handler, method)(params)
        assert "error" not in response
        assert "area" in callbacks
        if method != "mesa_explain_profile":
            assert "validity" in callbacks
        if method == "mesa_get_profile":
            assert response["semantic_moments"] == [{"id": "test"}]
            assert "moments" in callbacks

    asyncio.run(scenario())


@pytest.mark.parametrize("negate", [False, True])
@pytest.mark.parametrize("events", [None, False, True, {}, {"error": "unavailable"}, "", (), 0])
def test_calendar_bad_shapes_fail_closed(events, negate):
    profile = document(
        temporal_constraints=[
            {
                "id": "cal",
                "condition": {
                    "type": "calendar_entity",
                    "calendar_entity": "calendar.test",
                    "negate": negate,
                },
                "effect": {"control_mode": "prohibited"},
            }
        ]
    )
    result = MesaEnforcer(
        ProfileStore(MemoryBackend({"light.test": profile})), get_calendar_events=lambda _: events
    ).evaluate("light.test", "light.turn_on")
    assert not result.allowed
    assert result.warnings


@pytest.mark.parametrize(
    "events,negate,allowed",
    [([], False, True), ([{}], False, False), ([], True, False), ([{}], True, True)],
)
def test_calendar_valid_lists(events, negate, allowed):
    profile = document(
        temporal_constraints=[
            {
                "id": "cal",
                "condition": {
                    "type": "calendar_entity",
                    "calendar_entity": "calendar.test",
                    "negate": negate,
                },
                "effect": {"control_mode": "prohibited"},
            }
        ]
    )
    result = MesaEnforcer(
        ProfileStore(MemoryBackend({"light.test": profile})), get_calendar_events=lambda _: events
    ).evaluate("light.test", "light.turn_on")
    assert result.allowed is allowed
    assert not result.warnings


@pytest.mark.parametrize(
    "kind,bound,observed", [("max_value", 2**53, 2**53 + 1), ("min_value", 2**53 + 1, 2**53)]
)
def test_temporal_bounds_preserve_integer_precision(kind, bound, observed):
    profile = document(
        temporal_constraints=[
            {
                "id": "exact",
                "condition": {"type": "day_of_week", "days": ["tue"]},
                "effect": {"service": "number.set_value", "parameter": "value", kind: bound},
            }
        ]
    )
    enforcer = MesaEnforcer(ProfileStore(MemoryBackend({"number.test": profile})))
    assert not enforcer.evaluate(
        "number.test", "number.set_value", {"value": observed}, current_time=datetime(2026, 9, 22)
    ).allowed
    assert enforcer.evaluate(
        "number.test", "number.set_value", {"value": bound}, current_time=datetime(2026, 9, 22)
    ).allowed


@pytest.mark.parametrize(
    "operator,state,value,expected",
    [
        ("eq", str(2**53 + 1), 2**53 + 1, True),
        ("eq", str(2**53 + 1), 2**53, False),
        ("in", str(2**53 + 1), [2**53], False),
        ("in", str(2**53 + 1), [2**53 + 1], True),
        ("gte", "9007199254740993.0", 2**53 + 1, True),
        ("gt", "9007199254740993e0", 2**53, True),
        ("lt", str(-(2**53 + 1)), -(2**53), True),
        ("eq", "0.1", 0.1, True),
    ],
)
def test_numeric_comparison_precision_controls(operator, state, value, expected):
    from mesa_core.enforcer import _compare

    assert _compare(operator, state, value) is expected


def test_automation_cycles_raise_but_shared_aliases_work():
    from mesa_core import MesaValidationError
    from mesa_core.trigger_validator import entities_by_role

    shared = {"entity_id": "switch.test"}
    assert entities_by_role({"trigger": shared, "condition": shared})["condition"] == {
        "switch.test"
    }
    cycle = {}
    cycle["nested"] = cycle
    with pytest.raises(MesaValidationError, match="cyclic"):
        entities_by_role({"trigger": cycle})
    circular_list = []
    circular_list.append(circular_list)
    with pytest.raises(MesaValidationError, match="cyclic"):
        entities_by_role({"action": circular_list})


@pytest.mark.parametrize("negate", [False, True])
def test_calendar_exception_stays_active(negate):
    def unavailable(_):
        raise RuntimeError("unavailable")

    profile = document(
        temporal_constraints=[
            {
                "id": "cal",
                "condition": {
                    "type": "calendar_entity",
                    "calendar_entity": "calendar.test",
                    "negate": negate,
                },
                "effect": {"control_mode": "prohibited"},
            }
        ]
    )
    result = MesaEnforcer(
        ProfileStore(MemoryBackend({"light.test": profile})), get_calendar_events=unavailable
    ).evaluate("light.test", "light.turn_on")
    assert not result.allowed
    assert result.warnings
