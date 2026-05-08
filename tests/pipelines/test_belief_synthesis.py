# tests/pipelines/test_belief_synthesis.py
"""Tests for belief_synthesis asset configuration."""


def test_belief_synthesis_asset_exists():
    from context_service.pipelines.assets.belief_synthesis import belief_synthesis_asset

    assert belief_synthesis_asset is not None


def test_belief_synthesis_has_retry_policy():
    from context_service.pipelines.assets.belief_synthesis import belief_synthesis_asset

    spec = belief_synthesis_asset.specs_by_key[list(belief_synthesis_asset.keys)[0]]
    assert (
        spec.metadata.get("dagster/retry_policy") is not None
        or belief_synthesis_asset.op.retry_policy is not None
    )


def test_belief_synthesis_asset_name():
    from context_service.pipelines.assets.belief_synthesis import belief_synthesis_asset

    keys = list(belief_synthesis_asset.keys)
    assert len(keys) == 1
    assert keys[0].path[-1] == "belief_synthesis"
