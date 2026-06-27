"""Batch processing helpers for bulk ingestion endpoints."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import structlog

if TYPE_CHECKING:
    from context_service.embeddings.base import EmbeddingService

logger = structlog.get_logger(__name__)

EMBED_CHUNK_SIZE = 64
EMBED_CONCURRENCY = 4
EMBED_TIMEOUT_S = 30.0


@dataclass
class BatchResult:
    created: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)


class _GraphStoreWithDocIds(Protocol):
    async def query_document_ids(
        self, silo_id: str, document_ids: list[str]
    ) -> dict[str, str]: ...


async def batch_embed(
    texts: list[str],
    embedding_service: EmbeddingService,
    *,
    chunk_size: int = EMBED_CHUNK_SIZE,
    concurrency: int = EMBED_CONCURRENCY,
    timeout: float = EMBED_TIMEOUT_S,
) -> list[list[float] | None]:
    """Embed texts in chunks with concurrency control.

    Returns list parallel to input; None for any failed chunk items.
    """
    if not texts:
        return []

    results: list[list[float] | None] = [None] * len(texts)
    semaphore = asyncio.Semaphore(concurrency)

    async def embed_chunk(start: int, chunk: list[str]) -> None:
        async with semaphore:
            try:
                embeddings = await asyncio.wait_for(
                    embedding_service.embed(chunk),
                    timeout=timeout,
                )
                for i, emb in enumerate(embeddings):
                    results[start + i] = emb
            except TimeoutError:
                logger.warning("batch_embed_chunk_timeout", start=start, size=len(chunk))
            except Exception as exc:
                logger.warning("batch_embed_chunk_failed", start=start, error=str(exc))

    tasks = [
        embed_chunk(i, texts[i : i + chunk_size])
        for i in range(0, len(texts), chunk_size)
    ]
    await asyncio.gather(*tasks)
    return results


async def dedup_check(
    document_ids: list[str],
    silo_id: str,
    graph_store: _GraphStoreWithDocIds,
) -> dict[str, str]:
    """Check which document_ids already exist in the graph.

    Returns {document_id: node_id} for documents that already exist.
    Requires graph_store to implement query_document_ids. Added to HyperGraphStore protocol separately.
    """
    if not document_ids:
        return {}
    return await graph_store.query_document_ids(silo_id, document_ids)
