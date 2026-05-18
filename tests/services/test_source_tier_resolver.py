"""Tests for source tier resolution service."""

from unittest.mock import AsyncMock, patch

import pytest

from context_service.services.source_tier_resolver import (
    SourceRule,
    SourceTier,
    resolve_source_tier,
)

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
        SourceRule(pattern="https://internal.example.com/*", tier="authoritative", silo_id="silo-1", priority=150),
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
                "https://community.org/post/1",   # community
                "https://mit.edu/paper/42",        # validated
                "https://www.fda.gov/doc/9",       # authoritative  <- winner
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
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=rules),
    ), patch(
        "context_service.services.source_tier_resolver.batch_get_node_tiers",
        new=AsyncMock(return_value={}),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["node:abc-123"],
        )
    assert tier == SourceTier.UNKNOWN
    assert layer == "fallback"


@pytest.mark.asyncio
async def test_node_ref_with_tier_from_batch_lookup():
    """When batch_get_node_tiers returns a tier for a node, it should be used."""
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=[]),
    ), patch(
        "context_service.services.source_tier_resolver.batch_get_node_tiers",
        new=AsyncMock(return_value={"abc-123": "validated"}),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=["node:abc-123"],
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
# Mixed node: and URL refs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_refs_highest_tier_wins(global_rules):
    """node: refs and URL refs can be mixed; highest tier across all wins."""
    with patch(
        "context_service.services.source_tier_resolver.get_source_rules",
        new=AsyncMock(return_value=global_rules),
    ), patch(
        "context_service.services.source_tier_resolver.batch_get_node_tiers",
        new=AsyncMock(return_value={"node-xyz": "community"}),
    ):
        tier, layer = await resolve_source_tier(
            silo_id="silo-1",
            evidence_refs=[
                "node:node-xyz",                      # community from node
                "https://mit.edu/paper/42",           # validated from global rule
            ],
        )
    assert tier == SourceTier.VALIDATED
    assert layer == "global_rule"
