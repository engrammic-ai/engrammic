"""Evidence validation pipeline."""

from __future__ import annotations

import asyncio
import ipaddress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import httpx
import structlog

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

# Private/internal IP ranges that should never be accessed via evidence URIs
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / AWS IMDS
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 private
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


def _is_private_ip(hostname: str) -> bool:
    """Check if hostname resolves to a private/internal IP."""
    import socket

    try:
        # Resolve hostname to IP
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
        for _family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                for network in _BLOCKED_NETWORKS:
                    if ip in network:
                        return True
            except ValueError:
                continue
    except socket.gaierror:
        pass
    return False


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
            node_id = await self._upsert_stub_for_local_ref(ref, silo_id, "file")
            if node_id is None:
                return EvidenceResult(
                    status="invalid",
                    reason="Failed to create stub node for file URI",
                )
            return EvidenceResult(
                status="valid",
                node_id=node_id,
                confidence=0.9,
                reason="File URI accepted (stub created, local validation skipped)",
            )
        elif ref.startswith("urn:"):
            node_id = await self._upsert_stub_for_local_ref(ref, silo_id, "urn")
            if node_id is None:
                return EvidenceResult(
                    status="invalid",
                    reason="Failed to create stub node for URN",
                )
            return EvidenceResult(
                status="valid",
                node_id=node_id,
                confidence=0.85,
                reason="URN accepted (stub created, external validation skipped)",
            )
        else:
            return EvidenceResult(
                status="invalid",
                reason="Invalid evidence format. Must be node:<uuid>, URI, or URN.",
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
        # SSRF protection: block private/internal IPs
        parsed = urlparse(uri)
        hostname = parsed.hostname
        if not hostname:
            return EvidenceResult(
                status="invalid",
                reason="Invalid URI: no hostname",
            )
        if _is_private_ip(hostname):
            logger.warning("evidence_uri_blocked_ssrf", uri=uri, hostname=hostname)
            return EvidenceResult(
                status="invalid",
                reason="URI points to internal/private network (blocked for security)",
            )

        delays = [0.5, 1.0, 2.0]
        last_error: str = ""
        for attempt, delay in enumerate([0.0, *delays]):
            if delay:
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                    # Disable redirects to prevent SSRF via redirect chain
                    response = await client.head(uri, follow_redirects=False)
                    # If redirect, validate the target before following
                    if response.is_redirect:
                        location = response.headers.get("location", "")
                        if location:
                            redirect_parsed = urlparse(location)
                            redirect_host = redirect_parsed.hostname
                            if redirect_host and _is_private_ip(redirect_host):
                                logger.warning(
                                    "evidence_uri_redirect_blocked_ssrf",
                                    uri=uri,
                                    redirect=location,
                                )
                                return EvidenceResult(
                                    status="invalid",
                                    reason="URI redirects to internal/private network (blocked)",
                                )
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

    async def _upsert_stub_for_local_ref(self, uri: str, silo_id: str, ref_type: str) -> str | None:
        """Create or find a stub Document node for a local/external reference.

        silo_id is included in the hash so two silos citing the same URI get
        distinct nodes (MERGE key is (id, silo_id), so without this the UUID
        would collide across silos and the ON CREATE branch would never fire
        for the second silo).
        """
        from uuid import NAMESPACE_URL, uuid5

        doc_id = str(uuid5(NAMESPACE_URL, f"{silo_id}:{uri}"))
        query = """
        MERGE (d:Node:Document {id: $doc_id, silo_id: $silo_id})
        ON CREATE SET
            d.uri = $uri,
            d.stub = true,
            d.ref_type = $ref_type,
            d.created_at = datetime()
        RETURN d.id AS id
        """
        try:
            await self._store.execute_query(
                query,
                {"doc_id": doc_id, "silo_id": silo_id, "uri": uri, "ref_type": ref_type},
            )
        except Exception:
            logger.exception("evidence_stub_upsert_failed", uri=uri, silo_id=silo_id)
            return None
        return doc_id

    async def _upsert_document_for_uri(self, uri: str, silo_id: str) -> str:
        """Find or create a Document node for the given URI."""
        from uuid import NAMESPACE_URL, uuid5

        # Deterministic ID from URI
        doc_id = str(uuid5(NAMESPACE_URL, uri))

        query = """
        MERGE (d:Node:Document {id: $doc_id, silo_id: $silo_id})
        ON CREATE SET d.uri = $uri, d.created_at = datetime(), d.extracted_at = datetime()
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
