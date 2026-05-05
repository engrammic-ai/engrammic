# Auto-Tagging System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement hybrid sync/async auto-tagging with per-silo vocabulary stored in Postgres.

**Architecture:** Sync cosine matching at store time (~0.1ms) using numpy, async LLM refinement via Dagster every 30min. Tag config stored in Postgres for dashboard support, candidates tracked in Redis with TTL.

**Tech Stack:** SQLAlchemy 2.0 + asyncpg, Alembic, numpy, existing LLMProvider, Dagster

---

## File Structure

| File | Purpose |
|------|---------|
| `src/context_service/db/postgres.py` | Async Postgres session factory |
| `src/context_service/models/tag_config.py` | SQLAlchemy model for SiloTagConfig |
| `src/context_service/services/tag_config.py` | CRUD service for tag config |
| `src/context_service/services/auto_tagging.py` | Sync cosine matching + vocab cache |
| `src/context_service/pipelines/assets/auto_tagging.py` | Async LLM refinement asset |
| `src/context_service/pipelines/assets/tag_maintenance.py` | Vocabulary pruning asset |
| `src/context_service/config/tags.yaml` | System defaults |
| `alembic/versions/001_add_silo_tag_configs.py` | Migration |
| `tests/services/test_auto_tagging.py` | Unit tests for cosine matching |
| `tests/services/test_tag_config.py` | Unit tests for CRUD |

---

### Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add SQLAlchemy and asyncpg dependencies**

```toml
# Add to [project.optional-dependencies] under a new "postgres" extra
# Or add to main dependencies if Postgres is now required

# In pyproject.toml, add to dependencies list:
"sqlalchemy[asyncio]>=2.0.0",
"asyncpg>=0.29.0",
"alembic>=1.13.0",
```

- [ ] **Step 2: Run uv lock and sync**

Run: `uv lock && uv sync --all-extras`
Expected: Dependencies installed successfully

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add sqlalchemy, asyncpg, alembic dependencies"
```

---

### Task 2: Create Postgres Session Infrastructure

**Files:**
- Create: `src/context_service/db/postgres.py`
- Test: `tests/db/test_postgres.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/db/test_postgres.py
import pytest
from unittest.mock import AsyncMock, patch

from context_service.db.postgres import create_async_engine, get_session


@pytest.mark.asyncio
async def test_get_session_returns_async_session():
    with patch("context_service.db.postgres._engine") as mock_engine:
        mock_engine.return_value = AsyncMock()
        async with get_session() as session:
            assert session is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/db/test_postgres.py -v`
Expected: FAIL with "No module named 'context_service.db.postgres'"

- [ ] **Step 3: Create the postgres module**

```python
# src/context_service/db/postgres.py
"""Async Postgres session management using SQLAlchemy 2.0."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from context_service.config.settings import get_settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_postgres() -> AsyncEngine:
    """Initialize the Postgres connection pool."""
    global _engine, _session_factory
    
    settings = get_settings()
    dsn = settings.postgres_dsn.get_secret_value()
    
    # Convert postgresql:// to postgresql+asyncpg://
    if dsn.startswith("postgresql://"):
        dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    _engine = create_async_engine(
        dsn,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    return _engine


async def close_postgres() -> None:
    """Close the Postgres connection pool."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async session from the pool."""
    if _session_factory is None:
        await init_postgres()
    
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

- [ ] **Step 4: Update db __init__.py**

```python
# src/context_service/db/__init__.py
# Add to existing exports:
from context_service.db.postgres import Base, get_session, init_postgres, close_postgres
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/db/test_postgres.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/db/postgres.py tests/db/test_postgres.py
git commit -m "feat: add async Postgres session infrastructure"
```

---

### Task 3: Create SiloTagConfig Model

**Files:**
- Create: `src/context_service/models/tag_config.py`
- Test: `tests/models/test_tag_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/models/test_tag_config.py
import uuid
from context_service.models.tag_config import SiloTagConfig, DEFAULT_SETTINGS


def test_silo_tag_config_defaults():
    config = SiloTagConfig(silo_id=uuid.uuid4())
    assert config.core_tags == []
    assert config.dynamic_tags == []
    assert config.settings == DEFAULT_SETTINGS
    assert config.constraints == {"hierarchy": {}, "layer_hints": {}, "mutual_exclusion": []}


def test_default_settings_has_required_keys():
    assert "min_tags" in DEFAULT_SETTINGS
    assert "max_tags" in DEFAULT_SETTINGS
    assert "cosine_threshold" in DEFAULT_SETTINGS
    assert "promotion_threshold" in DEFAULT_SETTINGS
    assert "demotion_days" in DEFAULT_SETTINGS
    assert "synonym_threshold" in DEFAULT_SETTINGS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/models/test_tag_config.py -v`
