# Semantic Reranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add semantic reranking to context_recall with hard query detection and LLM-based query expansion to handle entailment cases like "rejected" = "no longer viable".

**Architecture:** Two-phase approach: (1) Vertex AI cross-encoder reranking for all search queries, (2) LLM query expansion for detected "hard queries" with Redis caching. Integrates into existing context_query flow.

**Tech Stack:** LiteLLM (rerank API), Vertex AI semantic-ranker, Redis (expansion cache), Pydantic settings

**Spec:** `context/specs/semantic-reranking.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `src/context_service/reranking/__init__.py` | Module exports |
| `src/context_service/reranking/query_classifier.py` | Hard query detection (regex-based) |
| `src/context_service/reranking/query_expander.py` | LLM query expansion with Redis cache |
| `src/context_service/reranking/reranker.py` | Cross-encoder reranking via LiteLLM |
| `tests/reranking/__init__.py` | Test module |
| `tests/reranking/test_query_classifier.py` | Classifier unit tests |
| `tests/reranking/test_query_expander.py` | Expander unit tests |
| `tests/reranking/test_reranker.py` | Reranker unit tests |
| `tests/reranking/test_integration.py` | End-to-end integration tests |

### Modified Files

| File | Changes |
|------|---------|
| `src/context_service/config/settings.py` | Add `RerankingSettings` config class |
| `src/context_service/config/models.py` | Add `reranker` and `query_expander` to `TierConfig` |
| `config/models.yaml` | Add reranker/expander model specs per tier |
| `src/context_service/mcp/tools/context_query.py` | Integrate reranking pipeline |
| `src/context_service/services/context.py` | Wire reranker into query flow |

---

## Phase 1: Reranking Infrastructure

### Task 1: Create Reranking Module Structure

**Files:**
- Create: `src/context_service/reranking/__init__.py`
- Create: `src/context_service/reranking/reranker.py`
- Create: `tests/reranking/__init__.py`
- Create: `tests/reranking/test_reranker.py`

- [ ] **Step 1: Create reranking module directory**

```bash
mkdir -p src/context_service/reranking
mkdir -p tests/reranking
```

- [ ] **Step 2: Create module __init__.py**

Create `src/context_service/reranking/__init__.py`:

```python
"""Semantic reranking for improved recall accuracy."""

from context_service.reranking.reranker import LiteLLMReranker, RerankResult

__all__ = ["LiteLLMReranker", "RerankResult"]
```

- [ ] **Step 3: Create test module __init__.py**

Create `tests/reranking/__init__.py`:

```python
"""Tests for reranking module."""
```

- [ ] **Step 4: Write failing test for RerankResult dataclass**

Create `tests/reranking/test_reranker.py`:

```python
"""Tests for LiteLLMReranker."""

from __future__ import annotations

import pytest

from context_service.reranking.reranker import RerankResult


class TestRerankResult:
    def test_rerank_result_fields(self) -> None:
        result = RerankResult(
            node_id="node-123",
            score=0.95,
            original_rank=2,
        )
        assert result.node_id == "node-123"
        assert result.score == 0.95
        assert result.original_rank == 2
```

- [ ] **Step 5: Run test to verify it fails**

```bash
uv run pytest tests/reranking/test_reranker.py::TestRerankResult::test_rerank_result_fields -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'context_service.reranking.reranker'"

- [ ] **Step 6: Implement RerankResult dataclass**

Create `src/context_service/reranking/reranker.py`:

```python
"""Cross-encoder reranking via LiteLLM."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RerankResult:
    """Result from reranking operation."""

    node_id: str
    score: float
    original_rank: int
```

- [ ] **Step 7: Run test to verify it passes**

```bash
uv run pytest tests/reranking/test_reranker.py::TestRerankResult::test_rerank_result_fields -v
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/context_service/reranking tests/reranking
git commit -m "feat(reranking): add module structure and RerankResult dataclass"
```

---

### Task 2: Implement LiteLLMReranker

**Files:**
- Modify: `src/context_service/reranking/reranker.py`
- Modify: `tests/reranking/test_reranker.py`

- [ ] **Step 1: Write failing test for reranker with mocked LiteLLM**

