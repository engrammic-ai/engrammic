# Standalone Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add TEI-based reranking and three standalone deployment tiers (lite/standard/pro) for fully air-gapped operation.

**Architecture:** Factory pattern selects `TEIReranker` or `LiteLLMReranker` based on `models.yaml` provider field. Compose files bundle Ollama + TEI services. Same Docker images as selfhosted.

**Tech Stack:** Python 3.12+, httpx (existing), TEI `/rerank` endpoint, Ollama, Docker Compose

---

## File Structure

**Create:**
- `src/context_service/reranking/tei_reranker.py` - TEI cross-encoder reranker
- `src/context_service/reranking/factory.py` - Reranker factory function
- `tests/reranking/test_tei_reranker.py` - TEI reranker unit tests
- `tests/reranking/test_factory.py` - Factory unit tests
- `docker/docker-compose.standalone-standard.yml` - Standard tier compose
- `docker/docker-compose.standalone-pro.yml` - Pro tier compose

**Modify:**
- `src/context_service/config/models.py:23-31` - Add `url` field to ModelSpec
- `src/context_service/config/models.py:50-52` - Add standalone tiers to Literal
- `src/context_service/reranking/__init__.py` - Export new classes
- `src/context_service/mcp/tools/context_query.py:27,150-182` - Use factory
- `config/models.yaml` - Add standalone tier definitions
- `docker/docker-compose.standalone-lite.yml` - Update to 768d embeddings

---

## Task 1: Add `url` field to ModelSpec

**Files:**
- Modify: `src/context_service/config/models.py:23-31`
- Test: `tests/config/test_models.py`

- [ ] **Step 1: Write failing test for ModelSpec.url**

```python
# tests/config/test_models.py - add to existing file

def test_model_spec_with_url() -> None:
    """ModelSpec should accept optional url field for TEI endpoints."""
    spec = ModelSpec(
        provider="tei",
        model="BAAI/bge-reranker-v2-m3",
        url="http://tei-reranker:8080",
    )
    assert spec.url == "http://tei-reranker:8080"


def test_model_spec_url_defaults_to_none() -> None:
    """ModelSpec.url should be None when not provided."""
    spec = ModelSpec(provider="vertex_ai", model="text-embedding-005")
    assert spec.url is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/config/test_models.py::test_model_spec_with_url -v`
Expected: FAIL with `unexpected keyword argument 'url'`

- [ ] **Step 3: Add url field to ModelSpec**

```python
# src/context_service/config/models.py

class ModelSpec(BaseModel):
    """Specification for a single model."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    provider: str
    model: str
    dimensions: int | None = None
    url: str | None = None  # TEI reranker endpoint URL
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/config/test_models.py::test_model_spec_with_url tests/config/test_models.py::test_model_spec_url_defaults_to_none -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/config/models.py tests/config/test_models.py
git commit -m "feat(config): add url field to ModelSpec for TEI endpoints"
```

---

## Task 2: Add standalone tiers to ModelsConfig Literal

**Files:**
- Modify: `src/context_service/config/models.py:50-52`
- Test: `tests/config/test_models.py`

- [ ] **Step 1: Write failing test for standalone tier**

```python
# tests/config/test_models.py - add to existing file

def test_models_config_accepts_standalone_tiers() -> None:
    """ModelsConfig should accept standalone tier values."""
    # Minimal tier config for testing
    tier_config = TierConfig(
        embeddings=ModelSpec(provider="tei", model="nomic-embed-v1.5", dimensions=768),
        reasoning=ModelSpec(provider="ollama", model="gemma4:e4b"),
        fast=ModelSpec(provider="ollama", model="gemma4:e4b"),
    )
    config = ModelsConfig(
        tier="standalone_lite",
        tiers={"standalone_lite": tier_config},
    )
    assert config.tier == "standalone_lite"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/config/test_models.py::test_models_config_accepts_standalone_tiers -v`
Expected: FAIL with `Input should be 'economy', 'balanced'...`

- [ ] **Step 3: Update ModelsConfig.tier Literal**

