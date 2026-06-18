# tests/pipelines/test_custodian_finalize.py
from context_service.pipelines.assets.custodian_finalize import (
    _BATCH_SIZE,
    _SCAN_PROMOTABLE_COMMITMENTS,
)


def test_batch_size():
    assert _BATCH_SIZE == 100


def test_scan_promotable_commitments_cypher():
    assert "MATCH (c:Claim:Commitment" in _SCAN_PROMOTABLE_COMMITMENTS
    assert "silo_id: $silo_id" in _SCAN_PROMOTABLE_COMMITMENTS
    assert "OPTIONAL MATCH (c)-[:PROMOTED_TO]->(f:Finding)" in _SCAN_PROMOTABLE_COMMITMENTS
    assert "f IS NULL" in _SCAN_PROMOTABLE_COMMITMENTS
    assert "LIMIT $batch_size" in _SCAN_PROMOTABLE_COMMITMENTS


def test_custodian_finalize_asset_exists():
    from context_service.pipelines.assets.custodian_finalize import custodian_finalize

    assert custodian_finalize is not None


def test_custodian_finalize_asset_name():
    from context_service.pipelines.assets.custodian_finalize import custodian_finalize

    keys = list(custodian_finalize.keys)
    assert len(keys) == 1
    assert keys[0].path[-1] == "custodian_finalize"


def test_custodian_finalize_has_dependency_keys():
    from context_service.pipelines.assets.custodian_finalize import custodian_finalize

    dep_keys = list(custodian_finalize.dependency_keys)
    dep_names = [k.path[-1] for k in dep_keys]
    assert "claim_to_fact_promotion" in dep_names