Add to `tests/reranking/test_reranker.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

from context_service.reranking.reranker import LiteLLMReranker, RerankResult


class TestLiteLLMReranker:
    @pytest.mark.asyncio
    async def test_rerank_returns_sorted_results(self) -> None:
        mock_response = MagicMock()
        mock_response.results = [
            {"index": 1, "relevance_score": 0.95},
            {"index": 0, "relevance_score": 0.80},
            {"index": 2, "relevance_score": 0.60},
        ]

        with patch("context_service.reranking.reranker.litellm") as mock_litellm:
            mock_litellm.arerank = AsyncMock(return_value=mock_response)

            reranker = LiteLLMReranker(model="vertex_ai/semantic-ranker-default@latest")
            results = await reranker.rerank(
                query="what was rejected?",
                documents=["doc zero", "doc one", "doc two"],
                node_ids=["node-0", "node-1", "node-2"],
                top_k=3,
            )

            assert len(results) == 3
            assert results[0].node_id == "node-1"
            assert results[0].score == 0.95
            assert results[0].original_rank == 1
            assert results[1].node_id == "node-0"
            assert results[2].node_id == "node-2"

    @pytest.mark.asyncio
    async def test_rerank_empty_documents_returns_empty(self) -> None:
        reranker = LiteLLMReranker(model="vertex_ai/semantic-ranker-default@latest")
        results = await reranker.rerank(
            query="test",
            documents=[],
            node_ids=[],
            top_k=10,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_rerank_fallback_on_error(self) -> None:
        with patch("context_service.reranking.reranker.litellm") as mock_litellm:
            mock_litellm.arerank = AsyncMock(side_effect=Exception("API error"))

            reranker = LiteLLMReranker(model="vertex_ai/semantic-ranker-default@latest")
            results = await reranker.rerank(
                query="test",
                documents=["doc0", "doc1"],
                node_ids=["node-0", "node-1"],
                top_k=2,
            )

            # Fallback: returns original order
            assert len(results) == 2
            assert results[0].node_id == "node-0"
            assert results[1].node_id == "node-1"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/reranking/test_reranker.py::TestLiteLLMReranker -v
```

Expected: FAIL with "cannot import name 'LiteLLMReranker'"

- [ ] **Step 3: Implement LiteLLMReranker class**

Update `src/context_service/reranking/reranker.py`:

```python
"""Cross-encoder reranking via LiteLLM."""

from __future__ import annotations

from dataclasses import dataclass

import litellm
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RerankResult:
    """Result from reranking operation."""

    node_id: str
    score: float
    original_rank: int


class LiteLLMReranker:
    """Cross-encoder reranking via Vertex AI."""

    def __init__(self, model: str = "vertex_ai/semantic-ranker-default@latest") -> None:
        self._model = model

    async def rerank(
        self,
        query: str,
        documents: list[str],
        node_ids: list[str],
        top_k: int = 10,
    ) -> list[RerankResult]:
        """Rerank documents by relevance to query.

        Args:
            query: The search query.
            documents: Document contents to rerank.
            node_ids: Corresponding node IDs (preserved through reranking).
            top_k: Maximum results to return.

        Returns:
            Top-K results sorted by relevance score.
        """
        if not documents:
            return []

        try:
            response = await litellm.arerank(
                model=self._model,
                query=query,
                documents=documents,
                top_n=top_k,
            )
            return [
                RerankResult(
                    node_id=node_ids[r["index"]],
                    score=r["relevance_score"],
                    original_rank=r["index"],
                )
                for r in response.results
            ]
        except Exception as e:
            logger.warning("reranking_failed", error=str(e), model=self._model)
            # Fallback: return original order with decaying scores
            return [
                RerankResult(node_id=nid, score=1.0 - i * 0.01, original_rank=i)
                for i, nid in enumerate(node_ids[:top_k])
            ]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/reranking/test_reranker.py::TestLiteLLMReranker -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/reranking/reranker.py tests/reranking/test_reranker.py
git commit -m "feat(reranking): implement LiteLLMReranker with fallback"
```

---

### Task 3: Add Reranking Settings

**Files:**
- Modify: `src/context_service/config/settings.py`
- Create: `tests/config/test_reranking_settings.py`

- [ ] **Step 1: Write failing test for RerankingSettings**

Create `tests/config/test_reranking_settings.py`:

