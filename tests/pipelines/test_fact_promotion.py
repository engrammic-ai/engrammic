# tests/pipelines/test_fact_promotion.py
from context_service.pipelines.assets.fact_promotion import (
    _BATCH_COUNT_EVIDENCE,
    _BATCH_FETCH_CORROBORATIONS,
    _BATCH_SIZE,
    _SCAN_UNPROMOTED_CLAIMS,
)


def test_batch_size():
    assert _BATCH_SIZE == 500


def test_scan_unpromoted_claims_cypher():
    assert "MATCH (c:Claim)" in _SCAN_UNPROMOTED_CLAIMS
    assert "NOT c:Fact" in _SCAN_UNPROMOTED_CLAIMS
    assert "silo_id = $silo_id" in _SCAN_UNPROMOTED_CLAIMS
    assert "LIMIT $batch_size" in _SCAN_UNPROMOTED_CLAIMS


def test_batch_count_evidence_cypher():
    assert "UNWIND $claim_ids AS cid" in _BATCH_COUNT_EVIDENCE
    assert "REFERENCES|DERIVED_FROM" in _BATCH_COUNT_EVIDENCE
    assert "count(*) AS cnt" in _BATCH_COUNT_EVIDENCE


def test_batch_fetch_corroborations_cypher():
    assert "UNWIND $claim_ids AS cid" in _BATCH_FETCH_CORROBORATIONS
    assert "REFERENCES|DERIVED_FROM" in _BATCH_FETCH_CORROBORATIONS
    assert "other.id <> cid" in _BATCH_FETCH_CORROBORATIONS
    assert "DISTINCT" in _BATCH_FETCH_CORROBORATIONS
