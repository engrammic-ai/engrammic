"""Batch embedding accumulator for the reactions system.

Collects (node_id, silo_id) tuples and flushes them as a single batch
when either 50 items accumulate or 100ms elapses — whichever comes first.

On flush the accumulator:
1. Fetches node content from the graph store (skips missing or content-free nodes).
2. Calls the embedding service with all texts in a single batch call.
3. Fan-outs Qdrant upserts concurrently via asyncio.gather.

The accumulator is fire-and-forget: ``add()`` enqueues the item and returns
immediately; callers never await the flush.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

# Flush when this many items have been collected.
# NOTE: Vertex AI text-embedding-005 has 20K token limit. With large documents
# (e.g. a11y trees), 4 items at ~4K tokens each stays safely under the limit.
# TODO: Make this configurable or compute dynamically based on content size.
_BATCH_SIZE = 4

# Maximum milliseconds to wait before flushing a partial batch.
_FLUSH_TIMEOUT_MS = 100


@dataclass(frozen=True, slots=True)
class _PendingItem:
    node_id: str
    silo_id: str


class BatchEmbeddingAccumulator:
    """Accumulates (node_id, silo_id) pairs and flushes them in batches.

    Thread-safety: designed for a single asyncio event loop. All state
    mutations happen under ``_lock``.
    """

    def __init__(
        self,
        batch_size: int = _BATCH_SIZE,
        timeout_ms: int = _FLUSH_TIMEOUT_MS,
    ) -> None:
        self._batch_size = batch_size
        self._timeout_s = timeout_ms / 1000

        self._pending: list[_PendingItem] = []
        self._lock = asyncio.Lock()
        self._timer_task: asyncio.Task[None] | None = None

        # Strong references prevent in-flight flush tasks from being GC'd.
        self._active_flushes: set[asyncio.Task[None]] = set()

    async def add(self, node_id: str, silo_id: str) -> None:
        """Enqueue a node for batch embedding. Returns immediately.

        Triggers an immediate flush when the batch reaches ``_batch_size``;
        otherwise schedules a timer flush if one is not already pending.

        Args:
            node_id: String UUID of the node to embed.
            silo_id: Tenant isolation identifier.
        """
        async with self._lock:
            self._pending.append(_PendingItem(node_id=node_id, silo_id=silo_id))

            if len(self._pending) >= self._batch_size:
                # Batch is full: cancel the pending timer and flush now.
                await self._cancel_timer()
                batch = self._take_batch()
                self._schedule_flush(batch)
            elif self._timer_task is None or self._timer_task.done():
                # Start a timer for the partial batch.
                self._timer_task = asyncio.create_task(self._flush_after_timeout())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _take_batch(self) -> list[_PendingItem]:
        """Swap out and return the pending list, leaving an empty one."""
        batch = self._pending
        self._pending = []
        return batch

    async def _cancel_timer(self) -> None:
        """Cancel the pending timer task if it is running. Caller holds lock."""
        if self._timer_task is not None and not self._timer_task.done():
            self._timer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._timer_task
        self._timer_task = None

    async def _flush_after_timeout(self) -> None:
        """Wait for the timeout then flush whatever has accumulated."""
        await asyncio.sleep(self._timeout_s)
        async with self._lock:
            if not self._pending:
                return
            batch = self._take_batch()
            self._timer_task = None
        self._schedule_flush(batch)

    def _schedule_flush(self, batch: list[_PendingItem]) -> None:
        """Create a flush task and hold a strong reference to it."""
        task: asyncio.Task[None] = asyncio.create_task(self._flush(batch))
        self._active_flushes.add(task)
        task.add_done_callback(self._active_flushes.discard)

    async def _flush(self, batch: list[_PendingItem]) -> None:
        """Fetch, embed, and upsert a batch of pending items.

        Items whose node does not exist or has no content are skipped.
        The embedding call uses a single batched request across all silos.
        Qdrant upserts are fanned out concurrently with asyncio.gather.

        Args:
            batch: The snapshot of pending items to process.
        """
        if not batch:
            return

        log = logger.bind(batch_size=len(batch))
        log.info("batch_embedding_flush_start")

        from context_service.embeddings import build_embedding_service
        from context_service.mcp.server import get_context_service

        try:
            ctx_svc = get_context_service()
        except RuntimeError:
            log.error("batch_embedding_services_not_configured")
            return

        store = ctx_svc.graph_store

        # Phase 1: fetch node content, keeping strict index alignment.
        # Items that are missing or empty are filtered out before embedding.
        valid_items: list[_PendingItem] = []
        texts: list[str] = []
        node_types: list[str] = []

        for item in batch:
            try:
                node = await store.get_node(uuid.UUID(item.node_id), item.silo_id)
            except Exception:
                log.exception(
                    "batch_embedding_get_node_error",
                    node_id=item.node_id,
                    silo_id=item.silo_id,
                )
                continue

            if node is None:
                log.warning(
                    "batch_embedding_node_not_found",
                    node_id=item.node_id,
                    silo_id=item.silo_id,
                )
                continue

            if not node.content:
                log.debug(
                    "batch_embedding_no_content_skip",
                    node_id=item.node_id,
                    silo_id=item.silo_id,
                )
                continue

            valid_items.append(item)
            texts.append(node.content)
            node_types.append(node.type)

        if not valid_items:
            log.debug("batch_embedding_nothing_to_embed")
            return

        # Phase 2: batch embed all texts in a single call.
        try:
            embedder = build_embedding_service()
            vectors = await embedder.embed(texts)
        except Exception:
            log.exception("batch_embedding_embed_error", valid_count=len(valid_items))
            return

        if len(vectors) != len(valid_items):
            log.error(
                "batch_embedding_vector_count_mismatch",
                expected=len(valid_items),
                got=len(vectors),
            )
            return

        # Phase 3: fan out Qdrant upserts concurrently.
        qdrant = ctx_svc.vector_store

        async def _upsert(item: _PendingItem, vector: list[float], node_type: str) -> None:
            try:
                await qdrant.upsert(
                    node_id=item.node_id,
                    vector=vector,
                    payload={"type": node_type},
                    silo_id=item.silo_id,
                )
            except Exception:
                log.exception(
                    "batch_embedding_upsert_error",
                    node_id=item.node_id,
                    silo_id=item.silo_id,
                )

        await asyncio.gather(
            *[
                _upsert(item, vector, node_type)
                for item, vector, node_type in zip(valid_items, vectors, node_types, strict=True)
            ]
        )

        log.info(
            "batch_embedding_flush_done",
            embedded=len(valid_items),
            skipped=len(batch) - len(valid_items),
        )

    async def close(self) -> None:
        """Flush any remaining pending items and wait for active flushes to finish."""
        async with self._lock:
            await self._cancel_timer()
            if self._pending:
                batch = self._take_batch()
                self._schedule_flush(batch)

        # Wait for all in-flight tasks.
        if self._active_flushes:
            await asyncio.gather(*list(self._active_flushes), return_exceptions=True)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_accumulator: BatchEmbeddingAccumulator | None = None


def get_batch_embedding_accumulator() -> BatchEmbeddingAccumulator:
    """Return the process-wide singleton BatchEmbeddingAccumulator.

    The instance is created on first call and reused thereafter.
    Callers that need custom batch sizes or timeouts should construct
    ``BatchEmbeddingAccumulator`` directly.

    Returns:
        The singleton accumulator instance.
    """
    global _accumulator
    if _accumulator is None:
        _accumulator = BatchEmbeddingAccumulator()
    return _accumulator
