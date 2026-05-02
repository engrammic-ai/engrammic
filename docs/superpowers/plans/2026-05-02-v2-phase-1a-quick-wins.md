# Phase 1a: Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate settings into a single canonical class and batch N+1 writes in the ingest hot path.

**Architecture:** Merge `core/settings.py` nested configs into `config/settings.py`, update all callers, add UNWIND batching for claim and hyperedge writes.

**Tech Stack:** Pydantic, pydantic-settings, Cypher UNWIND

**Pre-completed:** orjson swap (already done via `utils/json.py`)

---

## File Structure

**Settings consolidation:**
- Modify: `src/context_service/config/settings.py` (add nested configs from core)
- Modify: `src/context_service/core/settings.py` (reduce to re-export shim)
- Modify: ~8 files importing from `core.settings`
- Modify: `src/context_service/core/__init__.py` (update exports)

**N+1 batching:**
- Modify: `src/context_service/extraction/service.py` (batch claim writes)
- Modify: `src/context_service/engine/memgraph_store.py` (batch hyperedge participants)
- Modify: `src/context_service/db/queries.py` (add UNWIND query constants)

---

## Task 1: Audit Settings Divergence

**Files:**
- Read: `src/context_service/config/settings.py`
- Read: `src/context_service/core/settings.py`

- [ ] **Step 1: Document field differences**

Run this to find all unique fields in each file:

```bash
# List all field names in config/settings.py
rg "^\s+\w+:" src/context_service/config/settings.py | grep -v "model_config" | sort > /tmp/config_fields.txt

# List all field names in core/settings.py  
rg "^\s+\w+:" src/context_service/core/settings.py | grep -v "model_config" | sort > /tmp/core_fields.txt

# Show differences
diff /tmp/config_fields.txt /tmp/core_fields.txt
```

- [ ] **Step 2: Document nested model usage**

```bash
# Which files import CustodianSettings, RetrievalTuning, etc. from core?
rg "from context_service.core.settings import|from context_service.core import.*Settings" src/context_service/ -l
```

- [ ] **Step 3: Create migration mapping**

Create a text file documenting:
1. Fields unique to config/settings.py
2. Fields unique to core/settings.py
3. Nested models to migrate (CustodianSettings, RetrievalTuning, InfraConfig, etc.)
4. Deprecated aliases needed

---

## Task 2: Migrate Nested Models to config/settings.py

**Files:**
- Modify: `src/context_service/config/settings.py`
- Test: `tests/test_settings_consolidation.py`

- [ ] **Step 1: Write test for nested config access**

Create `tests/test_settings_consolidation.py`:

```python
"""Test that settings consolidation works correctly."""

import pytest
from context_service.config.settings import Settings, get_settings


def test_settings_has_custodian_config():
    """CustodianSettings should be accessible from config.settings."""
    settings = get_settings()
    assert hasattr(settings, "custodian")
    assert settings.custodian.enabled is not None


def test_settings_has_retrieval_tuning():
    """RetrievalTuning should be accessible from config.settings."""
    settings = get_settings()
    assert hasattr(settings, "retrieval_tuning")
    assert settings.retrieval_tuning.walker_alpha >= 0


def test_settings_has_infra_config():
    """InfraConfig should be accessible from config.settings."""
    settings = get_settings()
    assert hasattr(settings, "infra")
    assert settings.infra.memgraph is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_settings_consolidation.py -v
```