Expected: FAIL with "No module named 'context_service.models.tag_config'"

- [ ] **Step 3: Create the model**

```python
# src/context_service/models/tag_config.py
"""SQLAlchemy model for per-silo tag configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String

from context_service.db.postgres import Base


DEFAULT_SETTINGS: dict[str, Any] = {
    "min_tags": 2,
    "max_tags": 5,
    "cosine_threshold": 0.4,
    "promotion_threshold": 3,
    "demotion_days": 30,
    "synonym_threshold": 0.85,
}

DEFAULT_CONSTRAINTS: dict[str, Any] = {
    "hierarchy": {},
    "layer_hints": {},
    "mutual_exclusion": [],
}


class SiloTagConfig(Base):
    """Per-silo tag configuration stored in Postgres."""
    
    __tablename__ = "silo_tag_configs"
    
    silo_id: Mapped[UUID] = mapped_column(primary_key=True)
    core_tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default="{}"
    )
    dynamic_tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default="{}"
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=lambda: DEFAULT_SETTINGS.copy()
    )
    constraints: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=lambda: DEFAULT_CONSTRAINTS.copy()
    )
    created_at: Mapped[datetime] = mapped_column(
        default=func.now(), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        onupdate=func.now(), default=None
    )
    
    def all_tags(self) -> list[str]:
        """Return combined core + dynamic tags."""
        return list(set(self.core_tags + self.dynamic_tags))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/models/test_tag_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/models/tag_config.py tests/models/test_tag_config.py
git commit -m "feat: add SiloTagConfig SQLAlchemy model"
```

---

### Task 4: Create Alembic Migration

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/001_add_silo_tag_configs.py`

- [ ] **Step 1: Initialize Alembic**

Run: `uv run alembic init alembic`

- [ ] **Step 2: Configure alembic.ini**

Edit `alembic.ini`:
```ini
# Change sqlalchemy.url line to:
sqlalchemy.url = postgresql+asyncpg://user:password@localhost:5432/context_service
```

- [ ] **Step 3: Update alembic/env.py for async**

```python
# alembic/env.py
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from context_service.db.postgres import Base
from context_service.models.tag_config import SiloTagConfig  # noqa: F401 - registers model

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Generate migration**

Run: `uv run alembic revision --autogenerate -m "add silo_tag_configs table"`

- [ ] **Step 5: Verify generated migration**

Check `alembic/versions/*_add_silo_tag_configs.py` contains:
- `op.create_table("silo_tag_configs", ...)`
- Columns: silo_id, core_tags, dynamic_tags, settings, constraints, created_at, updated_at

- [ ] **Step 6: Commit**

```bash
git add alembic.ini alembic/
git commit -m "feat: add Alembic migration for silo_tag_configs"
```

---

### Task 5: Create TagConfigService

**Files:**
- Create: `src/context_service/services/tag_config.py`
- Test: `tests/services/test_tag_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/services/test_tag_config.py
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from context_service.services.tag_config import TagConfigService
from context_service.models.tag_config import SiloTagConfig


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def service(mock_session):
    return TagConfigService(mock_session)


@pytest.mark.asyncio
async def test_get_or_create_returns_new_config_when_not_exists(service, mock_session):
    silo_id = uuid.uuid4()
    mock_session.get.return_value = None
    
    config = await service.get_or_create(silo_id)
    
    assert config.silo_id == silo_id
    assert config.core_tags == []
    mock_session.add.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_returns_existing_config(service, mock_session):
    silo_id = uuid.uuid4()
    existing = SiloTagConfig(silo_id=silo_id, core_tags=["test"])
    mock_session.get.return_value = existing
    
    config = await service.get_or_create(silo_id)
    
    assert config.core_tags == ["test"]
    mock_session.add.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/services/test_tag_config.py -v`
Expected: FAIL with "No module named 'context_service.services.tag_config'"

- [ ] **Step 3: Create the service**