```python
# src/context_service/config/models.py

class ModelsConfig(BaseModel):
    """Central model configuration with tier presets."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    tier: Literal[
        "economy",
        "balanced",
        "premium",
        "hybrid",
        "self_hosted",
        "self_hosted_budget",
        "standalone_lite",
        "standalone_standard",
        "standalone_pro",
    ] = "balanced"
    vertex_location: str = "us-central1"
    vertex_project: str = ""
    tiers: dict[str, TierConfig]
    task_mapping: dict[str, str] = Field(default_factory=dict)
    overrides: dict[str, ModelSpec] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/config/test_models.py::test_models_config_accepts_standalone_tiers -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/config/models.py tests/config/test_models.py
git commit -m "feat(config): add standalone tiers to ModelsConfig"
```

---

## Task 3: Create TEIReranker class

**Files:**
- Create: `src/context_service/reranking/tei_reranker.py`
- Create: `tests/reranking/test_tei_reranker.py`

- [ ] **Step 1: Write failing test for TEIReranker**

```python
# tests/reranking/test_tei_reranker.py

"""Tests for TEIReranker."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from context_service.reranking.reranker import RerankResult


class TestTEIReranker:
    @pytest.mark.asyncio
    async def test_rerank_returns_results(self) -> None:
        """TEIReranker should return RerankResult list from TEI response."""
        from context_service.reranking.tei_reranker import TEIReranker

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"index": 1, "score": 0.95},
            {"index": 0, "score": 0.80},
            {"index": 2, "score": 0.60},
        ]

        with patch("context_service.reranking.tei_reranker.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            reranker = TEIReranker(
                base_url="http://tei-reranker:8080",
                model="BAAI/bge-reranker-v2-m3",
            )
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

    @pytest.mark.asyncio
    async def test_rerank_empty_documents(self) -> None:
        """TEIReranker should return empty list for empty documents."""
        from context_service.reranking.tei_reranker import TEIReranker

        reranker = TEIReranker(
            base_url="http://tei-reranker:8080",
            model="BAAI/bge-reranker-v2-m3",
        )
        results = await reranker.rerank(
            query="test",
            documents=[],
            node_ids=[],
            top_k=10,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_rerank_validates_document_node_id_length(self) -> None:
        """TEIReranker should raise ValueError if documents and node_ids mismatch."""
        from context_service.reranking.tei_reranker import TEIReranker

        reranker = TEIReranker(
            base_url="http://tei-reranker:8080",
            model="BAAI/bge-reranker-v2-m3",
        )
        with pytest.raises(ValueError, match="must have same length"):
            await reranker.rerank(
                query="test",
                documents=["doc1", "doc2"],
                node_ids=["node-1"],
                top_k=2,
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/reranking/test_tei_reranker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'context_service.reranking.tei_reranker'`

- [ ] **Step 3: Implement TEIReranker**

```python
# src/context_service/reranking/tei_reranker.py

"""TEI cross-encoder reranking via /rerank endpoint."""

from __future__ import annotations

import asyncio

import httpx
import structlog

from context_service.reranking.reranker import RerankResult

logger = structlog.get_logger(__name__)

MAX_RETRIES = 2
RETRY_BASE_DELAY = 0.1


class TEIRerankerError(Exception):
    """Raised when TEI reranking fails."""

    pass


class TEIReranker:
    """Cross-encoder reranking via TEI /rerank endpoint.

    TEI rerank endpoint expects:
        POST /rerank
        {"query": "...", "texts": ["...", "..."]}

    Returns:
        [{"index": 0, "score": 0.95}, ...]
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 10.0,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max_retries

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
            documents: List of document texts to rerank.
            node_ids: Corresponding node IDs for each document.
            top_k: Number of top results to return.

        Returns:
            List of RerankResult sorted by relevance score descending.

        Raises:
            ValueError: If documents and node_ids have different lengths.
            TEIRerankerError: If TEI request fails after retries.
        """
        if not documents:
            return []

        if len(documents) != len(node_ids):
            raise ValueError(
                f"documents ({len(documents)}) and node_ids ({len(node_ids)}) must have same length"
            )

        payload = {
            "query": query,
            "texts": documents,
        }

        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=self._timeout,
                ) as client:
                    response = await client.post("/rerank", json=payload)
                    response.raise_for_status()
                    data = response.json()

                    results = [
                        RerankResult(
                            node_id=node_ids[item["index"]],
                            score=item["score"],
                            original_rank=item["index"],
                        )
                        for item in data[:top_k]
                    ]
                    return results

            except Exception as e:
                if attempt < self._max_retries:
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    logger.debug(
                        "tei_rerank_retry",
                        attempt=attempt + 1,
                        error=str(e),
                        delay=delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.warning(
                    "tei_rerank_failed",
                    error=str(e),
                    base_url=self._base_url,
                    model=self._model,
                )
                raise TEIRerankerError(f"TEI rerank failed: {e}") from e

        raise RuntimeError("tei_rerank: unreachable")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/reranking/test_tei_reranker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/reranking/tei_reranker.py tests/reranking/test_tei_reranker.py
git commit -m "feat(reranking): add TEIReranker for local cross-encoder reranking"
```

