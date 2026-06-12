"""LLM-based query expansion with Redis caching."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

MAX_RETRIES = 2
RETRY_DELAY = 0.1

# Default model for query expansion (Gemini 3.1 flash-lite via global endpoint)
DEFAULT_EXPANSION_MODEL = "gemini-3.1-flash-lite-preview"

EXPANSION_PROMPT = """Expand this search query with semantically equivalent phrases.
The goal is to find documents that ANSWER the query, even if they use different words.

Query: {query}

Return JSON only:
{{"expanded": "original query OR synonym1 OR 'equivalent phrase' OR synonym2"}}

Examples:
- "rejected" -> "rejected OR denied OR dismissed OR 'no longer viable' OR 'not accepted'"
- "approved" -> "approved OR accepted OR 'green light' OR granted OR confirmed"
- "failed" -> "failed OR 'did not succeed' OR 'did not complete' OR unsuccessful"
"""


class QueryExpander:
    """LLM-based query expansion with Redis caching.

    Uses google-genai SDK with Vertex AI for low-latency expansion.
    """

    CACHE_PREFIX = "qexp:"

    def __init__(
        self,
        llm_model: str | None,
        redis: Redis,
        cache_ttl_seconds: int = 86400 * 7,
        timeout_seconds: float = 5.0,
        vertex_project: str | None = None,
        vertex_location: str | None = None,
    ) -> None:
        self._model = llm_model or DEFAULT_EXPANSION_MODEL
        self._redis = redis
        self._cache_ttl = cache_ttl_seconds
        self._timeout = timeout_seconds
        self._vertex_project = vertex_project
        # Force global for Gemini 3.x models (required by API)
        self._vertex_location = (
            "global" if "gemini-3" in self._model else (vertex_location or "global")
        )
        self._client: object | None = None

    async def expand(self, query: str, silo_id: str) -> str:
        """Expand query with semantic equivalents."""
        cache_key = f"{self.CACHE_PREFIX}{silo_id}:{self._normalize(query)}"

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
                await self._redis.set(cache_key, expanded.encode(), self._cache_ttl)
            except Exception as e:
                logger.warning("query_expansion_cache_set_error", error=str(e))
            return expanded
        except Exception as e:
            logger.warning("query_expansion_failed", query=query, error=str(e))
            return query  # fallback to original

    def _get_client(self) -> object:
        """Lazy-init google-genai client."""
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=True,
                project=self._vertex_project or "engrammic",
                location=self._vertex_location,
            )
        return self._client

    async def _llm_expand(self, query: str) -> str:
        """Expand query using LLM."""
        prompt = EXPANSION_PROMPT.format(query=query)
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                client = self._get_client()
                loop = asyncio.get_running_loop()

                def _generate(c: object = client) -> object:
                    return c.models.generate_content(  # type: ignore[union-attr]
                        model=self._model,
                        contents=prompt,
                        config={"response_mime_type": "application/json"},
                    )

                response = await asyncio.wait_for(
                    loop.run_in_executor(None, _generate),
                    timeout=self._timeout,
                )
                content = response.text or ""
                try:
                    data = json.loads(content)
                    return str(data.get("expanded", query))
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(
                        "query_expansion_json_parse_failed", error=str(e), content=content[:100]
                    )
                    raise
            except TimeoutError:
                last_error = TimeoutError(f"Query expansion timed out after {self._timeout}s")
                if attempt < MAX_RETRIES:
                    logger.debug("query_expansion_retry", attempt=attempt + 1, error="timeout")
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                raise last_error from None
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    logger.debug("query_expansion_retry", attempt=attempt + 1, error=str(e))
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                raise
        raise last_error  # type: ignore[misc]

    def _normalize(self, query: str) -> str:
        """Normalize query for cache key."""
        return query.lower().strip()