```python
# src/context_service/services/tag_config.py
"""CRUD service for per-silo tag configuration."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from context_service.models.tag_config import SiloTagConfig


class TagConfigService:
    """Manages per-silo tag configuration in Postgres."""
    
    def __init__(self, session: AsyncSession):
        self._session = session
    
    async def get(self, silo_id: UUID) -> SiloTagConfig | None:
        """Get tag config for a silo, or None if not exists."""
        return await self._session.get(SiloTagConfig, silo_id)
    
    async def get_or_create(self, silo_id: UUID) -> SiloTagConfig:
        """Get existing config or create default config for silo."""
        config = await self.get(silo_id)
        if config is None:
            config = SiloTagConfig(silo_id=silo_id)
            self._session.add(config)
            await self._session.flush()
        return config
    
    async def add_core_tags(self, silo_id: UUID, tags: list[str]) -> SiloTagConfig:
        """Add tags to core (protected) vocabulary."""
        config = await self.get_or_create(silo_id)
        config.core_tags = list(set(config.core_tags + tags))
        await self._session.flush()
        return config
    
    async def add_dynamic_tags(self, silo_id: UUID, tags: list[str]) -> SiloTagConfig:
        """Add tags to dynamic vocabulary."""
        config = await self.get_or_create(silo_id)
        config.dynamic_tags = list(set(config.dynamic_tags + tags))
        await self._session.flush()
        return config
    
    async def remove_dynamic_tags(self, silo_id: UUID, tags: list[str]) -> SiloTagConfig:
        """Remove tags from dynamic vocabulary (demote)."""
        config = await self.get_or_create(silo_id)
        config.dynamic_tags = [t for t in config.dynamic_tags if t not in tags]
        await self._session.flush()
        return config
    
    async def update_settings(self, silo_id: UUID, settings: dict) -> SiloTagConfig:
        """Update tag settings (merge with existing)."""
        config = await self.get_or_create(silo_id)
        config.settings = {**config.settings, **settings}
        await self._session.flush()
        return config
    
    async def update_constraints(self, silo_id: UUID, constraints: dict) -> SiloTagConfig:
        """Update tag constraints (merge with existing)."""
        config = await self.get_or_create(silo_id)
        config.constraints = {**config.constraints, **constraints}
        await self._session.flush()
        return config
    
    async def get_all_tags(self, silo_id: UUID) -> list[str]:
        """Get combined core + dynamic tags for a silo."""
        config = await self.get(silo_id)
        if config is None:
            return []
        return config.all_tags()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/services/test_tag_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/services/tag_config.py tests/services/test_tag_config.py
git commit -m "feat: add TagConfigService for CRUD operations"
```

---

### Task 6: Create AutoTaggingService (Sync Cosine Matching)

**Files:**
- Create: `src/context_service/services/auto_tagging.py`
- Test: `tests/services/test_auto_tagging.py`

- [ ] **Step 1: Write the failing test for VocabCache**

```python
# tests/services/test_auto_tagging.py
import numpy as np
import pytest

from context_service.services.auto_tagging import VocabCache


def test_vocab_cache_match_returns_matching_tags():
    tags = ["database", "api", "frontend"]
    # Create embeddings where "database" is similar to query
    vectors = np.array([
        [1.0, 0.0, 0.0],  # database
        [0.0, 1.0, 0.0],  # api
        [0.0, 0.0, 1.0],  # frontend
    ], dtype=np.float32)
    
    cache = VocabCache(tags=tags, matrix=vectors, loaded_at=0.0)
    
    # Query vector similar to "database"
    query = np.array([0.9, 0.1, 0.0], dtype=np.float32)
    
    matches = cache.match(query, threshold=0.4, max_tags=5)
    
    assert "database" in matches
    assert len(matches) <= 5


def test_vocab_cache_match_respects_threshold():
    tags = ["tag1", "tag2"]
    vectors = np.array([
        [1.0, 0.0],
        [0.0, 1.0],
    ], dtype=np.float32)
    
    cache = VocabCache(tags=tags, matrix=vectors, loaded_at=0.0)
    query = np.array([1.0, 0.0], dtype=np.float32)
    
    # High threshold - only exact match
    matches = cache.match(query, threshold=0.99, max_tags=5)
    assert matches == ["tag1"]
    
    # Low threshold - both match
    matches = cache.match(query, threshold=0.0, max_tags=5)
    assert len(matches) == 2


def test_vocab_cache_match_respects_max_tags():
    tags = ["t1", "t2", "t3", "t4", "t5"]
    vectors = np.eye(5, dtype=np.float32)
    
    cache = VocabCache(tags=tags, matrix=vectors, loaded_at=0.0)
    query = np.ones(5, dtype=np.float32)
    
    matches = cache.match(query, threshold=0.0, max_tags=2)
    assert len(matches) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/services/test_auto_tagging.py::test_vocab_cache_match_returns_matching_tags -v`
