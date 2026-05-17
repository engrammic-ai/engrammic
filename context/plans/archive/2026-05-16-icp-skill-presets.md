# ICP Skill Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind a named ICP "preset" per silo that shapes `patterns` skill delivery (namespace + onboarding) and one recall default, defined in git-versioned yaml with the silo binding stored in Postgres.

**Architecture:** A `PresetRegistry` loads `mcp_presets.yaml` (mirrors the existing `mcp_tools.yaml` loader). The silo->preset binding is a new nullable `preset` column on the Postgres `silo_config` table, read per request through a TTL-cached resolver. The `patterns` tool resolves the silo's preset when no explicit `profile` is passed, auto-qualifies a bare `onboarding` name against the preset namespace, and merges preset-namespace skills ahead of `engrammic:*`. Preset `param_overrides` feed one wired recall default.

**Tech Stack:** Python 3.12, FastAPI/FastMCP, SQLAlchemy + Alembic (Postgres), pytest, structlog, PyYAML, pydantic-settings.

**Conventions:** All commands via `uv run`. `just check` (ruff + mypy strict) must pass. No emojis. Tests mirror `src/` under `tests/`. Branch: `feat/icp-skill-presets`.

---

### Task 1: PresetRegistry and mcp_presets.yaml

**Files:**
- Create: `src/context_service/config/mcp_presets.yaml`
- Create: `src/context_service/mcp/tools/preset_registry.py`
- Test: `tests/mcp/tools/test_preset_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/tools/test_preset_registry.py
import pytest

from context_service.mcp.tools.preset_registry import (
    Preset,
    get_preset,
    load_preset_config,
)


def test_loads_builtin_presets():
    cfg = load_preset_config()
    assert "coding" in cfg["presets"]
    assert "b2b-ops" in cfg["presets"]


def test_get_preset_returns_typed_preset():
    p = get_preset("coding")
    assert isinstance(p, Preset)
    assert p.name == "coding"
    assert p.namespace == "coding"
    assert p.onboarding_skill == "coding:onboarding"
    assert isinstance(p.param_overrides, dict)


def test_unknown_preset_raises_keyerror():
    with pytest.raises(KeyError):
        get_preset("does-not-exist")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_preset_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'context_service.mcp.tools.preset_registry'`

- [ ] **Step 3: Create the preset config file**

```yaml
# src/context_service/config/mcp_presets.yaml
# ICP skill preset definitions. Git-versioned. Binding (which silo uses which
# preset) lives in the Postgres silo_config.preset column, not here.

presets:
  coding:
    namespace: coding
    onboarding_skill: "coding:onboarding"
    param_overrides:
      default_recall_top_k: 15

  b2b-ops:
    namespace: b2b-ops
    onboarding_skill: "b2b-ops:onboarding"
    param_overrides:
      default_recall_top_k: 8
```

- [ ] **Step 4: Write minimal implementation**

```python
# src/context_service/mcp/tools/preset_registry.py
"""ICP preset registry - loads preset definitions from YAML.

Mirrors the loader pattern in mcp/tools/registry.py. The silo->preset binding
is NOT here; it lives in the Postgres silo_config.preset column.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "mcp_presets.yaml"
_cached_config: dict[str, Any] | None = None


class Preset(BaseModel):
    """A resolved ICP preset."""

    name: str
    namespace: str
    onboarding_skill: str
    param_overrides: dict[str, Any] = Field(default_factory=dict)


def load_preset_config() -> dict[str, Any]:
    """Load preset configuration from YAML. Cached after first call.

    Raises on malformed yaml so a bad config fails fast at boot, matching
    mcp_tools.yaml behavior.
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    with open(_CONFIG_PATH) as f:
        _cached_config = yaml.safe_load(f)

    if not isinstance(_cached_config, dict) or "presets" not in _cached_config:
        raise ValueError(f"Malformed {_CONFIG_PATH}: missing 'presets' key")

    logger.info("mcp_preset_config_loaded", path=str(_CONFIG_PATH))
    return _cached_config


def get_preset(name: str) -> Preset:
    """Return the typed Preset for `name`. Raises KeyError if unknown."""
    config = load_preset_config()
    presets = config["presets"]
    if name not in presets:
        raise KeyError(name)
    raw = presets[name]
    return Preset(
        name=name,
        namespace=raw["namespace"],
        onboarding_skill=raw["onboarding_skill"],
        param_overrides=raw.get("param_overrides") or {},
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_preset_registry.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/context_service/config/mcp_presets.yaml src/context_service/mcp/tools/preset_registry.py tests/mcp/tools/test_preset_registry.py
git commit -m "feat(presets): add PresetRegistry and mcp_presets.yaml"
```

---

### Task 2: Settings.default_icp_preset field

