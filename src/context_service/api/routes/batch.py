"""Batch ingestion endpoints for bulk imports and benchmarks."""

from __future__ import annotations

import time
import uuid
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from context_service.api.routes._auth import get_authenticated_silo
from context_service.mcp.server import get_context_service
from context_service.sage.transactions import store_memory
from context_service.services.batch_processor import (
    batch_embed,
    dedup_check,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/batch", tags=["batch"])

GRAPH_WRITE_CHUNK_SIZE = 100
MAX_ITEMS_PER_REQUEST = 10_000


class BatchRememberItem(BaseModel):
    content: str
    user_id: str | None = None
    timestamp: str | None = None
    document_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class BatchRememberOptions(BaseModel):
    conflict_mode: Literal["skip", "error"] = "skip"


class BatchRememberRequest(BaseModel):
    items: list[BatchRememberItem] = Field(max_length=MAX_ITEMS_PER_REQUEST)
    options: BatchRememberOptions = Field(default_factory=BatchRememberOptions)


class BatchResultItem(BaseModel):
    node_id: str | None = None
    document_id: str | None = None
    status: Literal["created", "skipped"] | None = None
    error: str | None = None
    index: int | None = None


class BatchRememberResponse(BaseModel):
    request_id: str
    created: int
    skipped: int
    failed: int
    results: list[BatchResultItem]
    elapsed_ms: float


@router.post("/remember", response_model=BatchRememberResponse)
async def batch_remember(
    body: BatchRememberRequest,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
) -> BatchRememberResponse:
    """Batch store observations to Memory layer."""
    start = time.perf_counter()
    request_id = str(uuid.uuid4())
    silo_id, _ = auth_context
    agent_id = "batch-api"

    try:
        ctx = get_context_service()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Context service not available") from exc

    graph_store = ctx.graph_store
    embedding_service = ctx.embedding_client

    results: list[BatchResultItem] = []
    created = skipped = failed = 0

    # 1. Dedup check
    doc_ids = [it.document_id for it in body.items if it.document_id]
    existing = await dedup_check(doc_ids, silo_id, graph_store) if doc_ids else {}

    items_to_process: list[tuple[int, BatchRememberItem]] = []
    for i, item in enumerate(body.items):
        if item.document_id and item.document_id in existing:
            if body.options.conflict_mode == "error":
                results.append(
                    BatchResultItem(
                        error=f"Duplicate document_id: {item.document_id}",
                        index=i,
                        document_id=item.document_id,
                    )
                )
                failed += 1
            else:
                results.append(
                    BatchResultItem(
                        node_id=existing[item.document_id],
                        document_id=item.document_id,
                        status="skipped",
                        index=i,
                    )
                )
                skipped += 1
        else:
            items_to_process.append((i, item))

    if not items_to_process:
        return BatchRememberResponse(
            request_id=request_id,
            created=created,
            skipped=skipped,
            failed=failed,
            results=results,
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )

    # 2. Batch embed (skipped if no embedding service)
    texts = [item.content for _, item in items_to_process]
    if embedding_service is not None:
        embeddings: list[list[float] | None] = await batch_embed(texts, embedding_service)
    else:
        embeddings = [None] * len(texts)

    # 3. Process in chunks of GRAPH_WRITE_CHUNK_SIZE
    for chunk_start in range(0, len(items_to_process), GRAPH_WRITE_CHUNK_SIZE):
        chunk = items_to_process[chunk_start : chunk_start + GRAPH_WRITE_CHUNK_SIZE]
        chunk_failed = 0

        for j, (orig_idx, item) in enumerate(chunk):
            emb_idx = chunk_start + j
            embedding = embeddings[emb_idx]

            try:
                meta: dict[str, object] = {**item.metadata}
                if item.user_id:
                    meta["user_id"] = item.user_id
                if item.timestamp:
                    meta["timestamp"] = item.timestamp

                result, _ = await store_memory(
                    graph_store,
                    item.content,
                    silo_id,
                    agent_id,
                    tags=item.tags or None,
                    metadata=meta,
                    embedding=embedding,
                    document_id=item.document_id,
                )
                results.append(
                    BatchResultItem(
                        node_id=str(result.node_id),
                        document_id=item.document_id,
                        status="created",
                        index=orig_idx,
                    )
                )
                created += 1
            except Exception as exc:
                logger.warning(
                    "batch_remember_item_failed", index=orig_idx, error=str(exc)
                )
                results.append(
                    BatchResultItem(
                        error=str(exc),
                        index=orig_idx,
                        document_id=item.document_id,
                    )
                )
                failed += 1
                chunk_failed += 1

        # Abort if >50% of chunk failed
        if chunk_failed > len(chunk) // 2:
            logger.error(
                "batch_remember_chunk_abort",
                chunk_start=chunk_start,
                failed=chunk_failed,
            )
            for remaining_idx in range(chunk_start + len(chunk), len(items_to_process)):
                orig_idx, item = items_to_process[remaining_idx]
                results.append(
                    BatchResultItem(
                        error="Aborted due to prior failures",
                        index=orig_idx,
                        document_id=item.document_id,
                    )
                )
                failed += 1
            break

    logger.info(
        "batch_remember_complete",
        request_id=request_id,
        silo_id=silo_id,
        created=created,
        skipped=skipped,
        failed=failed,
    )

    return BatchRememberResponse(
        request_id=request_id,
        created=created,
        skipped=skipped,
        failed=failed,
        results=results,
        elapsed_ms=(time.perf_counter() - start) * 1000,
    )
