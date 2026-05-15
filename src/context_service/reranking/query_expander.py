"""LLM-based query expansion with Redis caching."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import litellm
import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

EXPANSION_PROMPT = '''Expand this search query with semantically equivalent phrases.
The goal is to find documents that ANSWER the query, even if they use different words.

Query: {query}

Return JSON only:
{{"expanded": "original query OR synonym1 OR 'equivalent phrase' OR synonym2"}}

Examples:
- "rejected" -> "rejected OR denied OR dismissed OR 'no longer viable' OR 'not accepted'"
- "approved" -> "approved OR accepted OR 'green light' OR granted OR confirmed"
- "failed" -> "failed OR 'did not succeed' OR 'did not complete' OR unsuccessful"
'''


class QueryExpander:
    """LLM-based query expansion with Redis caching."""

    CACHE_PREFIX = "qexp:"

    def __init__(
        self,
        llm_model: str,
        redis: Redis,
        cache_ttl_seconds: int = 86400 * 7,
    ) -> None:
        self._model = llm_model
        self._redis = redis
        self._cache_ttl = cache_ttl_seconds

    async def expand(self, query: str) -> str:
        """Expand query with semantic equivalents."""
        cache_key = f"{self.CACHE_PREFIX}{self._normalize(query)}"

        # Check cache
        try:
            cached = await self._redis.get(cache_key)
            if cached is not None:
                logger.debug("query_expansion_cache_hit", query=query)
                return cached.decode() if isinstance(cached, bytes) else cached
        except Exception as e:
            logger.warning("query_expansion_cache_get_error", error=str(e))

        # LLM expansion
        try:
            expanded = await self._llm_expand(query)
            # Cache the result
            try:
                await self._redis.set(cache_key, expanded.encode(), ex=self._cache_ttl)
            except Exception as e:
                logger.warning("query_expansion_cache_set_error", error=str(e))
            return expanded
        except Exception as e:
            logger.warning("query_expansion_failed", query=query, error=str(e))
            return query  # fallback to original

    async def _llm_expand(self, query: str) -> str:
        """Expand query using LLM."""
        prompt = EXPANSION_PROMPT.format(query=query)
        response = await litellm.acompletion(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout=30.0,
        )
        content = response.choices[0].message.content or ""
        try:
            data = json.loads(content)
            return str(data.get("expanded", query))
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("query_expansion_json_parse_failed", error=str(e), content=content[:100])
            raise  # Let outer handler catch and fallback

    def _normalize(self, query: str) -> str:
        """Normalize query for cache key."""
        return query.lower().strip()
