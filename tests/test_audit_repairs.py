"""Permanent regressions for the September 2026 adversarial audit."""

import asyncio
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from examples.ha_service_tool import build_call_ha_service
from mesa_core import (
    MesaEnforcer,
    MesaValidationError,
    ProfileStore,
    SemanticProfile,
    validate_document,
)
from mesa_core.backends import JsonFileBackend, MemoryBackend
from mesa_core.enforcer import ConfirmationManager
from mesa_core.lease import LeaseManager
from mesa_core.mcp.tools import MesaToolHandlers
from mesa_core.privacy import CallerContext


def document(**fields):
    return {"semantic_profile": {"metadata_origin": {"source": "user"}, **fields}}


def put(store, key, doc):
    store.set(key, SemanticProfile.from_dict(key, doc))


def test_solar_nan_must_fail_closed():
    store = ProfileStore(MemoryBackend())
    put(
        store,
        "light.test",
        document(
            operational_boundaries={
                "control_mode": "autonomous",
                "temporal_constraints": [
                    {
                        "id": "night",
                        "condition": {"type": "solar_angle", "solar_event": "sunset"},
                        "effect": {"control_mode": "prohibited"},
                    }
                ],
            }
        ),
    )
    result = MesaEnforcer(store, get_solar_elevation=lambda now: float("nan")).evaluate(
        "light.test", "light.turn_on"
    )
    assert not result.allowed, result


def test_in_predicate_requires_list_operand():
    doc = document(
        operational_boundaries={
            "declared_limits": [
                {
                    "id": "cap",
                    "predicate": {"entity": "sensor.on", "operator": "in", "value": "on"},
                    "limit": {
                        "service": "light.turn_on",
                        "parameter": "brightness",
                        "max_value": 10,
                    },
                }
            ]
        }
    )
    assert not validate_document(doc).ok


def test_malformed_in_operand_cannot_disable_limit():
    doc = document(
        operational_boundaries={
            "control_mode": "autonomous",
            "declared_limits": [
                {
                    "id": "cap",
                    "predicate": {"entity": "sensor.on", "operator": "in", "value": "on"},
                    "limit": {
                        "service": "light.turn_on",
                        "parameter": "brightness",
                        "max_value": 10,
                    },
                }
            ],
        }
    )
    store = ProfileStore(MemoryBackend({"light.test": doc}))
    try:
        result = MesaEnforcer(store, get_state=lambda eid: "on").evaluate(
            "light.test", "light.turn_on", {"brightness": 200}
        )
    except MesaValidationError:
        return  # Rejecting the malformed stored profile is also fail-closed.
    assert not result.allowed, result


def test_confirmation_redemption_is_atomic():
    manager = ConfirmationManager()
    now = datetime(2026, 9, 22, 12)
    challenge = manager.issue("cover.test", "cover.open_cover", {}, now)
    token = {
        "challenge_id": challenge["challenge_id"],
        "approved_by": "resident",
        "approved_at": now.isoformat(),
    }
    barrier = threading.Barrier(2)

    def redeem():
        barrier.wait(timeout=5)
        return manager.redeem(token, "cover.test", "cover.open_cover", {}, now)[0]

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(lambda _: redeem(), range(2)))
    assert sum(outcomes) == 1, outcomes