---

## Task 4: Create reranker factory

**Files:**
- Create: `src/context_service/reranking/factory.py`
- Create: `tests/reranking/test_factory.py`
- Modify: `src/context_service/reranking/__init__.py`

- [ ] **Step 1: Write failing test for factory**

```python
# tests/reranking/test_factory.py

"""Tests for reranker factory."""

from __future__ import annotations

import pytest

from context_service.config.models import ModelSpec, ModelsConfig, TierConfig


class TestGetReranker:
    def test_returns_none_when_no_reranker_configured(self) -> None:
        """Factory should return None when tier has no reranker."""
        from context_service.reranking.factory import get_reranker

        tier_config = TierConfig(
            embeddings=ModelSpec(provider="tei", model="nomic-embed-v1.5", dimensions=768),
            reasoning=ModelSpec(provider="ollama", model="gemma4:e4b"),
            fast=ModelSpec(provider="ollama", model="gemma4:e4b"),
            reranker=None,
        )
        config = ModelsConfig(
            tier="standalone_lite",
            tiers={"standalone_lite": tier_config},
        )

        reranker = get_reranker(config)
        assert reranker is None

    def test_returns_tei_reranker_for_tei_provider(self) -> None:
        """Factory should return TEIReranker when provider is 'tei'."""
        from context_service.reranking.factory import get_reranker
        from context_service.reranking.tei_reranker import TEIReranker

        tier_config = TierConfig(
            embeddings=ModelSpec(provider="tei", model="nomic-embed-v2", dimensions=768),
            reasoning=ModelSpec(provider="ollama", model="gemma4:12b"),
            fast=ModelSpec(provider="ollama", model="gemma4:12b"),
            reranker=ModelSpec(
                provider="tei",
                model="BAAI/bge-reranker-v2-m3",
                url="http://tei-reranker:8080",
            ),
        )
        config = ModelsConfig(
            tier="standalone_standard",
            tiers={"standalone_standard": tier_config},
        )

        reranker = get_reranker(config)
        assert isinstance(reranker, TEIReranker)

    def test_returns_litellm_reranker_for_vertex_provider(self) -> None:
        """Factory should return LiteLLMReranker for non-TEI providers."""
        from context_service.reranking.factory import get_reranker
        from context_service.reranking.reranker import LiteLLMReranker

        tier_config = TierConfig(
            embeddings=ModelSpec(provider="vertex_ai", model="text-embedding-005", dimensions=768),
            reasoning=ModelSpec(provider="vertex_ai", model="gemini-2.5-pro"),
            fast=ModelSpec(provider="vertex_ai", model="gemini-2.5-flash"),
            reranker=ModelSpec(
                provider="vertex_ai",
                model="semantic-ranker-default@latest",
            ),
        )
        config = ModelsConfig(
            tier="balanced",
            vertex_project="my-project",
            tiers={"balanced": tier_config},
        )

        reranker = get_reranker(config)
        assert isinstance(reranker, LiteLLMReranker)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/reranking/test_factory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'context_service.reranking.factory'`

- [ ] **Step 3: Implement factory**

```python
# src/context_service/reranking/factory.py

"""Reranker factory - selects implementation based on config."""

from __future__ import annotations

from typing import TYPE_CHECKING

from context_service.reranking.reranker import LiteLLMReranker
from context_service.reranking.tei_reranker import TEIReranker

if TYPE_CHECKING:
    from context_service.config.models import ModelsConfig


def get_reranker(
    config: ModelsConfig,
    timeout_seconds: float = 10.0,
) -> LiteLLMReranker | TEIReranker | None:
    """Create appropriate reranker based on models config.

    Args:
        config: Models configuration with tier and reranker spec.
        timeout_seconds: Timeout for reranker requests.

    Returns:
        LiteLLMReranker for cloud providers (vertex_ai, cohere, jina).
        TEIReranker for local TEI deployment.
        None if no reranker is configured for the tier.
    """
    spec = config.get_reranker_model()
    if spec is None:
        return None

    if spec.provider == "tei":
        if not spec.url:
            raise ValueError("TEI reranker requires 'url' field in ModelSpec")
        return TEIReranker(
            base_url=spec.url,
            model=spec.model,
            timeout_seconds=timeout_seconds,
        )

    # LiteLLM providers (vertex_ai, cohere, jina, etc.)
    return LiteLLMReranker(
        model=f"{spec.provider}/{spec.model}",
        timeout_seconds=timeout_seconds,
        vertex_project=config.vertex_project or None,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/reranking/test_factory.py -v`
