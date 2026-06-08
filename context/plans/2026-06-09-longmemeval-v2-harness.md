# LongMemEval-V2 Official Harness Integration

> **For agentic workers:** Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan.

**Goal:** Run official LongMemEval-V2 benchmark with Engrammic as memory backend to get credible, independently verifiable accuracy numbers.

**Branch:** `feat/longmemeval-v2-harness`

**Why official harness:** Somnus benchmark adapters have known issues (unimplemented supersession seeding, chunking loses coherence, role confusion). Fixing them is days of work. The official harness is maintained, credible, and just needs a thin adapter. Results are directly comparable to published baselines.

**Location:** Standalone repo or `delta-prime/benchmarks/longmemeval-v2/` (not inside context-service)

---

## Background

### LongMemEval-V2 Architecture

The harness evaluates memory systems on web-agent trajectory recall. Key characteristics:
- **451 manually curated questions** across 5 memory abilities
- **Web agent trajectories** (not chat messages) with screenshots
- **Up to 500 trajectories per haystack**, up to 115M tokens
- **Two domains:** web and enterprise
- **Two tiers:** small and medium

The adapter interface (from `memory_modules/memory.py`):

```python
from typing import Literal, TypedDict
from memory_modules.memory import Memory, register_memory

class MemoryContextItem(TypedDict):
    type: Literal["text", "image"]
    value: str  # text content or path to image file

@register_memory
class EngrammicMemory(Memory):
    memory_type = "engrammic"

    def insert(self, trajectory: dict) -> None:
        """Index a trajectory into memory.
        
        trajectory contains web-agent data with fields like:
        - trajectory_id: unique identifier
        - start_url: domain URL
        - actions: list of agent actions
        - states: page states with screenshots
        """
        pass

    def query(
        self, 
        query: str, 
        query_image: str | None = None,
    ) -> list[MemoryContextItem]:
        """Retrieve relevant context for a question.
        
        Use self.get_query_context() to access:
        - question_id
        - question_type  
        - raw question item
        """
        return [{"type": "text", "value": "retrieved text"}]
```

**Flow:**
1. Harness loads trajectories (web agent histories, not chat)
2. Memory backend indexes via `insert()`
3. Harness calls `query()` with benchmark question
4. Memory returns MemoryContextItem list
5. Reader LLM answers using context
6. LLM judge scores answer

**Model configuration (our setup):**
- **Reader:** Gemini 2.0 Flash via Vertex AI (cost-efficient, fast)
- **Judge:** Gemini 2.0 Flash via Vertex AI (same reasoning, consistent)

### Interface Notes (verified from repo)

**CLI arguments** (via `evaluation/harness.py`):
- `--domain`: "web" or "enterprise" (required)
- `--questions-path`: path to questions JSON
- `--haystack-path`: question ID to trajectory list mapping
- `--trajectories-path`: trajectory data JSON
- `--memory-config-path`: JSON with memory_type and memory_params
- `--output-dir`: results directory
- `--model`: reader model (required unless --skip-evaluation)
- `--memory-context-max-tokens`: default 200,000

**Memory config format:**
```json
{
  "memory_type": "engrammic",
  "memory_params": {
    "endpoint": "http://localhost:8000",
    "silo_id": "lme-run-001"
  }
}
```

### Engrammic Integration Challenge

**Critical:** Engrammic exposes MCP tools (`remember`, `recall`, `learn`), not REST endpoints. The benchmark adapter needs HTTP access. Options:

1. **Add REST wrapper endpoints** (recommended) - Add `/api/v1/remember`, `/api/v1/recall` to context-service
2. **Use MCP over HTTP** - Use streamable-http MCP transport
3. **Direct store access** - Bypass MCP, call stores directly (breaks abstraction)

**Recommendation:** Option 1 (REST wrapper) is cleanest for benchmarking and future integrations.

### Key Slices (5 memory abilities)

- **Static state recall** - page layouts, module affordances
- **Dynamic state tracking** - state changes over time
- **Workflow knowledge** - recurring task steps
- **Environment gotchas** - local failure modes
- **Premise awareness** - invalid assumptions

---

## Tasks

### Phase 0: Verify REST API Surface (~1 hour)

Before building the adapter, we need REST endpoints for memory operations.

- [ ] **Task 0.1: Check if REST endpoints exist**
  
  Look for `/api/v1/remember` or similar in context-service routes.
  Currently confirmed: **no REST endpoints for memory ops** - only MCP tools.

