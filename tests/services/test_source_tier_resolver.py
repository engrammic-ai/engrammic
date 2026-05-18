"""Tests for source tier resolution service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.services.source_tier_resolver import (
    SourceRule,
    SourceTier,
    batch_get_node_tiers,
    resolve_source_tier,
)

# Test UUID for node references
TEST_NODE_ID = "00000000-0000-0000-0000-000000000001"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def global_rules() -> list[SourceRule]:
    return [
        SourceRule(pattern="https://*.gov/*", tier="authoritative", silo_id=None, priority=100),
        SourceRule(pattern="https://*.edu/*", tier="validated", silo_id=None, priority=80),
        SourceRule(pattern="https://*.org/*", tier="community", silo_id=None, priority=60),
    ]


@pytest.fixture
def silo_rules() -> list[SourceRule]:
    """Silo-specific rules listed before global rules (as DB returns them)."""
    return [
        SourceRule(
            pattern="https://internal.example.com/*",
            tier="authoritative",
            silo_id="silo-1",
            priority=150,
        ),
        SourceRule(pattern="https://*.gov/*", tier="community", silo_id="silo-1", priority=90),
        SourceRule(pattern="https://*.gov/*", tier="authoritative", silo_id=None, priority=100),
        SourceRule(pattern="https://*.edu/*", tier="validated", silo_id=None, priority=80),
    ]


# ---------------------------------------------------------------------------
# Layer 3: global_rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_rule_match(global_rules):
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=global_rules),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["https://www.fda.gov/docs/123"],
        )
    assert tier == SourceTier.AUTHORITATIVE
    assert layer == "global_rule"


@pytest.mark.asyncio
async def test_global_rule_edu_match(global_rules):
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=global_rules),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["https://mit.edu/papers/topic"],
        )
    assert tier == SourceTier.VALIDATED
    assert layer == "global_rule"


# ---------------------------------------------------------------------------
# Layer 2: silo_rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_silo_rule_overrides_global(silo_rules):
    """Silo rule (community) for *.gov/* should win over global rule (authoritative)
    because silo rules are checked first. The first-match-per-URI behaviour means
    the silo_id-scoped rule for the same pattern is applied.
    """
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=silo_rules),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["https://www.fda.gov/docs/123"],
        )
    # silo-1 overrides *.gov/* to "community"; it appears first in the list
    assert tier == SourceTier.COMMUNITY
    assert layer == "silo_rule"


@pytest.mark.asyncio
async def test_silo_rule_internal_url(silo_rules):
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=silo_rules),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["https://internal.example.com/report"],
        )
    assert tier == SourceTier.AUTHORITATIVE
    assert layer == "silo_rule"


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_higher_priority_rule_wins():
    """When two global rules could match, the highest-priority one applies first."""
    rules = [
        SourceRule(pattern="https://*.gov/*", tier="authoritative", silo_id=None, priority=100),
        SourceRule(pattern="https://www.fda.gov/*", tier="community", silo_id=None, priority=50),
    ]
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=rules),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["https://www.fda.gov/docs/123"],
        )
    # The *.gov/* rule has priority 100 and is listed first, so it wins
    assert tier == SourceTier.AUTHORITATIVE
    assert layer == "global_rule"


# ---------------------------------------------------------------------------
# Highest tier across multiple evidence refs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_highest_tier_across_multiple_refs(global_rules):
    """When multiple refs match different tiers, the highest tier is returned."""
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=global_rules),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=[
                "https://community.org/post/1",  # community
                "https://mit.edu/paper/42",  # validated
                "https://www.fda.gov/doc/9",  # authoritative  <- winner
            ],
        )
    assert tier == SourceTier.AUTHORITATIVE
    assert layer == "global_rule"


@pytest.mark.asyncio
async def test_multiple_refs_no_match_fallback():
    """Multiple refs with no rule matches should fall through to fallback."""
    rules: list[SourceRule] = []
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=rules),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=[
                "https://example.com/a",
                "https://example.com/b",
            ],
        )
    assert tier == SourceTier.UNKNOWN
    assert layer == "fallback"


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fnmatch_glob_matches_subdomain():
    """https://*.gov/* should match any subdomain under .gov."""
    rules = [
        SourceRule(pattern="https://*.gov/*", tier="authoritative", silo_id=None, priority=100),
    ]
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=rules),
    ):
        tier, _ = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["https://www.fda.gov/docs/123"],
        )
    assert tier == SourceTier.AUTHORITATIVE


@pytest.mark.asyncio
async def test_fnmatch_glob_does_not_match_wrong_tld():
    rules = [
        SourceRule(pattern="https://*.gov/*", tier="authoritative", silo_id=None, priority=100),
    ]
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=rules),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["https://www.fda.com/docs/123"],
        )
    assert tier == SourceTier.UNKNOWN
    assert layer == "fallback"


# ---------------------------------------------------------------------------
# Layer 4: agent_hint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_hint_used_when_no_rules_match():
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=[]),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["https://example.com/doc"],
            agent_hint="validated",
        )
    assert tier == SourceTier.VALIDATED
    assert layer == "agent_hint"


@pytest.mark.asyncio
async def test_agent_hint_not_used_when_rule_matches(global_rules):
    """Rule match should win over agent hint."""
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=global_rules),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["https://www.fda.gov/doc"],
            agent_hint="community",
        )
    assert tier == SourceTier.AUTHORITATIVE
    assert layer == "global_rule"


# ---------------------------------------------------------------------------
# Layer 4: invalid agent hint falls through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_agent_hint_falls_to_fallback():
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=[]),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["https://example.com/doc"],
            agent_hint="nonsense_tier",
        )
    assert tier == SourceTier.UNKNOWN
    assert layer == "fallback"


# ---------------------------------------------------------------------------
# Layer 5: fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_evidence_refs_returns_unknown():
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=[]),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=[],
        )
    assert tier == SourceTier.UNKNOWN
    assert layer == "fallback"


@pytest.mark.asyncio
async def test_no_matching_rules_no_hint_returns_fallback():
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=[]),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["https://unknown-site.io/page"],
        )
    assert tier == SourceTier.UNKNOWN
    assert layer == "fallback"


# ---------------------------------------------------------------------------
# node: refs are skipped for rule matching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_refs_skipped_for_rule_matching():
    """node: refs should be ignored by rule matching (handled by batch_get_node_tiers).
    When batch_get_node_tiers returns empty (Phase 1), node refs produce no tier.
    """
    rules = [
        SourceRule(pattern="node:*", tier="authoritative", silo_id=None, priority=100),
    ]
    with (
        patch(
            "context_service.services.source_tier_resolver.get_source_rules",
            new=AsyncMock(return_value=rules),
        ),
        patch(
            "context_service.services.source_tier_resolver.batch_get_node_tiers",
            new=AsyncMock(return_value={}),
        ),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=[f"node:{TEST_NODE_ID}"],
        )
    assert tier == SourceTier.UNKNOWN
    assert layer == "fallback"


@pytest.mark.asyncio
async def test_invalid_node_id_skipped():
    """Invalid (non-UUID) node IDs are skipped without calling batch_get_node_tiers."""
    with (
        patch(
            "context_service.services.source_tier_resolver.get_source_rules",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "context_service.services.source_tier_resolver.batch_get_node_tiers",
            new=AsyncMock(return_value={}),
        ) as mock_batch,
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["node:not-a-uuid"],
        )
    assert tier == SourceTier.UNKNOWN
    assert layer == "fallback"
    # batch_get_node_tiers should not be called with invalid IDs
    mock_batch.assert_not_called()


@pytest.mark.asyncio
async def test_node_ref_with_tier_from_batch_lookup():
    """When batch_get_node_tiers returns a tier for a node, it should be used."""
    with (
        patch(
            "context_service.services.source_tier_resolver.get_source_rules",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "context_service.services.source_tier_resolver.batch_get_node_tiers",
            new=AsyncMock(return_value={TEST_NODE_ID: "validated"}),
        ),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=[f"node:{TEST_NODE_ID}"],
        )
    assert tier == SourceTier.VALIDATED
    assert layer == "evidence_node"


# ---------------------------------------------------------------------------
# Invalid rule tier values (rule.tier is not a valid SourceTier)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_rule_tier_is_skipped():
    """A rule with an unrecognised tier string should be skipped without crashing."""
    rules = [
        SourceRule(pattern="https://*.gov/*", tier="bogus_tier", silo_id=None, priority=100),
    ]
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=rules),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["https://www.fda.gov/docs/123"],
        )
    assert tier == SourceTier.UNKNOWN
    assert layer == "fallback"


# ---------------------------------------------------------------------------
# batch_get_node_tiers: direct unit tests (T8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_get_node_tiers_empty_list_returns_empty():
    """Empty node_ids should return {} without touching the store."""
    result = await batch_get_node_tiers([])
    assert result == {}


@pytest.mark.asyncio
async def test_batch_get_node_tiers_with_memgraph_store():
    """batch_get_node_tiers passes node_ids and silo_id to Memgraph and maps results."""
    mock_memgraph = MagicMock()
    mock_memgraph.execute_query = AsyncMock(
        return_value=[
            {"id": "node-a", "source_tier": "authoritative"},
            {"id": "node-b", "source_tier": None},
        ]
    )

    result = await batch_get_node_tiers(
        ["node-a", "node-b"],
        silo_id="silo-1",
        memgraph=mock_memgraph,
    )

    assert result == {"node-a": "authoritative", "node-b": None}
    mock_memgraph.execute_query.assert_awaited_once()
    call_params = mock_memgraph.execute_query.call_args[0][1]
    assert call_params["node_ids"] == ["node-a", "node-b"]
    assert call_params["silo_id"] == "silo-1"


@pytest.mark.asyncio
async def test_batch_get_node_tiers_no_silo_passes_none():
    """When silo_id is omitted, None is forwarded so all silos are matched."""
    mock_memgraph = MagicMock()
    mock_memgraph.execute_query = AsyncMock(
        return_value=[{"id": "node-x", "source_tier": "validated"}]
    )

    result = await batch_get_node_tiers(["node-x"], memgraph=mock_memgraph)

    assert result == {"node-x": "validated"}
    call_params = mock_memgraph.execute_query.call_args[0][1]
    assert call_params["silo_id"] is None


@pytest.mark.asyncio
async def test_resolve_source_tier_passes_silo_id_to_node_lookup():
    """resolve_source_tier forwards silo_id to batch_get_node_tiers."""
    captured: dict = {}

    async def fake_batch_get_node_tiers(
        node_ids: list[str],
        silo_id: str | None = None,
        memgraph=None,
    ) -> dict[str, str | None]:
        captured["node_ids"] = node_ids
        captured["silo_id"] = silo_id
        return {TEST_NODE_ID: "authoritative"}

    with (
        patch(
            "context_service.services.source_tier_resolver.batch_get_node_tiers",
            new=fake_batch_get_node_tiers,
        ),
        patch(
            "context_service.services.source_tier_resolver.get_source_rules",
            new=AsyncMock(return_value=[]),
        ),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-99",
            evidence_refs=[f"node:{TEST_NODE_ID}"],
        )

    assert tier == SourceTier.AUTHORITATIVE
    assert layer == "evidence_node"
    assert captured["silo_id"] == "silo-99"
    assert captured["node_ids"] == [TEST_NODE_ID]


# ---------------------------------------------------------------------------
# Mixed node: and URL refs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_refs_highest_tier_wins(global_rules):
    """node: refs and URL refs can be mixed; highest tier across all wins."""
    with (
        patch(
            "context_service.services.source_tier_resolver.get_source_rules",
            new=AsyncMock(return_value=global_rules),
        ),
        patch(
            "context_service.services.source_tier_resolver.batch_get_node_tiers",
            new=AsyncMock(return_value={"node-xyz": "community"}),
        ),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=[
                "node:node-xyz",  # community from node
                "https://mit.edu/paper/42",  # validated from global rule
            ],
        )
    assert tier == SourceTier.VALIDATED
    assert layer == "global_rule"