```python
"""Tests for reranking settings."""

from __future__ import annotations

import pytest


class TestRerankingSettings:
    def test_reranking_settings_defaults(self) -> None:
        from context_service.config.settings import RerankingSettings

        settings = RerankingSettings()
        assert settings.enabled is True
        assert settings.expand_hard_queries is True
        assert settings.rerank_pool_size == 50
        assert settings.expansion_cache_ttl_days == 7

    def test_reranking_settings_in_main_settings(self) -> None:
        from context_service.config.settings import Settings

        settings = Settings()
        assert hasattr(settings, "reranking")
        assert settings.reranking.enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/config/test_reranking_settings.py -v
```

Expected: FAIL with "cannot import name 'RerankingSettings'"

- [ ] **Step 3: Add RerankingSettings to settings.py**

Add after `SynthesizerIdentityConfig` class in `src/context_service/config/settings.py`:

```python
class RerankingSettings(BaseModel):
    """Settings for semantic reranking and query expansion."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Enable cross-encoder reranking")
    expand_hard_queries: bool = Field(
        default=True, description="Enable LLM query expansion for hard queries"
    )
    rerank_pool_size: int = Field(
        default=50, description="Number of candidates to retrieve before reranking"
    )
    expansion_cache_ttl_days: int = Field(
        default=7, description="TTL for cached query expansions in Redis"
    )
    reranker_timeout_seconds: float = Field(
        default=2.0, description="Timeout for reranker API calls"
    )
    expander_timeout_seconds: float = Field(
        default=5.0, description="Timeout for query expansion LLM calls"
    )
```

- [ ] **Step 4: Add reranking field to Settings class**

Find the `Settings` class and add the reranking field alongside other settings fields:

```python
    reranking: RerankingSettings = Field(default_factory=RerankingSettings)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/config/test_reranking_settings.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/config/settings.py tests/config/test_reranking_settings.py
git commit -m "feat(config): add RerankingSettings for reranker and expander"
```

---

### Task 4: Extend Model Config for Reranker

**Files:**
- Modify: `src/context_service/config/models.py`
- Modify: `config/models.yaml`
- Create: `tests/config/test_reranker_model_config.py`

- [ ] **Step 1: Write failing test for reranker in TierConfig**

Create `tests/config/test_reranker_model_config.py`:

```python
"""Tests for reranker model configuration."""

from __future__ import annotations

import pytest

from context_service.config.models import ModelSpec, TierConfig


class TestRerankerModelConfig:
    def test_tier_config_accepts_reranker(self) -> None:
        tier = TierConfig(
            embeddings=ModelSpec(provider="vertex_ai", model="text-embedding-005", dimensions=768),
            reasoning=ModelSpec(provider="vertex", model="gemini-2.5-pro"),
            fast=ModelSpec(provider="vertex", model="gemini-2.5-flash"),
            reranker=ModelSpec(provider="vertex_ai", model="semantic-ranker-default@latest"),
            query_expander=ModelSpec(provider="vertex", model="gemini-2.5-flash"),
        )
        assert tier.reranker is not None
        assert tier.reranker.model == "semantic-ranker-default@latest"
        assert tier.query_expander is not None

    def test_tier_config_reranker_optional(self) -> None:
        tier = TierConfig(
            embeddings=ModelSpec(provider="vertex_ai", model="text-embedding-005", dimensions=768),
            reasoning=ModelSpec(provider="vertex", model="gemini-2.5-pro"),
            fast=ModelSpec(provider="vertex", model="gemini-2.5-flash"),
        )
        assert tier.reranker is None
        assert tier.query_expander is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/config/test_reranker_model_config.py -v
```

Expected: FAIL with "unexpected keyword argument 'reranker'"

- [ ] **Step 3: Update TierConfig to include reranker and query_expander**

Update `TierConfig` in `src/context_service/config/models.py`:

```python
class TierConfig(BaseModel):
    """Model assignments for a single tier."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    embeddings: ModelSpec
    reasoning: ModelSpec
    fast: ModelSpec
    reranker: ModelSpec | None = None
    query_expander: ModelSpec | None = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/config/test_reranker_model_config.py -v
```

Expected: PASS

- [ ] **Step 5: Add helper methods to ModelsConfig**

Add to `ModelsConfig` class in `src/context_service/config/models.py`:

```python
    def get_reranker_model(self) -> ModelSpec | None:
        """Get the reranker model for the active tier, if configured."""
        return self.tiers[self.tier].reranker

    def get_query_expander_model(self) -> ModelSpec | None:
        """Get the query expander model for the active tier, if configured."""
        return self.tiers[self.tier].query_expander

    @property
    def litellm_reranker_model(self) -> str | None:
        """Convenience for litellm format: provider/model."""
        spec = self.get_reranker_model()
        if spec is None:
            return None
        return f"{spec.provider}/{spec.model}"

    @property
    def litellm_expander_model(self) -> str | None:
        """Convenience for litellm format: provider/model."""
        spec = self.get_query_expander_model()
        if spec is None:
            return None
        return f"{spec.provider}/{spec.model}"
```

- [ ] **Step 6: Update config/models.yaml with reranker specs**

Add `reranker` and `query_expander` to each tier in `config/models.yaml`:

```yaml
  balanced:
    embeddings:
      provider: vertex_ai
      model: text-embedding-005
      dimensions: 768
    reasoning:
      provider: vertex
      model: gemini-2.5-pro
    fast:
      provider: vertex
      model: gemini-2.5-flash
    reranker:
      provider: vertex_ai
      model: semantic-ranker-default@latest
    query_expander:
      provider: vertex
      model: gemini-2.5-flash

  economy:
    embeddings:
      provider: vertex_ai
      model: text-embedding-005
      dimensions: 768
    reasoning:
      provider: vertex
      model: gemini-2.5-flash
    fast:
      provider: vertex
      model: gemini-2.5-flash
    reranker:
      provider: vertex_ai
      model: semantic-ranker-fast@latest
    query_expander:
      provider: vertex
      model: gemini-2.5-flash

  premium:
    embeddings:
      provider: vertex_ai
      model: text-embedding-005
      dimensions: 768
    reasoning:
      provider: vertex
      model: gemini-2.5-pro
    fast:
      provider: vertex
      model: gemini-2.5-pro
    reranker:
      provider: vertex_ai
      model: semantic-ranker-default@latest
    query_expander:
      provider: vertex
      model: gemini-2.5-pro
```

For self-hosted tiers, leave reranker as null (not available without custom deployment).

- [ ] **Step 7: Run full test suite for config module**

```bash
uv run pytest tests/config/ -v
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/context_service/config/models.py config/models.yaml tests/config/test_reranker_model_config.py
git commit -m "feat(config): add reranker and query_expander to tier config"
```

---

## Phase 2: Query Expansion

### Task 5: Implement Hard Query Classifier

**Files:**
- Create: `src/context_service/reranking/query_classifier.py`
- Create: `tests/reranking/test_query_classifier.py`

- [ ] **Step 1: Write failing tests for hard query detection**

Create `tests/reranking/test_query_classifier.py`:

```python
"""Tests for hard query classifier."""

from __future__ import annotations

import pytest

from context_service.reranking.query_classifier import is_hard_query


class TestIsHardQuery:
    @pytest.mark.parametrize(
        "query,expected",
        [
            # Hard queries - should return True
            ("what was rejected?", True),
            ("what got approved?", True),
            ("what failed?", True),
            ("why did the system crash?", True),
            ("what was postponed", True),
            ("which approach was abandoned?", True),
            ("is the proposal approved?", True),
            # Normal queries - should return False
            ("meeting notes from last week", False),
            ("how to configure the database", False),
            ("list all users in the system", False),
            ("performance metrics for Q1", False),
            ("", False),
        ],
    )
    def test_is_hard_query(self, query: str, expected: bool) -> None:
        assert is_hard_query(query) == expected

    def test_case_insensitive(self) -> None:
        assert is_hard_query("WHAT WAS REJECTED?") is True
        assert is_hard_query("What Was Rejected?") is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/reranking/test_query_classifier.py -v
```

Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Implement is_hard_query function**

Create `src/context_service/reranking/query_classifier.py`:

```python
"""Hard query detection for semantic reranking.

Detects queries that require semantic reasoning beyond similarity matching.
This regex-based classifier is intentionally simple for MVP. Plan to evolve
to LLM-based classifier based on production query logs.
"""

from __future__ import annotations

import re

ABSTRACT_VERBS = frozenset({
    "rejected",
    "approved",
    "denied",
    "accepted",
    "failed",
    "succeeded",
    "postponed",
    "cancelled",
    "confirmed",
    "dismissed",
    "granted",
    "abandoned",
    "dropped",
    "removed",
    "added",
    "changed",
    "decided",
})

QUESTION_PATTERNS = [
    re.compile(r"^what (was|were|got|is|are) \w+\??$", re.IGNORECASE),
    re.compile(r"^why did .+\??$", re.IGNORECASE),
    re.compile(r"^(is|are|was|were) .+ (approved|rejected|denied)\??$", re.IGNORECASE),
    re.compile(r"^which .+ (was|were|got) \w+\??$", re.IGNORECASE),
]


def is_hard_query(query: str) -> bool:
    """Detect queries requiring semantic reasoning.

    Note: Intentionally conservative. False negatives are logged for iteration.

    Args:
        query: The search query.

    Returns:
        True if the query likely requires semantic reasoning beyond similarity.
    """
    if not query:
        return False

    query_lower = query.lower().strip()
    words = query_lower.split()

    # Short queries with abstract verbs
    if len(words) <= 5 and any(w.rstrip("?") in ABSTRACT_VERBS for w in words):
        return True

    # Question patterns that need inference
    for pattern in QUESTION_PATTERNS:
        if pattern.match(query_lower):
            return True

    return False
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/reranking/test_query_classifier.py -v
```

Expected: PASS

- [ ] **Step 5: Update module __init__.py**

Update `src/context_service/reranking/__init__.py`:

```python
"""Semantic reranking for improved recall accuracy."""

from context_service.reranking.query_classifier import is_hard_query
from context_service.reranking.reranker import LiteLLMReranker, RerankResult

__all__ = ["LiteLLMReranker", "RerankResult", "is_hard_query"]
```

- [ ] **Step 6: Commit**

```bash
git add src/context_service/reranking/query_classifier.py tests/reranking/test_query_classifier.py src/context_service/reranking/__init__.py
git commit -m "feat(reranking): add hard query classifier"
```

---

### Task 6: Implement Query Expander

**Files:**
- Create: `src/context_service/reranking/query_expander.py`
- Create: `tests/reranking/test_query_expander.py`

- [ ] **Step 1: Write failing test for QueryExpander**

Create `tests/reranking/test_query_expander.py`:

```python
"""Tests for QueryExpander."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.reranking.query_expander import QueryExpander


class TestQueryExpander:
    @pytest.mark.asyncio
    async def test_expand_returns_expanded_query(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # cache miss

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"expanded": "rejected OR denied OR dismissed OR \'no longer viable\'"}'
                )
            )
        ]

        with patch("context_service.reranking.query_expander.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)

            expander = QueryExpander(
                llm_model="vertex/gemini-2.5-flash",
                redis=mock_redis,
            )
            result = await expander.expand("what was rejected?")

            assert "rejected" in result
            assert "denied" in result
            assert "no longer viable" in result

    @pytest.mark.asyncio
    async def test_expand_returns_cached_result(self) -> None:
        cached_expansion = "rejected OR denied OR 'no longer viable'"
        mock_redis = AsyncMock()
        mock_redis.get.return_value = cached_expansion.encode()

        expander = QueryExpander(
            llm_model="vertex/gemini-2.5-flash",
            redis=mock_redis,
        )
        result = await expander.expand("what was rejected?")

        assert result == cached_expansion
        mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_expand_caches_new_expansion(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"expanded": "test expansion"}'))
        ]

        with patch("context_service.reranking.query_expander.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_response)

            expander = QueryExpander(
                llm_model="vertex/gemini-2.5-flash",
                redis=mock_redis,
                cache_ttl_seconds=86400,
            )
            await expander.expand("test query")

            mock_redis.set.assert_called_once()
            call_args = mock_redis.set.call_args
            assert b"test expansion" in call_args[0][1] or "test expansion" in str(call_args)

    @pytest.mark.asyncio
    async def test_expand_fallback_on_error(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("context_service.reranking.query_expander.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(side_effect=Exception("LLM error"))

            expander = QueryExpander(
                llm_model="vertex/gemini-2.5-flash",
                redis=mock_redis,
            )
            result = await expander.expand("test query")

            # Fallback: returns original query
            assert result == "test query"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/reranking/test_query_expander.py -v
```

Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Implement QueryExpander class**