**Files:**
- Modify: `src/context_service/config/settings.py` (the top-level `Settings` class, declared at line 690; add the field near `mcp_tool_profile` at line 775)
- Test: `tests/config/test_settings_icp_preset.py`

Do NOT touch `PromptsConfig.mcp_preset` (line ~413) - it is an unrelated LLM prompt-preset field.

- [ ] **Step 1: Write the failing test**

```python
# tests/config/test_settings_icp_preset.py
from context_service.config.settings import Settings


def test_default_icp_preset_defaults_to_coding():
    s = Settings()
    assert s.default_icp_preset == "coding"


def test_default_icp_preset_env_override(monkeypatch):
    monkeypatch.setenv("DEFAULT_ICP_PRESET", "b2b-ops")
    s = Settings()
    assert s.default_icp_preset == "b2b-ops"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/config/test_settings_icp_preset.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'default_icp_preset'`

- [ ] **Step 3: Add the field**

In `src/context_service/config/settings.py`, immediately after the `mcp_tool_profile` field (line 775), add:

```python
    default_icp_preset: str = Field(default="coding")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/config/test_settings_icp_preset.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/context_service/config/settings.py tests/config/test_settings_icp_preset.py
git commit -m "feat(presets): add Settings.default_icp_preset"
```

---

### Task 3: Postgres silo_config.preset column + Alembic migration

**Files:**
- Modify: `src/context_service/models/postgres/org.py:46-77` (`SiloConfig` ORM)
- Create: `alembic/versions/0002_add_silo_config_preset.py`
- Test: `tests/models/postgres/test_silo_config_preset.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/models/postgres/test_silo_config_preset.py
from uuid import uuid4

from context_service.models.postgres.org import SiloConfig


def test_silo_config_has_nullable_preset_default_none():
    sc = SiloConfig(silo_id=uuid4(), org_id=uuid4(), name="s1")
    assert sc.preset is None


def test_silo_config_accepts_preset():
    sc = SiloConfig(silo_id=uuid4(), org_id=uuid4(), name="s1", preset="coding")
    assert sc.preset == "coding"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/models/postgres/test_silo_config_preset.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'preset'`

- [ ] **Step 3: Add the column to the ORM model**

In `src/context_service/models/postgres/org.py`, add the mapped column to `SiloConfig` (after `feature_flags`, line 57):