- [ ] **Task 0.2: Add REST wrapper endpoints (if needed)**
  
  Create `src/context_service/api/routes/memory.py`:
  ```python
  """REST API wrapper for MCP memory operations."""
  from fastapi import APIRouter, Header
  from pydantic import BaseModel
  
  router = APIRouter(prefix="/api/v1", tags=["memory"])
  
  class RememberRequest(BaseModel):
      content: str
      tags: list[str] = []
  
  class RecallRequest(BaseModel):
      query: str
      top_k: int = 20
  
  @router.post("/remember")
  async def remember(
      req: RememberRequest,
      x_silo_id: str = Header(...),
      x_session_id: str = Header(...),
  ):
      # Call engine.remember() directly
      pass
  
  @router.post("/recall")
  async def recall(
      req: RecallRequest,
      x_silo_id: str = Header(...),
  ):
      # Call engine.recall() directly
      pass
  ```

- [ ] **Task 0.3: Register routes in app.py**

- [ ] **Task 0.4: Test endpoints locally**
  ```bash
  curl -X POST http://localhost:8000/api/v1/remember \
    -H "Content-Type: application/json" \
    -H "X-Silo-ID: test" \
    -H "X-Session-ID: test" \
    -d '{"content": "test memory"}'
  ```

### Phase 1: Setup (~30 min)

- [ ] **Task 1.1: Clone LongMemEval-V2**
  
  On devbox:
  ```bash
  cd ~/benchmarks
  git clone https://github.com/xiaowu0162/LongMemEval-V2.git
  cd LongMemEval-V2
  PYTHONNOUSERSITE=1 conda env create -f environment.yml
  conda activate lme-v2-release
  pip install -e .
  ```

- [ ] **Task 1.2: Download data**
  ```bash
  python data/download_data.py --data-root data/longmemeval-v2
  export DATA_ROOT="$(pwd)/data/longmemeval-v2"
  python data/prepare_data.py --data-root "$DATA_ROOT" --mode symlink
  python data/validate_data.py --data-root "$DATA_ROOT" --tier small
  ```

- [ ] **Task 1.3: Configure Vertex AI models**
  
  Set up Gemini Flash via Vertex AI:
  ```bash
  # Vertex AI configuration
  export GOOGLE_CLOUD_PROJECT=engrammic-prod
  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
  
  # Reader and judge model (Gemini 2.0 Flash)
  export READER_BASE_URL=https://us-central1-aiplatform.googleapis.com/v1
  export READER_MODEL=gemini-2.0-flash-001
  export JUDGE_MODEL=gemini-2.0-flash-001
  ```

- [ ] **Task 1.4: Verify harness runs with baseline**
  ```bash
  # Run no_retrieval baseline to verify setup
  evaluation/scripts/run_no_retrieval.sh
  ```

- [ ] **Task 1.5: Review existing adapter implementations**
  
  Read these files to understand patterns:
  - `memory_modules/memory.py` - base class, MemoryContextItem TypedDict
  - `memory_modules/no_retrieval.py` - minimal implementation
  - `memory_modules/rag.py` - indexed retrieval example

### Phase 2: Engrammic Adapter (~2 hours)

- [ ] **Task 2.1: Create adapter file**
  
  Create `memory_modules/engrammic.py`:
  
  ```python
  """Engrammic memory backend for LongMemEval-V2."""
  
  from __future__ import annotations
  
  import time
  from typing import Any
  
  import httpx
  from tenacity import retry, stop_after_attempt, wait_exponential
  
  from memory_modules.memory import Memory, MemoryContextItem, register_memory
  
  
  @register_memory
  class EngrammicMemory(Memory):
      """Engrammic MCP-based memory backend."""
      
      memory_type = "engrammic"
      
      def __init__(self, memory_params: dict[str, Any]) -> None:
          super().__init__(memory_params)
          self.endpoint = memory_params.get("endpoint", "http://localhost:8000")
          self.silo_id = memory_params.get("silo_id", "longmemeval-bench")
          self.session_id = memory_params.get("session_id", "eval-session")
          self.timeout = memory_params.get("timeout", 30.0)
          self.client = httpx.Client(timeout=self.timeout)
      
      def _headers(self) -> dict[str, str]:
          return {
              "X-Silo-ID": self.silo_id,
              "X-Session-ID": self.session_id,
              "Content-Type": "application/json",
          }
      
      @retry(
          stop=stop_after_attempt(3),
          wait=wait_exponential(multiplier=1, min=1, max=10),
      )
      def _post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
          """HTTP POST with retry logic."""
          response = self.client.post(
              f"{self.endpoint}{path}",
              headers=self._headers(),
              json=json,
          )
          response.raise_for_status()
          return response.json()
      
      def insert(self, trajectory: dict[str, Any]) -> None:
          """Index a trajectory into Engrammic.
          
          Trajectories are web-agent recordings with:
          - trajectory_id: unique identifier
          - actions: agent actions taken
          - states: page states (may include screenshots)
          - start_url: domain context
          """
          trajectory_id = trajectory.get("trajectory_id", "unknown")
          
          # Extract meaningful content from trajectory
          # TODO: Refine based on actual trajectory schema inspection
          content_parts = []
          
          # Add domain context
          if start_url := trajectory.get("start_url"):
              content_parts.append(f"Domain: {start_url}")
          
          # Add actions as a workflow summary
          actions = trajectory.get("actions", [])
          if actions:
              action_summary = self._summarize_actions(actions)
              content_parts.append(f"Actions: {action_summary}")
          
          # Add any notes/annotations
          if notes := trajectory.get("notes"):
              content_parts.append(f"Notes: {notes}")
          
          content = "\n".join(content_parts)
          if not content.strip():
              return  # Skip empty trajectories
          
          self._post("/api/v1/remember", {
              "content": content,
              "tags": [f"trajectory:{trajectory_id}"],
          })
      
      def query(
          self, 
          query: str, 
          query_image: str | None = None,
      ) -> list[MemoryContextItem]:
          """Retrieve relevant context from Engrammic."""
          # Access question metadata if needed
          ctx = self.get_query_context()
          question_type = ctx.get("question_type", "unknown")
          
          response = self._post("/api/v1/recall", {
              "query": query,
              "top_k": 20,
          })
          
          results: list[MemoryContextItem] = []
          for node in response.get("results", []):
              content = node.get("content", "")
              if content:  # Text values must be non-empty
                  results.append({
                      "type": "text",
                      "value": content,
                  })
          return results
      
      def _summarize_actions(self, actions: list[dict[str, Any]]) -> str:
          """Summarize agent actions into readable text."""
          parts = []
          for action in actions[:20]:  # Limit to avoid huge content
              action_type = action.get("type", "unknown")
              target = action.get("target", "")
              parts.append(f"{action_type}: {target}")
          return "; ".join(parts)
  ```

