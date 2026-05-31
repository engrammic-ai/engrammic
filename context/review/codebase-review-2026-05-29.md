# Codebase Review - 2026-05-29

**Mode**: checkup (exploration-based, whole codebase, not a diff review)
**Branch**: main  **HEAD**: dc1e1a2 (fix: address three learn-related bugs)
**Previous review**: 2026-05-25 (1 P0, 6 P1, 15 P2, 11 P3)
**Method**: 4 parallel explorers (arch / patterns / quality / domain) + a wanderer for gap-fill. Findings also stored in Engrammic (semantic recall: "context-service 2026-05-29 checkup", or fetch belief `17d0b5eb` for the overall verdict).

## Verdict

Production-ready with bounded, known risks. Operational maturity (deployment, schema lineage, telemetry, version kill-switch) is ahead of runtime safety posture (security, coverage). The codebase ships; the security and coverage items need an explicit milestone or an explicit "accept and document" decision, because they have now been flagged across 5+ consecutive review cycles (May 08 through May 29) with no action.

## Carried-forward open items (with evidence)

These were open at the May 25 review and remain open. Listed worst-first.

| ID | Sev | Item | Evidence |
|----|-----|------|----------|
| INJ-1 | P1 | Prompt injection in custodian. Raw DB fact content interpolated into LLM synthesis prompts, no sanitization or length bound. Note: `clustering/` already does this correctly via `escape_for_prompt()`, so the fix pattern exists in-repo. | `custodian/identities/custodian.py:108-111` |
| S-003 | P1 | Dev-auth bypass. If `AUTH_ENABLED` is unset, a dev `AuthContext` is returned. Mitigated by deploy config, no code-level guard. Acceptable for beta, must close before public launch. | `api/auth_dep.py:26-35` |
| AI-003 | P2 | `max_length=500` on the reasoning field not implemented. | custodian identity agents |
| AI-001 | P2 | `tool_calls_limit` removed from `deep_pass` limits and never restored. | custodian deep-pass limits |
| L-002/L-003 | P2 | `silo_id=None` passed to metrics in two core write tools. Per-silo attribution broken for ~50% of writes (`remember`/`recall` derive it correctly). | `mcp/tools/believe.py:48`, `mcp/tools/learn.py:71,73` |
| A-001 | P1 | OTLP firewall rule missing. Cloud Run cannot reach the SigNoz collector (port 4317). | infra (Cloud Run egress) |
| A-007 | P3 | `embedding_cache_miss` counter never recorded on the miss path, so cache hit-rate metric is systematically wrong. | `cache/embedding_cache.py:39` |

## New findings this checkup

### Quality / coverage
- **e2e MCP suite fully disabled.** 716 lines, module-level skip, pending the verb-promotion refactor. The primary agent surface has no live e2e coverage. Re-enabling it is the highest-leverage quality action. `tests/e2e/test_mcp_tools.py`
- **Coverage structurally unmeasured.** `pytest-cov` is installed but `--cov` is absent from `addopts` and the justfile, and no CI floor exists. One-line fix, deferred 5+ cycles. Decision needed: wire it or document why not. `pyproject.toml`
- **No asyncio timeout guards in the engine hot path.** `memgraph_store.py` and `queries.py` have zero `asyncio.wait_for`. Recall (<250ms) and write (<300ms p95) SLOs are unenforceable at the code level. A slow query blows the budget silently. The known ~500ms embedding bottleneck sits upstream of any timeout.
- **MCP tool unit-test gap.** 28 tool source files, 18 with dedicated tests. No dedicated tests for `commit`, `hypothesize`, `revise`, `reason`, `reflect`, `context_get`, `context_graph`, `context_history`, `context_skills`.
- **License renewal has no payment-status check.** Any cryptographically valid key renews indefinitely. Low risk pre-revenue, needs a milestone before first paying customer. `api/routes/license.py:48`