Expected: FAIL (config.settings doesn't have these nested configs yet)

- [ ] **Step 3: Copy nested model classes to config/settings.py**

Add these classes from core/settings.py to config/settings.py (before the Settings class):

```python
from pydantic import BaseModel, Field, SecretStr

class CustodianSettings(BaseModel):
    """Custodian phase settings: budgets, flags, and model identifiers."""
    model_config = {"extra": "ignore"}
    
    enabled: bool = Field(default=False)
    auto_publish_after_pass: bool = Field(default=False)
    cluster_min_members_for_deep_pass: int = Field(default=5)
    fast_pass_nominal_tokens: int = Field(default=2_000)
    fast_pass_hard_tokens: int = Field(default=6_000)
    fast_pass_request_limit: int = Field(default=5)
    fast_pass_tool_calls_limit: int = Field(default=8)
    plan_nominal_tokens: int = Field(default=4_500)
    deep_pass_nominal_tokens: int = Field(default=10_000)
    deep_pass_hard_tokens: int = Field(default=19_500)
    deep_pass_total_tokens_backstop: int = Field(default=20_000)
    deep_pass_soft_signal_ratio: float = Field(default=0.69)
    stitch_nominal_tokens: int = Field(default=1_200)
    stitch_hard_tokens: int = Field(default=1_500)
    max_cost_usd: float = Field(default=5.0)
    max_visits: int = Field(default=300)
    max_total_tokens: int = Field(default=5_000_000)
    per_visit_token_ceiling: int = Field(default=17_000)
    redis_trace_ttl_days: int = Field(default=30)
    concurrent_visit_limit: int = Field(default=4)
    per_visit_timeout_seconds: int = Field(default=120)
    flash_model: str = Field(default="google-vertex:gemini-2.5-flash")
    pro_model: str = Field(default="google-vertex:gemini-2.5-pro")
    pro_escalation_ab_sample_ratio: float = Field(default=0.10)
    min_edge_confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class RetrievalTuning(BaseModel):
    """Retrieval-ranking tuning knobs."""
    model_config = {"extra": "ignore"}
    
    walker_alpha: float = Field(default=0.4)
    walker_beta: float = Field(default=0.3)
    walker_gamma: float = Field(default=0.15)
    walker_delta: float = Field(default=0.15)
    walker_base_cost: float = Field(default=1.0)
    walker_tier_weight_hot: float = Field(default=1.0)
    walker_tier_weight_warm: float = Field(default=0.5)
    walker_tier_weight_cold: float = Field(default=0.25)
    walker_tier_weight_null: float = Field(default=0.1)
    walker_no_cluster_floor: float = Field(default=0.1)
    rrf_k: int = Field(default=60)
    rrf_channel_weights: dict[str, float] = Field(default_factory=dict)


class MemgraphConfig(BaseModel):
    model_config = {"extra": "ignore"}
    host: str = "localhost"
    port: int = 7687
    user: str = ""
    password: SecretStr = SecretStr("")
    pool_size: int = 50


class QdrantConfig(BaseModel):
    model_config = {"extra": "ignore"}
    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    api_key: SecretStr | None = None


class RedisConfig(BaseModel):
    model_config = {"extra": "ignore"}
    host: str = "localhost"
    port: int = 6379
    password: SecretStr | None = None
    db: int = 0


class InfraConfig(BaseModel):
    model_config = {"extra": "ignore"}
    memgraph: MemgraphConfig = Field(default_factory=MemgraphConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
```

- [ ] **Step 4: Add nested configs to Settings class**

In config/settings.py, add to the Settings class:

```python
class Settings(BaseSettings):
    # ... existing fields ...
    
    # Nested sub-configs (migrated from core/settings.py)
    infra: InfraConfig = Field(default_factory=InfraConfig)
    custodian: CustodianSettings = Field(default_factory=CustodianSettings)
    retrieval_tuning: RetrievalTuning = Field(default_factory=RetrievalTuning)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/test_settings_consolidation.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/config/settings.py tests/test_settings_consolidation.py
git commit -m "feat: migrate nested configs to config/settings.py"
```

---

## Task 3: Update core/settings.py to Re-export

**Files:**
- Modify: `src/context_service/core/settings.py`
- Modify: `src/context_service/core/__init__.py`

- [ ] **Step 1: Replace core/settings.py with re-export shim**

Replace the entire file with:

```python
"""Deprecated: use context_service.config.settings instead.

This module re-exports from config.settings for backwards compatibility.
All nested configs (CustodianSettings, RetrievalTuning, InfraConfig, etc.)
are now defined in config.settings.

TODO(2026-Q3): Remove this shim after all callers migrate.
"""

from context_service.config.settings import (
    CustodianSettings,
    InfraConfig,
    MemgraphConfig,
    QdrantConfig,
    RedisConfig,
    RetrievalTuning,
    Settings,
    get_settings,
)

__all__ = [
    "CustodianSettings",
    "InfraConfig",
    "MemgraphConfig",
    "QdrantConfig",
    "RedisConfig",
    "RetrievalTuning",
    "Settings",
    "get_settings",
]

# Backwards-compat: some callers do `from core.settings import settings`
settings = get_settings()
```

- [ ] **Step 2: Update core/__init__.py**

Ensure it re-exports from the shim:

```python
from context_service.core.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -v --tb=short
```

Expected: All tests pass (existing callers of core.settings still work via re-export)

- [ ] **Step 4: Commit**

```bash
git add src/context_service/core/settings.py src/context_service/core/__init__.py
git commit -m "refactor: core/settings.py now re-exports from config/settings.py"
```

---

## Task 4: Migrate Callers from core.settings to config.settings

**Files:**
- Modify: `src/context_service/extraction/prompts.py`
- Modify: `src/context_service/custodian/visit.py`
- Modify: `src/context_service/clustering/prompts.py`
- Modify: `src/context_service/custodian/validators.py`
- Modify: `src/context_service/custodian/silo_synthesis.py`
- Modify: `src/context_service/custodian/models.py`
- Modify: `src/context_service/custodian/agents.py`

- [ ] **Step 1: Update extraction/prompts.py**

Change:
```python
from context_service.core.settings import get_settings
```
To:
```python
from context_service.config.settings import get_settings
```

- [ ] **Step 2: Update custodian/visit.py**

Same pattern - change `core.settings` to `config.settings`.

- [ ] **Step 3: Update remaining custodian files**

Update these files with the same import change:
- `custodian/validators.py`
- `custodian/silo_synthesis.py`
- `custodian/models.py`
- `custodian/agents.py`
- `clustering/prompts.py`

- [ ] **Step 4: Run typecheck and tests**

```bash
just check
uv run pytest tests/ -v --tb=short
```

Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/context_service/extraction/ src/context_service/custodian/ src/context_service/clustering/
git commit -m "refactor: migrate core.settings callers to config.settings"
```

---

## Task 5: Batch Claim Writes with UNWIND

**Files:**
- Modify: `src/context_service/db/queries.py`
- Modify: `src/context_service/extraction/service.py`
- Test: `tests/extraction/test_batch_writes.py`

- [ ] **Step 1: Write test for batch claim creation**

Create `tests/extraction/test_batch_writes.py`:

```python
"""Test batch write operations for extraction."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from context_service.extraction.service import ExtractionService


@pytest.mark.asyncio
async def test_batch_create_claims_uses_unwind():
    """Batch claim creation should use UNWIND, not N individual writes."""
    mock_client = AsyncMock()
    mock_client.execute_write = AsyncMock(return_value=[])
    
    service = ExtractionService(client=mock_client)
    
    claims = [
        {"id": "claim-1", "content": "Claim 1", "silo_id": "silo-1"},
        {"id": "claim-2", "content": "Claim 2", "silo_id": "silo-1"},
        {"id": "claim-3", "content": "Claim 3", "silo_id": "silo-1"},
    ]
    
    await service.batch_create_claims(claims, silo_id="silo-1")
    
    # Should be called once with UNWIND, not 3 times
    assert mock_client.execute_write.call_count == 1
    call_args = mock_client.execute_write.call_args
    assert "UNWIND" in call_args[0][0]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/extraction/test_batch_writes.py -v
```

Expected: FAIL (batch_create_claims doesn't exist or doesn't use UNWIND)

- [ ] **Step 3: Add UNWIND query constant to db/queries.py**

Add to `src/context_service/db/queries.py`:

```python
BATCH_CREATE_CLAIMS = """
UNWIND $claims AS claim
MERGE (c:Claim {id: claim.id})
SET c.content = claim.content,
    c.silo_id = claim.silo_id,
    c.doc_id = claim.doc_id,
    c.created_at = datetime(),
    c.status = 'pending'
RETURN count(c) AS created
"""
```

- [ ] **Step 4: Implement batch_create_claims in extraction/service.py**

Add method to ExtractionService:

```python
async def batch_create_claims(
    self, claims: list[dict], silo_id: str
) -> int:
    """Batch create claims using UNWIND for efficiency."""
    if not claims:
        return 0
    
    result = await self.client.execute_write(
        BATCH_CREATE_CLAIMS,
        {"claims": claims, "silo_id": silo_id},
    )
    return result[0]["created"] if result else 0
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/extraction/test_batch_writes.py -v
```

Expected: PASS

- [ ] **Step 6: Update extraction hot path to use batch method**

Find the N+1 write loop in extraction/service.py (around line 354-416) and replace with batch call.

- [ ] **Step 7: Commit**

```bash
git add src/context_service/db/queries.py src/context_service/extraction/service.py tests/extraction/
git commit -m "perf: batch claim writes with UNWIND"
```

---

## Task 6: Batch Hyperedge Participant Writes

**Files:**
- Modify: `src/context_service/db/queries.py`
- Modify: `src/context_service/engine/memgraph_store.py`
- Test: `tests/engine/test_batch_hyperedge.py`

- [ ] **Step 1: Write test for batch hyperedge participants**

Create `tests/engine/test_batch_hyperedge.py`:

```python
"""Test batch hyperedge participant writes."""

import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_batch_add_participants_uses_unwind():
    """Adding multiple participants should use UNWIND."""
    from context_service.engine.memgraph_store import MemgraphStore
    
    mock_driver = AsyncMock()
    store = MemgraphStore(driver=mock_driver)
    
    participants = [
        {"node_id": "node-1", "role": "subject"},
        {"node_id": "node-2", "role": "object"},
        {"node_id": "node-3", "role": "context"},
    ]
    
    await store.batch_add_hyperedge_participants(
        hyperedge_id="edge-1",
        participants=participants,
        silo_id="silo-1",
    )
    
    # Check UNWIND was used
    call_args = mock_driver.execute_write.call_args
    assert "UNWIND" in call_args[0][0]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/engine/test_batch_hyperedge.py -v
```

Expected: FAIL

- [ ] **Step 3: Add UNWIND query for hyperedge participants**

Add to `src/context_service/db/queries.py`:

```python
BATCH_ADD_HYPEREDGE_PARTICIPANTS = """
MATCH (h:HyperEdge {id: $hyperedge_id, silo_id: $silo_id})
UNWIND $participants AS p
MATCH (n:Node {id: p.node_id, silo_id: $silo_id})
MERGE (h)-[r:PARTICIPATES]->(n)
SET r.role = p.role
RETURN count(r) AS linked
"""
```

- [ ] **Step 4: Implement batch method in memgraph_store.py**

Add method:

```python
async def batch_add_hyperedge_participants(
    self,
    hyperedge_id: str,
    participants: list[dict],
    silo_id: str,
) -> int:
    """Batch add participants to a hyperedge using UNWIND."""
    if not participants:
        return 0
    
    result = await self.execute_write(
        BATCH_ADD_HYPEREDGE_PARTICIPANTS,
        {
            "hyperedge_id": hyperedge_id,
            "participants": participants,
            "silo_id": silo_id,
        },
    )
    return result[0]["linked"] if result else 0
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/engine/test_batch_hyperedge.py -v
```

Expected: PASS

- [ ] **Step 6: Update upsert_hyperedge to use batch method**

Find the N+1 loop in memgraph_store.py (around line 629-655) and replace with batch call.

- [ ] **Step 7: Commit**

```bash
git add src/context_service/db/queries.py src/context_service/engine/memgraph_store.py tests/engine/
git commit -m "perf: batch hyperedge participant writes with UNWIND"
```

---

## Task 7: Final Verification

- [ ] **Step 1: Run full quality checks**

```bash
just check
```

Expected: lint + typecheck pass

- [ ] **Step 2: Run full test suite**

```bash
just test
```

Expected: All tests pass

- [ ] **Step 3: Verify no direct core.settings imports remain**

```bash
rg "from context_service.core.settings import" src/context_service/ --type py | grep -v "__pycache__"
```

Expected: Only the shim file should import from core (and it re-exports, not imports)

- [ ] **Step 4: Create PR**

```bash
git push -u origin phase-v2-1a-quick-wins
gh pr create --title "Phase 1a: Settings consolidation + N+1 batching" --body "$(cat <<'EOF'
## Summary
- Consolidated settings: merged nested configs from core/settings.py into config/settings.py
- core/settings.py now re-exports from config for backwards compatibility
- Added UNWIND batching for claim writes in extraction
- Added UNWIND batching for hyperedge participant writes

## Test plan
- [x] All existing tests pass
- [x] New tests for batch operations
- [x] Typecheck passes
- [x] Lint passes

Spec: docs/superpowers/specs/2026-05-02-arch-cleanup-perf-rest-api.md
EOF
)"
```
