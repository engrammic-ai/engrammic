"""Dagster assets for context-service."""

from typing import Any

from context_service.pipelines.assets.auto_tagging import auto_tagging
from context_service.pipelines.assets.belief_merge import belief_merge_asset
from context_service.pipelines.assets.belief_synthesis import belief_synthesis_asset
from context_service.pipelines.assets.cascade_review import cascade_review_asset
from context_service.pipelines.assets.causal import causal_transitivity
from context_service.pipelines.assets.causal_tombstone import causal_tombstone
from context_service.pipelines.assets.chain_feedback import chain_usefulness_signals
from context_service.pipelines.assets.chain_stitch import chain_stitch
from context_service.pipelines.assets.clustering import clustering
from context_service.pipelines.assets.compaction import reasoning_compaction
from context_service.pipelines.assets.custodian_finalize import custodian_finalize
from context_service.pipelines.assets.custodian_visit import custodian_visit
from context_service.pipelines.assets.edge_heat import edge_heat_asset
from context_service.pipelines.assets.embedding import embedding_asset as embedding
from context_service.pipelines.assets.extraction import extraction
from context_service.pipelines.assets.fact_promotion import claim_to_fact_promotion
from context_service.pipelines.assets.heat import heat_asset
from context_service.pipelines.assets.heat_diffusion import heat_diffusion_asset
from context_service.pipelines.assets.llm_pattern_detection import llm_pattern_detection
from context_service.pipelines.assets.pattern_detection import pattern_detection
from context_service.pipelines.assets.proposal_cleanup import proposal_cleanup
from context_service.pipelines.assets.proposal_detection import proposal_detection
from context_service.pipelines.assets.reconciliation_gc import reconciliation_gc
from context_service.pipelines.assets.retention import retention_sweep
from context_service.pipelines.assets.step_embedding import (
    session_step_embedding,
    step_embedding_backfill,
)
from context_service.pipelines.assets.tag_maintenance import tag_maintenance
from context_service.pipelines.assets.weak_link_creation import (
    create_weak_links_for_node as create_weak_links_for_node,
)
from context_service.pipelines.assets.prewarm_sweep import prewarm_sweep_asset
from context_service.pipelines.assets.weak_link_review import weak_link_review_asset

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
    heat_diffusion_asset,
    edge_heat_asset,
    reasoning_compaction,
    belief_synthesis_asset,
    retention_sweep,
    pattern_detection,
    llm_pattern_detection,
    chain_stitch,
    belief_merge_asset,
    cascade_review_asset,
    weak_link_review_asset,
    auto_tagging,
    tag_maintenance,
    reconciliation_gc,
    proposal_detection,
    proposal_cleanup,
    chain_usefulness_signals,
    step_embedding_backfill,
    session_step_embedding,
    prewarm_sweep_asset,
]