Expected: FAIL with "No module named 'context_service.services.auto_tagging'"

- [ ] **Step 3: Create VocabCache class**

```python
# src/context_service/services/auto_tagging.py
"""Auto-tagging service with sync cosine matching."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import numpy as np

if TYPE_CHECKING:
    from context_service.embeddings import EmbeddingService
    from context_service.services.tag_config import TagConfigService


@dataclass(slots=True)
class VocabCache:
    """Cached vocabulary with pre-normalized embedding matrix."""
    
    tags: list[str]
    matrix: np.ndarray  # (n_tags, dim), pre-normalized
    loaded_at: float
    
    def match(
        self,
        content_vec: np.ndarray,
        threshold: float,
        max_tags: int,
    ) -> list[str]:
        """Find tags with cosine similarity above threshold."""
        if len(self.tags) == 0:
            return []
        
        # Normalize query vector
        norm = np.linalg.norm(content_vec)
        if norm == 0:
            return []
        vec = content_vec / norm
        
        # Compute cosine similarities via matrix multiply
        scores = self.matrix @ vec
        
        # Sort by score descending
        indices = np.argsort(-scores)
        
        # Filter by threshold and limit
        return [
            self.tags[i]
            for i in indices
            if scores[i] > threshold
        ][:max_tags]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/services/test_auto_tagging.py -v`
Expected: PASS

- [ ] **Step 5: Write test for AutoTaggingService**

```python
# tests/services/test_auto_tagging.py (append)
import uuid
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_embedding():
    service = AsyncMock()
    service.embed_batch = AsyncMock(return_value=[
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ])
    return service


@pytest.fixture
def mock_tag_config():
    service = AsyncMock()
    service.get_all_tags = AsyncMock(return_value=["database", "api"])
    return service


@pytest.mark.asyncio
async def test_auto_tagging_service_suggest_tags(mock_embedding, mock_tag_config):
    from context_service.services.auto_tagging import AutoTaggingService
    
    service = AutoTaggingService(
        embedding=mock_embedding,
        tag_config=mock_tag_config,
    )
    
    silo_id = uuid.uuid4()
    content_vector = [0.9, 0.1, 0.0]  # Similar to "database"
    
    tags = await service.suggest_tags(content_vector, str(silo_id))
    
    assert "database" in tags


@pytest.mark.asyncio
async def test_auto_tagging_service_caches_vocabulary(mock_embedding, mock_tag_config):
    from context_service.services.auto_tagging import AutoTaggingService
    
    service = AutoTaggingService(
        embedding=mock_embedding,
        tag_config=mock_tag_config,
    )
    
    silo_id = str(uuid.uuid4())
    content_vector = [1.0, 0.0, 0.0]
    
    # First call loads vocabulary
    await service.suggest_tags(content_vector, silo_id)
    # Second call uses cache
    await service.suggest_tags(content_vector, silo_id)
    
    # embed_batch called only once (cached)
    assert mock_embedding.embed_batch.call_count == 1
```

- [ ] **Step 6: Implement AutoTaggingService**

