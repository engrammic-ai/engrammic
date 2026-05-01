# OpenAI Symphony

Analyzed: 2026-05-01

## What it is

OpenAI's open-source (Apache 2.0) Codex orchestrator, released April 28, 2026. Turns Linear boards into an agent control plane: every ticket gets a Codex agent that works until PR ready. Built on Elixir/BEAM for fault-tolerant concurrency. Claimed 500% increase in landed PRs internally.

## Architecture

- Polls Linear every 30 seconds
- Maps each open issue to a dedicated agent workspace
- Default: 10 concurrent agents
- Retry with exponential backoff
- Within a run: workspace persists (agent sees prior commits, partial code, test results)
- Between runs: nothing. Clean slate.

## The gap they acknowledge

"Symphony orchestrates execution, not experience."

Each implementation run starts without memory of the last. This is the explicit limitation in their spec. LangGraph, CrewAI, and AutoGen share this same constraint: coordination without continuity.

## Positioning implications

**Complementary, not competitive.** Symphony is task orchestration (ticket to PR). Delta Prime is cognitive infrastructure (memory, knowledge, wisdom, intelligence layers).

Their gap is our headline. Integration story: Symphony handles dispatch, context-service provides persistent cognition across runs.

## Sources

- https://openai.com/index/open-source-codex-orchestration-symphony/
- https://memu.pro/blog/openai-symphony-agentic-framework
- https://github.com/openai/symphony/blob/main/SPEC.md
