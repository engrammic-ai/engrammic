"""Dagster assets for context-service."""

from typing import Any

from context_service.pipelines.assets.clustering import clustering
from context_service.pipelines.assets.custodian_finalize import custodian_finalize
from context_service.pipelines.assets.custodian_visit import custodian_visit
from context_service.pipelines.assets.embedding import embedding_asset as embedding
from context_service.pipelines.assets.extraction import extraction
from context_service.pipelines.assets.fact_promotion import claim_to_fact_promotion

all_assets: list[Any] = [
    extraction,
    embedding,
    custodian_visit,
    custodian_finalize,
    claim_to_fact_promotion,
    clustering,
]
