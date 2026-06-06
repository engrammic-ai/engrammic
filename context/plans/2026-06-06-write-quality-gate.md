# Write Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement write-path quality enforcement with structural checks, telemetry, and response enrichment to improve KG quality.

**Architecture:** Quality gate wraps sage.transactions functions, runs sync structural checks, emits async telemetry via reactions, and enriches responses with quality signals. Read-side trust gate extended to filter unverified knowledge.

**Tech Stack:** Python 3.12, Pydantic, asyncio, Redis (session tracking), Postgres (telemetry), Alembic (migrations), pytest

**Spec:** context/specs/2026-06-06-write-quality-gate.md

---

## File Structure

### New Files
| File | Responsibility |
|------|----------------|
| `src/context_service/sage/quality_gate.py` | Core gate logic: assess(), record(), check functions |
| `src/context_service/sage/quality_types.py` | Type definitions: QualityContext, QualityResult, CheckResult |
| `src/context_service/db/quality_queries.py` | Postgres INSERT for write_quality_events |
| `tests/sage/test_quality_gate.py` | Unit tests for check functions and gate logic |
| `tests/integration/test_quality_gate_integration.py` | Integration tests with real transactions |

### Modified Files
| File | Changes |
|------|---------|
| `src/context_service/config/settings.py` | Add QualityGateSettings class |
| `src/context_service/reactions/events.py` | Add WRITE_QUALITY, CHECK_SEMANTIC_DUPLICATE event types |
| `src/context_service/reactions/tasks.py` | Add write_quality_task handler |
| `src/context_service/sage/transactions.py` | Integrate gate.assess() and gate.record() calls |
| `src/context_service/mcp/tools/recall.py` | Set recall_called Redis flag |
| `src/context_service/mcp/tools/trust_gate.py` | Add unverified_knowledge withhold reason |

---

## Task 1: Add QualityGateSettings

**Files:**
- Modify: `src/context_service/config/settings.py`
- Test: `tests/config/test_settings.py`

- [ ] **Step 1: Write failing test for QualityGateSettings**

```python
# tests/config/test_settings.py (append to existing file)

def test_quality_gate_settings_defaults():
    """QualityGateSettings has correct defaults."""
    from context_service.config.settings import QualityGateSettings
    
    settings = QualityGateSettings()
    assert settings.enabled is True
    assert settings.enforce_evidence is False
    assert settings.enforce_about_refs is True
    assert settings.check_recall_first is True
    assert settings.check_duplicates is True
    assert settings.emit_telemetry is True
    assert settings.resolvability_cache_ttl_seconds == 60


def test_quality_gate_settings_from_env(monkeypatch):
    """QualityGateSettings reads from environment."""
    monkeypatch.setenv("QUALITY_GATE__ENFORCE_EVIDENCE", "true")
    monkeypatch.setenv("QUALITY_GATE__ENABLED", "false")
    
    from context_service.config.settings import Settings
    
    # Force reload
    settings = Settings()
    assert settings.quality_gate.enforce_evidence is True
    assert settings.quality_gate.enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/config/test_settings.py::test_quality_gate_settings_defaults -v`
Expected: FAIL with "cannot import name 'QualityGateSettings'"

- [ ] **Step 3: Implement QualityGateSettings**

Add to `src/context_service/config/settings.py` after `TrustGateConfig`:

```python
class QualityGateSettings(BaseModel):
    """Settings for write-path quality enforcement."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Enable write quality gate")

    # Enforcement posture
    enforce_evidence: bool = Field(
        default=False,
        description="Hard-enforce evidence on learn (downgrade to memory if missing)",
    )
    enforce_about_refs: bool = Field(
        default=True,
        description="Hard-enforce about refs on believe (reject if missing)",
    )

    # Behavioral checks
    check_recall_first: bool = Field(
        default=True,
        description="Track whether recall was called before store",
    )
    check_duplicates: bool = Field(
        default=True,
        description="Check content hash for duplicates and suggest supersedes",
    )
    check_evidence_resolvable: bool = Field(
        default=True,
        description="Verify node: refs exist in silo",
    )
    check_about_layers: bool = Field(
        default=True,
        description="Warn if belief references other beliefs instead of facts",
    )

    # Telemetry
    emit_telemetry: bool = Field(
        default=True,
        description="Emit WRITE_QUALITY events to reactions broker",
    )

    # Performance
    resolvability_cache_ttl_seconds: int = Field(
        default=60,
        description="Cache node existence checks",
    )
```

- [ ] **Step 4: Add quality_gate field to Settings class**

Find the Settings class and add:

```python
    quality_gate: QualityGateSettings = Field(default_factory=QualityGateSettings)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/config/test_settings.py -k quality_gate -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/config/settings.py tests/config/test_settings.py
git commit -m "feat(config): add QualityGateSettings for write quality enforcement"
```

---

## Task 2: Define Quality Types

**Files:**
- Create: `src/context_service/sage/quality_types.py`
- Test: `tests/sage/test_quality_types.py`

- [ ] **Step 1: Write test for quality types**

