# LoCoMo-Plus Benchmark Integration

## Overview

Integrate Engrammic with the LoCoMo-Plus cognitive memory benchmark to produce publishable scores demonstrating Engrammic's retrieval quality on implicit conversational memory tasks.

## Goal

Publishable leaderboard scores on LoCoMo-Plus, particularly the cognitive category (cue-trigger semantic disconnect) which tests exactly what Engrammic is designed for.

## Approach

Fork LoCoMo-Plus into `engrammic-ai/benchmarks`, add an Engrammic backend wrapper.

## Repo Structure

```
engrammic-ai/benchmarks/
├── locomo-plus/              # Fork of xjtuleeyf/Locomo-Plus
│   ├── evaluation_framework/
│   │   ├── backends/
│   │   │   ├── llm.py        # Existing
│   │   │   └── engrammic.py  # Wrapper (~80 LOC)
│   │   └── scripts/
│   │       └── evaluate.sh
│   └── task_eval/
│       └── evaluate_qa.py    # Modified to add engrammic backend
├── docker-compose.yaml       # Engrammic stack for benchmark runs
├── run_benchmark.sh          # Entry point
└── results/
    └── YYYY-MM-DD.json       # Published scores
```

## Wrapper Architecture

`engrammic.py` implements `call_engrammic(input_prompt) -> str`:

1. **Parse**: Extract conversation turns from input_prompt by splitting on speaker markers. Identify final trigger query.

2. **Store**: Feed conversation history to Engrammic via MCP `remember` tool. Each user turn stored with turn index metadata for temporal ordering.

3. **Retrieve + Answer**: Call `recall(trigger_query)` to get relevant context, then generate answer via Gemini with retrieved context.

Storage layer: `remember` (memory layer) not `learn` - benchmark turns lack evidence URIs.

## MCP Integration

- MCP client connects via stdio to Engrammic server process
- Server runs via docker-compose (Memgraph, Qdrant, Redis, app)
- Each benchmark sample uses a fresh silo for isolation
- `run_benchmark.sh` handles lifecycle: start stack, health check, run eval, teardown

## Sample Flow

```
1. Create temp silo
2. Store N conversation turns via remember()
3. recall(trigger_query) -> retrieved context
4. Gemini(trigger + context) -> answer string
5. Return answer to harness
6. GPT-4o-mini judge scores (1 / 0.5 / 0)
```

## LLM Configuration

- Answer generation: Gemini 2.5 Flash via Vertex AI
- Judge: GPT-4o-mini (LoCoMo-Plus default)

Note in published results that answer generation uses Gemini, not GPT-4o-mini.

## Categories

Run all 6 LoCoMo-Plus categories:
- multi-hop
- temporal
- common-sense
- single-hop
- adversarial
- cognitive (primary interest)

## Output Format

```json
{
  "model": "engrammic-v0.x + gemini-2.5-flash",
  "date": "2026-06-XX",
  "scores": {
    "multi-hop": 0.XX,
    "temporal": 0.XX,
    "common-sense": 0.XX,
    "single-hop": 0.XX,
    "adversarial": 0.XX,
    "cognitive": 0.XX
  },
  "aggregate": 0.XX
}
```

## Publishing

- Results committed to `results/` directory
- README with comparison table vs LoCoMo-Plus baselines
- Headline metric: cognitive category delta vs baseline LLMs

## Estimated Effort

- Repo setup + fork: 1 hour
- Wrapper implementation: 2-4 hours
- Docker/runner setup: 1-2 hours
- Run + debug: 2-4 hours
- Total: 1-2 days

## Dependencies

- LoCoMo-Plus repo (MIT license assumed, verify)
- Engrammic server (context-service)
- MCP Python client
- Vertex AI credentials (Gemini)
- OpenAI API key (judge only)

## Open Questions

None - design approved.
