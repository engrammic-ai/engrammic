# Somnus: Agentic Test Harness for Engrammic

**Date**: 2026-05-13  
**Mode**: architecture brainstorm  
**Repo**: ../somnus (sibling to context-service)

## Summary

Somnus extends the existing `context/qa/` v0 (which already found 5 bugs) into a production-grade harness. The core insight: testing "do MCP tools work" is different from testing "does Engrammic help agents reason better." Somnus must do both, with the second being the differentiator for partner conversations.

## Key Insights

1. **With/without ablation is the killer feature** - run same task twice (Engrammic enabled vs disabled), measure lift. This is the falsifiable claim that matters.

2. **Existing infrastructure is 70% there** - `tests/evals/` has pydantic-evals, LLM-as-judge, silo isolation. Somnus's unique contribution is the Claude agent session driver + graph state inspection.

3. **V0's blind spot is scripted scenarios** - agents execute predetermined steps, so we confirm tools work but not whether agents naturally reach for Engrammic when reasoning freely.

4. **Session-boundary testing is missing** - no current scenario tests: store at T1, terminate process, recall at T2. This is the core memory persistence claim.

---

## Architecture Decisions

| Decision | Recommendation | Rationale |
|---|---|---|
| Orchestration | Minimal custom + pydantic-evals | Observability, no framework overhead |
| LLM client | litellm + pydantic-ai | Already in deps |
| Transport | MCP over HTTP | Same as Claude Code |
| Execution | Hybrid (scripted setup, emergent run) | Catches real agent failures |
| Evaluation | Metrics primary, LLM-judge secondary | Cost-gated |
| Isolation | Per-run silo_id | Already works, cheap |
| Results storage | SQLite in Somnus | Lightweight, queryable |

---

## Component Design

### Core Components

```
somnus/
  scenarios/           # YAML scenario definitions
  somnus/
    agent.py           # SomnusAgent - Claude agent with MCP client
    connection.py      # LiveContextClient / NullContextClient
    evaluation/        # Evaluators (keyword, llm_judge, tool_audit, recall_k)
    runner.py          # SomnusRunner - orchestrates test runs
    report.py          # SomnusReport - aggregates results
    db.py              # SQLite result storage
  cli.py               # CLI entrypoint
```

### Data Flow

```
  YAML Scenarios
        |
        v
  ScenarioLoader
        |
        v
  SomnusRunner.run()
        |
   _____|_____
  |           |
  v           v
"with"     "without"
mode        mode
  |           |
  v           v
SomnusAgent SomnusAgent
(MCP client) (NullClient)
  |           |
  v           v
AgentTrace  AgentTrace
  |___________|
        |
        v
   Evaluator
        |
        v
   TrialResult x2
        |
        v
   SomnusReport
   (lift = with - without)
```

### Key Metric

```
lift = score_with - score_without

lift > 0.1  -> Engrammic helped
lift < -0.1 -> Engrammic hurt (regression)
|lift| <= 0.1 -> no signal
```

---

## Integration Design

### Connections

- **LLM**: litellm + pydantic-ai (provider-agnostic)
- **Engrammic**: MCP over HTTP (`http://localhost:8000/mcp`)
- **Results**: SQLite in `somnus-output/somnus.db`

### Isolation

- Per-run `silo_id = f"somnus-{run_id}"`
- Create via `context_admin(action=create_silo)` at start
- Delete via `context_admin(action=delete_silo)` at teardown
- Use `memgraph-test` profile (port 17687) for destructive tests

### Failure Handling

| Failure | Status | Action |
|---|---|---|
| LLM rate limit | `SKIPPED_RATE_LIMITED` | Retry 3x with backoff, then skip |
| Engrammic down | `ERROR_INFRA` | Log, continue other tests |
| Agent loops | `FAILED_AGENT_LOOP` | 10-turn limit, then fail |
| Schema violation | `FAILED_SCHEMA` | Log raw output, fail |

---

## Success Criteria (Tiered)

### Tier 1 - CI (every commit)

- All 10 MCP tools return valid responses
- Silo isolation holds (writes in A invisible in B)
- Latency SLOs: recall <20ms cached, <250ms search, store <300ms
- `context_crystallize` produces correct provenance edges

### Tier 2 - Release

- LLM-as-judge coherence/relevance tests pass
- sage.synthesizer produces expected Beliefs (80%+)
- Time-travel queries return correct state at T-1
- Ablation shows positive lift on reference tasks