```python
# tests/sage/test_quality_types.py

from context_service.sage.quality_types import (
    CheckResult,
    QualityContext,
    QualityResult,
    QualityOutcome,
)


def test_check_result_passed():
    """CheckResult with passed=True has no message."""
    result = CheckResult(passed=True, name="evidence_present")
    assert result.passed is True
    assert result.message is None


def test_check_result_failed():
    """CheckResult with passed=False has message."""
    result = CheckResult(passed=False, name="evidence_present", message="No evidence")
    assert result.passed is False
    assert result.message == "No evidence"


def test_quality_context_minimal():
    """QualityContext with required fields only."""
    ctx = QualityContext(
        tool="learn",
        layer="knowledge",
        session_id="sess-123",
        silo_id="silo-456",
        content="Test claim",
    )
    assert ctx.evidence_refs is None
    assert ctx.about_refs is None
    assert ctx.supersedes is None


def test_quality_result_passed():
    """QualityResult with passed outcome."""
    result = QualityResult(
        outcome=QualityOutcome.PASSED,
        checks=[CheckResult(passed=True, name="evidence_present")],
    )
    assert result.outcome == QualityOutcome.PASSED
    assert result.suggestions == []
    assert result.original_layer is None


def test_quality_result_downgraded():
    """QualityResult with downgraded outcome tracks original layer."""
    result = QualityResult(
        outcome=QualityOutcome.DOWNGRADED,
        checks=[CheckResult(passed=False, name="evidence_present", message="No evidence")],
        original_layer="knowledge",
        suggestions=["Add file:// or node: refs"],
    )
    assert result.outcome == QualityOutcome.DOWNGRADED
    assert result.original_layer == "knowledge"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sage/test_quality_types.py -v`
Expected: FAIL with "No module named 'context_service.sage.quality_types'"

- [ ] **Step 3: Implement quality types**

```python
# src/context_service/sage/quality_types.py
"""Type definitions for write quality gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class QualityOutcome(StrEnum):
    """Outcome of quality gate assessment."""

    PASSED = "passed"
    WARNED = "warned"
    DOWNGRADED = "downgraded"
    REJECTED = "rejected"


@dataclass
class CheckResult:
    """Result of a single quality check."""

    passed: bool
    name: str
    message: str | None = None


@dataclass
class QualityContext:
    """Context for quality gate assessment."""

    tool: str
    layer: str
    session_id: str
    silo_id: str
    content: str
    evidence_refs: list[str] | None = None
    about_refs: list[str] | None = None
    supersedes: str | None = None
    node_id: str | None = None  # Set after store for telemetry


@dataclass
class QualityResult:
    """Result of quality gate assessment."""

    outcome: QualityOutcome
    checks: list[CheckResult]
    reason: str | None = None
    suggestions: list[str] = field(default_factory=list)
    original_layer: str | None = None


@dataclass
class QualitySignals:
    """Quality signals for response enrichment."""

    outcome: str
    layer_stored: str
    checks: list[dict]
    suggestions: list[str]
    recall_before_store: bool

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "outcome": self.outcome,
            "layer_stored": self.layer_stored,
            "checks": self.checks,
            "suggestions": self.suggestions,
            "recall_before_store": self.recall_before_store,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_quality_types.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/sage/quality_types.py tests/sage/test_quality_types.py
git commit -m "feat(sage): add quality gate type definitions"
```

---

## Task 3: Implement Check Functions

**Files:**
- Create: `src/context_service/sage/quality_gate.py` (partial)
- Test: `tests/sage/test_quality_gate.py`

- [ ] **Step 1: Write tests for check functions**

```python
# tests/sage/test_quality_gate.py
"""Unit tests for quality gate check functions."""

import pytest

from context_service.sage.quality_gate import (
    _check_evidence_present,
    _check_evidence_format,
    _check_about_present,
    _check_no_self_ref,
    _check_content_hash,
)
from context_service.sage.quality_types import CheckResult


class TestCheckEvidencePresent:
    def test_no_evidence_fails(self):
        result = _check_evidence_present(None, enforce=False)
        assert result.passed is False
        assert result.name == "evidence_present"
        assert "No evidence" in result.message

    def test_empty_list_fails(self):
        result = _check_evidence_present([], enforce=False)
        assert result.passed is False

    def test_with_evidence_passes(self):
        result = _check_evidence_present(["node:abc123"], enforce=False)
        assert result.passed is True
        assert result.message is None


class TestCheckEvidenceFormat:
    def test_valid_node_ref(self):
        result = _check_evidence_format(["node:550e8400-e29b-41d4-a716-446655440000"])
        assert result.passed is True

    def test_valid_file_uri(self):
        result = _check_evidence_format(["file:///path/to/file.py"])
        assert result.passed is True

    def test_valid_https_uri(self):
        result = _check_evidence_format(["https://example.com/doc"])
        assert result.passed is True

    def test_invalid_format_fails(self):
        result = _check_evidence_format(["just some text"])
        assert result.passed is False
        assert "invalid format" in result.message.lower()

    def test_mixed_valid_invalid(self):
        result = _check_evidence_format(["node:abc", "not valid"])
        assert result.passed is False


class TestCheckAboutPresent:
    def test_no_about_fails(self):
        result = _check_about_present(None)
        assert result.passed is False
        assert result.name == "about_present"

    def test_empty_about_fails(self):
        result = _check_about_present([])
        assert result.passed is False

    def test_with_about_passes(self):
        result = _check_about_present(["node:abc"])
        assert result.passed is True


class TestCheckNoSelfRef:
    def test_self_ref_fails(self):
        result = _check_no_self_ref(["node:abc", "node:def"], node_id="abc")
        assert result.passed is False
        assert "self-reference" in result.message.lower()

    def test_no_self_ref_passes(self):
        result = _check_no_self_ref(["node:abc", "node:def"], node_id="xyz")
        assert result.passed is True

    def test_no_node_id_passes(self):
        result = _check_no_self_ref(["node:abc"], node_id=None)
        assert result.passed is True


class TestCheckContentHash:
    @pytest.mark.asyncio
    async def test_no_duplicate_passes(self):
        # Mock: no existing node with this hash
        result = await _check_content_hash("unique content", "silo-123", find_fn=None)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_duplicate_warns(self):
        async def mock_find(hash, silo_id):
            return "existing-node-id"

        result = await _check_content_hash("duplicate content", "silo-123", find_fn=mock_find)
        assert result.passed is False
        assert "existing-node-id" in result.message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/sage/test_quality_gate.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Implement check functions**

```python
# src/context_service/sage/quality_gate.py
"""Write quality gate: structural checks and telemetry."""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from context_service.sage.quality_types import CheckResult