- [ ] **Task 2.2: Register adapter**
  
  Add import to `memory_modules/__init__.py` or `memory_modules/memory.py`:
  ```python
  from memory_modules import engrammic  # noqa: F401
  ```

- [ ] **Task 2.3: Create config file**
  
  Create `evaluation/memory_configs/engrammic.json`:
  ```json
  {
    "memory_type": "engrammic",
    "memory_params": {
      "endpoint": "http://engrammic-dev-box:8000",
      "silo_id": "lme-v2-run-001",
      "session_id": "eval-001",
      "timeout": 30.0
    }
  }
  ```

- [ ] **Task 2.4: Add cleanup between runs**
  
  Add method to adapter or create cleanup script:
  ```python
  def reset_silo(self) -> None:
      """Clear all data in the silo before a new run."""
      # Call GDPR erasure endpoint or admin clear
      self._post("/gdpr/erasure", {"silo_id": self.silo_id})
  ```

### Phase 3: Silo Isolation Strategy

**Problem:** Single silo causes cross-contamination between trajectories/runs.

- [ ] **Task 3.1: Choose isolation strategy**
  
  Options:
  1. **Per-run silo** - Create unique silo_id per benchmark run (e.g., `lme-run-{timestamp}`)
  2. **Per-haystack silo** - New silo per haystack (question group)
  3. **Cleanup between runs** - Clear silo before each run
  
  **Recommendation:** Per-run silo is cleanest and allows parallel runs.

- [ ] **Task 3.2: Implement dynamic silo creation**
  
  Update adapter to generate unique silo_id:
  ```python
  def __init__(self, memory_params: dict) -> None:
      super().__init__(memory_params)
      base_silo = memory_params.get("silo_id", "lme-bench")
      run_id = memory_params.get("run_id") or f"{int(time.time())}"
      self.silo_id = f"{base_silo}-{run_id}"
  ```

- [ ] **Task 3.3: Add silo cleanup hook**
  
  Implement `_save_backend` or separate cleanup to remove silo data after run.

### Phase 4: Dry Run (~30 min)

- [ ] **Task 4.1: Ensure Engrammic stack is running**
  
  On devbox:
  ```bash
  cd ~/context-service
  just up
  # Verify: curl http://localhost:8000/health
  ```

- [ ] **Task 4.2: Test adapter with small tier, limited questions**
  
  ```bash
  cd ~/benchmarks/LongMemEval-V2
  export DATA_ROOT="$(pwd)/data/longmemeval-v2"
  export OUTPUT_ROOT=runs
  export TIER=small
  
  # Run with just web domain first
  python evaluation/harness.py \
    --domain web \
    --questions-path "$DATA_ROOT/questions.json" \
    --haystack-path "$DATA_ROOT/haystacks_${TIER}.json" \
    --trajectories-path "$DATA_ROOT/trajectories.json" \
    --memory-config-path evaluation/memory_configs/engrammic.json \
    --output-dir runs/engrammic-dry-run \
    --model "$READER_MODEL" \
    --base-url "$READER_BASE_URL"
  ```

