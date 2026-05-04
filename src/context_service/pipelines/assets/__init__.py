"""Dagster assets for context-service."""

from typing import Any

from context_service.pipelines.assets.belief_synthesis import belief_synthesis_asset
from context_service.pipelines.assets.causal import causal_transitivity
from context_service.pipelines.assets.causal_tombstone import causal_tombstone
from context_service.pipelines.assets.chain_stitch import chain_stitch
from context_service.pipelines.assets.clustering import clustering
from context_service.pipelines.assets.compaction import reasoning_compaction
from context_service.pipelines.assets.custodian_finalize import custodian_finalize
from context_service.pipelines.assets.custodian_visit import custodian_visit
from context_service.pipelines.assets.embedding import embedding_asset as embedding
from context_service.pipelines.assets.extraction import extraction
from context_service.pipelines.assets.fact_promotion import claim_to_fact_promotion
from context_service.pipelines.assets.heat import heat_asset
from context_service.pipelines.assets.llm_pattern_detection import llm_pattern_detection
from context_service.pipelines.assets.pattern_detection import pattern_detection
from context_service.pipelines.assets.retention import retention_sweep

all_assets: list[Any] = [
    extraction,
    embedding,
    custodian_visit,
    custodian_finalize,
    claim_to_fact_promotion,
    causal_transitivity,
    causal_tombstone,
    clustering,
    heat_asset,
    reasoning_compaction,
    belief_synthesis_asset,
    retention_sweep,
    pattern_detection,
    llm_pattern_detection,
    chain_stitch,
]