```python
# src/context_service/services/auto_tagging.py (append to existing file)

class AutoTaggingService:
    """Service for automatic tag suggestion using cosine similarity."""
    
    CACHE_TTL = 300  # 5 minutes
    
    def __init__(
        self,
        embedding: EmbeddingService,
        tag_config: TagConfigService,
    ):
        self._embedding = embedding
        self._tag_config = tag_config
        self._cache: dict[str, VocabCache] = {}
    
    async def load_vocabulary(self, silo_id: str) -> VocabCache | None:
        """Load and cache vocabulary embeddings for a silo."""
        cached = self._cache.get(silo_id)
        if cached and (time.monotonic() - cached.loaded_at) < self.CACHE_TTL:
            return cached
        
        tags = await self._tag_config.get_all_tags(UUID(silo_id))
        if not tags:
            return None
        
        vectors = await self._embedding.embed_batch(tags)
        matrix = np.array(vectors, dtype=np.float32)
        
        # Pre-normalize rows
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1  # Avoid division by zero
        matrix = matrix / norms
        
        self._cache[silo_id] = VocabCache(
            tags=tags,
            matrix=matrix,
            loaded_at=time.monotonic(),
        )
        return self._cache[silo_id]
    
    async def suggest_tags(
        self,
        content_vector: list[float],
        silo_id: str,
        threshold: float = 0.4,
        max_tags: int = 5,
    ) -> list[str]:
        """Suggest tags for content using cosine similarity."""
        vocab = await self.load_vocabulary(silo_id)
        if vocab is None:
            return []
        
        vec = np.array(content_vector, dtype=np.float32)
        return vocab.match(vec, threshold, max_tags)
    
    def invalidate(self, silo_id: str) -> None:
        """Invalidate cached vocabulary for a silo."""
        self._cache.pop(silo_id, None)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/services/test_auto_tagging.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/context_service/services/auto_tagging.py tests/services/test_auto_tagging.py
git commit -m "feat: add AutoTaggingService with numpy cosine matching"
```

---

### Task 7: Integrate Auto-Tagging with ContextService.store()

**Files:**
- Modify: `src/context_service/services/context.py`
- Test: `tests/services/test_context_auto_tagging.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/services/test_context_auto_tagging.py
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from context_service.services.context import ContextService
from context_service.services.models import Node


@pytest.fixture
def mock_auto_tagging():
    service = AsyncMock()
    service.suggest_tags = AsyncMock(return_value=["suggested-tag"])
    return service


@pytest.mark.asyncio
async def test_store_adds_auto_tags_when_service_configured(mock_auto_tagging):
    memgraph = AsyncMock()
    memgraph.execute_query = AsyncMock(return_value=[])
    memgraph.execute_write = AsyncMock(return_value=[{"n": {"id": str(uuid.uuid4())}}])
    
    qdrant = AsyncMock()
    qdrant.upsert = AsyncMock()
    
    embedding = AsyncMock()
    embedding.embed_single = AsyncMock(return_value=[0.1] * 768)
    
    svc = ContextService(
        memgraph=memgraph,
        qdrant=qdrant,
        embedding=embedding,
        auto_tagging=mock_auto_tagging,
    )
    
    node = Node(
        id=uuid.uuid4(),
        type="memory",
        content="Test content for auto-tagging",
    )
    silo_id = uuid.uuid4()
    
    await svc.store(node, silo_id, tags=["user-tag"])
    
    # Verify auto_tagging was called with the content vector
    mock_auto_tagging.suggest_tags.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/services/test_context_auto_tagging.py -v`
Expected: FAIL (auto_tagging parameter not accepted)

- [ ] **Step 3: Add auto_tagging parameter to ContextService**

```python
# src/context_service/services/context.py
# Find the __init__ method and add auto_tagging parameter

# Add import at top:
from context_service.services.auto_tagging import AutoTaggingService

# Modify __init__ signature to include:
def __init__(
    self,
    memgraph: HyperGraphStore,
    qdrant: QdrantClient,
    embedding: EmbeddingService | None = None,
    splade: SpladeEncoder | None = None,
    cache: RedisClient | None = None,
    auto_tagging: AutoTaggingService | None = None,  # Add this
):
    # ... existing init ...
    self._auto_tagging = auto_tagging  # Add this
```

- [ ] **Step 4: Integrate auto-tagging in store() method**

```python
# In ContextService.store(), after embedding is computed and before CREATE query:
# Find the section around line 231 where vector is computed

# After: vector = await self._embedding.embed_single(content)
# Add:
auto_tags: list[str] = []
if vector and self._auto_tagging:
    auto_tags = await self._auto_tagging.suggest_tags(
        vector,
        str(silo_id),
        threshold=0.4,
        max_tags=5,
    )

# Merge auto_tags with user-provided tags
all_tags = list(set((tags or []) + auto_tags))

# Update the CREATE query to use all_tags instead of tags
# And store user_tags and auto_tags separately for the node
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/services/test_context_auto_tagging.py -v`
Expected: PASS

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `uv run pytest tests/ --ignore=tests/e2e --ignore=tests/integration -x --tb=short`
Expected: All existing tests still pass

- [ ] **Step 7: Commit**

