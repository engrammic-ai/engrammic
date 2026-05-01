# Plan: Dagger Test Pipeline

**Status:** Draft 2026-05-01
**Goal:** Portable CI pipeline via Dagger (runs locally + any CI provider).

## Scope

Test pipeline only: `lint -> typecheck -> test -> test-integration`

Build/deploy out of scope for now.

## Pipeline Stages

```
lint (ruff check)
    |
typecheck (mypy)
    |
test (pytest unit)
    |
test-integration (pytest -m integration, needs docker services)
```

First three stages run in parallel (no deps between them). Integration tests run after unit tests pass.

## Implementation

### Option A: Python SDK (recommended)

Single `dagger/pipeline.py`:

```python
import dagger
from dagger import dag, function, object_type

@object_type
class ContextService:
    @function
    async def lint(self, source: dagger.Directory) -> str:
        return await (
            dag.container()
            .from_("ghcr.io/astral-sh/uv:python3.12-alpine")
            .with_directory("/app", source)
            .with_workdir("/app")
            .with_exec(["uv", "sync", "--frozen"])
            .with_exec(["uv", "run", "ruff", "check", "src", "tests"])
            .stdout()
        )

    @function
    async def typecheck(self, source: dagger.Directory) -> str:
        # similar, with mypy

    @function
    async def test(self, source: dagger.Directory) -> str:
        # pytest without integration marker

    @function
    async def test_integration(
        self, 
        source: dagger.Directory,
        memgraph: dagger.Service,
        qdrant: dagger.Service,
        redis: dagger.Service,
    ) -> str:
        # pytest -m integration with service bindings

    @function
    async def all(self, source: dagger.Directory) -> str:
        # parallel lint + typecheck + test, then integration
```

### Option B: Daggerverse module

Publish as reusable module. Overkill for now.

## Services for Integration Tests

Dagger can spin up service containers:

```python
memgraph = dag.container().from_("memgraph/memgraph:2.14").as_service()
qdrant = dag.container().from_("qdrant/qdrant:v1.7.4").as_service()
redis = dag.container().from_("redis:7-alpine").as_service()
```

Bind to test container via `.with_service_binding()`.

## Local Usage

```bash
# Run full pipeline
dagger call all --source=.

# Run just lint
dagger call lint --source=.

# Run integration with services
dagger call test-integration --source=.
```

## CI Integration (future)

Any CI that runs containers:

```yaml
# GitLab example
test:
  image: ghcr.io/dagger/dagger:latest
  script:
    - dagger call all --source=.

# GHA example
- uses: dagger/dagger-for-github@v5
  with:
    verb: call
    args: all --source=.
```

## Files to Create

| File | Purpose |
|------|---------|
| `dagger/pipeline.py` | Pipeline definition |
| `dagger.json` | Module config |

## Tasks

1. [ ] Install dagger CLI locally
2. [ ] Init dagger module (`dagger init --sdk=python`)
3. [ ] Implement lint/typecheck/test functions
4. [ ] Add service containers for integration tests
5. [ ] Add `just dagger-*` recipes
6. [ ] Test locally
7. [ ] Document in README or devlog

## Done Criteria

- `dagger call all --source=.` runs full test suite
- Same pipeline works on any CI with no changes
- `just dagger-test` as shorthand