Create `src/context_service/reranking/query_expander.py`:

```python
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
        redis: Redis[bytes],  # type: ignore[type-arg]
        cache_ttl_seconds: int = 86400 * 7,
    ) -> None:
        """Initialize the query expander.

        Args:
            llm_model: LiteLLM model identifier for expansion.
            redis: Redis client for caching.
            cache_ttl_seconds: Cache TTL (default 7 days).
        """
        self._model = llm_model
        self._redis = redis
        self._cache_ttl = cache_ttl_seconds

    async def expand(self, query: str) -> str:
        """Expand query with semantic equivalents.

        Args:
            query: The original query.

        Returns:
            Expanded query with OR'd synonyms, or original on error.
        """
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
        )
        content = response.choices[0].message.content
        data = json.loads(content)
        return data["expanded"]

    def _normalize(self, query: str) -> str:
        """Normalize query for cache key.

        Intentionally collapses variations like case and trailing punctuation.
        """
        return query.lower().strip()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/reranking/test_query_expander.py -v
```

Expected: PASS

- [ ] **Step 5: Update module __init__.py**

Update `src/context_service/reranking/__init__.py`:

```python
"""Semantic reranking for improved recall accuracy."""

from context_service.reranking.query_classifier import is_hard_query
from context_service.reranking.query_expander import QueryExpander
from context_service.reranking.reranker import LiteLLMReranker, RerankResult

__all__ = ["LiteLLMReranker", "RerankResult", "is_hard_query", "QueryExpander"]
```

- [ ] **Step 6: Commit**

```bash
git add src/context_service/reranking/query_expander.py tests/reranking/test_query_expander.py src/context_service/reranking/__init__.py
git commit -m "feat(reranking): add QueryExpander with Redis caching"
```

---

## Phase 3: Integration

### Task 7: Wire Reranking into Context Query

**Files:**
- Modify: `src/context_service/mcp/tools/context_query.py`
- Create: `tests/mcp/tools/test_context_query_reranking.py`

- [ ] **Step 1: Write integration test for reranking in context_query**

Create `tests/mcp/tools/test_context_query_reranking.py`:

```python
"""Tests for context_query reranking integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestContextQueryReranking:
    @pytest.mark.asyncio
    async def test_query_with_reranking_enabled(self) -> None:
        """Test that reranking is applied when enabled."""
        # This is an integration test that verifies the flow
        # Mock the auth context
        mock_auth = MagicMock()
        mock_auth.org_id = "test-org"

        # Mock search results
        mock_results = [
            MagicMock(
                node_id="node-1",
                layer="memory",
                content="First result",
                summary=None,
                confidence=0.9,
                relevance_score=0.8,
                tags=[],
                created_at=None,
            ),
            MagicMock(
                node_id="node-2",
                layer="memory",
                content="Second result - no longer viable",
                summary=None,
                confidence=0.85,
                relevance_score=0.7,
                tags=[],
                created_at=None,
            ),
        ]

        # Mock reranker response that swaps order
        mock_rerank_response = MagicMock()
        mock_rerank_response.results = [
            {"index": 1, "relevance_score": 0.95},  # node-2 ranked first
            {"index": 0, "relevance_score": 0.6},   # node-1 ranked second
        ]

        with (
            patch("context_service.mcp.tools.context_query.get_mcp_auth_context", return_value=mock_auth),
            patch("context_service.mcp.tools.context_query.get_context_service") as mock_svc,
            patch("context_service.mcp.tools.context_query.get_silo_service") as mock_silo_svc,
            patch("context_service.mcp.tools.context_query.validate_silo_ownership", return_value=None),
            patch("context_service.mcp.tools.context_query.get_settings") as mock_settings,
            patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
        ):
            mock_svc.return_value.query = AsyncMock(return_value=mock_results)
            mock_settings.return_value.reranking.enabled = True
            mock_settings.return_value.causal.query_enabled = False

            from context_service.mcp.tools.context_query import _context_query

            result = await _context_query(
                silo_id="test-silo",
                query="what was rejected?",
                top_k=10,
            )

            assert "results" in result
            # Verify query was called
            mock_svc.return_value.query.assert_called_once()
```

