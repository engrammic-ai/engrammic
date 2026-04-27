"""Tests for MCP tool models."""

from context_service.models.mcp import (
    DecayClass,
    EvidenceRef,
    ObservationType,
    SourceType,
    SPOClaim,
)


def test_spo_claim_valid():
    claim = SPOClaim(subject="OAuth", predicate="expires_in", object="30 days")
    assert claim.subject == "OAuth"
    assert claim.qualifiers is None


def test_spo_claim_with_qualifiers():
    claim = SPOClaim(
        subject="OAuth",
        predicate="expires_in",
        object="30 days",
        qualifiers={"as_of": "2026-04-01"},
    )
    assert claim.qualifiers["as_of"] == "2026-04-01"


def test_evidence_ref_node():
    ref = EvidenceRef(ref="node:abc-123")
    assert ref.is_node_ref
    assert ref.node_id == "abc-123"


def test_evidence_ref_uri():
    ref = EvidenceRef(ref="https://docs.example.com")
    assert ref.is_uri
    assert not ref.is_node_ref


def test_decay_class_values():
    assert DecayClass.EPHEMERAL == "ephemeral"
    assert DecayClass.STANDARD == "standard"
    assert DecayClass.DURABLE == "durable"
    assert DecayClass.PERMANENT == "permanent"


def test_source_type_values():
    assert SourceType.DOCUMENT == "document"
    assert SourceType.USER == "user"
    assert SourceType.EXTERNAL == "external"
    assert SourceType.AGENT == "agent"


def test_observation_type_values():
    assert ObservationType.BELIEF_CHANGE == "belief_change"
    assert ObservationType.CONTRADICTION == "contradiction"
