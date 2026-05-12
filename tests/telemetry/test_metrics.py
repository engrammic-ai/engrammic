"""Tests for telemetry metrics recording functions."""

from __future__ import annotations


def test_record_chain_lookup_exists() -> None:
    """record_chain_lookup function exists and is callable."""
    from context_service.telemetry.metrics import record_chain_lookup

    # Should not raise
    record_chain_lookup(
        hit=True,
        layer_reached=3,
        similarity_score=0.92,
        cold_start=False,
        latency_ms=85.0,
    )


def test_record_chain_feedback_exists() -> None:
    """record_chain_feedback function exists and is callable."""
    from context_service.telemetry.metrics import record_chain_feedback

    # Should not raise
    record_chain_feedback(signal="useful")


def test_record_chain_evidence_modified_exists() -> None:
    """record_chain_evidence_modified function exists and is callable."""
    from context_service.telemetry.metrics import record_chain_evidence_modified

    # Should not raise
    record_chain_evidence_modified()