```bash
git add src/context_service/services/context.py tests/services/test_context_auto_tagging.py
git commit -m "feat: integrate auto-tagging with ContextService.store()"
```

---

### Task 8: Create Auto-Tagging Dagster Asset

**Files:**
- Create: `src/context_service/pipelines/assets/auto_tagging.py`
- Test: `tests/pipelines/test_auto_tagging_asset.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pipelines/test_auto_tagging_asset.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_auto_tagging_asset_exists():
    from context_service.pipelines.assets.auto_tagging import auto_tagging_asset
    assert auto_tagging_asset is not None


def test_auto_tagging_asset_has_correct_schedule():
    from context_service.pipelines.assets.auto_tagging import auto_tagging_asset
    # Asset should be partitioned by silo
    assert auto_tagging_asset.partitions_def is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/pipelines/test_auto_tagging_asset.py -v`
Expected: FAIL with "No module named..."

- [ ] **Step 3: Create the asset**

```python
# src/context_service/pipelines/assets/auto_tagging.py
"""Dagster asset for async LLM-based tag refinement."""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from datetime import UTC, datetime
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource, RedisResource


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=600)


_FETCH_UNTAGGED = """
MATCH (n:Node {silo_id: $silo_id})
WHERE n.auto_tagged_at IS NULL
RETURN n.id AS id, n.content AS content
LIMIT 50
"""

_UPDATE_TAGS = """
MATCH (n:Node {id: $id, silo_id: $silo_id})
SET n.tags = $tags,
    n.auto_tags = $auto_tags,
    n.auto_tagged_at = $now
"""


@dg.asset(
    name="auto_tagging",
    partitions_def=silo_partitions,
    description="LLM-based tag refinement for nodes missing auto_tagged_at.",
    retry_policy=dg.RetryPolicy(max_retries=2, delay=30.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "auto_tagging"},
)
def auto_tagging_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    llm: LLMResource,
    redis: RedisResource,
) -> dg.Output[dict[str, Any]]:
    """Process untagged nodes with LLM-based tag suggestions."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()
    
    async def _run() -> tuple[int, int]:
        from context_service.stores import MemgraphClient
        
        driver = await memgraph.driver()
        mg_client = MemgraphClient(driver)
        llm_client = await llm.client()
        
        # Fetch untagged nodes
        rows = await mg_client.execute_query(_FETCH_UNTAGGED, {"silo_id": silo_id})
        
        if not rows:
            return 0, 0
        
        # Build LLM prompt
        content_map = {row["id"]: row["content"] for row in rows}
        prompt = _build_tagging_prompt(content_map)
        
        # Call LLM
        response = await llm_client.complete(prompt)
        suggestions = _parse_suggestions(response)
        
        # Apply tags
        now_iso = datetime.now(UTC).isoformat()
        processed = 0
        for node_id, tags in suggestions.items():
            if node_id in content_map:
                await mg_client.execute_write(
                    _UPDATE_TAGS,
                    {
                        "id": node_id,
                        "silo_id": silo_id,
                        "tags": tags,
                        "auto_tags": tags,
                        "now": now_iso,
                    },
                )
                processed += 1
        
        return len(rows), processed
    
    fetched, processed = _run_async(_run())
    duration_s = time.monotonic() - t0
    
    context.log.info(
        f"silo={silo_id} fetched={fetched} processed={processed} "
        f"duration={duration_s:.2f}s"
    )
    
    return dg.Output(
        value={
            "silo_id": silo_id,
            "fetched": fetched,
            "processed": processed,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "fetched": dg.MetadataValue.int(fetched),
            "processed": dg.MetadataValue.int(processed),
        },
    )


def _build_tagging_prompt(content_map: dict[str, str]) -> str:
    """Build LLM prompt for batch tagging."""
    items = "\n".join(
        f"- {node_id}: \"{content[:200]}...\""
        if len(content) > 200 else f"- {node_id}: \"{content}\""
        for node_id, content in content_map.items()
    )
    return f"""Suggest 2-5 tags for each content snippet below.
Return JSON only: {{"node_id": ["tag1", "tag2"], ...}}

Content:
{items}"""


def _parse_suggestions(response: str) -> dict[str, list[str]]:
    """Parse LLM response into tag suggestions."""
    import json
    try:
        # Find JSON in response
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
    except json.JSONDecodeError:
        pass
    return {}


__all__ = ["auto_tagging_asset"]
```

- [ ] **Step 4: Add to assets __init__.py**

