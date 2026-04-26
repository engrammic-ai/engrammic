from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from context_service.extraction.filter.circuit_breaker import CircuitBreaker
from context_service.extraction.filter.models import FilterDecision, FilterRuleSet, RuleFired

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from context_service.extraction.models import ClaimTriple
    from context_service.stores.redis import RedisClient

log = logging.getLogger(__name__)


def _cache_key(claim: ClaimTriple) -> str:
    canonical = f"{claim.predicate}|{str(claim.subject).lower()}|{str(claim.object).lower()}"
    h = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    return f"wikidata:hit:{h}"


def _build_sparql_ask(claim: ClaimTriple) -> str:
    # Minimum-viable: label-based ASK. Precision is low but FP rate stays near zero
    # because a NO answer falls through — a YES is only produced on an actual match.
    s = str(claim.subject).replace('"', '\\"')
    o = str(claim.object).replace('"', '\\"')
    return f'''
ASK {{
  ?subj ?p ?obj .
  ?subj rdfs:label "{s}"@en .
  ?obj  rdfs:label "{o}"@en .
}}
'''


async def default_sparql_ask(endpoint: str, claim: ClaimTriple, timeout_s: float) -> bool:
    def _run() -> bool:
        # Lazy import: SPARQLWrapper is an optional runtime dep. When missing,
        # WikidataRule's caller catches and degrades to EXTERNAL_FAILURE, so
        # the filter still loads (rules 1, 3, 4 keep working) — only the
        # Wikidata oracle is unavailable.
        from SPARQLWrapper import JSON, SPARQLWrapper

        w = SPARQLWrapper(endpoint)
        w.setReturnFormat(JSON)
        w.setTimeout(int(timeout_s) or 1)
        w.setQuery(_build_sparql_ask(claim))
        data = w.queryAndConvert()
        if not isinstance(data, dict):
            return False
        return bool(data.get("boolean", False))

    return await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout_s)


class WikidataRule:
    """Rule 2 — SPARQL present-check with Redis cache + circuit breaker.

    fail-open: on timeout / CB-open / unparseable, returns an EXTERNAL_FAILURE
    FilterDecision which the orchestrator treats as non-decisive.
    """

    def __init__(
        self,
        rs: FilterRuleSet,
        redis: RedisClient,
        sparql_fn: Callable[[str, ClaimTriple, float], Awaitable[bool]] | None = None,
    ) -> None:
        self._rs = rs
        self._redis = redis
        self._sparql = sparql_fn or default_sparql_ask
        self._cb = CircuitBreaker(
            failure_threshold=rs.wikidata_cb_failure_threshold,
            window_s=rs.wikidata_cb_window_s,
            cooldown_s=rs.wikidata_cb_cooldown_s,
        )
        self._ttl_s = int(rs.wikidata_cache_ttl_days * 86400)

    async def evaluate(self, claim: ClaimTriple) -> FilterDecision | None:
        key = _cache_key(claim)
        try:
            cached = await self._redis.get(key)
            if cached is not None:
                entry = json.loads(cached)
                return self._decision_from_present(entry.get("present", False))
        except Exception as e:  # cache failures are non-fatal
            log.warning("wikidata cache read failed: %s", e)

        if self._cb.is_open():
            return FilterDecision(
                action="keep",
                rule_fired=RuleFired.EXTERNAL_FAILURE,
                reason="wikidata_cb_open",
            )

        try:
            present = await self._sparql(
                self._rs.wikidata_endpoint, claim, self._rs.wikidata_timeout_s
            )
            self._cb.record_success()
            entry = {"present": present, "checked_at": datetime.now(UTC).isoformat()}
            try:
                await self._redis.set(key, json.dumps(entry), ttl_seconds=self._ttl_s)
            except Exception as e:
                log.warning("wikidata cache write failed: %s", e)
            return self._decision_from_present(present)
        except (TimeoutError, Exception) as e:
            self._cb.record_failure()
            log.info("wikidata sparql failed: %s", e)
            return FilterDecision(
                action="keep",
                rule_fired=RuleFired.EXTERNAL_FAILURE,
                reason=f"wikidata_error:{type(e).__name__}",
            )

    def _decision_from_present(self, present: bool) -> FilterDecision | None:
        if present:
            return FilterDecision.drop(rule=RuleFired.WIKIDATA, reason="wikidata_present")
        return None  # absent ≠ decisive; falls through to Rule 3+
