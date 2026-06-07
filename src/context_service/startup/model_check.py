"""Startup model accessibility checks.

Verifies all configured models can be loaded before accepting traffic.
Fails fast with clear error messages for permission/download issues.
"""

from __future__ import annotations

import asyncio
import os

from context_service.config.logging import get_logger
from context_service.config.settings import get_settings

logger = get_logger(__name__)

# Skip model checks in CI/build environments
SKIP_MODEL_CHECK = os.getenv("SKIP_MODEL_CHECK", "").lower() in ("1", "true", "yes")


class ModelCheckError(Exception):
    """One or more models failed to load."""


async def verify_models(*, timeout: float = 120.0) -> None:
    """Verify all configured models are accessible.

    Attempts to load SPLADE, embedding model, and reranker (if configured).
    Raises ModelCheckError if any model fails to load.

    Args:
        timeout: Maximum seconds to wait for all models to load.

    Raises:
        ModelCheckError: If any model fails to load.
    """
    if SKIP_MODEL_CHECK:
        logger.info("model_check_skipped", reason="SKIP_MODEL_CHECK env var set")
        return

    settings = get_settings()
    errors: list[str] = []

    async def check_splade() -> None:
        if not settings.hybrid_search_enabled:
            logger.info("model_check_skip", model="splade", reason="hybrid search disabled")
            return
        try:
            from context_service.embeddings.splade import SpladeEncoder

            encoder = SpladeEncoder(settings.embedding.splade.model)
            await encoder.encode("startup check")
            logger.info("model_check_ok", model="splade")
        except Exception as e:
            errors.append(f"SPLADE ({settings.embedding.splade.model}): {e}")
            logger.error("model_check_failed", model="splade", error=str(e))

    async def check_embeddings() -> None:
        try:
            from context_service.embeddings import build_embedding_service

            service = build_embedding_service()
            await service.embed(["startup check"])
            logger.info("model_check_ok", model="embeddings")
        except Exception as e:
            errors.append(f"Embeddings: {e}")
            logger.error("model_check_failed", model="embeddings", error=str(e))

    async def check_reranker() -> None:
        if not settings.reranking.enabled:
            logger.info("model_check_skip", model="reranker", reason="reranking disabled")
            return
        try:
            from context_service.config.config_loader import load_config
            from context_service.reranking import LiteLLMReranker

            config = load_config("models")
            tier = config.get("tier", "default")
            tier_config = config.get("tiers", {}).get(tier, {})
            reranker_spec = tier_config.get("reranker")
            if reranker_spec is None:
                logger.info("model_check_skip", model="reranker", reason="no reranker in config")
                return
            reranker = LiteLLMReranker(model=reranker_spec.get("model", "rerank-v3.5"))
            await reranker.rerank("test query", ["test document"], ["test-node"])
            logger.info("model_check_ok", model="reranker")
        except Exception as e:
            errors.append(f"Reranker: {e}")
            logger.error("model_check_failed", model="reranker", error=str(e))

    logger.info("model_check_starting")

    try:
        await asyncio.wait_for(
            asyncio.gather(check_splade(), check_embeddings(), check_reranker()),
            timeout=timeout,
        )
    except TimeoutError:
        raise ModelCheckError(f"Model loading timed out after {timeout}s") from None

    if errors:
        raise ModelCheckError("Model check failed:\n" + "\n".join(f"  - {e}" for e in errors))

    logger.info("model_check_complete")