### Tier 3 - Track over time

- Embedding similarity >0.85 for semantic pairs
- Belief drift rate (Commitments revised within 24h)
- Mean agent turns to task completion

---

## Ablation Task Design

**Approach**: Constrained LLM generation with three-model separation.

### Three-Model Separation

```
Task Generator:  Gemini (or OpenAI) - creates task from constraints
Agent Under Test: Claude - runs with/without Engrammic  
Judge:           GPT-4 (or separate Claude) - scores output
```

Key properties:
- Generator doesn't know who's being tested
- Agent doesn't know the oracle answers
- Judge doesn't share context with agent

### Configuration

```yaml
# somnus.config.yaml
models:
  generator:
    provider: google
    model: gemini-2.5-pro
  agent:
    provider: anthropic
    model: claude-sonnet-4-6
  judge:
    provider: openai
    model: gpt-4o

# Optional: test same tasks across multiple agents
agent_matrix:
  - provider: anthropic
    model: claude-sonnet-4-6
  - provider: openai
    model: gpt-4o
```

### Task Categories (5 total)

Each category has a constraint schema. LLM generates concrete tasks within constraints.

**1. Fact Accumulation**
```yaml
category: fact_accumulation
constraints:
  num_facts: 4-6
  fact_sources: [user_statement, document_snippet, tool_result]
  noise_turns: 1-2
  synthesis_type: one_of [comparison, summary, recommendation]
  domains: [tech_stack, product_features, team_structure]
oracle:
  requires_all_facts: true
  no_hallucination: true
  correct_synthesis: true
```

**2. Preference Tracking**
```yaml
category: preference_tracking
constraints:
  num_preferences: 3-4
  preference_types: [positive, negative, conditional]
  gap_turns: 2-4
  application_context: different_from_statement
  domains: [dev_workflow, communication_style, scheduling]
oracle:
  respects_all_preferences: true
  no_reprompting: true
  handles_conflicts: true
```

**3. Contradiction Resolution**
```yaml
category: contradiction_resolution
constraints:
  contradiction_type: one_of [direct, temporal, source_conflict]
  num_contradictions: 1-2
  resolution_required: true
  domains: [requirements, facts, schedules]
oracle:
  detected_contradiction: true
  surfaced_to_user: true
  reasoning_shown: true
  resolution_justified: true
```

**4. Temporal Reasoning**
```yaml
category: temporal_reasoning
constraints:
  state_changes: 2-4
  query_type: one_of [point_in_time, diff, sequence]
  time_references: one_of [absolute, relative, implicit]
  domains: [project_status, decisions, requirements]
oracle:
  correct_state_at_t: true
  no_anachronism: true
  provenance_available: true
```

**5. Cross-Session Recall**
```yaml
category: cross_session_recall
constraints:
  session_gap: one_of [minutes, hours, days]
  stored_items: 3-5
  storage_layers: [memory, knowledge]
  recall_cue: one_of [direct, semantic, contextual]
  domains: [project_context, user_profile, decisions]
oracle:
  all_items_retrievable: true
  no_session_bleed: true
  confidence_appropriate: true
```

### Generation Flow

```
Constraints (YAML)
       |
       v
  Task Generator (Gemini)
  - produces: task_prompt, seeded_facts, oracle_answers
       |
       v
  Frozen artifact (disk)
       |
       v
  Agent Under Test (Claude)
  - sees only: task_prompt + MCP tools
       |
       v
  Agent output captured
       |
       v
  Judge (GPT-4)
  - sees: task_prompt, agent_output, oracle_answers
  - scores against rubric
```

---

## Evaluation Metrics

### Multi-Dimensional Scoring

Single 0-1 scores lose signal. Use structured scoring per trial:

```yaml
trial_result:
  task_id: "pref-tracking-0042"
  category: preference_tracking
  mode: with_engrammic
  
  scores:
    task_completion: 0.8
    factual_accuracy: 1.0
    recall_completeness: 0.75
    reasoning_quality: 0.9
    
  composite: 0.86
  
  metadata:
    turns: 7
    tokens: 2847
    mcp_calls: 4
    latency_ms: 12340
```

### Multi-Dimensional Lift

```
lift_recall = recall_with - recall_without
lift_accuracy = accuracy_with - accuracy_without
lift_composite = composite_with - composite_without
```

Actionable insight: "Engrammic helps recall (+0.3) but doesn't affect accuracy (+0.02)".