```python
    preset: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

And extend `SiloConfig.__init__` signature and body. Replace the existing `__init__` (lines 63-77) with:

```python
    def __init__(
        self,
        silo_id: UUID | str,
        org_id: UUID | str,
        name: str,
        quotas: dict[str, Any] | None = None,
        feature_flags: dict[str, Any] | None = None,
        preset: str | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.silo_id = silo_id  # type: ignore[assignment]
        self.org_id = org_id  # type: ignore[assignment]
        self.name = name
        self.quotas = quotas if quotas is not None else {}
        self.feature_flags = feature_flags if feature_flags is not None else {}
        self.preset = preset
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/models/postgres/test_silo_config_preset.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Create the Alembic migration**

```python
# alembic/versions/0002_add_silo_config_preset.py
"""add preset column to silo_config

Revision ID: 0002_add_silo_config_preset
Revises: 0001_initial_schema
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_add_silo_config_preset"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "silo_config",
        sa.Column("preset", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("silo_config", "preset")
```

Verify the `down_revision` string matches the actual revision id in `alembic/versions/0001_initial_schema.py` (open it and read the `revision = ...` line). If it differs, set `down_revision` to that exact value.

- [ ] **Step 6: Apply and reverse the migration to verify it is clean**

Run: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: three commands succeed with no error; `silo_config.preset` exists after the final upgrade.

- [ ] **Step 7: Commit**

```bash
git add src/context_service/models/postgres/org.py alembic/versions/0002_add_silo_config_preset.py tests/models/postgres/test_silo_config_preset.py
git commit -m "feat(presets): add silo_config.preset column and migration"
```

---

### Task 4: TTL-cached silo->preset resolver

**Files:**
- Create: `src/context_service/mcp/preset_resolver.py`
- Test: `tests/mcp/test_preset_resolver.py`

The resolver maps a `silo_id` to a resolved `Preset` by reading `silo_config.preset` from Postgres, falling back to `settings.default_icp_preset`, with an in-process TTL cache (default 60s) so `patterns` does not issue a DB round trip per call.

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/test_preset_resolver.py
import pytest

from context_service.mcp.preset_resolver import PresetResolver


class _FakeBindingSource:
    """Stands in for the Postgres silo_config.preset lookup."""

    def __init__(self, value: str | None):
        self.value = value
        self.calls = 0

    async def get_silo_preset_name(self, silo_id: str) -> str | None:
        self.calls += 1
        return self.value


@pytest.mark.asyncio
async def test_resolves_bound_preset():
    src = _FakeBindingSource("b2b-ops")
    r = PresetResolver(binding_source=src, default_preset="coding", ttl_seconds=60)
    p = await r.resolve("silo-1")
    assert p.name == "b2b-ops"
    assert p.namespace == "b2b-ops"


@pytest.mark.asyncio
async def test_falls_back_to_default_when_unbound():
    src = _FakeBindingSource(None)
    r = PresetResolver(binding_source=src, default_preset="coding", ttl_seconds=60)
    p = await r.resolve("silo-1")
    assert p.name == "coding"


@pytest.mark.asyncio
async def test_unknown_bound_name_falls_back_to_default():
    src = _FakeBindingSource("garbage-preset")
    r = PresetResolver(binding_source=src, default_preset="coding", ttl_seconds=60)
    p = await r.resolve("silo-1")
    assert p.name == "coding"


@pytest.mark.asyncio
async def test_cache_avoids_repeat_db_calls_within_ttl():
    src = _FakeBindingSource("coding")
    r = PresetResolver(binding_source=src, default_preset="coding", ttl_seconds=60)
    await r.resolve("silo-1")
    await r.resolve("silo-1")
    assert src.calls == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_preset_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'context_service.mcp.preset_resolver'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/context_service/mcp/preset_resolver.py
"""Resolve a silo to its ICP Preset, with a small in-process TTL cache.

Binding source of truth: Postgres silo_config.preset. Definitions come from
the PresetRegistry (mcp_presets.yaml). Unknown or absent bindings fall back to
the configured default preset.
"""

from __future__ import annotations

import time
from typing import Protocol

import structlog

from context_service.mcp.tools.preset_registry import Preset, get_preset

logger = structlog.get_logger(__name__)


class BindingSource(Protocol):
    """Reads the raw preset name bound to a silo (or None)."""

    async def get_silo_preset_name(self, silo_id: str) -> str | None: ...


class PresetResolver:
    """Silo -> Preset with TTL caching."""

    def __init__(
        self,
        binding_source: BindingSource,
        default_preset: str,
        ttl_seconds: float = 60.0,
    ) -> None:
        self._src = binding_source
        self._default = default_preset
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, Preset]] = {}

    async def resolve(self, silo_id: str) -> Preset:
        now = time.monotonic()
        cached = self._cache.get(silo_id)
        if cached is not None and (now - cached[0]) < self._ttl:
            return cached[1]

        raw_name = await self._src.get_silo_preset_name(silo_id)
        preset = self._resolve_name(raw_name)
        self._cache[silo_id] = (now, preset)
        return preset

    def _resolve_name(self, raw_name: str | None) -> Preset:
        name = raw_name or self._default
        try:
            return get_preset(name)
        except KeyError:
            logger.warning(
                "invalid_mcp_preset", preset=name, fallback=self._default
            )
            return get_preset(self._default)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/test_preset_resolver.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/preset_resolver.py tests/mcp/test_preset_resolver.py
git commit -m "feat(presets): add TTL-cached silo->preset resolver"
```

---

### Task 5: Postgres binding source + wire resolver into MCP services

**Files:**
- Create: `src/context_service/mcp/postgres_binding_source.py`
- Modify: `src/context_service/mcp/server.py` (add `get_preset_resolver()` accessor near `get_skill_service()` at line 103-111; construct resolver in `configure_services()` near line 63-69)
- Test: `tests/mcp/test_postgres_binding_source.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/test_postgres_binding_source.py
import pytest
from sqlalchemy import insert
from uuid import uuid4

from context_service.models.postgres.org import OrgPreferences, SiloConfig
from context_service.mcp.postgres_binding_source import PostgresBindingSource


@pytest.mark.asyncio
async def test_returns_preset_for_bound_silo(pg_session):
    org_id = uuid4()
    silo_id = uuid4()
    pg_session.add(OrgPreferences(org_id=org_id))
    pg_session.add(
        SiloConfig(silo_id=silo_id, org_id=org_id, name="s", preset="b2b-ops")
    )
    await pg_session.flush()

    src = PostgresBindingSource()
    assert await src.get_silo_preset_name(str(silo_id)) == "b2b-ops"


@pytest.mark.asyncio
async def test_returns_none_for_unbound_or_missing_silo(pg_session):
    src = PostgresBindingSource()
    assert await src.get_silo_preset_name(str(uuid4())) is None
```

If no `pg_session` fixture exists in `tests/conftest.py`, reuse the existing Postgres test-session fixture used by other `tests/models/postgres/` or `tests/services/` tests (grep `tests/` for `silo_config` or `OrgPreferences` in a test that writes to Postgres and copy that fixture name). Match the fixture name to the existing one.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/test_postgres_binding_source.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'context_service.mcp.postgres_binding_source'`

