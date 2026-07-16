"""Shared fixtures for the MCP adapter integration tests.

The two lineages (`fastmcp` and `mcp.server.fastmcp`) are driven by separate
test modules because their client APIs differ, but they register the same tools
over the same store, so the store seed and the tool set live here once.
"""

from __future__ import annotations

from mesa_core.backends import MemoryBackend
from mesa_core.profile import SemanticProfile
from mesa_core.store import ProfileStore

CORE_TOOLS = {
    "mesa_query_profiles",
    "mesa_get_profile",
    "mesa_explain_profile",
    "mesa_get_caller_context",
}


def seeded_store() -> ProfileStore:
    """A store with one user light and one inferred light.

    The inferred entity is excluded from a default query (``include_inferred`` is
    false), so ``light.ai`` lets a lineage assert that a string ``"false"`` is
    not coerced into an opt-in without disturbing the documented-payload tests.
    """
    store = ProfileStore(backend=MemoryBackend())
    store.set(
        "light.kitchen",
        SemanticProfile.from_dict(
            "light.kitchen",
            {
                "semantic_profile": {
                    "semantic_tags": ["lighting.ambient"],
                    "metadata_origin": {"source": "user"},
                    "operational_boundaries": {"control_mode": "autonomous"},
                }
            },
        ),
    )
    store.set(
        "light.ai",
        SemanticProfile.from_dict(
            "light.ai",
            {
                "semantic_profile": {
                    "semantic_tags": ["lighting.ambient"],
                    "metadata_origin": {
                        "source": "inferred_ai",
                        "confidence": 0.9,
                        "generated_at": "2026-01-01T00:00:00",
                    },
                }
            },
        ),
    )
    return store