def test_documented_service_tool_snapshots_nested_parameters():
    async def scenario():
        evaluated, resume = asyncio.Event(), asyncio.Event()

        class ScheduledEnforcer(MesaEnforcer):
            async def aevaluate(self, *args, **kwargs):
                result = await super().aevaluate(*args, **kwargs)
                if result.allowed:
                    # Pause after genuine policy/token evaluation and before dispatch.
                    evaluated.set()
                    await resume.wait()
                return result

        sent = []

        async def perform(domain, service, data):
            sent.append(copy.deepcopy(data))

        store = ProfileStore(MemoryBackend())
        put(store, "light.test", document(operational_boundaries={"control_mode": "confirm"}))
        tool = build_call_ha_service(
            ScheduledEnforcer(store), lambda: CallerContext("resident"), perform
        )
        data = {"rgb_color": [1, 2, 3]}
        response = await tool("light", "turn_on", "light.test", data)
        challenge = response["requires_confirmation"]
        token = {
            "challenge_id": challenge["challenge_id"],
            "approved_by": "resident",
            "approved_at": datetime.now().isoformat(),
        }
        pending = asyncio.create_task(tool("light", "turn_on", "light.test", data, token))
        await asyncio.wait_for(evaluated.wait(), timeout=5)
        data["rgb_color"][:] = [255, 255, 255]
        resume.set()
        await pending
        assert sent[0]["rgb_color"] == [1, 2, 3], sent

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["declared_limits", "temporal_constraints"])
def test_duplicate_safety_ids_rejected(field):
    if field == "declared_limits":
        first = {
            "id": "same",
            "predicate": {"entity": "sensor.on", "operator": "eq", "value": "on"},
            "limit": {"service": "light.turn_on", "parameter": "brightness", "max_value": 255},
        }
        second = copy.deepcopy(first)
        second["limit"]["max_value"] = 10
    else:
        first = {
            "id": "same",
            "condition": {"type": "day_of_week", "days": ["mon"]},
            "effect": {"control_mode": "prohibited"},
        }
        second = copy.deepcopy(first)
        second["condition"]["days"] = ["tue"]
    doc = document(operational_boundaries={"control_mode": "autonomous", field: [first, second]})
    assert not validate_document(doc).ok


def test_duplicate_limit_cannot_disappear_in_resolution():
    pred = {"entity": "sensor.on", "operator": "eq", "value": "on"}
    doc = document(
        operational_boundaries={
            "control_mode": "autonomous",
            "declared_limits": [
                {
                    "id": "cap",
                    "predicate": pred,
                    "limit": {
                        "service": "light.turn_on",
                        "parameter": "brightness",
                        "max_value": 255,
                    },
                },
                {
                    "id": "cap",
                    "predicate": pred,
                    "limit": {
                        "service": "light.turn_on",
                        "parameter": "brightness",
                        "max_value": 10,
                    },
                },
            ],
        }
    )
    store = ProfileStore(MemoryBackend({"light.test": doc}))
    try:
        result = MesaEnforcer(store, get_state=lambda eid: "on").evaluate(
            "light.test", "light.turn_on", {"brightness": 200}
        )
    except MesaValidationError:
        return  # Rejecting the malformed stored profile is also fail-closed.
    assert not result.allowed, result


def test_explicit_omit_survives_store_write():
    store = ProfileStore(MemoryBackend())
    domain = document()
    domain["privacy_classification"] = {
        "level": "sensitive",
        "deny_response_mode": "error",
        "access_roles": {"deny_for": ["guest"]},
    }
    store.set_domain_profile("camera", SemanticProfile.from_dict("camera", domain))
    entity = document()
    entity["privacy_classification"] = {"level": "sensitive", "deny_response_mode": "omit"}
    put(store, "camera.private", entity)
    caller = CallerContext("guest1", roles=["guest"], is_authenticated=True)
    response = asyncio.run(
        MesaToolHandlers(store, caller_context_fn=lambda: caller).mesa_get_profile(
            {"entity_id": "camera.private"}
        )
    )
    assert response["error"] == "not_found", response


def test_empty_person_associations_survive_store_write():
    doc = document(person_traits={"associated_zones": []})
    profile = SemanticProfile.from_dict("person.test", doc)
    assert (
        profile.to_dict()["semantic_profile"].get("person_traits", {}).get("associated_zones") == []
    )


def test_false_privacy_flag_survives_store_write():
    doc = document()
    doc["privacy_classification"] = {"level": "normal", "contains_audio_capture": False}
    result = SemanticProfile.from_dict("sensor.test", doc).to_dict()
    assert result["privacy_classification"].get("contains_audio_capture") is False