- [ ] **Step 3: Write the binding source**

```python
# src/context_service/mcp/postgres_binding_source.py
"""Reads silo_config.preset from Postgres for the PresetResolver."""

from __future__ import annotations

from sqlalchemy import select

from context_service.db.postgres import get_session
from context_service.models.postgres.org import SiloConfig


class PostgresBindingSource:
    """BindingSource backed by the Postgres silo_config table."""

    async def get_silo_preset_name(self, silo_id: str) -> str | None:
        async for session in get_session():
            stmt = select(SiloConfig.preset).where(
                SiloConfig.silo_id == silo_id
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return row
        return None
```

Note: `get_session()` (`src/context_service/db/postgres.py:82`) is an async generator; the `async for ... return` pattern above consumes exactly one session and is the established read pattern. If other read-only call sites in the codebase use a different helper (grep `async for session in get_session`), match whichever pattern is dominant.

- [ ] **Step 4: Wire the resolver accessor into server.py**

In `src/context_service/mcp/server.py`, inside `configure_services()` after the skills block (line 69), add:

```python
    from context_service.config.settings import get_settings
    from context_service.mcp.postgres_binding_source import PostgresBindingSource
    from context_service.mcp.preset_resolver import PresetResolver

    _services["preset_resolver"] = PresetResolver(
        binding_source=PostgresBindingSource(),
        default_preset=get_settings().default_icp_preset,
    )
```

If `get_settings()` is not the accessor name, grep `src/context_service/config/settings.py` for the module-level settings accessor (e.g. `get_settings` or `settings`) and use that.

Then add an accessor next to `get_skill_service()` (after line 111):

```python
def get_preset_resolver() -> Any:
    """Get the configured PresetResolver instance."""
    if "preset_resolver" not in _services:
        raise RuntimeError(
            "PresetResolver not configured — call configure_services() at startup"
        )
    return _services["preset_resolver"]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/mcp/test_postgres_binding_source.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/postgres_binding_source.py src/context_service/mcp/server.py tests/mcp/test_postgres_binding_source.py
git commit -m "feat(presets): postgres binding source and resolver wiring"
```

---

### Task 6: Reserve coding: and b2b-ops: namespaces

**Files:**
- Modify: `src/context_service/schemas/skill.py:22-30` (`validate_name_format`)
- Modify: `src/context_service/services/skills.py:214-215` (`import_from` guard)
- Test: `tests/schemas/test_skill_reserved_namespaces.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/schemas/test_skill_reserved_namespaces.py
import pytest
from pydantic import ValidationError

from context_service.schemas.skill import SkillCreate


@pytest.mark.parametrize("ns", ["engrammic", "coding", "b2b-ops"])
def test_reserved_namespaces_rejected(ns):
    with pytest.raises(ValidationError):
        SkillCreate(name=f"{ns}:mine", description="d", body="b")


def test_non_reserved_namespace_allowed():
    s = SkillCreate(name="acme:mine", description="d", body="b")
    assert s.name == "acme:mine"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/schemas/test_skill_reserved_namespaces.py -v`
Expected: FAIL - `coding:mine` and `b2b-ops:mine` do not raise yet.

- [ ] **Step 3: Update the validator**

In `src/context_service/schemas/skill.py`, replace the single-namespace check inside `validate_name_format` (line 27-28):

```python
        if v.startswith("engrammic:"):
            raise ValueError("The 'engrammic:' namespace is reserved")
```

with:

```python
        for reserved in ("engrammic:", "coding:", "b2b-ops:"):
            if v.startswith(reserved):
                raise ValueError(f"The '{reserved}' namespace is reserved")
```

- [ ] **Step 4: Update the import_from guard**

In `src/context_service/services/skills.py`, replace lines 214-215:

```python
        if name.startswith("engrammic:"):
            raise ValueError(f"Skill name '{name}' uses reserved namespace 'engrammic'")
```

with:

```python
        for reserved in ("engrammic:", "coding:", "b2b-ops:"):
            if name.startswith(reserved):
                raise ValueError(
                    f"Skill name '{name}' uses reserved namespace '{reserved.rstrip(':')}'"
                )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/schemas/test_skill_reserved_namespaces.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add src/context_service/schemas/skill.py src/context_service/services/skills.py tests/schemas/test_skill_reserved_namespaces.py
git commit -m "feat(presets): reserve coding and b2b-ops skill namespaces"
```

---

### Task 7: patterns preset resolution, auto-qualification, merge order

**Files:**
- Modify: `src/context_service/mcp/tools/patterns.py` (`_patterns_impl`, lines 17-56; docstring at 71-87)
- Test: `tests/mcp/tools/test_patterns_presets.py`