Expected: PASS

- [ ] **Step 5: Update __init__.py exports**

```python
# src/context_service/reranking/__init__.py

"""Semantic reranking for improved recall accuracy."""

from context_service.reranking.factory import get_reranker
from context_service.reranking.quality import (
    LAYER_THRESHOLDS,
    RERANK_SCORE_FLOOR,
    RetrievalQuality,
    apply_threshold_filter,
    classify_quality,
    compute_adaptive_threshold,
    compute_retrieval_quality,
)
from context_service.reranking.query_classifier import is_hard_query
from context_service.reranking.query_expander import QueryExpander
from context_service.reranking.reranker import LiteLLMReranker, RerankResult
from context_service.reranking.tei_reranker import TEIReranker, TEIRerankerError

__all__ = [
    "LAYER_THRESHOLDS",
    "RERANK_SCORE_FLOOR",
    "LiteLLMReranker",
    "QueryExpander",
    "RerankResult",
    "RetrievalQuality",
    "TEIReranker",
    "TEIRerankerError",
    "apply_threshold_filter",
    "classify_quality",
    "compute_adaptive_threshold",
    "compute_retrieval_quality",
    "get_reranker",
    "is_hard_query",
]
```

- [ ] **Step 6: Commit**

```bash
git add src/context_service/reranking/factory.py src/context_service/reranking/__init__.py tests/reranking/test_factory.py
git commit -m "feat(reranking): add factory for provider-based reranker selection"
```

---

## Task 5: Update context_query.py to use factory

**Files:**
- Modify: `src/context_service/mcp/tools/context_query.py`

- [ ] **Step 1: Locate and read the reranking section**

Run: `grep -n "LiteLLMReranker\|reranker_model" src/context_service/mcp/tools/context_query.py`

- [ ] **Step 2: Update imports**

Replace:
```python
from context_service.reranking import (
    RERANK_SCORE_FLOOR,
    LiteLLMReranker,
    QueryExpander,
    apply_threshold_filter,
    compute_adaptive_threshold,
    compute_retrieval_quality,
    is_hard_query,
)
```

With:
```python
from context_service.reranking import (
    RERANK_SCORE_FLOOR,
    QueryExpander,
    apply_threshold_filter,
    compute_adaptive_threshold,
    compute_retrieval_quality,
    get_reranker,
    is_hard_query,
)
```

- [ ] **Step 3: Update reranker instantiation**

Find and replace the reranker creation block (around lines 150-185). Replace:
```python
    models_config = load_models_config()
    reranker_model = models_config.litellm_reranker_model
    if reranker_model is None:
        return results, False, False
    
    # ... cache lookup ...
    
    reranker = LiteLLMReranker(
        model=reranker_model,
        timeout_seconds=settings.reranking.reranker_timeout_seconds,
        vertex_project=settings.vertex_project,
    )
```

With:
```python
    models_config = load_models_config()
    reranker = get_reranker(
        config=models_config,
        timeout_seconds=settings.reranking.reranker_timeout_seconds,
    )
    if reranker is None:
        return results, False, False
    
    # ... cache lookup unchanged ...
```

- [ ] **Step 4: Run existing tests to verify no regression**

Run: `uv run pytest tests/mcp/tools/test_context_query.py -v -k rerank`
Expected: PASS (or skip if no specific rerank tests)

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/context_query.py
git commit -m "refactor(mcp): use reranker factory in context_query"
```

---

## Task 6: Add standalone tiers to models.yaml

**Files:**
- Modify: `config/models.yaml`

- [ ] **Step 1: Add standalone_lite tier**

Add after `standalone_standard` (existing):
```yaml
  standalone_lite:
    embeddings:
      provider: tei
      model: nomic-ai/nomic-embed-text-v1.5
      dimensions: 768
    reasoning:
      provider: ollama
      model: gemma4:e4b
    fast:
      provider: ollama
      model: gemma4:e4b
    # reranker: intentionally absent for lite tier
