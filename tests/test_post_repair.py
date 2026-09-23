"""Regressions from the September post-repair review."""

import asyncio

import pytest

from mesa_core import MesaValidationError, ProfileStore, import_from_integration
from mesa_core.backends import MemoryBackend
from mesa_core.lease import LeaseManager
from mesa_core.mcp.tools import MesaToolHandlers
from mesa_core.privacy import CallerContext


def document(**fields):
    return {"semantic_profile": {"metadata_origin": {"source": "user"}, **fields}}


@pytest.mark.parametrize("legacy_field", ["semantic_routing", "metadata_origin"])
def test_newly_invalid_protective_profile_cannot_grant_lease(legacy_field):
    profile = document(
        cooperative_priority={"level": "critical"},
        environmental_dependencies={"trigger_entities": ["switch.vent"]},
    )
    # Both shapes were accepted before the audit repairs. An unrelated invalid
    # field must not turn existing critical protection into a successful grant.
    profile["semantic_profile"][legacy_field] = (
        "legacy" if legacy_field == "semantic_routing" else {}
    )
    store = ProfileStore(MemoryBackend({"automation.fire": profile}))
    try:
        response = LeaseManager(store).request(["switch.vent"], 10, session_id="audit")
    except MesaValidationError:
        return  # Explicit failure is safe; a successful grant is not.
    assert not response.granted, response.to_dict()


def test_ignored_nested_privacy_cannot_erase_inherited_denial():
    domain = document()
    domain["privacy_classification"] = {
        "level": "sensitive",
        "access_roles": {"deny_for": ["guest"]},
    }
    entity = document(privacy_classification={"level": "normal", "access_roles": {}})
    # This sibling is canonical. The nested object must contribute no paths.
    entity["privacy_classification"] = {"level": "normal"}
    store = ProfileStore(MemoryBackend({"__domain__:camera": domain, "camera.private": entity}))
    caller = CallerContext("guest1", roles=["guest"], is_authenticated=True)
    response = asyncio.run(
        MesaToolHandlers(store, caller_context_fn=lambda: caller).mesa_get_profile(
            {"entity_id": "camera.private"}
        )
    )
    assert response.get("error") == "not_found", response


@pytest.mark.parametrize(
    "query", [{}, {"domains": ["light", "switch"]}, {"tags": ["lighting.ambient"]}]
)
def test_malformed_inherited_profile_does_not_hide_healthy_rows(query):
    bad_domain = document(semantic_routing="legacy")
    entity = document(semantic_tags=["lighting.ambient"])
    store = ProfileStore(
        MemoryBackend(
            {
                "__domain__:light": bad_domain,
                "light.bad": entity,
                "switch.good": entity,
            }
        )
    )
    response = asyncio.run(MesaToolHandlers(store).mesa_query_profiles(query))
    assert [row["entity_id"] for row in response.get("results", [])] == ["switch.good"], response
    assert response.get("warnings")


def test_bad_sidecar_encoding_uses_documented_validation_error(tmp_path):
    (tmp_path / "mesa_profile.json").write_bytes(b"\xff")
    with pytest.raises(MesaValidationError):
        import_from_integration(tmp_path)


@pytest.mark.parametrize("scope", ["entity", "domain", "integration", "area", "device"])
@pytest.mark.parametrize("invalid", ["routing", "origin"])
def test_invalid_automation_policy_denies_all_requested_entities(scope, invalid):
    from mesa_core.inheritance import InheritanceResolver

    bad = document(cooperative_priority={"level": "critical"})
    bad["semantic_profile"]["semantic_routing" if invalid == "routing" else "metadata_origin"] = (
        "legacy" if invalid == "routing" else {}
    )
    key = (
        "automation.fire"
        if scope == "entity"
        else f"__{scope}__:" + ("automation" if scope == "domain" else "test")
    )
    data = {"automation.fire": document()}
    data[key] = bad
    store = ProfileStore(MemoryBackend(data))
    resolver = InheritanceResolver(
        store,
        get_entity_integration=lambda _: "test",
        get_entity_area=lambda _: "test",
        get_entity_device=lambda _: "test",
    )
    manager = LeaseManager(store, resolver=resolver)
    response = manager.request(["switch.vent", "lock.front"], 10, session_id="audit")
    assert not response.granted
    assert response.entities_granted == []
    assert set(response.entities_denied) == {"switch.vent", "lock.front"}
    assert set(response.automation_denials) == {"switch.vent", "lock.front"}
    assert response.warnings
    assert manager.sensor_state()["state"] == "off"


