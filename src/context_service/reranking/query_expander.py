"""LLM-based query expansion with Redis caching."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

# Module-level genai client cache (avoid cold start per request)
_GENAI_CLIENT: object | None = None
_GENAI_CLIENT_KEY: tuple[str | None, str | None] = (None, None)

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


def _use_genai_sdk(provider: str | None, model: str) -> bool:
    """Check if we should use google-genai SDK (Vertex AI with Gemini)."""
    return provider == "vertex_ai" and "gemini" in model.lower()


class QueryExpander:
    """LLM-based query expansion with Redis caching.

    Uses google-genai SDK for Gemini models, litellm for others.
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
        provider: str | None = None,
    ) -> None:
        raw_model = llm_model or DEFAULT_EXPANSION_MODEL
        self._raw_model = raw_model  # Keep full model string for litellm
        # Strip provider prefix for genai SDK (e.g., vertex_ai/gemini-3.5-flash -> gemini-3.5-flash)
        self._model = raw_model.split("/", 1)[-1] if "/" in raw_model else raw_model
        self._redis = redis
        self._cache_ttl = cache_ttl_seconds
        self._timeout = timeout_seconds
        self._vertex_project = vertex_project
        self._provider = provider
        self._use_genai = _use_genai_sdk(provider, self._model)
        logger.info(
            "query_expander_init",
            model=self._model,
            provider=provider,
            use_genai=self._use_genai,
        )
        # Gemini 3.x requires global region; otherwise use passed location
        if "gemini-3" in self._model:
            self._vertex_location = "global"
        else:
            self._vertex_location = vertex_location or "us-central1"

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

    def _get_genai_client(self) -> object:
        """Get cached google-genai client for Gemini models."""
        global _GENAI_CLIENT, _GENAI_CLIENT_KEY

        key = (self._vertex_project, self._vertex_location)
        if _GENAI_CLIENT is None or key != _GENAI_CLIENT_KEY:
            from google import genai

            _GENAI_CLIENT = genai.Client(
                vertexai=True,
                project=self._vertex_project or "engrammic",
                location=self._vertex_location,
            )
            _GENAI_CLIENT_KEY = key
            logger.info(
                "genai_client_created", project=self._vertex_project, location=self._vertex_location
            )
        return _GENAI_CLIENT

    async def _llm_expand(self, query: str) -> str:
        """Expand query using LLM."""
        prompt = EXPANSION_PROMPT.format(query=query)
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                if self._use_genai:
                    content, input_tokens, output_tokens = await self._expand_with_genai(prompt)
                else:
                    content, input_tokens, output_tokens = await self._expand_with_litellm(prompt)

                logger.debug(
                    "query_expansion_tokens",
                    model=self._model,
                    provider=self._provider,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

                try:
                    data = json.loads(content)
                    return str(data.get("expanded", query))
                except (json.JSONDecodeError, TypeError):
                    # Try json-repair for malformed JSON from models without response_format
                    try:
                        from json_repair import repair_json

                        repaired = repair_json(content, return_objects=True)
                        if isinstance(repaired, dict) and "expanded" in repaired:
                            logger.debug("query_expansion_json_repaired", content=content[:100])
                            return str(repaired["expanded"])
                    except Exception:
                        pass
                    logger.warning("query_expansion_json_parse_failed", content=content[:100])
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
        if last_error is not None:
            raise last_error
        raise RuntimeError("Query expansion failed without capturing error")

    async def _expand_with_genai(self, prompt: str) -> tuple[str, int, int]:
        """Expand using google-genai SDK (for Gemini models).

        Returns (content, input_tokens, output_tokens).
        """
        import time

        start = time.monotonic()
        try:
            client = self._get_genai_client()
        except Exception as e:
            logger.warning("genai_client_init_failed", error=str(e))
            raise RuntimeError(f"Failed to initialize genai client: {e}") from e
        logger.debug("genai_expand_start", model=self._model, prompt_len=len(prompt))
        loop = asyncio.get_running_loop()

        def _generate(c: Any = client) -> Any:
            gen_start = time.monotonic()
            result = c.models.generate_content(
                model=self._model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            logger.info(
                "genai_generate_content_done", elapsed_ms=int((time.monotonic() - gen_start) * 1000)
            )
            return result

        response = await asyncio.wait_for(
            loop.run_in_executor(None, _generate),
            timeout=self._timeout,
        )
        logger.info("genai_expand_complete", elapsed_ms=int((time.monotonic() - start) * 1000))
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0 if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0 if usage else 0
        return str(response.text) if response.text else "", input_tokens, output_tokens

    async def _expand_with_litellm(self, prompt: str) -> tuple[str, int, int]:
        """Expand using litellm (for non-Gemini models).

        Returns (content, input_tokens, output_tokens).
        """
        import litellm

        response = await asyncio.wait_for(
            litellm.acompletion(
                model=self._raw_model,
                messages=[{"role": "user", "content": prompt}],
                vertex_ai_project=self._vertex_project,
                vertex_ai_location=self._vertex_location,
            ),
            timeout=self._timeout,
        )
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0 if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0 if usage else 0
        return response.choices[0].message.content or "", input_tokens, output_tokens

    def _normalize(self, query: str) -> str:
        """Normalize query for cache key."""
        return query.lower().strip()