```

- [ ] **Step 2: Update standalone_standard tier**

Update existing `standalone_standard`:
```yaml
  standalone_standard:
    embeddings:
      provider: tei
      model: nomic-ai/nomic-embed-text-v2-moe
      dimensions: 768
    reasoning:
      provider: ollama
      model: gemma4:12b
    fast:
      provider: ollama
      model: gemma4:12b
    reranker:
      provider: tei
      model: BAAI/bge-reranker-v2-m3
      url: http://tei-reranker:8080
```

- [ ] **Step 3: Add standalone_pro tier**

```yaml
  standalone_pro:
    embeddings:
      provider: tei
      model: nomic-ai/nomic-embed-text-v2-moe
      dimensions: 768
    reasoning:
      provider: ollama
      model: gemma4:26b
    fast:
      provider: ollama
      model: gemma4:12b
    reranker:
      provider: tei
      model: jinaai/jina-reranker-v2-base-multilingual
      url: http://tei-reranker:8080
```

- [ ] **Step 4: Validate YAML syntax**

Run: `uv run python -c "import yaml; yaml.safe_load(open('config/models.yaml'))"`
Expected: No error

- [ ] **Step 5: Commit**

```bash
git add config/models.yaml
git commit -m "feat(config): add standalone tier definitions to models.yaml"
```

---

## Task 7: Update standalone-lite compose file

**Files:**
- Modify: `docker/docker-compose.standalone-lite.yml`

- [ ] **Step 1: Update embedding dimensions to 768**

Change `EMBEDDING_DIMENSIONS=384` to `EMBEDDING_DIMENSIONS=768`

- [ ] **Step 2: Update TEI model to nomic-embed-v1.5**

Change TEI command from `all-MiniLM-L6-v2` to `nomic-ai/nomic-embed-text-v1.5`

- [ ] **Step 3: Update Ollama model to gemma4:e4b**

Change entrypoint from `phi4-mini` to `gemma4:e4b`

- [ ] **Step 4: Add MODELS__TIER environment variable**

Add to app and dagster services:
```yaml
      - MODELS__TIER=standalone_lite
```

- [ ] **Step 5: Validate compose syntax**

Run: `docker compose -f docker/docker-compose.standalone-lite.yml config --quiet`
Expected: No error

- [ ] **Step 6: Commit**

```bash
git add docker/docker-compose.standalone-lite.yml
git commit -m "feat(docker): update standalone-lite to 768d embeddings and gemma4"
```

---

## Task 8: Create standalone-standard compose file

**Files:**
- Create: `docker/docker-compose.standalone-standard.yml` (copy and modify from standalone.yml)

- [ ] **Step 1: Copy existing standalone.yml**

Run: `cp docker/docker-compose.standalone.yml docker/docker-compose.standalone-standard.yml`

- [ ] **Step 2: Update header comment**

```yaml
# docker/docker-compose.standalone-standard.yml
# Engrammic Standalone Standard - 32GB RAM recommended
# Includes: Ollama (gemma4:12b), TEI embeddings, TEI reranker
```

- [ ] **Step 3: Update MODELS__TIER**

Change to `MODELS__TIER=standalone_standard`

- [ ] **Step 4: Add tei-reranker service**

Add after tei service:
```yaml
  tei-reranker:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.5
    container_name: engrammic-tei-reranker
    ports:
      - "8082:8080"
    command: ["--model-id", "BAAI/bge-reranker-v2-m3"]
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8080/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s
    deploy:
      resources:
        limits:
          memory: 2G
    restart: unless-stopped
```

- [ ] **Step 5: Update Ollama model to gemma4:12b**

Change entrypoint model pull to `gemma4:12b`

- [ ] **Step 6: Update TEI embed model to nomic-v2**

Change TEI command to `nomic-ai/nomic-embed-text-v2-moe`

- [ ] **Step 7: Add app dependency on tei-reranker**

Add to app service depends_on:
```yaml
      tei-reranker:
        condition: service_healthy