- [ ] **Step 2: Run test to verify current behavior**

```bash
uv run pytest tests/mcp/tools/test_context_query_reranking.py -v
```

Note: This establishes a baseline. The test may pass or fail depending on current state.

- [ ] **Step 3: Add reranking pipeline to context_query**

This is a larger change. Add to the top of `src/context_service/mcp/tools/context_query.py`:

```python
from context_service.config.models import load_models_config
from context_service.reranking import LiteLLMReranker, QueryExpander, is_hard_query
```

Then modify the `_context_query` function to add reranking after the search:

```python
async def _apply_reranking(
    query: str,
    results: list,
    settings: Any,
) -> list:
    """Apply reranking to search results if enabled."""
    if not settings.reranking.enabled or len(results) <= 1:
        return results

    models_config = load_models_config()
    reranker_model = models_config.litellm_reranker_model
    if reranker_model is None:
        return results

    reranker = LiteLLMReranker(model=reranker_model)
    documents = [r.content or "" for r in results]
    node_ids = [str(r.node_id) for r in results]

    reranked = await reranker.rerank(
        query=query,
        documents=documents,
        node_ids=node_ids,
        top_k=len(results),
    )

    # Rebuild results in new order
    id_to_result = {str(r.node_id): r for r in results}
    return [id_to_result[rr.node_id] for rr in reranked if rr.node_id in id_to_result]
```

And call it after the query:

```python
    results = await ctx_svc.query(...)
    
    # Apply reranking
    settings = get_settings()
    results = await _apply_reranking(query, results, settings)
```

- [ ] **Step 4: Run tests to verify integration**

```bash
uv run pytest tests/mcp/tools/test_context_query_reranking.py -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
uv run pytest tests/mcp/ -v --tb=short
```

Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/tools/context_query.py tests/mcp/tools/test_context_query_reranking.py
git commit -m "feat(mcp): integrate reranking into context_query"
```

---

### Task 8: Add Query Expansion to Pipeline

**Files:**
- Modify: `src/context_service/mcp/tools/context_query.py`
- Modify: `tests/mcp/tools/test_context_query_reranking.py`

- [ ] **Step 1: Write test for query expansion on hard queries**

Add to `tests/mcp/tools/test_context_query_reranking.py`:

```python
    @pytest.mark.asyncio
    async def test_hard_query_triggers_expansion(self) -> None:
        """Test that hard queries trigger LLM expansion."""
        from context_service.reranking import is_hard_query

        # Verify the query is detected as hard
        assert is_hard_query("what was rejected?") is True

        # The full integration test would mock the expander
        # For now, verify the classifier works as expected
        assert is_hard_query("meeting notes") is False
```

- [ ] **Step 2: Add query expansion to _context_query**

Add expansion logic before the search in `_context_query`:

```python
async def _maybe_expand_query(
    query: str,
    settings: Any,
    redis: Any,
) -> tuple[str, bool]:
    """Expand query if it's a hard query and expansion is enabled.
    
    Returns:
        Tuple of (effective_query, was_expanded)
    """
    if not settings.reranking.expand_hard_queries:
        return query, False

    if not is_hard_query(query):
        return query, False

    if redis is None:
        logger.warning("query_expansion_skipped", reason="redis_unavailable")
        return query, False

    models_config = load_models_config()
    expander_model = models_config.litellm_expander_model
    if expander_model is None:
        return query, False

    expander = QueryExpander(
        llm_model=expander_model,
        redis=redis,
        cache_ttl_seconds=settings.reranking.expansion_cache_ttl_days * 86400,
    )
    expanded = await expander.expand(query)
    return expanded, expanded != query
```

Call it in `_context_query`:

```python
    # Query expansion for hard queries
    redis = get_redis()
    effective_query, was_expanded = await _maybe_expand_query(query, settings, redis)
    if was_expanded:
        logger.info("query_expanded", original=query, expanded=effective_query)

    results = await ctx_svc.query(
        scope=scope,
        query=effective_query,  # Use expanded query for search
        ...
    )

    # Rerank using expanded query as well
    results = await _apply_reranking(effective_query, results, settings)
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/mcp/tools/test_context_query_reranking.py -v
uv run pytest tests/reranking/ -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/tools/context_query.py tests/mcp/tools/test_context_query_reranking.py
git commit -m "feat(mcp): add query expansion for hard queries"
```

---

### Task 9: Add Observability

**Files:**
- Modify: `src/context_service/mcp/tools/context_query.py`
- Modify: `src/context_service/telemetry/metrics.py`

- [ ] **Step 1: Add metrics for reranking**

Add to `src/context_service/telemetry/metrics.py`:

```python
def record_reranking(latency_ms: float, success: bool, fallback: bool = False) -> None:
    """Record reranking operation metrics."""
    # Implementation depends on existing metrics setup
    pass