@pytest.mark.parametrize("role_field", ["deny_for", "restricted_for"])
@pytest.mark.parametrize(
    "nested",
    [
        {"level": "normal", "access_roles": {}},
        {
            "level": "normal",
            "access_roles": {"unrestricted_for": ["guest"]},
            "deny_response_mode": "error",
        },
    ],
)
def test_ignored_privacy_copy_cannot_change_retrieval_or_enforcement(role_field, nested):
    from mesa_core import MesaEnforcer

    domain = document(operational_boundaries={"control_mode": "autonomous"})
    domain["privacy_classification"] = {
        "level": "sensitive",
        "access_roles": {role_field: ["guest"]},
    }
    entity = document(privacy_classification=nested)
    entity["privacy_classification"] = {"level": "normal"}
    store = ProfileStore(MemoryBackend({"__domain__:camera": domain, "camera.private": entity}))
    caller = CallerContext("guest1", roles=["guest"], is_authenticated=True)
    effective = store.get_effective("camera.private")
    assert effective.privacy_classification.access_roles == {role_field: ["guest"]}
    response = asyncio.run(
        MesaToolHandlers(store, caller_context_fn=lambda: caller).mesa_get_profile(
            {"entity_id": "camera.private"}
        )
    )
    if role_field == "deny_for":
        assert response["error"] == "not_found"
    else:
        assert response["privacy_classification"]["access_roles"] == {"restricted_for": ["guest"]}
    decision = MesaEnforcer(store).evaluate(
        "camera.private", "camera.turn_on", caller_context=caller
    )
    assert not decision.allowed


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"domains": ["light", "switch"]},
        {"tags": ["lighting.ambient"]},
        {"intents": ["lighting.ambient"]},
    ],
)
@pytest.mark.parametrize("limit", [1, 2])
def test_query_skips_invalid_layers_before_counting_and_paging(query, limit):
    entity = document(semantic_tags=["lighting.ambient"])
    store = ProfileStore(
        MemoryBackend(
            {
                "__domain__:light": document(semantic_routing="bad"),
                "light.bad": entity,
                **{f"switch.good{i}": entity for i in range(3)},
            }
        )
    )
    cursor = None
    found = []
    for _ in range(4):
        result = store.query(**query, limit=limit, cursor=cursor)
        assert result.total_matched == 3
        assert result.warnings
        found.extend(row.entity_id for row in result.rows)
        if not result.has_more:
            assert result.next_cursor is None
            break
        assert len(result.rows) == limit
        assert result.next_cursor != cursor
        cursor = result.next_cursor
    assert found == ["switch.good0", "switch.good1", "switch.good2"]


def test_query_with_only_malformed_effective_profiles_is_empty():
    store = ProfileStore(
        MemoryBackend(
            {"__domain__:light": document(semantic_routing="bad"), "light.bad": document()}
        )
    )
    result = store.query(limit=1)
    assert result.rows == []
    assert result.total_matched == 0
    assert not result.has_more
    assert result.next_cursor is None
    assert result.warnings


def test_sidecar_filesystem_errors_remain_distinguishable(tmp_path, monkeypatch):
    from pathlib import Path

    (tmp_path / "mesa_profile.json").write_text("{}")

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(PermissionError):
        import_from_integration(tmp_path)
