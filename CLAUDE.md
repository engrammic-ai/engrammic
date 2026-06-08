# CLAUDE.md

## Repository

`context-service` — Engrammic production backend. Lives in `delta-prime/` monorepo alongside `primitives/` (sibling at `../primitives`, editable path source via `[tool.uv.sources]`).

## Stack

Python 3.12+ / FastAPI / FastMCP / Memgraph / Qdrant / Redis / Dagster / structlog. Optional: Vertex AI, Gemini, Anthropic, OpenAI (`llm`, `embeddings`), WorkOS (`auth`).

Two surfaces: **MCP server** (primary) + **FastAPI REST** (admin). Multi-tenancy via `silo_id`.

## Commands

All Python via `uv run`. See `justfile` for full list.

```bash
just install-dev   # uv sync --all-extras
just check         # lint + typecheck (must pass before merge)
just test          # pytest (takes args: just test -k name)
just ci            # check + test (pre-push)
just dev           # FastAPI with reload
just up / down     # local stack (ASK BEFORE BUILDING)
just db-migrate    # run migrations
just dagster-web   # Dagster UI (SAGE jobs: custodian / synthesizer / groundskeeper)
```

## Concepts

- **EAG** (Epistemic Augmented Generation) — generation paradigm
- **CITE** (Context In Tiered Epistemology) — schema/architecture (see `primitives.schema.*`)
- Four cognitive layers: Memory → Knowledge → Wisdom → Intelligence
- **Meta-Memory** — provenance, time-travel, reflection (cross-cutting, not a 5th layer)

## Key paths

- `src/context_service/mcp/` — MCP server + tools (primary agent surface)
- `src/context_service/engine/protocols.py` — storage interfaces (depend on this, not concrete stores)
- `../primitives/docs/` — EAG paradigm docs
- `context/architecture.md` — service architecture (surfaces, storage, SAGE pipeline)
- `context/architecture/sage-system.md` — SAGE sub-agents (custodian, synthesizer, groundskeeper, validator)
- `context/plans/` — active implementation plans
- `context/brainstorm/2026-05-10-eag-agent-instructions.md` — cognitive guide for EAG usage
- `skills/` — MCP skills for agent onboarding (copy to `~/.claude/skills/` to use)

## Rules

1. Always `uv run` (never system Python)
2. `just check` must pass before merge (mypy strict + ruff)
3. No emojis in code or docs
4. Depend on `engine/protocols.py`, not concrete stores
5. Check `context/plans/` before non-trivial work
6. Never commit directly to `main`
7. Primitives imports: `primitives.eag.*`, `primitives.schema.*`

## Communication style

1. No reflexive agreement - never start with "You're absolutely right!" or similar
2. Question unclear requirements - ask for clarification when specs are ambiguous
3. Suggest alternatives when a better approach exists, explain trade-offs
4. Discuss before implementing - present approach and get confirmation for significant changes
5. Push back on problematic requests - explain why something might be a bad idea

## MCP tool surface

Source of truth: `src/context_service/config/mcp_tools.yaml`. Names and descriptions are config, not code. The surface is intent/verb-based.

| Tool | Maps to |
|------|---------|
| `remember` | memory (observation, no evidence) |
| `learn` | knowledge (claim, evidence required) |
| `decide` | commitment (agent decision, requires about nodes) |
| `accept` | promote ProposedBelief to Belief |
| `recall` | retrieval (query or node_id) |
| `trace` | provenance (where did this come from?) |
| `history` | versioning (how did this evolve?) |
| `link` | typed relationship |
| `reason` | intelligence (reasoning steps) |
| `reflect` | meta-observation |
| `hypothesize` | tentative belief (finalize with `commit`) |
| `revise` | update tentative belief |
| `commit` | crystallize hypotheses |
| `forget` | request node deletion |
| `patterns` | skills / workflow templates |
| `dismiss` | dismiss marker or reject ProposedBelief |
| `tick` | acknowledge engagement without action |

## Belief architecture

Two Wisdom subtypes with different trust models:

**Commitments (agent decisions):**
- Created via `decide` (direct) or `commit` (from hypotheses)
- Agent-scoped trust: "this agent decided"
- No synthesis chain required

**Beliefs (system-synthesized):**
- Created by SAGE synthesizer as ProposedBelief
- Require agent `accept` to promote to full Belief
- System-scoped trust: "corroborated from facts"
- Full provenance chain (SYNTHESIZED_FROM edges to Facts)
- Use `dismiss` to reject

**Formation flows:**
```
Agent observes    -> remember()     -> Memory (decays)
Agent claims      -> learn()        -> Claim (Knowledge)
System verifies   -> [custodian]    -> Fact (Knowledge, promoted)
System clusters   -> [custodian]    -> Cluster reaches threshold
System synthesizes-> [synthesizer]  -> ProposedBelief (pending)
Agent reviews     -> accept/dismiss -> Belief (Wisdom) or rejected
Agent decides     -> decide()       -> Commitment (Wisdom)
Agent reasons     -> hypothesize()  -> WorkingHypothesis (Intelligence)
Agent crystallizes-> commit()       -> Commitment (from hypothesis)
```

Agent-facing verbs: `decide` for direct decisions, `hypothesize` then `commit` for reasoning, `accept` to approve SAGE synthesis.

## Memory (Engrammic MCP)

**At session start:** `recall` what's relevant to today's work.

**Store proactively (don't wait to be asked):**
- User preferences or corrections → `remember`
- Codebase discoveries with file evidence → `learn`
- Bug fixes (what was wrong, why, how fixed) → `learn`
- Decisions or conclusions from multiple facts → `decide`
- Changed understanding or mistakes → `reflect`

**Always `recall` before storing** — supersede existing nodes, don't duplicate.

**Skip:** debug output, terminal logs, obvious-from-code things, speculation.

### Layer selection

| Layer | When | Evidence? |
|-------|------|-----------|
| Memory (`remember`) | Raw observation, preference | No |
| Knowledge (`learn`) | Verifiable claim, discovery | Yes (file://, https://) |
| Wisdom (`decide`) | Conclusion from facts | Links to supporting nodes |
| Meta (`reflect`) | Understanding changed | Links to affected nodes |

### Quick heuristics

- Memory: "Would I tell a colleague tomorrow?" If no, don't store.
- Knowledge: "Do I have evidence?" If no, use Memory instead.
- Wisdom: "Based on [facts], I believe [conclusion]." If you can't fill in [facts], it's a hunch, not a belief.

See `context/brainstorm/2026-05-10-eag-agent-instructions.md` or the `engrammic:eag-guide` skill for full documentation.

## Performance targets

| Operation                        | Target    |
|----------------------------------|-----------|
| `recall` (cached)            | < 20ms    |
| `recall` (search)            | < 250ms   |
| `recall` (graph depth 2)     | < 500ms   |
| `remember` / `learn` (write) | < 300ms p95 |
| `link`                       | < 100ms   |