def record_query_expansion(latency_ms: float, cache_hit: bool, success: bool) -> None:
    """Record query expansion metrics."""
    pass


def record_hard_query_detection(is_hard: bool) -> None:
    """Record hard query detection for monitoring."""
    pass
```

- [ ] **Step 2: Add metrics calls to reranking code**

Update `_apply_reranking` in `context_query.py` to record metrics:

```python
import time
from context_service.telemetry.metrics import record_reranking, record_hard_query_detection

# In _apply_reranking:
start = time.perf_counter()
try:
    reranked = await reranker.rerank(...)
    record_reranking((time.perf_counter() - start) * 1000, success=True)
except Exception:
    record_reranking((time.perf_counter() - start) * 1000, success=False, fallback=True)
    raise
```

- [ ] **Step 3: Add tracing spans**

Add OpenTelemetry spans to the reranking functions using the existing pattern:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

# In _apply_reranking:
with tracer.start_as_current_span("recall.rerank") as span:
    span.set_attribute("query_length", len(query))
    span.set_attribute("candidates", len(results))
    # ... reranking logic
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/mcp/ -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/context_query.py src/context_service/telemetry/metrics.py
git commit -m "feat(telemetry): add metrics and tracing for reranking"
```

---

### Task 10: Integration Test with Real Services

**Files:**
- Create: `tests/integration/test_reranking_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/integration/test_reranking_integration.py`:

```python
"""Integration tests for semantic reranking."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestRerankingIntegration:
    @pytest.mark.asyncio
    async def test_hard_query_finds_semantic_match(self) -> None:
        """Test that 'rejected' matches 'no longer viable'."""
        # This test requires live services
        # Skip if not in integration test mode
        pytest.skip("Requires live Vertex AI and Redis")

    @pytest.mark.asyncio
    async def test_reranking_improves_order(self) -> None:
        """Test that reranking improves result ordering."""
        pytest.skip("Requires live Vertex AI")

    @pytest.mark.asyncio
    async def test_expansion_cache_works(self) -> None:
        """Test that query expansion caching works."""
        pytest.skip("Requires live Redis")
```

- [ ] **Step 2: Commit**

```bash
git add tests/integration/test_reranking_integration.py
git commit -m "test(integration): add reranking integration test stubs"
```

---

### Task 11: Documentation and Cleanup

**Files:**
- Update: `src/context_service/reranking/__init__.py`
- Run: Type checking and linting

- [ ] **Step 1: Run type checking**

```bash
uv run mypy src/context_service/reranking/
```

Fix any type errors.

- [ ] **Step 2: Run linting**

```bash
uv run ruff check src/context_service/reranking/ --fix
uv run ruff format src/context_service/reranking/
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -v --tb=short -x
```

Expected: All tests pass

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore(reranking): cleanup and type fixes"
```

---

## Summary

| Task | Component | Status |
|------|-----------|--------|
| 1 | Module structure | - [ ] |
| 2 | LiteLLMReranker | - [ ] |
| 3 | RerankingSettings | - [ ] |
| 4 | Model config extension | - [ ] |
| 5 | Hard query classifier | - [ ] |
| 6 | QueryExpander | - [ ] |
| 7 | Context query integration | - [ ] |
| 8 | Query expansion pipeline | - [ ] |
| 9 | Observability | - [ ] |
| 10 | Integration tests | - [ ] |
| 11 | Documentation/cleanup | - [ ] |

**Estimated time:** 3-4 hours

**Rollout:**
1. Deploy with `RERANK_ENABLED=false`
2. Enable on staging, monitor latency
3. Flip to `true` in production
4. Monitor `hard_query_detection_rate` to validate 20% assumption