```

- [ ] **Step 8: Validate compose syntax**

Run: `docker compose -f docker/docker-compose.standalone-standard.yml config --quiet`
Expected: No error

- [ ] **Step 9: Commit**

```bash
git add docker/docker-compose.standalone-standard.yml
git commit -m "feat(docker): add standalone-standard compose with TEI reranker"
```

---

## Task 9: Create standalone-pro compose file

**Files:**
- Create: `docker/docker-compose.standalone-pro.yml`

- [ ] **Step 1: Copy standalone-standard**

Run: `cp docker/docker-compose.standalone-standard.yml docker/docker-compose.standalone-pro.yml`

- [ ] **Step 2: Update header comment**

```yaml
# docker/docker-compose.standalone-pro.yml
# Engrammic Standalone Pro - 64GB RAM recommended
# Includes: Ollama (gemma4:26b), TEI embeddings, Jina reranker
```

- [ ] **Step 3: Update MODELS__TIER**

Change to `MODELS__TIER=standalone_pro`

- [ ] **Step 4: Update Ollama model to gemma4:26b**

Change entrypoint model pull to `gemma4:26b`

- [ ] **Step 5: Update Ollama memory limit**

Change memory limit to `20G`

- [ ] **Step 6: Update reranker model to Jina**

Change tei-reranker command to:
```yaml
    command: ["--model-id", "jinaai/jina-reranker-v2-base-multilingual"]
```

- [ ] **Step 7: Validate compose syntax**

Run: `docker compose -f docker/docker-compose.standalone-pro.yml config --quiet`
Expected: No error

- [ ] **Step 8: Commit**

```bash
git add docker/docker-compose.standalone-pro.yml
git commit -m "feat(docker): add standalone-pro compose with gemma4:26b and jina reranker"
```

---

## Task 10: Add reranker status to health endpoint

**Files:**
- Modify: `src/context_service/api/health.py` (or equivalent health endpoint)

- [ ] **Step 1: Find health endpoint**

Run: `grep -r "def health\|async def health" src/context_service/`

- [ ] **Step 2: Add reranker status helper**

Add to health module:
```python
async def get_reranker_status() -> str:
    """Get reranker availability status.
    
    Returns:
        "disabled" - No reranker configured (lite tier)
        "ready" - Reranker available and responding
        "unavailable" - Reranker configured but not responding
    """
    from context_service.config.models import load_models_config
    from context_service.reranking import get_reranker
    
    config = load_models_config()
    reranker = get_reranker(config)
    
    if reranker is None:
        return "disabled"
    
    try:
        # Minimal probe - empty docs returns immediately without network call
        await reranker.rerank("probe", ["test"], ["probe-id"], top_k=1)
        return "ready"
    except Exception:
        return "unavailable"
```

- [ ] **Step 3: Include in health response**

Update health endpoint response to include:
```python
{
    "status": "healthy",
    "reranker": await get_reranker_status(),
    # ... other fields
}
```

- [ ] **Step 4: Commit**

```bash
git add src/context_service/api/health.py
git commit -m "feat(health): add reranker status to health endpoint"
```

---

## Task 11: Run full test suite

**Files:** None (verification only)

- [ ] **Step 1: Run type check**

Run: `uv run mypy src/context_service/reranking/`
Expected: PASS with no errors

- [ ] **Step 2: Run lint**

Run: `uv run ruff check src/context_service/reranking/`
Expected: PASS with no errors

- [ ] **Step 3: Run all reranking tests**

Run: `uv run pytest tests/reranking/ -v`
Expected: All tests PASS

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -x --ignore=tests/integration`
Expected: PASS (some skips OK)

- [ ] **Step 5: Commit any fixes**

If any fixes needed:
```bash
git add -A
git commit -m "fix: address test/lint issues from standalone implementation"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Add url to ModelSpec | models.py |
| 2 | Add standalone tiers to Literal | models.py |
| 3 | Create TEIReranker | tei_reranker.py |
| 4 | Create factory | factory.py |
| 5 | Update context_query | context_query.py |
| 6 | Add tiers to models.yaml | models.yaml |
| 7 | Update standalone-lite compose | docker-compose.standalone-lite.yml |
| 8 | Create standalone-standard compose | docker-compose.standalone-standard.yml |
| 9 | Create standalone-pro compose | docker-compose.standalone-pro.yml |
| 10 | Add reranker status to health | health.py |
| 11 | Verify full test suite | - |

**Note:** Installer changes (mcp-client repo) are a separate plan.
