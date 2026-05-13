# Somnus Days 3-4 Risk Analysis: Evaluators, Runner, Report, CLI

**Date**: 2026-05-13  
**Scope**: Implementation of evaluation pipeline, test orchestration, result aggregation, and user-facing CLI  
**Status**: Pre-implementation risk identification

---

## Executive Summary

Days 3-4 implement the **execution and evaluation pipeline** - the core loop that runs agents, judges their outputs, and reports findings. This phase carries **8 high-risk items** across cost, technical complexity, and operational fragility:

1. **LLM-as-judge consistency** (HIGH severity, medium likelihood)
2. **Async runner complexity under contention** (HIGH severity, high likelihood)
3. **Cost explosion from repeated judgments** (HIGH severity, high likelihood)
4. **MCP connection failures during multi-scenario runs** (MEDIUM severity, medium likelihood)
5. **Flaky evaluation from LLM non-determinism** (MEDIUM severity, high likelihood)
6. **Evaluator composability brittleness** (MEDIUM severity, medium likelihood)
7. **CLI UX degradation under complexity** (LOW severity, high likelihood)
8. **CI integration + secret management** (MEDIUM severity, low likelihood)

---

## Risk Matrix (Severity x Likelihood)

```
                HIGH LIKELIHOOD
HIGH SEVERITY   - Async runner contention (3)
                - Cost explosion (2)
                - LLM non-determinism (5)

MEDIUM          - MCP connection failures (4)
SEVERITY        - Evaluator brittleness (6)
                - CI secrets/timeouts (8)

LOW SEVERITY    - CLI UX decay (7)
                - LLM judge consistency (1)
```

**Recommended Focus Order**: Address 2, 3 early (gates all subsequent work). Then 4, 6 (architectural).

---

## Risk 1: LLM-as-Judge Consistency / Reliability