def test_lease_honors_inherited_critical_profile():
    store = ProfileStore(MemoryBackend())
    domain = document(cooperative_priority={"level": "critical"})
    store.set_domain_profile("automation", SemanticProfile.from_dict("automation", domain))
    put(
        store,
        "automation.fire",
        document(environmental_dependencies={"trigger_entities": ["switch.vent"]}),
    )
    assert (
        store.get_effective("automation.fire").raw["semantic_profile"]["cooperative_priority"][
            "level"
        ]
        == "critical"
    )
    response = LeaseManager(store).request(["switch.vent"], 10, session_id="session")
    assert not response.granted, response


def test_origin_object_requires_source():
    assert not validate_document({"semantic_profile": {"metadata_origin": {}}}).ok


@pytest.mark.parametrize("routing", ["invalid", {"intent_tags": [1, {}]}])
def test_known_routing_shape_is_validated(routing):
    assert not validate_document(document(semantic_routing=routing)).ok


def test_invalid_routing_cannot_poison_query():
    store = ProfileStore(MemoryBackend())
    try:
        put(store, "light.test", document(semantic_routing="invalid"))
    except MesaValidationError:
        return  # Rejecting malformed routing at the write boundary is preferred.
    response = asyncio.run(
        MesaToolHandlers(store).mesa_query_profiles({"intents": ["lighting.ambient"]})
    )
    assert response.get("error") != "server_error", response


def test_unknown_origin_extension_survives_roundtrip():
    doc = document()
    doc["semantic_profile"]["metadata_origin"]["x_vendor"] = {"model": "audit"}
    output = SemanticProfile.from_dict("light.test", doc).to_dict()
    assert output["semantic_profile"]["metadata_origin"].get("x_vendor") == {"model": "audit"}


def test_json_backend_readers_never_observe_truncated_write(tmp_path, monkeypatch):
    backend = JsonFileBackend(tmp_path)
    original = document(operational_boundaries={"control_mode": "prohibited"})
    backend.write("light.test", original)
    opened, resume = threading.Event(), threading.Event()
    import os

    real_replace = os.replace

    def scheduled_replace(source, destination):
        opened.set()
        assert resume.wait(timeout=5)
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", scheduled_replace)
    with ThreadPoolExecutor(1) as pool:
        writer = pool.submit(backend.write, "light.test", document())
        try:
            assert opened.wait(timeout=5)
            assert backend.read("light.test") == original
        finally:
            resume.set()
            writer.result(timeout=5)


@pytest.mark.parametrize(
    "reading", [float("nan"), float("inf"), -float("inf"), True, "0", {}, None]
)
@pytest.mark.parametrize("negate", [False, True])
def test_invalid_solar_readings_are_unevaluable(reading, negate):
    from mesa_core.temporal import TemporalEvaluator

    evaluator = TemporalEvaluator(get_solar_elevation=lambda now: reading)
    assert (
        evaluator.evaluate_condition(
            {"type": "solar_angle", "solar_event": "sunset", "negate": negate}, datetime.now()
        )
        is None
    )


@pytest.mark.parametrize("operator", ["eq", "neq", "gt", "gte", "lt", "lte", "in", "contains"])
@pytest.mark.parametrize(
    ("value", "allowed"),
    [
        (None, set()),
        (False, {"eq", "neq"}),
        (1, {"eq", "neq", "gt", "gte", "lt", "lte"}),
        ("on", {"eq", "neq", "contains"}),
        ([], {"in"}),
        ([1, "on"], {"in"}),
        ([False], set()),
        ({}, set()),
        ([None], set()),
    ],
)
def test_operator_operand_schema_matrix(operator, value, allowed):
    from pathlib import Path

    import jsonschema

    from mesa_core.enforcer import _compare

    schema = json.loads(
        (Path(__file__).parents[1] / "mesa_core/schemas/mesa_profile.schema.json").read_text()
    )
    doc = document(
        operational_boundaries={
            "declared_limits": [
                {
                    "id": "cap",
                    "predicate": {"entity": "sensor.test", "operator": operator, "value": value},
                    "limit": {
                        "service": "light.turn_on",
                        "parameter": "brightness",
                        "max_value": 10,
                    },
                }
            ]
        }
    )
    expected = operator in allowed
    assert validate_document(doc).ok == expected
    assert jsonschema.Draft202012Validator(schema).is_valid(doc) == expected
    if not expected:
        assert _compare(operator, "on", value) is None