if TYPE_CHECKING:
    pass

# Evidence format patterns
_NODE_REF_PATTERN = re.compile(r"^node:[a-f0-9-]{36}$", re.IGNORECASE)
_URI_PATTERN = re.compile(r"^(file://|https?://|node:)", re.IGNORECASE)


def _check_evidence_present(
    refs: list[str] | None,
    enforce: bool,
) -> CheckResult:
    """Check that evidence refs are provided."""
    if not refs or len(refs) == 0:
        return CheckResult(
            passed=False,
            name="evidence_present",
            message="No evidence refs provided; add node: or file:// refs for higher confidence",
        )
    return CheckResult(passed=True, name="evidence_present")


def _check_evidence_format(refs: list[str]) -> CheckResult:
    """Check that evidence refs are valid format."""
    invalid = []
    for ref in refs:
        if not _URI_PATTERN.match(ref):
            invalid.append(ref)
    
    if invalid:
        return CheckResult(
            passed=False,
            name="evidence_format",
            message=f"Invalid format: {invalid[:3]}. Use node:<uuid>, file://, or https://",
        )
    return CheckResult(passed=True, name="evidence_format")


def _check_about_present(refs: list[str] | None) -> CheckResult:
    """Check that about refs are provided for wisdom layer."""
    if not refs or len(refs) == 0:
        return CheckResult(
            passed=False,
            name="about_present",
            message="Beliefs require about: refs to supporting knowledge",
        )
    return CheckResult(passed=True, name="about_present")


def _check_no_self_ref(refs: list[str], node_id: str | None) -> CheckResult:
    """Check that about refs don't include self-reference."""
    if node_id is None:
        return CheckResult(passed=True, name="no_self_ref")
    
    for ref in refs:
        if ref.startswith("node:") and ref[5:] == node_id:
            return CheckResult(
                passed=False,
                name="no_self_ref",
                message="Self-reference detected in about refs",
            )
    return CheckResult(passed=True, name="no_self_ref")