```python
# src/context_service/pipelines/assets/__init__.py
# Add import:
from context_service.pipelines.assets.auto_tagging import auto_tagging_asset

# Add to all_assets list:
# auto_tagging_asset,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/pipelines/test_auto_tagging_asset.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/pipelines/assets/auto_tagging.py tests/pipelines/test_auto_tagging_asset.py
git commit -m "feat: add auto_tagging Dagster asset for LLM refinement"
```

---

### Task 9: Add Auto-Tagging Schedule

**Files:**
- Modify: `src/context_service/pipelines/schedules.py`

- [ ] **Step 1: Add the schedule**

```python
# src/context_service/pipelines/schedules.py
# Add after existing schedules:

@dg.schedule(
    cron_schedule="*/30 * * * *",
    name="auto_tagging_schedule",
    target=dg.AssetSelection.assets("auto_tagging"),
    description="Tag refinement every 30 minutes per active silo.",
    execution_timezone="UTC",
)
def auto_tagging_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Yield one auto_tagging RunRequest per active silo."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"auto_tagging:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )
```

- [ ] **Step 2: Add to all_schedules list**

```python
# In the same file, add to all_schedules:
all_schedules: list[Any] = [
    # ... existing schedules ...
    auto_tagging_schedule,
]
```

- [ ] **Step 3: Run existing schedule tests**

Run: `uv run pytest tests/test_schedules.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/pipelines/schedules.py
git commit -m "feat: add 30-minute auto_tagging schedule"
```

---

### Task 10: Create Tag Maintenance Asset

**Files:**
- Create: `src/context_service/pipelines/assets/tag_maintenance.py`
- Modify: `src/context_service/pipelines/schedules.py`

- [ ] **Step 1: Create the asset**

```python
# src/context_service/pipelines/assets/tag_maintenance.py
"""Dagster asset for vocabulary pruning and maintenance."""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource, PostgresResource


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=600)


@dg.asset(
    name="tag_maintenance",
    partitions_def=silo_partitions,
    description="Daily vocabulary pruning: demote unused tags, prune orphan candidates.",
    retry_policy=dg.RetryPolicy(max_retries=2, delay=60.0),
    tags={"dagster/concurrency_key": "tag_maintenance"},
)
def tag_maintenance_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    postgres: PostgresResource,
) -> dg.Output[dict[str, Any]]:
    """Prune stale dynamic tags and orphan candidates."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()
    
    async def _run() -> dict[str, int]:
        from uuid import UUID
        from context_service.db.postgres import get_session
        from context_service.services.tag_config import TagConfigService
        from context_service.stores import MemgraphClient
        
        driver = await memgraph.driver()
        mg_client = MemgraphClient(driver)
        
        demoted = 0
        
        async with get_session() as session:
            tag_svc = TagConfigService(session)
            config = await tag_svc.get(UUID(silo_id))
            
            if config and config.dynamic_tags:
                # Find tags not used in last 30 days
                demotion_days = config.settings.get("demotion_days", 30)
                stale_tags = await _find_stale_tags(
                    mg_client, silo_id, config.dynamic_tags, demotion_days
                )
                
                if stale_tags:
                    await tag_svc.remove_dynamic_tags(UUID(silo_id), stale_tags)
                    demoted = len(stale_tags)
        
        return {"demoted": demoted}
    
    result = _run_async(_run())
    duration_s = time.monotonic() - t0
    
    context.log.info(
        f"silo={silo_id} demoted={result['demoted']} duration={duration_s:.2f}s"
    )
    
    return dg.Output(
        value={"silo_id": silo_id, **result, "duration_s": duration_s},
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "demoted": dg.MetadataValue.int(result["demoted"]),
        },
    )


async def _find_stale_tags(
    mg_client: Any,
    silo_id: str,
    dynamic_tags: list[str],
    demotion_days: int,
) -> list[str]:
    """Find dynamic tags not used in the last N days."""
    from datetime import datetime, timedelta, UTC
    
    cutoff = datetime.now(UTC) - timedelta(days=demotion_days)
    cutoff_ts = int(cutoff.timestamp() * 1_000_000)
    
    query = """
    UNWIND $tags AS tag
    OPTIONAL MATCH (n:Node {silo_id: $silo_id})
    WHERE tag IN n.tags AND n.created_at > $cutoff
    WITH tag, count(n) AS usage
    WHERE usage = 0
    RETURN tag
    """
    
    rows = await mg_client.execute_query(
        query,
        {"silo_id": silo_id, "tags": dynamic_tags, "cutoff": cutoff_ts},
    )
    
    return [row["tag"] for row in rows]


__all__ = ["tag_maintenance_asset"]
```