def test_numeric_membership_matches_numeric_equality():
    from mesa_core.enforcer import _compare

    assert _compare("in", "1.0", [1]) is True
    assert _compare("in", "1.0", ["1"]) is False
    assert _compare("in", "unknown", [1]) is None


@pytest.mark.parametrize("scope", ["domain", "integration", "area", "device"])
@pytest.mark.parametrize("attach", [False, True])
def test_lease_inherits_scope_and_priority(scope, attach):
    from mesa_core.inheritance import InheritanceResolver

    store = ProfileStore(MemoryBackend())
    resolver = InheritanceResolver(
        store,
        get_entity_integration=lambda _: "test",
        get_entity_area=lambda _: "test",
        get_entity_device=lambda _: "test",
    )
    key = "automation" if scope == "domain" else "test"
    getattr(store, f"set_{scope}_profile")(
        key,
        SemanticProfile.from_dict(
            key,
            document(
                cooperative_priority={"level": "critical"},
                environmental_dependencies={"trigger_entities": ["switch.vent"]},
            ),
        ),
    )
    put(store, "automation.fire", document())
    if attach:
        store.attach_resolver(resolver)
    manager = LeaseManager(store, resolver=None if attach else resolver)
    assert not manager.request(["switch.vent"], 10, session_id="session").granted


def test_atomic_write_failure_preserves_original(tmp_path, monkeypatch):
    import os

    backend = JsonFileBackend(tmp_path)
    original = document()
    backend.write("light.test", original)

    def fail(*args):
        raise OSError("interrupted replacement")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        backend.write("light.test", document(semantic_tags=["lighting.ambient"]))
    assert backend.read("light.test") == original
    assert list(tmp_path.glob("*.tmp")) == []


def test_parse_warnings_survive_resolution():
    doc = document()
    doc["semantic_profile"]["metadata_origin"]["generated_at"] = "2026-09-22"
    profile = SemanticProfile.from_dict("light.test", doc)
    assert any("trust laundering" in warning for warning in profile.parse_warnings)


def test_declared_defaults_survive_serialization():
    doc = document(
        semantic_tags=[],
        inheritance_scope="entity",
        operational_boundaries={
            "declared_limits": [],
            "temporal_constraints": [],
            "override_control_mode": False,
        },
    )
    doc["semantic_profile"]["metadata_origin"].update(
        staleness_window_days=60, confirmed_fields=[], x_vendor={"nested": []}
    )
    profile = SemanticProfile.from_dict("light.test", doc)
    output = profile.to_dict()["semantic_profile"]
    for key, value in doc["semantic_profile"].items():
        assert output[key] == value


def test_default_only_tool_retrieval_is_not_found():
    store = ProfileStore(MemoryBackend())
    store.set_deployment_defaults({"default_control_mode": "autonomous"})
    assert (
        store.get_effective("light.absent").operational_boundaries.control_mode.value
        == "autonomous"
    )
    response = asyncio.run(MesaToolHandlers(store).mesa_get_profile({"entity_id": "light.absent"}))
    assert response["error"] == "not_found"


def test_invalid_stored_routing_does_not_hide_other_results():
    backend = MemoryBackend(
        {
            "light.bad": document(semantic_routing={"intent_tags": [{}]}),
            "light.good": document(semantic_routing={"intent_tags": ["lighting.ambient"]}),
        }
    )
    result = ProfileStore(backend).query(intents=["lighting.ambient"])
    assert [row.entity_id for row in result.rows] == ["light.good"]
    assert result.warnings