async def _check_content_hash(
    content: str,
    silo_id: str,
    find_fn: Callable[[str, str], Coroutine[Any, Any, str | None]] | None = None,
) -> CheckResult:
    """Check for duplicate content via hash."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    
    if find_fn is None:
        # No lookup function provided, skip check
        return CheckResult(passed=True, name="duplicate_check")
    
    existing_id = await find_fn(content_hash, silo_id)
    if existing_id:
        return CheckResult(
            passed=False,
            name="duplicate_check",
            message=f"Similar content exists: node:{existing_id}. Consider supersedes='{existing_id}'",
        )
    return CheckResult(passed=True, name="duplicate_check")


async def _check_recall_first(session_id: str, redis_client: Any | None = None) -> bool:
    """Check if recall was called in this session before store."""
    if redis_client is None:
        return False
    
    key = f"session:{session_id}:recall_called"
    result = await redis_client.exists(key)
    return bool(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_quality_gate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/sage/quality_gate.py tests/sage/test_quality_gate.py
git commit -m "feat(sage): implement quality gate check functions"
```

---

## Task 4: Implement WriteQualityGate Class

**Files:**
- Modify: `src/context_service/sage/quality_gate.py`
- Test: `tests/sage/test_quality_gate.py`

- [ ] **Step 1: Write test for WriteQualityGate.assess()**

```python
# tests/sage/test_quality_gate.py (append)

from context_service.sage.quality_gate import WriteQualityGate
from context_service.sage.quality_types import QualityContext, QualityOutcome
from context_service.config.settings import QualityGateSettings


class TestWriteQualityGateAssess:
    @pytest.fixture
    def gate(self):
        settings = QualityGateSettings()
        return WriteQualityGate(settings)

    @pytest.fixture
    def soft_gate(self):
        settings = QualityGateSettings(enforce_evidence=False)
        return WriteQualityGate(settings)

    @pytest.fixture
    def hard_gate(self):
        settings = QualityGateSettings(enforce_evidence=True)
        return WriteQualityGate(settings)

    @pytest.mark.asyncio
    async def test_memory_layer_always_passes(self, gate):
        ctx = QualityContext(
            tool="remember",
            layer="memory",
            session_id="sess",
            silo_id="silo",
            content="observation",
        )
        result = await gate.assess(ctx)
        assert result.outcome == QualityOutcome.PASSED

    @pytest.mark.asyncio
    async def test_knowledge_with_evidence_passes(self, gate):
        ctx = QualityContext(
            tool="learn",
            layer="knowledge",
            session_id="sess",
            silo_id="silo",
            content="claim with evidence",
            evidence_refs=["file:///path/to/source.py"],
        )
        result = await gate.assess(ctx)
        assert result.outcome == QualityOutcome.PASSED

    @pytest.mark.asyncio
    async def test_knowledge_without_evidence_warns_soft(self, soft_gate):
        ctx = QualityContext(
            tool="learn",
            layer="knowledge",
            session_id="sess",
            silo_id="silo",
            content="claim without evidence",
            evidence_refs=None,
        )
        result = await soft_gate.assess(ctx)
        assert result.outcome == QualityOutcome.WARNED
        assert any(c.name == "evidence_present" for c in result.checks)

    @pytest.mark.asyncio
    async def test_knowledge_without_evidence_downgrades_hard(self, hard_gate):
        ctx = QualityContext(
            tool="learn",
            layer="knowledge",
            session_id="sess",
            silo_id="silo",
            content="claim without evidence",
            evidence_refs=None,
        )
        result = await hard_gate.assess(ctx)
        assert result.outcome == QualityOutcome.DOWNGRADED
        assert result.original_layer == "knowledge"

    @pytest.mark.asyncio
    async def test_wisdom_without_about_rejected(self, gate):
        ctx = QualityContext(
            tool="believe",
            layer="wisdom",
            session_id="sess",
            silo_id="silo",
            content="belief without grounding",
            about_refs=None,
        )
        result = await gate.assess(ctx)
        assert result.outcome == QualityOutcome.REJECTED

    @pytest.mark.asyncio
    async def test_wisdom_with_about_passes(self, gate):
        ctx = QualityContext(
            tool="believe",
            layer="wisdom",
            session_id="sess",
            silo_id="silo",
            content="belief with grounding",
            about_refs=["node:550e8400-e29b-41d4-a716-446655440000"],
        )
        result = await gate.assess(ctx)
        assert result.outcome == QualityOutcome.PASSED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sage/test_quality_gate.py::TestWriteQualityGateAssess -v`
Expected: FAIL

- [ ] **Step 3: Implement WriteQualityGate class**

Append to `src/context_service/sage/quality_gate.py`:

```python
from context_service.config.settings import QualityGateSettings
from context_service.sage.quality_types import (
    QualityContext,
    QualityOutcome,
    QualityResult,
)


class WriteQualityGate:
    """Write-path quality enforcement gate."""

    def __init__(self, settings: QualityGateSettings):
        self.settings = settings

    async def assess(self, ctx: QualityContext) -> QualityResult:
        """Run structural checks and return quality assessment."""
        if not self.settings.enabled:
            return QualityResult(outcome=QualityOutcome.PASSED, checks=[])

        checks: list[CheckResult] = []
        failed_checks: list[CheckResult] = []

        # Memory layer: no checks
        if ctx.layer == "memory":
            return QualityResult(outcome=QualityOutcome.PASSED, checks=[])

        # Knowledge layer checks
        if ctx.layer == "knowledge":
            # Evidence present
            ev_check = _check_evidence_present(
                ctx.evidence_refs, enforce=self.settings.enforce_evidence
            )
            checks.append(ev_check)
            if not ev_check.passed:
                failed_checks.append(ev_check)

            # Evidence format (only if evidence provided)
            if ctx.evidence_refs:
                fmt_check = _check_evidence_format(ctx.evidence_refs)
                checks.append(fmt_check)
                if not fmt_check.passed:
                    failed_checks.append(fmt_check)

        # Wisdom layer checks
        if ctx.layer == "wisdom":
            # About refs present
            about_check = _check_about_present(ctx.about_refs)
            checks.append(about_check)
            if not about_check.passed:
                failed_checks.append(about_check)
                # Hard reject for missing about refs
                if self.settings.enforce_about_refs:
                    return QualityResult(
                        outcome=QualityOutcome.REJECTED,
                        checks=checks,
                        reason="about_refs_required",
                        suggestions=["Pass about=[node:xxx] referencing supporting facts"],
                    )

            # No self-reference
            if ctx.about_refs:
                self_check = _check_no_self_ref(ctx.about_refs, ctx.node_id)
                checks.append(self_check)
                if not self_check.passed:
                    failed_checks.append(self_check)
                    return QualityResult(
                        outcome=QualityOutcome.REJECTED,
                        checks=checks,
                        reason="self_reference",
                        suggestions=["Remove self-reference from about refs"],
                    )

        # Determine outcome
        if not failed_checks:
            return QualityResult(outcome=QualityOutcome.PASSED, checks=checks)

        # Check if we should downgrade
        if ctx.layer == "knowledge" and self.settings.enforce_evidence:
            evidence_failed = any(c.name == "evidence_present" for c in failed_checks)
            if evidence_failed:
                return QualityResult(
                    outcome=QualityOutcome.DOWNGRADED,
                    checks=checks,
                    original_layer="knowledge",
                    reason="no_evidence",
                    suggestions=["Call learn again with evidence refs to promote to knowledge"],
                )

        # Default: warn
        return QualityResult(
            outcome=QualityOutcome.WARNED,
            checks=checks,
            suggestions=[c.message for c in failed_checks if c.message],
        )

    async def record(self, ctx: QualityContext, result: QualityResult) -> None:
        """Emit telemetry event (async, non-blocking)."""
        if not self.settings.emit_telemetry:
            return
        # TODO: Implement in Task 6
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_quality_gate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/sage/quality_gate.py tests/sage/test_quality_gate.py
git commit -m "feat(sage): implement WriteQualityGate.assess()"
```

---

## Task 5: Add Reaction Events

**Files:**
- Modify: `src/context_service/reactions/events.py`
- Test: `tests/reactions/test_events.py`

- [ ] **Step 1: Write test for new event types**

```python
# tests/reactions/test_events.py (append or create)

def test_write_quality_event_type_exists():
    from context_service.reactions.events import ReactionEventType
    
    assert hasattr(ReactionEventType, "WRITE_QUALITY")
    assert ReactionEventType.WRITE_QUALITY == "write_quality"


def test_check_semantic_duplicate_event_type_exists():
    from context_service.reactions.events import ReactionEventType
    
    assert hasattr(ReactionEventType, "CHECK_SEMANTIC_DUPLICATE")
    assert ReactionEventType.CHECK_SEMANTIC_DUPLICATE == "check_semantic_duplicate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/reactions/test_events.py -k "write_quality or semantic_duplicate" -v`
Expected: FAIL

- [ ] **Step 3: Add event types**

In `src/context_service/reactions/events.py`, add to `ReactionEventType` enum:

```python
    WRITE_QUALITY = "write_quality"
    CHECK_SEMANTIC_DUPLICATE = "check_semantic_duplicate"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/reactions/test_events.py -k "write_quality or semantic_duplicate" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/reactions/events.py tests/reactions/test_events.py
git commit -m "feat(reactions): add WRITE_QUALITY and CHECK_SEMANTIC_DUPLICATE event types"
```

---

## Task 6: Add Postgres Migration for write_quality_events

**Files:**
- Create: `src/context_service/alembic/versions/xxxx_add_write_quality_events.py`
- Create: `src/context_service/db/quality_queries.py`

- [ ] **Step 1: Create migration file**

Run: `uv run alembic revision -m "add write_quality_events table"`

- [ ] **Step 2: Implement migration**

```python
# In the generated migration file

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "..."  # auto-generated
down_revision = "..."  # auto-generated
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "write_quality_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("silo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("layer", sa.Text(), nullable=False),
        sa.Column("original_layer", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("checks_failed", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("about_node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recall_before_store", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("supersedes_used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("duplicate_detected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    
    op.create_index("idx_wqe_silo_created", "write_quality_events", ["silo_id", "created_at"])
    op.create_index("idx_wqe_outcome", "write_quality_events", ["outcome"])
    op.create_index("idx_wqe_tool", "write_quality_events", ["tool"])


def downgrade() -> None:
    op.drop_index("idx_wqe_tool")
    op.drop_index("idx_wqe_outcome")
    op.drop_index("idx_wqe_silo_created")
    op.drop_table("write_quality_events")
```

- [ ] **Step 3: Create quality_queries.py**

```python
# src/context_service/db/quality_queries.py
"""Postgres queries for write quality telemetry."""

INSERT_WRITE_QUALITY_EVENT = """
INSERT INTO write_quality_events (
    silo_id, session_id, agent_id, tool, layer, original_layer,
    outcome, checks_failed, evidence_count, about_node_count,
    recall_before_store, supersedes_used, duplicate_detected
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
)
"""
```

- [ ] **Step 4: Commit**

```bash
git add src/context_service/alembic/versions/ src/context_service/db/quality_queries.py
git commit -m "feat(db): add write_quality_events table migration"
```

---

## Task 7: Implement Telemetry Task Handler

**Files:**
- Modify: `src/context_service/reactions/tasks.py`
- Test: `tests/reactions/test_tasks.py`

- [ ] **Step 1: Write test for write_quality_task**

```python
# tests/reactions/test_tasks.py (append)

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_write_quality_task_inserts_event():
    """write_quality_task inserts event to Postgres."""
    from context_service.reactions.tasks import write_quality_task
    
    payload = {
        "silo_id": "550e8400-e29b-41d4-a716-446655440000",
        "session_id": "sess-123",
        "agent_id": "agent-456",
        "tool": "learn",
        "layer": "knowledge",
        "original_layer": None,
        "outcome": "passed",
        "checks_failed": [],
        "evidence_count": 2,
        "about_node_count": 0,
        "recall_before_store": True,
        "supersedes_used": False,
        "duplicate_detected": False,
    }
    
    mock_conn = AsyncMock()
    mock_pool = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    
    with patch("context_service.reactions.tasks.get_postgres_pool", return_value=mock_pool):
        await write_quality_task(payload, "550e8400-e29b-41d4-a716-446655440000")
    
    mock_conn.execute.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/reactions/test_tasks.py::test_write_quality_task_inserts_event -v`
Expected: FAIL

- [ ] **Step 3: Implement write_quality_task**

In `src/context_service/reactions/tasks.py`, add:

```python
from context_service.db.quality_queries import INSERT_WRITE_QUALITY_EVENT


@broker.task("write_quality_task")
async def write_quality_task(payload: dict, silo_id: str) -> None:
    """Persist write quality event to Postgres."""
    pool = get_postgres_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            INSERT_WRITE_QUALITY_EVENT,
            payload["silo_id"],
            payload["session_id"],
            payload.get("agent_id"),
            payload["tool"],
            payload["layer"],
            payload.get("original_layer"),
            payload["outcome"],
            payload.get("checks_failed", []),
            payload.get("evidence_count", 0),
            payload.get("about_node_count", 0),
            payload.get("recall_before_store", False),
            payload.get("supersedes_used", False),
            payload.get("duplicate_detected", False),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/reactions/test_tasks.py::test_write_quality_task_inserts_event -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/reactions/tasks.py tests/reactions/test_tasks.py
git commit -m "feat(reactions): add write_quality_task handler"
```

---

## Task 8: Implement WriteQualityGate.record()

**Files:**
- Modify: `src/context_service/sage/quality_gate.py`
- Test: `tests/sage/test_quality_gate.py`

- [ ] **Step 1: Write test for record()**

```python
# tests/sage/test_quality_gate.py (append)

from unittest.mock import AsyncMock, patch


class TestWriteQualityGateRecord:
    @pytest.mark.asyncio
    async def test_record_emits_reaction(self):
        settings = QualityGateSettings(emit_telemetry=True)
        gate = WriteQualityGate(settings)
        
        ctx = QualityContext(
            tool="learn",
            layer="knowledge",
            session_id="sess-123",
            silo_id="silo-456",
            content="test claim",
            evidence_refs=["file:///test.py"],
            node_id="node-789",
        )
        result = QualityResult(
            outcome=QualityOutcome.PASSED,
            checks=[CheckResult(passed=True, name="evidence_present")],
        )
        
        with patch("context_service.sage.quality_gate.emit_reaction") as mock_emit:
            mock_emit.return_value = None
            await gate.record(ctx, result)
            
            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            assert call_args[0][0] == "write_quality"

    @pytest.mark.asyncio
    async def test_record_skipped_when_disabled(self):
        settings = QualityGateSettings(emit_telemetry=False)
        gate = WriteQualityGate(settings)
        
        ctx = QualityContext(
            tool="learn", layer="knowledge", session_id="s", silo_id="s", content="c"
        )
        result = QualityResult(outcome=QualityOutcome.PASSED, checks=[])
        
        with patch("context_service.sage.quality_gate.emit_reaction") as mock_emit:
            await gate.record(ctx, result)
            mock_emit.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/sage/test_quality_gate.py::TestWriteQualityGateRecord -v`
Expected: FAIL

- [ ] **Step 3: Implement record()**

Update `WriteQualityGate.record()` in `src/context_service/sage/quality_gate.py`:

```python
from context_service.reactions.events import emit_reaction, ReactionEventType
from datetime import UTC, datetime


class WriteQualityGate:
    # ... existing code ...

    async def record(self, ctx: QualityContext, result: QualityResult) -> None:
        """Emit telemetry event (async, non-blocking)."""
        if not self.settings.emit_telemetry:
            return

        failed_checks = [c.name for c in result.checks if not c.passed]
        
        payload = {
            "silo_id": ctx.silo_id,
            "session_id": ctx.session_id,
            "agent_id": None,  # TODO: get from auth context
            "tool": ctx.tool,
            "layer": ctx.layer,
            "original_layer": result.original_layer,
            "outcome": result.outcome.value,
            "checks_failed": failed_checks,
            "evidence_count": len(ctx.evidence_refs) if ctx.evidence_refs else 0,
            "about_node_count": len(ctx.about_refs) if ctx.about_refs else 0,
            "recall_before_store": False,  # TODO: check Redis
            "supersedes_used": ctx.supersedes is not None,
            "duplicate_detected": any(c.name == "duplicate_check" and not c.passed for c in result.checks),
        }

        await emit_reaction(
            ReactionEventType.WRITE_QUALITY,
            silo_id=ctx.silo_id,
            payload=payload,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_quality_gate.py::TestWriteQualityGateRecord -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/sage/quality_gate.py tests/sage/test_quality_gate.py
git commit -m "feat(sage): implement WriteQualityGate.record() telemetry emission"
```

---

## Task 9: Set recall_called Flag in Recall Tool

**Files:**
- Modify: `src/context_service/mcp/tools/recall.py`
- Test: `tests/mcp/test_context_recall.py`

- [ ] **Step 1: Write test for recall_called flag**

```python
# tests/mcp/test_context_recall.py (append)

@pytest.mark.asyncio
async def test_recall_sets_session_flag(mock_redis):
    """recall sets session:xxx:recall_called in Redis."""
    # ... setup mocks ...
    
    await _recall_impl(query="test", session_id="sess-123", silo_id="silo-456")
    
    mock_redis.set.assert_called_with(
        "session:sess-123:recall_called", "1", ex=3600
    )
```

- [ ] **Step 2: Implement recall_called flag setting**

In `src/context_service/mcp/tools/recall.py`, after successful recall:

```python
# After query execution, before return
if session_id:
    redis = get_redis_client()
    if redis:
        await redis.set(
            f"session:{session_id}:recall_called",
            "1",
            ex=3600,  # 1 hour TTL
        )
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/mcp/test_context_recall.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/tools/recall.py tests/mcp/test_context_recall.py
git commit -m "feat(mcp): set recall_called session flag for quality gate tracking"
```

---

## Task 10: Integrate Gate into Transactions

**Files:**
- Modify: `src/context_service/sage/transactions.py`
- Test: `tests/sage/test_transactions.py`

- [ ] **Step 1: Write integration test**

```python
# tests/sage/test_transactions.py (append)

@pytest.mark.asyncio
async def test_store_claim_runs_quality_gate(mock_store, mock_settings):
    """store_claim calls quality gate assess and record."""
    mock_settings.quality_gate.enabled = True
    
    result = await store_claim(
        store=mock_store,
        content="Test claim",
        evidence_refs=["file:///test.py"],
        silo_id="silo-123",
        agent_id="agent-456",
    )
    
    assert "quality_signals" in result
    assert result["quality_signals"]["outcome"] == "passed"
```

- [ ] **Step 2: Integrate gate into store_claim**

In `src/context_service/sage/transactions.py`, modify `store_claim`:

```python
from context_service.sage.quality_gate import WriteQualityGate, get_quality_gate
from context_service.sage.quality_types import QualityContext, QualityOutcome

async def store_claim(
    store: HyperGraphStore,
    content: str,
    evidence_refs: list[str],
    silo_id: str,
    agent_id: str,
    # ... other params
) -> dict:
    """Store a claim to the Knowledge layer with quality enforcement."""
    settings = get_settings()
    gate = get_quality_gate()
    
    # Build quality context
    ctx = QualityContext(
        tool="learn",
        layer="knowledge",
        session_id=session_id or "unknown",
        silo_id=silo_id,
        content=content,
        evidence_refs=evidence_refs,
        supersedes=supersedes,
    )
    
    # Assess quality
    quality = await gate.assess(ctx)
    
    # Handle outcomes
    if quality.outcome == QualityOutcome.REJECTED:
        return {
            "error": "quality_rejected",
            "reason": quality.reason,
            "quality_signals": _build_quality_signals(quality, ctx.layer, False),
        }
    
    if quality.outcome == QualityOutcome.DOWNGRADED:
        # Route to memory layer instead
        return await store_memory(
            store=store,
            content=content,
            silo_id=silo_id,
            session_id=session_id,
            # ... with quality_signals indicating downgrade
        )
    
    # Proceed with normal store
    # ... existing implementation ...
    
    # Record telemetry (fire-and-forget)
    ctx.node_id = str(node_id)
    asyncio.create_task(gate.record(ctx, quality))
    
    # Enrich response
    result["quality_signals"] = _build_quality_signals(quality, ctx.layer, recall_before_store)
    
    return result
```

- [ ] **Step 3: Add helper to build quality signals**

```python
def _build_quality_signals(
    quality: QualityResult,
    layer_stored: str,
    recall_before_store: bool,
) -> dict:
    """Build quality_signals dict for response."""
    return {
        "outcome": quality.outcome.value,
        "layer_stored": layer_stored,
        "checks": [
            {"name": c.name, "passed": c.passed, "message": c.message}
            for c in quality.checks
        ],
        "suggestions": quality.suggestions,
        "recall_before_store": recall_before_store,
    }
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/sage/test_transactions.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/context_service/sage/transactions.py tests/sage/test_transactions.py
git commit -m "feat(sage): integrate quality gate into store_claim transaction"
```

---

## Task 11: Extend Trust Gate for Unverified Knowledge

**Files:**
- Modify: `src/context_service/mcp/tools/trust_gate.py`
- Modify: `src/context_service/config/settings.py`
- Test: `tests/mcp/test_trust_gate.py`

- [ ] **Step 1: Write test for unverified knowledge filtering**

```python
# tests/mcp/test_trust_gate.py (append)

def test_withhold_unverified_knowledge():
    """Trust gate withholds knowledge nodes without evidence."""
    from context_service.mcp.tools.trust_gate import apply_trust_gate
    
    results = [
        {"node_id": "a", "layer": "knowledge", "evidence_count": 2, "confidence": 0.8},
        {"node_id": "b", "layer": "knowledge", "evidence_count": 0, "confidence": 0.8},
        {"node_id": "c", "layer": "memory", "confidence": 0.8},
    ]
    
    surfaced, withheld = apply_trust_gate(
        results,
        confidence_floor=0.0,
        withhold_conflicts=True,
        withhold_unverified=True,
    )
    
    assert len(surfaced) == 2  # a and c
    assert withheld["count"] == 1
    assert withheld["by_reason"]["unverified_knowledge"] == 1
```

- [ ] **Step 2: Add withhold_unverified_knowledge to TrustGateConfig**

In `src/context_service/config/settings.py`:

```python
class TrustGateConfig(BaseModel):
    # ... existing fields ...
    
    withhold_unverified_knowledge: bool = Field(
        default=False,
        description="Withhold knowledge nodes lacking evidence from ambient recall",
    )
```

- [ ] **Step 3: Implement filtering in trust_gate.py**

```python
def apply_trust_gate(
    results: list[dict[str, Any]],
    *,
    confidence_floor: float,
    withhold_conflicts: bool,
    withhold_unverified: bool = False,  # NEW
    include_withheld: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_reason: dict[str, int] = {
        "unresolved_conflict": 0,
        "low_confidence": 0,
        "unverified_knowledge": 0,  # NEW
    }
    
    # ... existing logic ...
    
    for item in results:
        # ... existing checks ...
        
        # NEW: Check unverified knowledge
        if withhold_unverified and reason is None:
            layer = item.get("layer")
            evidence_count = item.get("evidence_count", 1)  # default to 1 for old nodes
            if layer == "knowledge" and evidence_count == 0:
                reason = "unverified_knowledge"
        
        # ... rest of logic ...
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/mcp/test_trust_gate.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/trust_gate.py src/context_service/config/settings.py tests/mcp/test_trust_gate.py
git commit -m "feat(trust-gate): add unverified_knowledge withhold reason"
```

---

## Task 12: Add Node Properties for Quality Metadata

**Files:**
- Modify: `src/context_service/sage/transactions.py`
- Create: Alembic migration for node properties

- [ ] **Step 1: Create migration for node properties**

Run: `uv run alembic revision -m "add quality metadata to nodes"`

```python
def upgrade() -> None:
    # Add columns to nodes (Memgraph - done via Cypher, not SQL)
    # This is a no-op migration for Postgres; Memgraph schema is dynamic
    pass
```

- [ ] **Step 2: Set quality properties on node creation**

In transaction store functions, set:

```python
node_properties = {
    # ... existing properties ...
    "quality_outcome": quality.outcome.value,
    "evidence_count": len(evidence_refs) if evidence_refs else 0,
    "pending_promotion": quality.outcome == QualityOutcome.DOWNGRADED,
}
```

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): persist quality metadata on nodes"
```

---

## Task 13: Final Integration Test

**Files:**
- Create: `tests/integration/test_quality_gate_integration.py`

- [ ] **Step 1: Write end-to-end integration test**

```python
# tests/integration/test_quality_gate_integration.py
"""Integration tests for write quality gate."""

import pytest
from context_service.sage.transactions import store_claim, store_memory


@pytest.mark.integration
class TestQualityGateIntegration:
    @pytest.mark.asyncio
    async def test_learn_with_evidence_stores_to_knowledge(self, test_store, test_silo):
        result = await store_claim(
            store=test_store,
            content="Verified claim",
            evidence_refs=["file:///src/test.py"],
            silo_id=test_silo,
            agent_id="test-agent",
        )
        
        assert "error" not in result
        assert result["quality_signals"]["outcome"] == "passed"
        assert result["quality_signals"]["layer_stored"] == "knowledge"

    @pytest.mark.asyncio
    async def test_learn_without_evidence_warns_soft_mode(self, test_store, test_silo, soft_settings):
        result = await store_claim(
            store=test_store,
            content="Unverified claim",
            evidence_refs=[],
            silo_id=test_silo,
            agent_id="test-agent",
        )
        
        assert "error" not in result
        assert result["quality_signals"]["outcome"] == "warned"

    @pytest.mark.asyncio
    async def test_learn_without_evidence_downgrades_hard_mode(self, test_store, test_silo, hard_settings):
        result = await store_claim(
            store=test_store,
            content="Unverified claim",
            evidence_refs=[],
            silo_id=test_silo,
            agent_id="test-agent",
        )
        
        assert "error" not in result
        assert result["quality_signals"]["outcome"] == "downgraded"
        assert result["quality_signals"]["layer_stored"] == "memory"

    @pytest.mark.asyncio
    async def test_believe_without_about_rejected(self, test_store, test_silo):
        from context_service.sage.transactions import store_commitment
        
        result = await store_commitment(
            store=test_store,
            content="Ungrounded belief",
            about_refs=[],
            silo_id=test_silo,
            agent_id="test-agent",
        )
        
        assert result.get("error") == "quality_rejected"
```

- [ ] **Step 2: Run integration tests**

Run: `uv run pytest tests/integration/test_quality_gate_integration.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_quality_gate_integration.py
git commit -m "test(integration): add quality gate end-to-end tests"
```

---

## Task 14: Run Full Test Suite and Typecheck

- [ ] **Step 1: Run typecheck**

Run: `just check`
Expected: PASS with no new type errors

- [ ] **Step 2: Run full test suite**

Run: `just test`
Expected: All tests pass

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat(sage): complete write quality gate implementation"
```

---

## Summary

| Task | Description | Est. Time |
|------|-------------|-----------|
| 1 | QualityGateSettings | 10 min |
| 2 | Quality types | 10 min |
| 3 | Check functions | 20 min |
| 4 | WriteQualityGate.assess() | 20 min |
| 5 | Reaction events | 5 min |
| 6 | Postgres migration | 15 min |
| 7 | Telemetry task handler | 15 min |
| 8 | WriteQualityGate.record() | 15 min |
| 9 | Recall flag | 10 min |
| 10 | Transaction integration | 30 min |
| 11 | Trust gate extension | 15 min |
| 12 | Node quality properties | 10 min |
| 13 | Integration tests | 20 min |
| 14 | Final verification | 10 min |

**Total estimated time:** ~3-4 hours

**Dependencies:**
- Tasks 1-4 can run in parallel (no dependencies)
- Task 5-8 depend on types being defined
- Task 10 depends on all gate logic being complete
- Task 13-14 are final verification
