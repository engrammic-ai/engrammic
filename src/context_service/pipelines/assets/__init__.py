"""Dagster assets for context-service."""

from typing import Any

from context_service.pipelines.assets.fact_promotion import claim_to_fact_promotion

all_assets: list[Any] = [claim_to_fact_promotion]