- [ ] **Task 4.3: Verify results format**
  
  Check `runs/engrammic-dry-run/` contains:
  - `per_question.jsonl`
  - `aggregated_metrics.json`
  - `prompt_rows.jsonl`

### Phase 5: Full Benchmark Run (~2-4 hours runtime)

**Threshold for proceeding:** Dry run succeeds with valid output format and non-zero retrieval.

- [ ] **Task 5.1: Run small tier - web domain**
  
  ```bash
  python evaluation/harness.py \
    --domain web \
    --questions-path "$DATA_ROOT/questions.json" \
    --haystack-path "$DATA_ROOT/haystacks_small.json" \
    --trajectories-path "$DATA_ROOT/trajectories.json" \
    --memory-config-path evaluation/memory_configs/engrammic.json \
    --output-dir runs/engrammic_web_small \
    --model "$READER_MODEL" \
    --base-url "$READER_BASE_URL"
  ```

- [ ] **Task 5.2: Run small tier - enterprise domain**
  
  Same command with `--domain enterprise` and unique silo.

- [ ] **Task 5.3: Combine results**
  
  ```bash
  python leaderboard/combine_aggregated_metrics.py \
    runs/engrammic_enterprise_small/aggregated_metrics.json \
    runs/engrammic_web_small/aggregated_metrics.json \
    -o runs/engrammic_small_combined_metrics.json
  ```

- [ ] **Task 5.4: Compare to published baselines**
  
  LongMemEval-V2 publishes baseline numbers. Compare:
  - Engrammic vs no_retrieval
  - Engrammic vs rag_query_to_slice
  - Engrammic vs AgentRunbook-R

- [ ] **Task 5.5: Document results**
  
  Write up in `context/notes/2026-06-XX-longmemeval-v2-results.md`:
  - Methodology (official harness, config used)
  - Results table by domain and memory ability
  - Comparison to baselines
  - Analysis of wins/losses per ability type

### Phase 6: Improvements (if needed)

Trigger: Phase 5 accuracy is below `rag_query_to_slice` baseline on 2+ abilities.

- [ ] **Task 6.1: Fact extraction during insert**
  
  Use LLM to extract structured facts from trajectories before storing.

- [ ] **Task 6.2: Query expansion during recall**
  
  Expand query with question_type-specific terms.

- [ ] **Task 6.3: Supersession-aware indexing**
  
  For dynamic_state_tracking, detect state updates and use supersession.

---

## Out of Scope

- Fixing Somnus benchmark adapters (keep as-is for internal iteration)
- BEAM benchmark via official harness (different repo, defer)
- LoCoMo via official harness (defer)
- Medium tier runs (until small tier shows promise)

---

## Done Criteria

1. REST wrapper endpoints added to context-service (Phase 0)
2. Engrammic adapter merged into local LongMemEval-V2 fork
3. Small tier benchmark run completed for both domains
4. Results documented with comparison to published baselines
5. Numbers are credible for external communication (if positive)

---

## Estimates

| Phase | Time | Cost (API) |
|-------|------|------------|
| REST endpoints | 1 hour | $0 |
| Setup | 30 min | $0 |
| Adapter | 2 hours | $0 |
| Silo isolation | 30 min | $0 |
| Dry run | 30 min | ~$0.50 |
| Full run (small) | 2-4 hours | ~$5-10 (see breakdown) |
| **Total** | **5-8 hours** | **~$5-15** |

### Cost Breakdown

**Our setup uses Gemini Flash via Vertex AI:**
- **Reader model:** Gemini 2.0 Flash (~$0.075/1M input, ~$0.30/1M output)
- **LLM judge:** Gemini 2.0 Flash (same pricing)
- **Embeddings:** Engrammic stack (already running)

**Estimated costs:**
- 451 questions x 2 domains = 902 evaluations
- ~50K tokens input + ~500 tokens output per evaluation
- Reader: 902 x (50K x $0.075/1M + 500 x $0.30/1M) = ~$3.50 + $0.14 = ~$4
- Judge: 902 x (2K x $0.075/1M + 100 x $0.30/1M) = ~$0.14 + $0.03 = ~$0.17
- **Total: ~$5-10** (conservative with retries and larger contexts)

---

## References

- [LongMemEval-V2 repo](https://github.com/xiaowu0162/LongMemEval-V2)
- [LongMemEval-V2 paper](https://arxiv.org/abs/2605.12493) (ICLR 2025)
- [Somnus recall investigation](../somnus/context/notes/2026-06-07-recall-accuracy-investigation.md)
- [Memory benchmark strategy](context_store recall "benchmark strategy")
