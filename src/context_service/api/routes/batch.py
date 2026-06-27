"""Batch ingestion endpoints for bulk imports and benchmarks."""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from context_service.api.routes._auth import (
    check_sage_bypass,
    get_authenticated_silo,
    require_admin_override,
)
from context_service.mcp.server import get_context_service, get_redis
from context_service.sage.transactions import store_claim, store_memory
from context_service.services.batch_processor import (
    batch_embed,
    dedup_check,
)
from context_service.services.supersession import (
    BatchLearnItem,
    detect_supersession,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/batch", tags=["batch"])

GRAPH_WRITE_CHUNK_SIZE = 100
MAX_ITEMS_PER_REQUEST = 10_000
BATCH_LOCK_TTL = 300  # 5 min max lock duration


@asynccontextmanager
async def batch_silo_lock(silo_id: str) -> AsyncIterator[None]:
    """Acquire per-silo lock to serialize batch writes.

    Prevents Memgraph transaction conflicts from concurrent supersession detection.
    """
    redis = get_redis()
    if redis is None:
        yield  # No Redis, skip locking
        return

    lock_key = f"batch:lock:{silo_id}"
    lock_value = str(uuid.uuid4())

    # Try to acquire lock with exponential backoff
    for attempt in range(10):
        acquired = await redis._redis.set(
            lock_key, lock_value, nx=True, ex=BATCH_LOCK_TTL
        )
        if acquired:
            try:
                yield
            finally:
                # Release lock only if we still own it
                current = await redis._redis.get(lock_key)
                if current and current.decode() == lock_value:
                    await redis._redis.delete(lock_key)
            return

        # Wait with exponential backoff
        wait = min(0.5 * (2 ** attempt), 10)  # Max 10 sec wait
        logger.debug("batch_lock_wait", silo_id=silo_id, attempt=attempt, wait=wait)
        await asyncio.sleep(wait)

    raise HTTPException(503, "Batch lock unavailable - concurrent batch in progress")


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


class BatchLearnItemModel(BaseModel):
    content: str
    evidence: list[str] = Field(default_factory=list)
    user_id: str | None = None
    timestamp: str | None = None
    document_id: str | None = None
    confidence: float = 0.8
    tags: list[str] = Field(default_factory=list)
    source_tier: str | None = None
    subject: str | None = None
    predicate: str | None = None
    object_value: str | None = Field(None, alias="object")
    supersedes: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class BatchLearnOptions(BaseModel):
    skip_evidence_validation: bool = False
    conflict_mode: Literal["skip", "supersede", "error"] = "skip"


class BatchLearnRequest(BaseModel):
    items: list[BatchLearnItemModel] = Field(max_length=MAX_ITEMS_PER_REQUEST)
    options: BatchLearnOptions = Field(default_factory=BatchLearnOptions)


class BatchLearnResponse(BaseModel):
    request_id: str
    created: int
    skipped: int
    failed: int
    results: list[BatchResultItem]
    elapsed_ms: float
    sage_deferred: bool


@router.post("/learn", response_model=BatchLearnResponse)
async def batch_learn(
    request: Request,
    body: BatchLearnRequest,
    auth_context: tuple[str, str | None] = Depends(get_authenticated_silo),
    sage_bypass: bool = Depends(check_sage_bypass),
) -> BatchLearnResponse:
    """Batch store claims to Knowledge layer with supersession detection."""
    start = time.perf_counter()
    request_id = str(uuid.uuid4())
    silo_id, _ = auth_context

    if body.options.skip_evidence_validation:
        await require_admin_override(request.headers.get("X-Admin-Override"))

    # Serialize batch writes per silo to prevent Memgraph transaction conflicts
    async with batch_silo_lock(silo_id):
        return await _batch_learn_impl(
            body, silo_id, request_id, sage_bypass, start
        )


async def _batch_learn_impl(
    body: BatchLearnRequest,
    silo_id: str,
    request_id: str,
    sage_bypass: bool,
    start: float,
) -> BatchLearnResponse:
    """Inner implementation of batch_learn, called under silo lock."""
    try:
        ctx = get_context_service()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Context service not available") from exc

    graph_store = ctx.graph_store
    embedding_service = ctx.embedding_client
    agent_id = "batch-api"

    results: list[BatchResultItem] = []
    created = skipped = failed = 0

    # Convert to internal items
    items = [
        BatchLearnItem(
            content=it.content,
            evidence=it.evidence,
            user_id=it.user_id,
            timestamp=it.timestamp,
            document_id=it.document_id,
            confidence=it.confidence,
            tags=it.tags,
            source_tier=it.source_tier,
            subject=it.subject,
            predicate=it.predicate,
            object=it.object_value,
            supersedes=it.supersedes,
            metadata=it.metadata,
            array_index=i,
        )
        for i, it in enumerate(body.items)
    ]

    # 1. Dedup check
    doc_ids = [it.document_id for it in items if it.document_id]
    existing = await dedup_check(doc_ids, silo_id, graph_store) if doc_ids else {}

    for item in items:
        if item.document_id and item.document_id in existing:
            if body.options.conflict_mode == "error":
                item.error = f"Duplicate document_id: {item.document_id}"
            else:
                item.skip = True

    # 2. Supersession detection (full request scope)
    try:
        await detect_supersession(
            [it for it in items if not it.skip and not it.error],
            silo_id,
            body.options.conflict_mode,
            graph_store,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    # 3. Batch embed
    items_to_embed = [it for it in items if not it.skip and not it.error]
    texts = [it.content for it in items_to_embed]
    if embedding_service is not None and texts:
        embeddings: list[list[float] | None] = await batch_embed(texts, embedding_service)
    else:
        embeddings = [None] * len(texts)
    emb_map = {it.array_index: emb for it, emb in zip(items_to_embed, embeddings, strict=True)}

    # 4. Process in chunks
    items_to_write = [it for it in items if not it.skip and not it.error]

    # Track node_ids created this batch for intra-batch supersession
    created_nodes: dict[int, str] = {}  # array_index -> node_id
    created_by_doc_id: dict[str, str] = {}  # document_id -> node_id

    for chunk_start in range(0, len(items_to_write), GRAPH_WRITE_CHUNK_SIZE):
        chunk = items_to_write[chunk_start : chunk_start + GRAPH_WRITE_CHUNK_SIZE]
        chunk_failed = 0

        for item in chunk:
            embedding = emb_map.get(item.array_index)

            # Resolve intra-batch supersession
            supersedes = item.supersedes
            if not supersedes and item._supersedes_array_index is not None:
                supersedes = created_nodes.get(item._supersedes_array_index)
            if not supersedes and item.supersedes_document_id:
                supersedes = created_by_doc_id.get(item.supersedes_document_id)

            try:
                meta: dict[str, object] = {**item.metadata}
                if item.user_id:
                    meta["user_id"] = item.user_id
                if item.timestamp:
                    meta["timestamp"] = item.timestamp

                result, _ = await store_claim(
                    graph_store,
                    item.content,
                    item.evidence,
                    silo_id,
                    agent_id,
                    subject=item.subject,
                    predicate=item.predicate,
                    object_value=item.object,
                    source_tier=item.source_tier,
                    confidence=item.confidence,
                    supersedes=supersedes,
                    metadata=meta,
                    tags=item.tags or None,
                    embedding=embedding,
                    skip_sage_triggers=sage_bypass,
                    document_id=item.document_id,
                )
                created_nodes[item.array_index] = str(result.node_id)
                if item.document_id:
                    created_by_doc_id[item.document_id] = str(result.node_id)
                results.append(
                    BatchResultItem(
                        node_id=str(result.node_id),
                        document_id=item.document_id,
                        status="created",
                        index=item.array_index,
                    )
                )
                created += 1
            except Exception as exc:
                logger.warning(
                    "batch_learn_item_failed", index=item.array_index, error=str(exc)
                )
                results.append(
                    BatchResultItem(
                        error=str(exc),
                        index=item.array_index,
                        document_id=item.document_id,
                    )
                )
                failed += 1
                chunk_failed += 1

        if chunk_failed > len(chunk) // 2:
            logger.error(
                "batch_learn_chunk_abort",
                chunk_start=chunk_start,
                failed=chunk_failed,
            )
            for remaining_idx in range(chunk_start + len(chunk), len(items_to_write)):
                rem_item = items_to_write[remaining_idx]
                results.append(
                    BatchResultItem(
                        error="Aborted due to prior failures",
                        index=rem_item.array_index,
                        document_id=rem_item.document_id,
                    )
                )
                failed += 1
            break

    # Add skipped/errored items to results
    for item in items:
        if item.skip:
            results.append(
                BatchResultItem(
                    node_id=existing.get(item.document_id) if item.document_id else None,
                    document_id=item.document_id,
                    status="skipped",
                    index=item.array_index,
                )
            )
            skipped += 1
        elif item.error:
            results.append(
                BatchResultItem(
                    error=item.error,
                    index=item.array_index,
                    document_id=item.document_id,
                )
            )
            failed += 1

    logger.info(
        "batch_learn_complete",
        request_id=request_id,
        silo_id=silo_id,
        created=created,
        skipped=skipped,
        failed=failed,
    )

    return BatchLearnResponse(
        request_id=request_id,
        created=created,
        skipped=skipped,
        failed=failed,
        results=results,
        elapsed_ms=(time.perf_counter() - start) * 1000,
        sage_deferred=sage_bypass,
    )
