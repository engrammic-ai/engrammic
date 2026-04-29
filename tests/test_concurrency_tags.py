"""Tests: each Dagster asset has a dagster/concurrency_key tag and a retry policy."""

import dagster as dg
import pytest

from context_service.pipelines.assets.clustering import clustering
from context_service.pipelines.assets.custodian_finalize import custodian_finalize
from context_service.pipelines.assets.custodian_visit import custodian_visit
from context_service.pipelines.assets.embedding import embedding_asset as embedding
from context_service.pipelines.assets.extraction import extraction
from context_service.pipelines.assets.fact_promotion import claim_to_fact_promotion

_ALL_ASSETS = [
    extraction,
    embedding,
    custodian_visit,
    custodian_finalize,
    claim_to_fact_promotion,
    clustering,
]

_CONCURRENCY_TAG = "dagster/concurrency_key"


def _get_tags(asset: dg.AssetsDefinition) -> dict[str, str]:
    all_tags: dict[str, str] = {}
    for tags in asset.tags_by_key.values():
        all_tags.update(tags)
    return all_tags


@pytest.mark.parametrize("asset", _ALL_ASSETS, ids=lambda a: a.key.to_user_string())
def test_concurrency_key_tag_present(asset: dg.AssetsDefinition) -> None:
    tags = _get_tags(asset)
    assert _CONCURRENCY_TAG in tags, (
        f"{asset.key.to_user_string()} is missing {_CONCURRENCY_TAG!r} tag"
    )


@pytest.mark.parametrize("asset", _ALL_ASSETS, ids=lambda a: a.key.to_user_string())
def test_concurrency_key_tag_nonempty(asset: dg.AssetsDefinition) -> None:
    tags = _get_tags(asset)
    assert tags.get(_CONCURRENCY_TAG), (
        f"{asset.key.to_user_string()} has empty {_CONCURRENCY_TAG!r} tag"
    )


@pytest.mark.parametrize("asset", _ALL_ASSETS, ids=lambda a: a.key.to_user_string())
def test_retry_policy_present(asset: dg.AssetsDefinition) -> None:
    retry = asset.op.retry_policy
    assert retry is not None, (
        f"{asset.key.to_user_string()} has no retry_policy"
    )


@pytest.mark.parametrize("asset", _ALL_ASSETS, ids=lambda a: a.key.to_user_string())
def test_retry_policy_max_retries(asset: dg.AssetsDefinition) -> None:
    retry = asset.op.retry_policy
    assert retry is not None
    assert retry.max_retries == 3