Behavior:
- Explicit `profile` arg: used verbatim as the namespace filter (today's behavior, no preset lookup).
- No `profile`: resolve silo preset, use `preset.namespace`. For `list`/`search`, do NOT pass `namespace` to the service (so base `engrammic:*` and user skills are still returned); instead reorder results so preset-namespace skills come first, then everything else in existing order.
- `get` with a bare name (no `:`): auto-qualify to `f"{preset.namespace}:{name}"`. A name containing `:` is passed through unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/tools/test_patterns_presets.py
import pytest

from context_service.mcp.tools import patterns as patterns_mod


class _Skill:
    def __init__(self, name: str):
        self.name = name

    def model_dump(self, exclude_none: bool = True):
        return {"name": self.name}


class _FakeSkillSvc:
    def __init__(self):
        self.last_namespace = "UNSET"

    async def list(self, silo_id, namespace=None, limit=50, offset=0):
        self.last_namespace = namespace
        return [_Skill("engrammic:recall"), _Skill("coding:onboarding")]

    async def get(self, silo_id, name):
        return _Skill(name) if name == "coding:onboarding" else None


class _FakePreset:
    name = "coding"
    namespace = "coding"
    onboarding_skill = "coding:onboarding"


class _FakeResolver:
    async def resolve(self, silo_id):
        return _FakePreset()


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    svc = _FakeSkillSvc()
    monkeypatch.setattr(patterns_mod, "get_skill_service", lambda: svc)
    monkeypatch.setattr(patterns_mod, "get_preset_resolver", lambda: _FakeResolver())

    async def _auth():
        class A:
            org_id = "org-1"
        return A()

    monkeypatch.setattr(patterns_mod, "get_mcp_auth_context", _auth)
    monkeypatch.setattr(patterns_mod, "derive_silo_id", lambda org_id: "silo-1")
    return svc


@pytest.mark.asyncio
async def test_list_without_profile_ranks_preset_namespace_first(_patch):
    out = await patterns_mod._patterns_impl("list")
    names = [p["name"] for p in out["patterns"]]
    assert names[0] == "coding:onboarding"
    assert "engrammic:recall" in names
    # base guides not filtered out: service called with no namespace
    assert _patch.last_namespace is None


@pytest.mark.asyncio
async def test_explicit_profile_passed_through_as_namespace(_patch):
    await patterns_mod._patterns_impl("list", profile="reasoning")
    assert _patch.last_namespace == "reasoning"


@pytest.mark.asyncio
async def test_get_bare_name_autoqualifies_to_preset_namespace(_patch):
    out = await patterns_mod._patterns_impl("get", name="onboarding")
    assert out["pattern"]["name"] == "coding:onboarding"


@pytest.mark.asyncio
async def test_get_qualified_name_passed_through(_patch):
    out = await patterns_mod._patterns_impl("get", name="engrammic:recall")
    assert out["error"] == "not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_patterns_presets.py -v`
Expected: FAIL (`get_preset_resolver` not imported in patterns; no auto-qualify/reorder logic).

- [ ] **Step 3: Rewrite `_patterns_impl`**

Replace the body of `_patterns_impl` in `src/context_service/mcp/tools/patterns.py` (lines 17-56) with:

```python
async def _patterns_impl(
    action: Literal["list", "get", "search"],
    name: str | None = None,
    query: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Implementation for patterns tool."""
    auth = await get_mcp_auth_context()
    silo_id = str(derive_silo_id(auth.org_id))

    try:
        skill_svc = get_skill_service()
    except RuntimeError:
        return {"error": "patterns_unavailable", "message": "Patterns service not configured"}

    # Resolve preset namespace only when caller did not pin a profile.
    preset_ns: str | None = None
    if profile is None:
        try:
            preset = await get_preset_resolver().resolve(silo_id)
            preset_ns = preset.namespace
        except RuntimeError:
            preset_ns = None

    def _rank(skills: list[Any]) -> list[Any]:
        if preset_ns is None:
            return skills
        prefix = f"{preset_ns}:"
        first = [s for s in skills if s.name.startswith(prefix)]
        rest = [s for s in skills if not s.name.startswith(prefix)]
        return first + rest

    if action == "list":
        skills = await skill_svc.list(silo_id, namespace=profile, limit=50, offset=0)
        ranked = _rank(skills)
        return {
            "patterns": [s.model_dump(exclude_none=True) for s in ranked],
            "count": len(ranked),
        }

    elif action == "get":
        if not name:
            return {"error": "missing_name", "message": "name required for get action"}
        resolved_name = name
        if ":" not in name and preset_ns is not None:
            resolved_name = f"{preset_ns}:{name}"
        skill = await skill_svc.get(silo_id, resolved_name)
        if not skill:
            return {"error": "not_found", "message": f"Pattern not found: {resolved_name}"}
        return {"pattern": skill.model_dump(exclude_none=True)}

    elif action == "search":
        if not query:
            return {"error": "missing_query", "message": "query required for search action"}
        skills = await skill_svc.search(silo_id, query, namespace=profile, limit=20)
        ranked = _rank(skills)
        return {
            "patterns": [s.model_dump(exclude_none=True) for s in ranked],
            "count": len(ranked),
        }

    return {"error": "invalid_action", "valid": ["list", "get", "search"]}
```

Add the import at the top of `patterns.py` (in the existing `from context_service.mcp.server import ...` line at line 8):

```python
from context_service.mcp.server import (
    get_mcp_auth_context,
    get_preset_resolver,
    get_skill_service,
)
```

Update the registered tool's `profile` docstring (lines 79) to:

```python
            profile: Optional explicit namespace filter (e.g. standard|reasoning).
                When omitted, the silo's ICP preset namespace is ranked first
                and a bare `name` in `get` is auto-qualified to it.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_patterns_presets.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the existing patterns tests to check for regressions**

Run: `uv run pytest tests/ -k patterns -v`
Expected: all pass. If a pre-existing patterns test asserted `namespace=profile` filtering with no profile, update it to the new ranking behavior (base skills are no longer filtered out when no profile is passed).

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/tools/patterns.py tests/mcp/tools/test_patterns_presets.py
git commit -m "feat(presets): preset-aware patterns resolution and ranking"
```

---

### Task 8: Onboarding pointer line in mcp_tools.yaml

**Files:**
- Modify: `src/context_service/config/mcp_tools.yaml` (`mcp_instructions` block)
- Test: `tests/mcp/tools/test_mcp_instructions_pointer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/tools/test_mcp_instructions_pointer.py
from context_service.mcp.tools.registry import get_mcp_instructions


def test_instructions_point_to_onboarding_pattern():
    text = get_mcp_instructions()
    assert "patterns" in text
    assert "onboarding" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_mcp_instructions_pointer.py -v`
Expected: FAIL (current `mcp_instructions` mentions `patterns` 0 times in the prose).

Note: `registry.py` caches config in `_cached_config`. If a prior test in the same process loaded it, run this test file in isolation (the command above already does).

- [ ] **Step 3: Add the pointer line**

In `src/context_service/config/mcp_tools.yaml`, append to the `mcp_instructions` block, after the `Guidelines:` list:

```yaml
  Onboarding:
  - At session start, call patterns(action='get', name='onboarding') for your workflow guide
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_mcp_instructions_pointer.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add src/context_service/config/mcp_tools.yaml tests/mcp/tools/test_mcp_instructions_pointer.py
git commit -m "feat(presets): point mcp_instructions at onboarding pattern"
```

---

### Task 9: Wire default_recall_top_k from preset into recall

**Files:**
- Modify: `src/context_service/mcp/tools/recall.py:19-38` (`_recall_impl`)
- Test: `tests/mcp/tools/test_recall_preset_top_k.py`

Behavior: when `recall` is called without an explicit `top_k`, the effective `top_k` comes from the silo preset's `param_overrides["default_recall_top_k"]`; an explicit `top_k` argument always wins.

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/tools/test_recall_preset_top_k.py
import pytest

from context_service.mcp.tools import recall as recall_mod


class _FakePreset:
    param_overrides = {"default_recall_top_k": 15}


class _FakeResolver:
    async def resolve(self, silo_id):
        return _FakePreset()


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    captured = {}

    async def _fake_context_recall(*, silo_id, query, node_ids, depth, layers, top_k):
        captured["top_k"] = top_k
        return {"results": []}

    async def _auth():
        class A:
            org_id = "org-1"
        return A()

    monkeypatch.setattr(recall_mod, "_context_recall", _fake_context_recall)
    monkeypatch.setattr(recall_mod, "get_mcp_auth_context", _auth)
    monkeypatch.setattr(recall_mod, "derive_silo_id", lambda org_id: "silo-1")
    monkeypatch.setattr(
        recall_mod, "get_preset_resolver", lambda: _FakeResolver(), raising=False
    )
    return captured


@pytest.mark.asyncio
async def test_top_k_defaults_from_preset(_patch):
    await recall_mod._recall_impl(query="x")
    assert _patch["top_k"] == 15


@pytest.mark.asyncio
async def test_explicit_top_k_overrides_preset(_patch):
    await recall_mod._recall_impl(query="x", top_k=3)
    assert _patch["top_k"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_recall_preset_top_k.py -v`
Expected: FAIL (`get_preset_resolver` not referenced in recall; default stays 10/3).

- [ ] **Step 3: Implement preset-sourced default**

In `src/context_service/mcp/tools/recall.py`, change the `_recall_impl` signature default for `top_k` from `10` to a sentinel and resolve it. Replace lines 19-38:

```python
async def _recall_impl(
    query: str | None = None,
    node_ids: list[str] | None = None,
    depth: int = 0,
    layers: list[str] | None = None,
    top_k: int | None = None,
    include_hypotheses: bool = False,
) -> dict[str, Any]:
    """Implementation for recall tool."""
    auth = await get_mcp_auth_context()
    silo_id = str(derive_silo_id(auth.org_id))

    effective_top_k = top_k
    if effective_top_k is None:
        effective_top_k = 10
        try:
            from context_service.mcp.server import get_preset_resolver

            preset = await get_preset_resolver().resolve(silo_id)
            override = preset.param_overrides.get("default_recall_top_k")
            if isinstance(override, int) and override > 0:
                effective_top_k = override
        except RuntimeError:
            pass

    result = await _context_recall(
        silo_id=silo_id,
        query=query,
        node_ids=node_ids,
        depth=depth,
        layers=layers,
        top_k=effective_top_k,
    )
```

Also update the registered `recall` tool wrapper signature (later in the same file, the `@mcp.tool` function) so its `top_k` parameter default becomes `top_k: int | None = None` and it forwards the value unchanged to `_recall_impl`. Grep the file for the second `top_k` occurrence in the tool registration and change `= 10` to `= None`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_recall_preset_top_k.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run existing recall tests for regressions**

Run: `uv run pytest tests/ -k recall -v`
Expected: all pass. If a test asserted the literal default `top_k == 10`, it still holds (fallback is 10 when no resolver/override).

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/tools/recall.py tests/mcp/tools/test_recall_preset_top_k.py
git commit -m "feat(presets): source recall default top_k from preset"
```

---

### Task 10: Ship ICP skill bundles and update README install path

**Files:**
- Create: `skills/coding:onboarding/SKILL.md`
- Create: `skills/b2b-ops:onboarding/SKILL.md`
- Modify: `skills/README.md`
- Test: `tests/skills/test_icp_bundles.py`

`_load_builtin` keys by frontmatter `name`, not directory name, but existing dirs use the `namespace:name` form - follow that convention.

- [ ] **Step 1: Write the failing test**

```python
# tests/skills/test_icp_bundles.py
from pathlib import Path

import yaml


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n")
    fm = text.split("---\n", 2)[1]
    return yaml.safe_load(fm)


def test_coding_onboarding_bundle_valid():
    p = Path("skills/coding:onboarding/SKILL.md")
    fm = _frontmatter(p)
    assert fm["name"] == "coding:onboarding"
    assert fm["description"]
    assert len(p.read_text().splitlines()) < 500


def test_b2b_ops_onboarding_bundle_valid():
    p = Path("skills/b2b-ops:onboarding/SKILL.md")
    fm = _frontmatter(p)
    assert fm["name"] == "b2b-ops:onboarding"
    assert fm["description"]
    assert len(p.read_text().splitlines()) < 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/skills/test_icp_bundles.py -v`
Expected: FAIL (`FileNotFoundError` - bundles do not exist).

- [ ] **Step 3: Create the coding onboarding skill**

```markdown
# skills/coding:onboarding/SKILL.md
---
name: coding:onboarding
description: ICP onboarding for coding and dev agents. Use at session start to learn how to use Engrammic memory while writing, reviewing, and debugging code - what to remember, when to learn with evidence, and when to form beliefs.
---

# Engrammic onboarding: coding agents

You are using Engrammic, epistemic memory for AI agents. This guide tunes the
defaults for code work.

## What to put where

- `remember`: transient context you will want later this session - a failing
  command, a file path, a stack trace. No evidence needed.
- `learn`: a durable claim about the codebase with evidence (a file:line, a
  test result, a commit). Example: "Auth tokens expire after 15m" with the
  config line as evidence.
- `believe`: a synthesized engineering position drawn from several facts -
  "this module is the right integration point" - and cite the nodes it rests
  on.
- `recall`: before solving, query what is already known about the area.
- `trace`: when a belief drives a risky change, check its provenance first.

## Heuristics for code

- Prefer `learn` over `remember` for anything another engineer would need to
  trust - evidence is the difference between a note and a fact.
- After a debugging session, `reflect` when your understanding changed.
- Recall is tuned to return more candidates for this ICP; narrow with a
  specific query rather than broad terms.

## When not to store

Do not store generated code, secrets, or anything reconstructable from the
repo. Store the decision and its evidence, not the diff.
```

- [ ] **Step 4: Create the b2b-ops onboarding skill**

```markdown
# skills/b2b-ops:onboarding/SKILL.md
---
name: b2b-ops:onboarding
description: ICP onboarding for vertical B2B and operations assistants. Use at session start to learn how to use Engrammic memory for domain workflows - capturing customer and process facts, recalling prior context, and avoiding over-formal epistemics.
---

# Engrammic onboarding: B2B / ops agents

You are using Engrammic, epistemic memory for AI agents. This guide tunes the
defaults for vertical B2B and operations work.

## What to put where

- `remember`: the working details of a task - who asked, what the customer
  said, the current state of a process step.
- `learn`: a durable domain fact with a source - a policy, an SLA, a
  contractual term - cite where it came from.
- `believe`: a standing operational position synthesized from facts; use
  sparingly and cite the facts.
- `recall`: open every task by recalling prior context for this account or
  process before acting.

## Heuristics for ops

- Lean on `remember` and `recall`; reserve `learn`/`believe` for facts that
  must survive the session and influence later decisions.
- Recall is tuned to return a tighter set for this ICP - phrase queries around
  the account, process, or document you are working.
- When a process outcome contradicts a stored fact, `reflect` so the record
  self-corrects.

## When not to store

Do not store PII beyond what the task needs, or raw documents. Store the
operative fact and its source.
```

- [ ] **Step 5: Update the skills README install path**

In `skills/README.md`, find the line instructing users to copy skills to `~/.claude/skills/` and replace that guidance with the portable path. Add (or replace the existing copy instruction with):

```markdown
## Installing skills locally

Engrammic skills follow the SKILL.md open standard. Copy the base skill
directories into the portable agent-skills location so any compatible harness
(Claude Code, Codex, Cursor, Windsurf, Gemini CLI) can discover them:

    cp -r skills/engrammic:* ~/.agents/skills/

Claude Code also reads `~/.claude/skills/`; either location works for that
harness. ICP overlay skills (`coding:*`, `b2b-ops:*`) are delivered per
tenant through the `patterns` MCP tool and are not installed from the
filesystem.
```

If the README has no such section, append this section at the end.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/skills/test_icp_bundles.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add "skills/coding:onboarding/SKILL.md" "skills/b2b-ops:onboarding/SKILL.md" skills/README.md tests/skills/test_icp_bundles.py
git commit -m "feat(presets): ship coding and b2b-ops onboarding bundles"
```

---

### Task 11: Full check and integration sanity

**Files:** none (verification only)

- [ ] **Step 1: Run the full preset-related suite**

Run: `uv run pytest tests/ -k "preset or patterns or recall or skill or silo_config" -v`
Expected: all pass.

- [ ] **Step 2: Run lint and typecheck**

Run: `just check`
Expected: ruff clean, mypy strict clean. Fix any type errors (notably: the `Any` return on `get_preset_resolver`, and `top_k: int | None` propagation in recall).

- [ ] **Step 3: Run the full test suite**

Run: `just test`
Expected: no new failures versus the pre-existing baseline (per project test-debt notes some unrelated tests may already fail; only newly introduced failures block).

- [ ] **Step 4: Final commit if any fixes were applied**

```bash
git add -A
git commit -m "chore(presets): satisfy just check and full suite"
```

---

## Self-Review

**Spec coverage:**

- Definition (`mcp_presets.yaml` + registry): Task 1.
- Binding (Postgres `silo_config.preset` + migration): Task 3.
- Resolution (TTL-cached resolver, fallback precedence): Tasks 4-5.
- `patterns` namespace ranking + explicit-profile escape hatch + bare-name auto-qualification: Task 7.
- Onboarding pointer line, boot-global instructions: Task 8.
- One param wired end to end (`default_recall_top_k`): Task 9 (+ field in Task 2).
- Reserved `coding:`/`b2b-ops:` namespaces: Task 6.
- Two ICP SKILL.md bundles, README portable path: Task 10.
- Tool profile untouched: confirmed - no task modifies `mcp_tools.yaml` profiles or `registry.py` profile logic.
- Dual-channel delivery: Task 10 README captures filesystem base-tier vs `patterns` ICP delivery.
- Error handling (unknown preset -> default + `invalid_mcp_preset` log; malformed yaml -> fail fast): Tasks 1 and 4.

No spec requirement is left without a task.

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step contains full code. Two places intentionally instruct a grep-and-match against existing patterns (test Postgres-session fixture name in Task 5; settings accessor name in Task 5) because those identifiers are environment-specific - each gives the exact grep and the dominant-pattern rule, not a vague placeholder.

**Type consistency:** `Preset` (fields `name`, `namespace`, `onboarding_skill`, `param_overrides`) is defined in Task 1 and used unchanged in Tasks 4, 7, 9. `PresetResolver.resolve(silo_id) -> Preset` defined in Task 4, called identically in Tasks 7 and 9. `get_preset_resolver()` accessor defined in Task 5, imported in Tasks 7 and 9. `BindingSource.get_silo_preset_name` signature consistent between Task 4 protocol and Task 5 implementation. `top_k: int | None` introduced in Task 9 and applied to both `_recall_impl` and the tool wrapper in the same task.