### Weights Derived from Constraints

Weights follow from what the oracle checks, not arbitrary numbers:

```yaml
# Contradiction resolution oracle requires:
#   - detected_contradiction: true
#   - surfaced_to_user: true  
#   - reasoning_shown: true
#   - resolution_justified: true
# 3 of 4 are reasoning-related, so reasoning_quality gets higher weight

weights:
  contradiction_resolution:
    factual_accuracy: 0.2
    recall_completeness: 0.2
    reasoning_quality: 0.6
```

Override profiles for specific demos:

```yaml
profiles:
  accuracy_focused:
    factual_accuracy: 0.6
    recall_completeness: 0.3
    reasoning_quality: 0.1
  balanced:
    factual_accuracy: 0.33
    recall_completeness: 0.33
    reasoning_quality: 0.34
```

---

## Session-Boundary Testing

### Boundary Types

| Type | What it tests | Speed |
|---|---|---|
| Context boundary | MCP storage/retrieval across agent instances | Fast (v1) |
| Process boundary | No hidden in-process state leaking | Slow (v2) |
| Time boundary | SAGE synthesis doesn't break recall | Slow (v2) |

### Context Boundary (v1)

```yaml
session_boundary_test:
  session_1:
    silo_id: "somnus-{run_id}"
    agent_id: "agent-{uuid}"
    actions:
      - store preference "user likes FastAPI"
      - store fact "project deadline is May 20"
    
  boundary: context_clear
  
  session_2:
    silo_id: "somnus-{run_id}"  # same silo
    agent_id: "agent-{new_uuid}" # new agent
    task: "recommend a framework for the user's new project"
    
  oracle:
    must_recall: ["FastAPI", "May 20"]
    must_not_hallucinate: true
```

---

## Emergent Use Scenarios

### Purpose

Test whether agents *naturally* reach for Engrammic when reasoning freely, not just when told to.

### Design

```yaml
emergent_use_scenario:
  setup:
    silo: seeded with prior context
    agent_system_prompt: |
      You have access to Engrammic memory tools.
      Use them however you see fit.
      # NO instructions on when/how
      
  task: |
    Research the pros and cons of React Server Components
    vs traditional SSR. Form an opinion and explain your reasoning.
    
  observation:
    track_mcp_calls: true
    track_call_timing: true
    track_call_purpose: true
```

### Emergent Metrics

```yaml
emergent_metrics:
  tool_adoption:
    used_any_mcp: bool
    mcp_calls_count: int
    first_call_turn: int  # early = natural, late = afterthought
    
  tool_appropriateness:
    stored_relevant: ratio
    recalled_relevant: ratio
    layer_choice_correct: ratio  # Memory vs Knowledge vs Wisdom
    
  cognitive_pattern:
    observation_before_claim: bool  # Memory before Knowledge
    evidence_before_belief: bool    # Knowledge before Wisdom
    used_meta_on_uncertainty: bool
```

### Judge Rubric

```yaml
judge_rubric:
  - Did agent use memory tools without being told? (0/1)
  - Were tool uses appropriate to the task? (0-1)
  - Did tool use improve answer quality? (0-1)
  - Did agent demonstrate belief formation flow? (0/1)
```

If agents don't naturally use Engrammic, that's a product signal - onboarding or tool surface needs work.

---

## Nice-to-Have Metrics

### Efficiency Metrics

```yaml
efficiency:
  token_efficiency:
    # Did Engrammic reduce total tokens vs re-explaining context?
    tokens_with: int
    tokens_without: int
    savings_ratio: float
    
  turn_efficiency:
    # Fewer turns to task completion with memory?
    turns_with: int
    turns_without: int
```

### Cost Metrics

```yaml
cost:
  llm_cost_delta:
    # Did Engrammic reduce spend or increase it?
    cost_with: float
    cost_without: float
    
  latency_budget:
    # How much of task time was MCP overhead?
    mcp_latency_ms: int
    total_latency_ms: int
    overhead_ratio: float
```

### Cognitive Quality Metrics

**1. Belief Coherence** - Are beliefs internally consistent?

```yaml
belief_coherence:
  measures:
    direct_contradiction:
      count: int
      examples: list[tuple[belief, belief]]
    implication_violation:
      count: int
    confidence_consistency:
      weighted_score: float  # penalize high-high conflicts
    temporal_coherence:
      violations: int
  scoring:
    0_contradictions: 1.0
    1_contradiction: 0.7
    2+_contradictions: 0.3
```

