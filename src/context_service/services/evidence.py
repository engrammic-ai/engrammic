"""Evidence validation pipeline."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import httpx
import structlog

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


@dataclass
class EvidenceResult:
    """Result of evidence validation."""

    status: Literal["valid", "invalid", "pending"]
    node_id: str | None = None
    confidence: float = 0.0
    reason: str | None = None


class EvidenceValidator:
    """Validates evidence references for context_assert."""

    def __init__(
        self,
        store: HyperGraphStore,
        http_timeout: float = 10.0,
    ) -> None:
        self._store = store
        self._http_timeout = http_timeout

    async def validate(self, ref: str, silo_id: str) -> EvidenceResult:
        """Validate an evidence reference.

        Args:
            ref: Evidence reference (node:<uuid> or URI)
            silo_id: Silo context for node lookups

        Returns:
            EvidenceResult with status and confidence
        """
        if ref.startswith("node:"):
            return await self._validate_node_ref(ref[5:], silo_id)
        elif ref.startswith("http://") or ref.startswith("https://"):
            return await self._validate_uri(ref, silo_id)
        elif ref.startswith("file://"):
            return EvidenceResult(
                status="valid",
                confidence=0.9,
                reason="File URI accepted (local validation skipped)",
            )
        else:
            return EvidenceResult(
                status="invalid",
                reason="Invalid evidence format. Must be node:<uuid> or URI.",
            )

    async def _validate_node_ref(self, node_id: str, silo_id: str) -> EvidenceResult:
        """Check if node exists in silo."""
        query = """
        MATCH (n {id: $node_id, silo_id: $silo_id})
        RETURN n.id AS id
        LIMIT 1
        """
        results = await self._store.execute_query(
            query,
            {"node_id": node_id, "silo_id": silo_id},
        )

        if results:
            return EvidenceResult(
                status="valid",
                node_id=node_id,
                confidence=1.0,
            )
        return EvidenceResult(
            status="invalid",
            reason=f"Node {node_id} not found in silo {silo_id}",
        )

    async def _validate_uri(self, uri: str, silo_id: str) -> EvidenceResult:
        """Check if URI is reachable and upsert a Document node for it."""
        delays = [0.5, 1.0, 2.0]
        last_error: str = ""
        for attempt, delay in enumerate([0.0, *delays]):
            if delay:
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                    response = await client.head(uri, follow_redirects=True)
                if response.status_code < 400:
                    logger.debug("evidence_uri_valid", uri=uri, status=response.status_code)
                    # Upsert Document node for valid URI
                    node_id = await self._upsert_document_for_uri(uri, silo_id)
                    return EvidenceResult(
                        status="valid",
                        node_id=node_id,
                        confidence=0.7,
                        reason=f"URI reachable (status {response.status_code})",
                    )
                # 4xx/5xx — no retry
                return EvidenceResult(
                    status="invalid",
                    reason=f"URI returned status {response.status_code}",
                )
            except httpx.RequestError as e:
                last_error = str(e)
                logger.warning(
                    "evidence_uri_unreachable",
                    uri=uri,
                    attempt=attempt,
                    error=last_error,
                )
        return EvidenceResult(
            status="invalid",
            reason=f"URI unreachable after retries: {last_error}",
        )

    async def _upsert_document_for_uri(self, uri: str, silo_id: str) -> str:
        """Find or create a Document node for the given URI."""
        from uuid import NAMESPACE_URL, uuid5

        # Deterministic ID from URI
        doc_id = str(uuid5(NAMESPACE_URL, uri))

        query = """
        MERGE (d:Node:Document {id: $doc_id, silo_id: $silo_id})
        ON CREATE SET d.uri = $uri, d.created_at = datetime()
        RETURN d.id AS id
        """
        await self._store.execute_query(
            query,
            {"doc_id": doc_id, "silo_id": silo_id, "uri": uri},
        )
        return doc_id

    async def validate_all(self, refs: list[str], silo_id: str) -> list[EvidenceResult]:
        """Validate multiple evidence refs."""
        results = []
        for ref in refs:
            result = await self.validate(ref, silo_id)
            results.append(result)
        return results
