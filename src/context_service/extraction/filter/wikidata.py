from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import context_service.extraction.filter.circuit_breaker as cb_module
from context_service.extraction.filter.circuit_breaker import CircuitBreaker
from context_service.extraction.filter.models import FilterDecision, FilterRuleSet, RuleFired
from context_service.utils.json import dumps, loads

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from context_service.extraction.models import ClaimTriple
    from context_service.stores.redis import RedisClient

log = logging.getLogger(__name__)


def _cache_key(claim: ClaimTriple) -> str:
    canonical = f"{claim.predicate}|{str(claim.subject).lower()}|{str(claim.object).lower()}"
    h = hashlib.sha256(canonical.encode()).hexdigest()
    return f"wikidata:hit:{h}"


_SPARQL_ESCAPES = (
    ("\\", "\\\\"),  # backslash MUST be first
    ('"', '\\"'),
    ("\n", "\\n"),
    ("\r", "\\r"),
    ("\t", "\\t"),
)

# Unicode bidi-override codepoints that could be used to mislead log readers or
# bypass naive content filters.  We strip them outright; they have no legitimate
# place in a SPARQL label query.
_BIDI_OVERRIDES: frozenset[str] = frozenset(
    "​‌‍‎‏"  # zero-width / directional marks
    "‪‫‬‭‮"  # LRE, RLE, PDF, LRO, RLO
    "⁦⁧⁨⁩"  # FSI, LRI, RLI, PDI
    "﻿"  # BOM / zero-width no-break space
)


def _escape_sparql_literal(value: str) -> str:
    """Escape a string for safe inclusion inside a double-quoted SPARQL literal.

    Per SPARQL 1.1 §19.7 the string-literal escape set is \\, ", \\n, \\r, \\t,
    \\u, \\U.  This function handles all of those *plus*:

    - Bidi-override and zero-width characters (stripped; harmless in labels).
    - The \\u / \\U escape sequences themselves: because we escape backslash
      first, any literal \\u in the input becomes \\\\u, preventing injection
      via ``\\u0022`` or similar sequences.
    """
    # Strip bidi overrides and zero-width characters before other processing.
    value = "".join(ch for ch in value if ch not in _BIDI_OVERRIDES)

    for needle, replacement in _SPARQL_ESCAPES:
        value = value.replace(needle, replacement)
    return value


def _build_sparql_ask(claim: ClaimTriple) -> str:
    # Minimum-viable: label-based ASK. Precision is low but FP rate stays near zero
    # because a NO answer falls through — a YES is only produced on an actual match.
    s = _escape_sparql_literal(str(claim.subject))
    o = _escape_sparql_literal(str(claim.object))
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
        from SPARQLWrapper import JSON, SPARQLWrapper  # type: ignore[import-not-found]

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

    Pass silo_id to bind the CB to the registry so state persists across requests.
    When silo_id is omitted (tests / one-shot usage) a fresh CB is used instead.
    """

    def __init__(
        self,
        rs: FilterRuleSet,
        redis: RedisClient,
        sparql_fn: Callable[[str, ClaimTriple, float], Awaitable[bool]] | None = None,
        *,
        silo_id: str | None = None,
    ) -> None:
        self._rs = rs
        self._redis = redis
        self._sparql = sparql_fn or default_sparql_ask
        self._silo_id = silo_id
        self._local_cb: CircuitBreaker | None = (
            None
            if silo_id is not None
            else CircuitBreaker(
                failure_threshold=rs.wikidata_cb_failure_threshold,
                window_s=rs.wikidata_cb_window_s,
                cooldown_s=rs.wikidata_cb_cooldown_s,
            )
        )
        self._ttl_s = int(rs.wikidata_cache_ttl_days * 86400)

    async def _get_cb(self) -> CircuitBreaker:
        if self._local_cb is not None:
            return self._local_cb
        if self._silo_id is None:
            raise RuntimeError("silo_id required - filter not properly initialized")
        return await cb_module.get_or_create(
            self._silo_id,
            "wikidata",
            failure_threshold=self._rs.wikidata_cb_failure_threshold,
            window_s=self._rs.wikidata_cb_window_s,
            cooldown_s=self._rs.wikidata_cb_cooldown_s,
        )

    async def evaluate(self, claim: ClaimTriple) -> FilterDecision | None:
        key = _cache_key(claim)
        try:
            cached = await self._redis.get(key)
            if cached is not None:
                entry = loads(cached)
                return self._decision_from_present(entry.get("present", False))
        except Exception as e:  # cache failures are non-fatal
            log.warning("wikidata cache read failed: %s", e)

        cb = await self._get_cb()
        if await cb.is_open():
            return FilterDecision(
                action="keep",
                rule_fired=RuleFired.EXTERNAL_FAILURE,
                reason="wikidata_cb_open",
            )

        try:
            present = await self._sparql(
                self._rs.wikidata_endpoint, claim, self._rs.wikidata_timeout_s
            )
            await cb.record_success()
            entry = {"present": present, "checked_at": datetime.now(UTC).isoformat()}
            try:
                await self._redis.set(key, dumps(entry), ttl_seconds=self._ttl_s)
            except Exception as e:
                log.warning("wikidata cache write failed: %s", e)
            return self._decision_from_present(present)
        except Exception as e:
            await cb.record_failure()
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