**2. Provenance Depth** - Can agent justify beliefs?

```yaml
provenance_depth:
  measures:
    grounding_ratio:
      # % of Wisdom with edges to Knowledge
      target: > 0.8
    evidence_chain_length:
      avg_depth: float
      min_depth: int
    orphan_beliefs:
      # Wisdom with no incoming edges
      count: int
      acceptable: 0
    circular_reasoning:
      detected: bool
    source_diversity:
      avg_sources_per_belief: float
  scoring:
    grounding_ratio * 0.4 +
    chain_length * 0.3 +
    (1 - orphan_ratio) * 0.2 +
    diversity * 0.1
```

**3. Decay Appropriateness** - Right decay class for info type?

```yaml
decay_appropriateness:
  expected_mappings:
    user_preference: long_term
    meeting_note: medium_term
    transient_state: short_term
    factual_claim: indefinite
  measures:
    correct_class_ratio: target > 0.7
    over_persistence: count  # transient as long_term
    under_persistence: count  # important as short_term (worse)
```

**4. Layer Discipline** - Right cognitive layer?

```yaml
layer_discipline:
  violations:
    observation_in_knowledge: count  # raw observation as fact
    claim_in_memory: count           # fact stored as observation
    premature_wisdom: count          # belief without grounding
    skipped_layers: count            # Memory -> Wisdom, no Knowledge
```

**5. Meta-Cognition Quality** - Appropriate reflection?

```yaml
meta_cognition:
  measures:
    uncertainty_acknowledgment: ratio
    belief_revision: ratio  # updated on contradiction?
    contradiction_detection: ratio
    reflection_on_error: ratio
```

**Composite Cognitive Quality:**

```yaml
cognitive_quality:
  belief_coherence: 0.25
  provenance_depth: 0.25
  decay_appropriateness: 0.15
  layer_discipline: 0.20
  meta_cognition: 0.15
```

### Recovery and Calibration

```yaml
recovery:
  error_correction:
    # If agent stores something wrong, do they correct it?
    self_corrections: int
    uncorrected_errors: int
    
  uncertainty_calibration:
    # Does confidence match actual correctness?
    calibration_error: float  # lower = better
```

---

## Contaminated State Seeding

**Approach**: Generate realistic noise via SAGE-style synthesis on synthetic observations.

1. Seed 50-100 Memory nodes with realistic but outdated/partial information
2. Run a mini-synthesis pass to create some Knowledge/Wisdom nodes
3. Manually inject 2-3 contradictions and 2-3 superseded facts
4. Save as a fixture: `fixtures/contaminated_corpus.yaml`

This creates a "lived-in" silo that tests agent navigation of messy state.

---

## Priority Build Order

1. **Day 1**: ScenarioLoader + YAML schema + 3 reference scenarios
2. **Day 2**: SomnusAgent with MCP client (with/without modes)
3. **Day 3**: Evaluators (keyword, llm_judge) + TrialResult
4. **Day 4**: SomnusRunner + SomnusReport + CLI
5. **Day 5**: LiveContextClient integration + first ablation run
6. **Day 6**: SQLite persistence + regression tracking
7. **Day 7**: Session-boundary scenario + emergent-use scenario

---

## CLI Interface

```bash
# Run all scenarios
uv run somnus run

# Run specific tags
uv run somnus run --tags retrieval,belief

# Run single scenario
uv run somnus run --scenario fact_accumulation

# Run ablation comparison
uv run somnus ablation --task preference_tracking

# Compare runs
uv run somnus compare run-001 run-002

# Generate new task
uv run somnus generate-task --category temporal_reasoning
```

---

## Future: Claude Dreaming Comparison

When Claude's dreaming feature ships, add a three-way ablation:

1. **No memory** (baseline)
2. **Engrammic** (explicit cognitive substrate)
3. **Claude Dreaming** (native memory)

Hypothesis: complementary rather than competing. Engrammic provides structured beliefs, provenance, and time-travel that native memory likely won't. Dreaming may excel at implicit recall and continuity. Test both alone and combined.

---

## Open Items Resolved

- **Ablation tasks**: 5 categories, LLM-generated with held-out oracles
- **Contaminated state**: SAGE-style synthesis on synthetic observations + manual contradiction injection
- **Repo location**: Stays at ../somnus, connects to context-service as black box