### Architecture
- **`EAGKnowledgeStore.ingest`/`query` raise `NotImplementedError`.** The primitives protocol contract is not wired end-to-end at the store level; only the higher service layer satisfies it. Fine today, a trap for any future primitives-level consumer. `engine/memgraph_store.py`
- **MCP surface has no health monitoring.** FastAPI uses `ServiceRegistry` (30s health-check + auto-rebuild on `app.state`); the MCP surface uses a static module-level `_services` dict with no background checking. If Memgraph drops and reconnects, the MCP surface keeps the stale client until process restart. `mcp/server.py`, `core/service_registry.py`
- **Pipeline assets bypass the protocol boundary.** Several Dagster assets import `MemgraphClient` directly instead of `MemgraphStore`. Allowlisted in `test_architecture_boundary.py`, but the list is growing. `pipelines/assets/{pattern_detection,heat_diffusion,causal_tombstone,custodian_finalize}.py`, `pipelines/schedules.py`

### Patterns / minor drift
- Logger naming drift: 6 files use `log =` instead of canonical `logger =` (`engine/chain_applicability.py`, `engine/chain_saga.py`, `mcp/tools/learn.py`, `pipelines/jobs/usage_retention.py`, `pipelines/jobs/orphan_recovery.py`, `pipelines/assets/step_embedding.py`); two omit `__name__`.
- `context_skills.py` registers under the old tool name `context_skills` and takes an explicit `service` param, unlike every other tool module. Unclear if it is wired into `register_tools()` or dead. Worth confirming.
- `get_mcp_auth_context()` is called twice per tool invocation (once in `@rate_limited`, once in `_impl`). Stateless header reads, so not a bug, just redundant.

## Documentation drift (cheap to fix)

- **CLAUDE.md tool table is stale.** Lists 13 verbs; the live surface (`mcp_tools.yaml`) has 15. `dismiss` and `tick` are missing from the table.
- **`believe` writes a `Commitment` node, not a `Belief`.** Correct per spec (Commitment is the cross-layer node; `Belief` is produced only by the SAGE synthesizer), but the verb-name vs node-type mismatch trips up new contributors. Worth one explicit sentence in the docs.
- **architecture.md lists 3 Dagster jobs; code has 7** (`causal_tombstone`, `groundskeeper_nightly`, `orphan_chain_recovery`, `sage_validator`, `telemetry_gauges`, `telemetry_prune`, `usage_retention`). Also missing from the doc: the Postgres hybrid storage for the Intelligence layer (ReasoningChain saga).
- **`MetaObservation` maps to `PersistenceLayer.AUDIT`.** Documented as a distinct cross-cutting Meta-Memory concern, but collapsed into AUDIT for storage classification. Either give it a dedicated `PersistenceLayer.META` or document the simplification. `primitives/schema/labels.py:118`

## Process notes (not codebase issues)

- **`known-issues.md` is stale on subagent MCP.** Today's probe confirmed that plain Agent-tool subagents CAN reach the HTTP MCP at `beta.engrammic.ai` (both `mcp__engrammic__*` and `mcp__claude_ai_engrammic__*` returned data). The "Claude Code Subagents Cannot Use MCP" entry (dated 2026-05-06, stdio-era) no longer holds for the url-based server. Recommend updating that entry.
- **The explore-codebase skill's tag-recall degrades silently here.** This MCP `recall` has no `tags` parameter, and store-time tagging came back inconsistent (many nodes have empty `tags`). The skill's "recall your tag at the end" steps fall back to semantic search. Retrieve checkup findings by semantic query or node_id, not by tag.

## Pick up next (suggested order)

1. Decide the security milestone: INJ-1 (reuse `escape_for_prompt`) + S-003 code-level guard. These are the only items that gate sensitive-data scale.
2. Re-enable the e2e MCP suite (blocked on the verb-promotion refactor) and wire `--cov` with a CI floor.
3. Cheap doc fixes: CLAUDE.md tool table, architecture.md job count, `believe`/Commitment note, known-issues.md subagent update.
4. P2/P3 cleanup as opportunistic: `silo_id` in believe/learn metrics, engine timeout guards, embedding_cache miss counter, logger naming.