**Severity**: HIGH (gates release decision on Engrammic's effectiveness)  
**Likelihood**: MEDIUM (depends on rubric quality + model temperature)  
**Impact**: False negatives (Engrammic helped, judge didn't detect). False positives (noise scored as signal).

**Constraints**:
- Judge must score 16+ dimensions across 5 task categories
- Same oracle facts → judge should assign consistent scores
- Temperature low (0.1-0.3) necessary for consistency, but may reduce nuance
- Three-model separation means judge model may not understand agent's reasoning context

**Root Causes**:
1. Judge LLM sees only agent output + oracle; doesn't see agent's internal traces (MCP calls, reasoning steps)
2. Multi-dimensional rubric (task_completion, accuracy, recall, reasoning) has unclear boundaries
   - Example: when is recall_completeness 0.7 vs 0.8? No hard criteria
3. Oracle answers sometimes under-specify (e.g., "must_recall=['FastAPI']" but agent says "async Python framework")
4. Judge may confuse agent's reasoning quality with output quality

**Mitigations** (Priority order):

1. **Build rubric with concrete anchors** (CRITICAL, do before Day 4 evaluator coding)
   - For each dimension, define: score=0 (fails), 0.5 (partial), 1.0 (passes)
   - Example:
     ```
     task_completion:
       0.0: Agent didn't attempt or output is incoherent
       0.5: Incomplete attempt; missing key aspects
       1.0: Covers all oracle requirements
     
     recall_completeness:
       0.0: Missed >50% of oracle facts
       0.5: Recalled 50-80% of facts
       1.0: Recalled ≥80% (or all that apply)
     ```
   - Embed rubric directly in judge prompt

2. **Use few-shot examples in judge prompt** 
   - Provide 2-3 examples of agent outputs with correct scores
   - Show boundary cases (e.g., partial recall = 0.5 vs full = 1.0)
   - Reduces judge variance significantly

3. **Implement judge score validation** 
   - Consistency check: judge same output twice, ensure |score_A - score_B| < 0.1
   - Catch: silently inconsistent judges before they pollute results
   - Action: if inconsistent, flag trial for manual review

4. **Add "confidence" dimension to judge output**
   ```json
   {
     "task_completion": 0.8,
     "task_completion_confidence": 0.9,
     "recall_completeness": 0.7,
     "recall_completeness_confidence": 0.7
   }
   ```
   - Filter trials where avg_confidence < 0.6 at report time
   - Reduces false signal from low-confidence judgments

5. **Implement semantic matching for oracle facts**
   - Don't require exact substring match ("FastAPI" vs "async Python framework")
   - Use embedding similarity: `embed(agent_mention) ~ embed(oracle_fact)` → similarity > 0.85 = match
   - Prevents judge from scoring 0.0 on recall for minor word choice differences

6. **Start with keyword evaluator only** (for Days 3-4)
   - Keyword eval (exact substring match) is deterministic, zero LLM cost
   - Proves pipeline works end-to-end
   - Deploy LLM judge in Phase 2 with anchored rubric

---

## Risk 2: Cost Explosion from Repeated LLM Judgments

**Severity**: HIGH (budget risk, can overflow without caps)  
**Likelihood**: HIGH (easy to trigger accidentally)  
**Impact**: $500-$2000+ spend in single unmonitored test run

**Constraints**:
- Each trial produces AgentTrace with LLM output (1000-5000 tokens)
- Judge must score with fresh LLM call (GPT-4o ~$0.03/1K input, $0.06/1K output)
- Scenario count: 5 categories × N scenarios each = 15+ scenarios
- Ablation requires 2 modes (with/without) = 30+ judgments minimum
- No built-in cost tracking or gating

**Cost Example**:
```
15 scenarios × 2 modes × 2 trials (retries) × 3K tokens × $0.03/1K = $2.70 per scenario
15 scenarios × $2.70 = $40.50 per full run

But: add debugging iteration:
- Run 1: $40, identify bug
- Run 2: $40, fix
- Run 3: $40, validation
= $120 + failures/reruns easily hits $200-300

Uncontrolled: 10 iteration cycles = $500+
```

**Root Causes**:
1. No cost tracking, budget threshold, or warning system
2. No way to disable LLM judge (all-or-nothing evaluation)
3. Agent LLM calls also add cost (3K tokens × 2 modes × 15 scenarios × $0.03 = ~$2.70)
4. Easy to accidentally re-run same trial without dedup

**Mitigations**:

1. **Implement cost gate (CRITICAL, enforce Day 3)**
   ```python
   class SomnusRunner:
       def __init__(self, max_cost: float = 10.0):  # $10 default
           self.max_cost = max_cost
           self.current_cost = 0.0
           
       async def run_trial(self, scenario: Scenario) -> TrialResult:
           est_cost = self._estimate_trial_cost(scenario)
           if self.current_cost + est_cost > self.max_cost:
               raise BudgetExceeded(
                   f"Would exceed budget. Current: ${self.current_cost:.2f}, "
                   f"trial est: ${est_cost:.2f}"
               )
           # ... run trial ...
           self.current_cost += actual_cost
   ```
   - Default: $10 per run (covers ~2-3 full scenario sets)
   - User can raise via CLI: `somnus run --max-cost 50`
   - No judgment calls once threshold hit

2. **Provide deterministic (non-LLM) evaluation path**
   ```python
   # Keyword evaluator: zero cost, deterministic
   evaluator = KeywordEvaluator(oracle)
   score = evaluator.score(agent_output)
   
   # LLM judge: high cost, enable only on demand
   if config.use_llm_judge:
       judge = LLMJudge(model="gpt-4o")
       score = judge.score(agent_output, oracle)
   ```
   - Default: keyword evaluator only (CI-safe, repeatable)
   - LLM judge opt-in: `somnus run --use-llm-judge --max-cost 100`

3. **Implement trial caching**
   ```python
   class TrialCache:
       def key(self, scenario_id: str, agent_output: str) -> str:
           return hashlib.sha256(
               f"{scenario_id}:{agent_output}".encode()
           ).hexdigest()
       
       def get_score(self, cache_key: str) -> TrialResult | None:
           # Check SQLite: `cache(key, score)`
           ...
   ```
   - First run: $X cost
   - Re-run same scenario/output: $0 (cached)

4. **Add cost visibility to CLI output**
   ```
   $ somnus run --max-cost 50
   
   Running scenarios...
   ✓ fact-001 [with] (cost: $0.12, total: $0.12)
   ✓ fact-001 [without] (cost: $0.10, total: $0.22)
   ✓ pref-001 [with] (cost: $0.09, total: $0.31)
   ...
   
   Total: 8 trials, $4.32 / $50.00 budget (8.6% used)
   ```

5. **Implement token tracking for each LLM call**
   ```python
   @dataclass
   class TrialResult:
       agent_tokens_in: int
       agent_tokens_out: int
       judge_tokens_in: int
       judge_tokens_out: int
       
       @property
       def total_cost(self) -> float:
           return (
               (self.agent_tokens_in + self.agent_tokens_out) * ANTHROPIC_COST_PER_K +
               (self.judge_tokens_in + self.judge_tokens_out) * OPENAI_COST_PER_K
           )
   ```

6. **Require explicit `--enable-cost-intensive` for LLM judge**
   - Prevents accidental spend
   - CLI enforces: `--use-llm-judge` requires `--enable-cost-intensive` flag

---

## Risk 3: Async Runner Contention / Concurrency Bugs

**Severity**: HIGH (can deadlock or corrupt state silently)  
**Likelihood**: HIGH (easy to introduce, hard to test)  
**Impact**: Intermittent test failures, race conditions, silent state corruption

**Constraints**:
- Runner needs to parallelize trials for speed (10 scenarios × 2 modes = 20 trials ideally ~10-20s total)
- Each trial owns a silo_id, so isolation is safe, but...
- Shared resources: config, log files, SQLite result DB, HTTP client pool
- No async coordinator yet; easy to write unsafe concurrent code

**Root Causes**:
1. Multiple trials writing to same SQLite DB without locking
2. HTTP client pool exhaustion (only N concurrent connections)
3. Agent message history not isolated between concurrent trial executions
4. LLM API rate limits (Anthropic allows ~100K tokens/min shared across runs)

**Concurrent Execution Example (Dangerous)**:
```python
async def run_all_scenarios(scenarios):
    tasks = [run_scenario(s) for s in scenarios]
    results = await asyncio.gather(*tasks)  # No semaphore
    # What if 10 scenarios write results simultaneously?
    # SQLite can deadlock or lose writes
```

**Mitigations**:

1. **Enforce sequential trial execution (safe v1)** (Day 3, recommended)
   ```python
   class SomnusRunner:
       async def run_all(self, scenarios: list[Scenario]) -> list[TrialResult]:
           results = []
           for scenario in scenarios:
               with_result = await self.run_trial(scenario, mode="with_engrammic")
               without_result = await self.run_trial(scenario, mode="without_engrammic")
               results.extend([with_result, without_result])
           return results
   ```
   - **Pro**: Zero concurrency bugs, predictable
   - **Con**: Slower (10-20 scenarios × 10s each = 100-200s total)
   - **Timeline acceptable**: First full run should take < 5min

2. **Add asyncio.Semaphore for controlled parallelism (v1.1)** (after sequential works)
   ```python
   class SomnusRunner:
       def __init__(self, max_concurrent: int = 2):
           self.semaphore = asyncio.Semaphore(max_concurrent)
       
       async def run_scenario_limited(self, scenario: Scenario) -> TrialResult:
           async with self.semaphore:
               return await self._run_scenario_impl(scenario)
       
       async def run_all(self, scenarios):
           tasks = [
               self.run_scenario_limited(s, mode)
               for s in scenarios
               for mode in ["with_engrammic", "without_engrammic"]
           ]
           return await asyncio.gather(*tasks)
   ```
   - **Pro**: Speeds up to 2-3x while staying safe
   - **Con**: More complex, requires careful testing

3. **Serialize DB writes with a lock** (mandatory if parallelizing)
   ```python
   class TrialDB:
       def __init__(self, db_path: Path):
           self.db_path = db_path
           self.lock = asyncio.Lock()
       
       async def save_result(self, result: TrialResult) -> None:
           async with self.lock:
               conn = sqlite3.connect(self.db_path)
               conn.execute("INSERT INTO trials ...")
               conn.commit()
               conn.close()
   ```

4. **Use HTTP connection pool with explicit limits**
   ```python
   client = httpx.AsyncClient(
       limits=httpx.Limits(
           max_connections=5,
           max_keepalive_connections=2,
           keepalive_expiry=5.0
       ),
       timeout=30.0
   )
   ```

5. **Add test for concurrent scenario execution**
   ```python
   async def test_concurrent_scenarios_isolate_state():
       scenarios = [scenario1, scenario2]
       results = await asyncio.gather(
           runner.run_trial(scenario1, mode="with"),
           runner.run_trial(scenario2, mode="with")
       )
       assert results[0].scenario_id == "scenario1"
       assert results[1].scenario_id == "scenario2"
   ```

6. **Implement run-level locking for SQLite**
   ```python
   conn = sqlite3.connect(db_path)
   conn.execute("PRAGMA journal_mode=WAL")
   conn.close()
   ```
   - Enables safe concurrent reads + single writer atomicity

---

## Risk 4: MCP Connection Failures During Multi-Scenario Runs

**Severity**: MEDIUM (fails just one scenario, not entire run)  
**Likelihood**: MEDIUM (Engrammic may be flaky under load)  
**Impact**: Lost trial data, incomplete ablations

**Constraints**:
- LiveContextClient makes HTTP calls to Engrammic
- Engrammic may be down, slow, or rate-limiting
- No retry logic yet
- No circuit breaker

**Failure Modes**:
1. Engrammic service down (timeout after 30s)
2. Rate limit hit (429 Too Many Requests)
3. Network packet loss (partial request)
4. MCP tool crash (500 from context-service)

**Impact on Run**:
```
Scenarios: fact, pref, contra, temporal, session
Running: fact [with] - OK
Running: pref [with] - TIMEOUT (Engrammic slow)
    -> Trial lost, no result stored
Running: pref [without] - OK
Running: contra [with] - OK
Result: cannot compare pref (only without), ablation invalid
```

**Mitigations**:

1. **Add exponential backoff retry for transient failures** (Day 3, before CI)
   ```python
   async def store_with_retry(
       self,
       layer: str,
       content: str,
       max_retries: int = 3
   ) -> dict[str, Any] | None:
       for attempt in range(max_retries):
           try:
               return await self.store(layer, content)
           except httpx.TimeoutException:
               wait_time = 2 ** attempt
               if attempt < max_retries - 1:
                   await asyncio.sleep(wait_time)
               else:
                   raise
   ```

2. **Expose retry policy to SomnusRunner**
   ```python
   runner = SomnusRunner(
       context_client=client,
       retry_policy=RetryPolicy(max_retries=3, backoff_factor=2)
   )
   ```

3. **Log each MCP call with result** (enable post-hoc debugging)
   ```python
   @dataclass
   class MCPCall:
       tool: str
       args: dict[str, Any]
       result: dict[str, Any] | None
       status: str  # "ok", "timeout", "error", "rate_limited"
       duration_ms: int
       attempt: int
   
   @dataclass
   class AgentTrace:
       mcp_calls: list[MCPCall]
   ```

4. **Fail-fast on Engrammic down**
   - On first connection failure, try once more
   - If second attempt fails, stop runner and report
   - Don't waste 10 scenarios' time if service is down
   ```python
   async def healthcheck(self) -> bool:
       try:
           result = await self.admin(action="status")
           return result.get("status") == "ok"
       except Exception:
           return False
   
   async def run_all(self, scenarios):
       if not await self.healthcheck():
           raise InfrastructureError("Engrammic service unavailable")
       # ... proceed ...
   ```

5. **Mark trials as skipped on infrastructure errors**
   ```python
   @dataclass
   class TrialResult:
       status: str  # "ok", "skipped", "failed"
       skip_reason: str | None  # "rate_limited", "engrammic_down"
   ```
   - Report acknowledges skipped trials
   - Ablation comparison skips both with/without for that scenario

6. **Implement circuit breaker to fail fast** (v1.1)
   ```python
   class CircuitBreaker:
       def __init__(self, failure_threshold: int = 3):
           self.failures = 0
           self.failure_threshold = failure_threshold
           self.open = False
       
       async def call(self, coro):
           if self.open:
               raise CircuitBreakerOpen()
           try:
               return await coro
           except Exception as e:
               self.failures += 1
               if self.failures >= self.failure_threshold:
                   self.open = True
               raise
   ```

---

## Risk 5: Flaky Evaluation from LLM Non-Determinism

**Severity**: MEDIUM (makes CI unreliable)  
**Likelihood**: HIGH (even at low temperature, LLMs are non-deterministic)  
**Impact**: Same scenario produces different scores on re-run, false regressions

**Example**:
```
Run 1: fact-001 [with] -> judge scores recall=0.9
Run 2: fact-001 [with] -> judge scores recall=0.7 (same output!)
Regression detected? No - just LLM variance
```

**Constraints**:
- LLM judge at temp=0.1 still has ~5-10% variance
- No fingerprinting to detect "same output scored differently"

**Mitigations**:

1. **Use keyword evaluator for determinism (recommended v1)** (Day 3)
   - Substring matching: 100% deterministic
   - Zero variance across runs
   - Easy to validate in CI
   - Can add LLM judge in Phase 2

2. **Implement output fingerprinting** (if using LLM judge)
   ```python
   def fingerprint(agent_output: str) -> str:
       return hashlib.sha256(agent_output.encode()).hexdigest()
   
   @dataclass
   class TrialResult:
       agent_output_fingerprint: str
       judge_scores: dict  # Only changes if fingerprint changes
   ```
   - Alert if same fingerprint gets different scores

3. **Add multi-judge consensus** (expensive, phase 2)
   ```python
   scores = [
       await judge_a.score(output, oracle),
       await judge_b.score(output, oracle),
       await judge_c.score(output, oracle)
   ]
   result.judge_score = np.median(scores)
   result.judge_confidence = np.std(scores)
   ```
   - If std > 0.2, low confidence

4. **Implement confidence threshold for signal detection**
   ```python
   lift = score_with - score_without
   confidence = min(judge_confidence_with, judge_confidence_without)
   
   if confidence < 0.6:
       result.signal = "UNCERTAIN"
   elif lift > 0.1:
       result.signal = "POSITIVE"
   elif lift < -0.1:
       result.signal = "NEGATIVE"
   else:
       result.signal = "NO_CHANGE"
   ```

---

## Risk 6: Evaluator Composability and Brittleness

**Severity**: MEDIUM (makes adding new evaluators hard)  
**Likelihood**: MEDIUM (easy to design, easy to break)  
**Impact**: Hard to add cognitive quality metrics later

**Current Design Issues**:
- How do evaluators compose? (multiple evaluators per scenario?)
- What's the interface? (score 0-1 only? multi-dimensional?)
- How do you weight/combine evaluator outputs?
- How do you handle evaluators that conflict?

**Example Conflict**:
```
KeywordEvaluator: oracle has ["FastAPI"]
  agent_output: "async Python framework"
  score: 0.0

SemanticEvaluator: oracle has ["FastAPI"]
  agent_output: "async Python framework"
  score: 1.0 (embedding similarity 0.92)

Which wins? How do you choose?
```

**Mitigations**:

1. **Define clear Evaluator protocol** (Day 3, before coding)
   ```python
   @dataclass
   class EvaluationScore:
       dimension: str
       score: float    # 0.0 - 1.0
       evidence: str
       evaluator: str  # "KeywordEvaluator", "LLMJudge"
   
   class Evaluator(ABC):
       @abstractmethod
       async def evaluate(
           self,
           scenario: Scenario,
           agent_trace: AgentTrace
       ) -> list[EvaluationScore]:
           pass
   ```

2. **Use composition pattern (not inheritance)**
   ```python
   class CompositeEvaluator:
       def __init__(self, evaluators: list[Evaluator]):
           self.evaluators = evaluators
       
       async def evaluate(self, scenario, trace):
           all_scores = []
           for evaluator in self.evaluators:
               scores = await evaluator.evaluate(scenario, trace)
               all_scores.extend(scores)
           return all_scores
   ```

3. **Define conflict resolution upfront**
   ```python
   def aggregate_scores(
       scores: list[EvaluationScore],
       weights: dict[str, float] | None = None
   ) -> float:
       """
       weights example:
       {
           "KeywordEvaluator": 0.3,
           "LLMJudge": 0.7
       }
       """
       if not weights:
           weights = {s.evaluator: 1.0 for s in scores}
       
       total = 0
       for score in scores:
           weight = weights.get(score.evaluator, 0)
           total += score.score * weight
       return total / sum(weights.values())
   ```

4. **Implement evaluator testing harness** (Day 3)
   ```python
   def test_evaluator_consistency():
       evaluator = KeywordEvaluator(oracle)
       
       result1 = await evaluator.evaluate(scenario, trace)
       result2 = await evaluator.evaluate(scenario, trace)
       
       assert result1 == result2, "Evaluator not deterministic"
   ```

5. **Make evaluators pluggable via config**
   ```yaml
   # somnus.config.yaml
   evaluators:
     - name: keyword
       enabled: true
       weight: 0.5
     - name: llm_judge
       enabled: false
       weight: 0.5
   ```

---

## Risk 7: CLI UX Decay Under Complexity

**Severity**: LOW (doesn't gate functionality)  
**Likelihood**: HIGH (easy to add flags, hard to keep simple)  
**Impact**: Confusing user experience, wrong flags used

**Risk**: By Day 4, you might have:
```bash
somnus run --scenario fact_accumulation --use-llm-judge --max-cost 50 \
  --enable-cost-intensive --retry-policy exponential --max-concurrent 2 \
  --judge-model gpt-4o --agent-model claude-sonnet --tags retrieval \
  --output-format json --output-path /tmp/results.json --parallel \
  --db-path somnus.db --silo-prefix somnus --include-meta-cognition
```

**Mitigations**:

1. **Build minimal CLI first, add flags incrementally** (Day 4)
   ```bash
   somnus run  # Just this, all defaults
   ```

2. **Use sensible defaults** (no flags needed for 80% use cases)
   ```python
   @click.command()
   @click.option("--scenario", default=None, help="Run single scenario")
   @click.option("--tags", default=None, help="Filter by tags")
   @click.option("--output", type=click.Path(), default="somnus-output")
   def run(scenario, tags, output):
       pass
   ```

3. **Implement subcommands for distinct workflows**
   ```bash
   somnus run          # Run scenarios
   somnus report       # View results
   somnus ablation     # Compare with/without
   somnus compare      # Compare two runs
   ```

4. **Add `--help` at every level**
   ```bash
   somnus --help
   somnus run --help
   somnus run --tags --help
   ```

5. **Provide example commands in help text**
   ```bash
   $ somnus run --help
   
   Usage: somnus run [OPTIONS]
   
   Examples:
       somnus run                     # Run all scenarios
       somnus run --tags retrieval    # Run retrieval scenarios
       somnus run --scenario fact-001 # Run one scenario
   ```

---

## Risk 8: CI Integration (Secrets, Timeouts, Flakiness)

**Severity**: MEDIUM (blocks CI adoption)  
**Likelihood**: LOW (detected early, fixable)  
**Impact**: Can't run tests in GitHub Actions / GitLab CI

**Constraints**:
- Engrammic needs secrets: OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY
- Agent LLM calls may timeout in CI
- Flaky tests (LLM variance) will cause false failures
- Docker Compose for Engrammic takes time to start

**Failure Modes**:
1. CI job runs 5min, Engrammic still starting → timeout
2. Tests pass locally, fail in CI (different models, keys)
3. LLM call takes 30s in CI, 5s locally (rate limiting)

**Mitigations**:

1. **Use deterministic evaluation only in CI** (Day 4)
   ```python
   if os.environ.get("CI"):
       runner = SomnusRunner(evaluators=[KeywordEvaluator()])
   else:
       runner = SomnusRunner(
           evaluators=[KeywordEvaluator(), LLMJudge()]
       )
   ```

2. **Make Engrammic optional for CI runs** (Use NullContextClient)
   ```python
   if os.environ.get("SOMNUS_ABLATE"):
       context_client = LiveContextClient(...)
   else:
       context_client = NullContextClient()
   ```

3. **Set generous timeouts for CI**
   ```python
   if os.environ.get("CI"):
       timeout = 60.0  # 60s vs 30s locally
   else:
       timeout = 30.0
   
   client = httpx.AsyncClient(timeout=timeout)
   ```

4. **Separate smoke tests from integration tests**
   ```bash
   # CI runs smoke tests (fast, no LLM)
   pytest tests/test_schema.py tests/test_loader.py tests/test_agent.py
   
   # Local/nightly runs full integration tests
   pytest tests/integration/test_runner.py --use-llm-judge
   ```

5. **Mock Engrammic in CI if not available**
   ```python
   @pytest.fixture
   def context_client(monkeypatch):
       if os.environ.get("CI") and not is_engrammic_available():
           return NullContextClient()
       return LiveContextClient()
   ```

---

## Implementation Checklist for Day 3-4

### Phase: Pre-Code (Critical Decisions)
- [ ] Write evaluator protocol + interface (use Risk 6 framework)
- [ ] Define judge rubric with concrete anchors (use Risk 1 framework)
- [ ] Decide on keyword vs LLM judge for v1 (STRONGLY RECOMMEND keyword only)
- [ ] Set cost gate defaults (RECOMMEND $10 per run)
- [ ] Define CLI command structure (subcommands: run, report, compare)

### Phase: Day 3 (Evaluators)
- [ ] Implement Evaluator ABC + protocol
- [ ] Implement KeywordEvaluator (deterministic baseline)
- [ ] Implement TrialResult schema (with evaluator scores)
- [ ] Write evaluator tests (consistency, correctness)
- [ ] Implement cost tracking skeleton
- [ ] Add TrialResult serialization (to JSON/SQLite prep)

### Phase: Day 4A (Runner)
- [ ] Implement SomnusRunner (sequential execution, no parallelism)
- [ ] Add cost gating + tracking
- [ ] Implement MCP error handling + logging
- [ ] Add healthcheck before run start
- [ ] Implement TrialDB (SQLite result storage)
- [ ] Add tests for runner (single scenario, multiple scenarios, error cases)

### Phase: Day 4B (Report)
- [ ] Implement SomnusReport aggregation
- [ ] Calculate lift (with_score - without_score)
- [ ] Add summary statistics (mean, std, min/max)
- [ ] Implement output formats (JSON, table, markdown)
- [ ] Add comparison logic (run-001 vs run-002)

### Phase: Day 4C (CLI)
- [ ] Implement Click CLI structure
- [ ] Add `run` subcommand (minimal options)
- [ ] Add `report` subcommand
- [ ] Add `compare` subcommand
- [ ] Write integration tests (CLI → runner → results)

---

## Recommended Implementation Strategy

### DO (High Priority)
1. Use **KeywordEvaluator only** for Days 3-4 (deterministic, zero cost)
2. **Sequential execution** (no parallelism) - simple, safe, adequate speed
3. **Cost gate enforcement** - prevent budget surprises
4. **Clear evaluator protocol** - enables Phase 2 (LLM judge) cleanly
5. **Comprehensive logging** - debug MCP failures post-hoc

### DON'T (Avoid Complexity)
1. Don't implement LLM judge yet - save for Phase 2 with anchored rubric
2. Don't add parallelism - sequential is fine for <30 scenarios
3. Don't invent new scoring dimensions - stick to oracle requirements
4. Don't make CLI fancy - minimal flags, sensible defaults
5. Don't assume Engrammic availability - NullContextClient works for baseline

### DEFER (Phase 2+)
1. LLM judge with confidence/consistency checking
2. Multi-judge consensus for robustness
3. Cognitive quality metrics (layer discipline, provenance depth)
4. Session-boundary testing
5. Emergent-use scenario instrumentation
6. SQLite result tracking / regression analysis

---

## Estimated Implementation Effort

| Component | Est. Effort | Risk Level |
|-----------|-------------|-----------|
| Evaluator protocol | 2h | LOW |
| KeywordEvaluator | 1h | LOW |
| TrialResult schema | 1h | LOW |
| SomnusRunner (sequential) | 4h | MEDIUM |
| Cost gating + tracking | 2h | MEDIUM |
| TrialDB (SQLite) | 2h | LOW |
| SomnusReport | 2h | LOW |
| CLI structure | 2h | LOW |
| Integration tests | 4h | MEDIUM |
| **TOTAL (Days 3-4)** | **20h** | |

**Timeline**: Feasible in 2 days (10h/day) with focus on mitigations 1, 2, 3, 5 from high-risk items.

---

## Success Criteria for Days 3-4

- [ ] All 5 scenarios run end-to-end (with + without modes)
- [ ] Results saved to SQLite, queryable
- [ ] Lift calculated correctly (with_score - without_score)
- [ ] Cost tracked and limited (max $10 default)
- [ ] No SQL deadlocks or race conditions
- [ ] CLI works: `somnus run`, `somnus report`, `somnus compare`
- [ ] Integration tests pass (4/5 scenarios; allow 1 flaky)
- [ ] README documents: usage, cost, known limitations