def test_explicit_fields_survive_archive_and_resolution(tmp_path):
    from mesa_core import export_profiles, import_profiles

    source = ProfileStore(MemoryBackend())
    inherited = document(person_traits={"associated_zones": ["zone.home"]})
    inherited["privacy_classification"] = {
        "level": "normal",
        "contains_audio_capture": True,
        "deny_response_mode": "error",
    }
    source.set_domain_profile("person", SemanticProfile.from_dict("person", inherited))
    doc = document(person_traits={"associated_zones": []})
    doc["semantic_profile"]["metadata_origin"]["x_vendor"] = {"nested": []}
    doc["privacy_classification"] = {
        "level": "normal",
        "contains_audio_capture": False,
        "deny_response_mode": "omit",
    }
    put(source, "person.test", doc)
    destination = ProfileStore(JsonFileBackend(tmp_path))
    assert import_profiles(destination, export_profiles(source)).ok
    profile = destination.get_effective("person.test")
    assert profile.person_traits.associated_zones == []
    assert profile.privacy_classification.contains_audio_capture is False
    assert profile.privacy_classification.deny_response_mode == "omit"
    stored = destination.get("person.test")
    assert stored.to_dict()["semantic_profile"]["metadata_origin"]["x_vendor"] == {"nested": []}


def test_confirmation_second_thread_cannot_enter_consumption():
    import inspect
    import sys

    manager = ConfirmationManager()
    now = datetime.now()
    challenge = manager.issue("cover.test", "cover.open_cover", {}, now)
    token = {
        "challenge_id": challenge["challenge_id"],
        "approved_by": "resident",
        "approved_at": now.isoformat(),
    }
    lines, start = inspect.getsourcelines(ConfirmationManager.redeem)
    mark = start + next(i for i, line in enumerate(lines) if 'record["used"] = True' in line)
    paused, release, attempted = threading.Event(), threading.Event(), threading.Event()

    def trace(frame, event, arg):
        if (
            frame.f_code is ConfirmationManager.redeem.__code__
            and event == "line"
            and frame.f_lineno == mark
        ):
            paused.set()
            assert release.wait(5)
        return trace

    def first():
        sys.settrace(trace)
        try:
            return manager.redeem(token, "cover.test", "cover.open_cover", {}, now)[0]
        finally:
            sys.settrace(None)

    def second():
        attempted.set()
        return manager.redeem(token, "cover.test", "cover.open_cover", {}, now)[0]

    with ThreadPoolExecutor(2) as pool:
        one = pool.submit(first)
        try:
            assert paused.wait(5)
            two = pool.submit(second)
            assert attempted.wait(5)
            # The unused record remains protected while the first consumer pauses.
            assert not two.done()
        finally:
            release.set()
        assert one.result(5) is True
        assert two.result(5) is False


@pytest.mark.parametrize("scope", ["domain", "integration", "area", "device"])
def test_duplicate_ids_across_layers_remain_valid(scope):
    from mesa_core.inheritance import InheritanceResolver

    store = ProfileStore(MemoryBackend())
    resolver = InheritanceResolver(
        store,
        get_entity_integration=lambda _: "test",
        get_entity_area=lambda _: "test",
        get_entity_device=lambda _: "test",
    )

    def limited(maximum):
        return document(
            operational_boundaries={
                "declared_limits": [
                    {
                        "id": "cap",
                        "predicate": {"entity": "sensor.on", "operator": "eq", "value": "on"},
                        "limit": {
                            "service": "light.turn_on",
                            "parameter": "brightness",
                            "max_value": maximum,
                        },
                    }
                ]
            }
        )

    key = "light" if scope == "domain" else "test"
    getattr(store, f"set_{scope}_profile")(key, SemanticProfile.from_dict(key, limited(255)))
    put(store, "light.test", limited(10))
    effective = resolver.resolve("light.test")
    assert len(effective.operational_boundaries.declared_limits) == 1
    assert effective.operational_boundaries.declared_limits[0]["limit"]["max_value"] == 10