- [ ] **Step 2: Add to assets __init__.py**

```python
# src/context_service/pipelines/assets/__init__.py
from context_service.pipelines.assets.tag_maintenance import tag_maintenance_asset
# Add to all_assets list
```

- [ ] **Step 3: Add schedule to schedules.py**

```python
# src/context_service/pipelines/schedules.py

@dg.schedule(
    cron_schedule="0 3 * * *",
    name="tag_maintenance_schedule",
    target=dg.AssetSelection.assets("tag_maintenance"),
    description="Daily tag maintenance at 03:00 UTC per active silo.",
    execution_timezone="UTC",
)
def tag_maintenance_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Yield one tag_maintenance RunRequest per active silo."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"tag_maintenance:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
        )

# Add to all_schedules list
```

- [ ] **Step 4: Commit**

```bash
git add src/context_service/pipelines/assets/tag_maintenance.py src/context_service/pipelines/schedules.py
git commit -m "feat: add tag_maintenance asset and daily schedule"
```

---

### Task 11: Create config/tags.yaml

**Files:**
- Create: `src/context_service/config/tags.yaml`

- [ ] **Step 1: Create the config file**

```yaml
# src/context_service/config/tags.yaml
# System-wide defaults for auto-tagging.
# Per-silo overrides are stored in Postgres.

defaults:
  min_tags: 2
  max_tags: 5
  cosine_threshold: 0.4
  promotion_threshold: 3
  demotion_days: 30
  synonym_threshold: 0.85
  cache_ttl_seconds: 300
```

- [ ] **Step 2: Add config loader**

```python
# src/context_service/config/tags.py
"""Load tag configuration from YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).parent / "tags.yaml"
_config: dict[str, Any] | None = None


def get_tag_defaults() -> dict[str, Any]:
    """Load default tag settings from YAML."""
    global _config
    if _config is None:
        with open(_CONFIG_PATH) as f:
            _config = yaml.safe_load(f)
    return _config.get("defaults", {})
```

- [ ] **Step 3: Commit**

```bash
git add src/context_service/config/tags.yaml src/context_service/config/tags.py
git commit -m "feat: add tags.yaml config with system defaults"
```

---

### Task 12: Wire Up App Lifecycle

**Files:**
- Modify: `src/context_service/api/app.py`

- [ ] **Step 1: Add Postgres init/close to app lifespan**

```python
# src/context_service/api/app.py
# In the lifespan context manager, add:

from context_service.db.postgres import init_postgres, close_postgres

# In startup section (after Redis init):
await init_postgres()
logger.info("postgres_connected")

# In shutdown section:
await close_postgres()
logger.info("postgres_closed")
```

- [ ] **Step 2: Wire AutoTaggingService to MCP**

```python
# In the same file, after creating embedding_service:

from context_service.services.auto_tagging import AutoTaggingService
from context_service.services.tag_config import TagConfigService
from context_service.db.postgres import get_session

# Create auto_tagging service (will need session per-request)
# For now, pass None and wire it properly in configure_services
```

- [ ] **Step 3: Run app to verify startup**

Run: `uv run python -m context_service`
Expected: App starts without errors, logs show postgres_connected

- [ ] **Step 4: Commit**

```bash
git add src/context_service/api/app.py
git commit -m "feat: wire Postgres lifecycle and AutoTaggingService"
```

---

## Summary

This plan implements the auto-tagging system in 12 tasks:

1. **Dependencies** - Add SQLAlchemy, asyncpg, Alembic
2. **Postgres infrastructure** - Session factory
3. **SiloTagConfig model** - SQLAlchemy model
4. **Alembic migration** - Database schema
5. **TagConfigService** - CRUD operations
6. **AutoTaggingService** - Sync cosine matching
7. **ContextService integration** - Wire auto-tagging to store()
8. **auto_tagging asset** - Async LLM refinement
9. **auto_tagging schedule** - Every 30 minutes
10. **tag_maintenance asset** - Daily pruning
11. **config/tags.yaml** - System defaults
12. **App lifecycle** - Wire everything together

Each task is independently testable and committable.
