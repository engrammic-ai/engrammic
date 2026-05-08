# Codebase Review - 2026-05-08

**Mode**: full
**Branch**: main  **Base**: main
**Plan**: none active
**Previous review**: 2026-05-06 (56 findings: 1 P0, 14 P1, 22 P2, 19 P3)
**Linter baseline**: ruff clean (0 issues)

## Executive Summary

Previous P0 cypher injection (S-001) **STILL OPEN** - confirmed regression. Previous E-005 to E-009 (Qdrant ops) and P-006/P-007 (N+1 in promotion.py) are **FIXED**.

New critical issues:
- **CRITICAL**: Auto-promote on single assert (R1_THRESHOLD=1) violates consensus spec (T5)
- **HIGH**: Prompt injection in `proposal_worker.py` and `silo_synthesis.py` - user data unsanitized
- **HIGH**: No timeout on synthesis agents - unbounded hangs
- **HIGH**: N+1 in `context_get.py` - batch method exists but unused
- **HIGH**: Causal invalidation has O(N*depth) RTTs

| Category | P0 | P1 | P2 | P3 | Resolved |
|----------|----|----|----|----|----------|
| Security | 1 | 0 | 1 | 0 | 0 |
| Logic/Spec | 2 | 1 | 4 | 3 | 0 |
| Performance | 0 | 3 | 8 | 4 | 4 |
| Error Handling | 0 | 3 | 6 | 5 | 0 |
| AI/LLM | 0 | 4 | 4 | 2 | 0 |
| Blast Radius | 0 | 3 | 1 | 0 | 0 |
| Docs | 0 | 2 | 3 | 5 | 0 |
| **Total** | **3** | **16** | **27** | **19** | **4** |

## Themes

1. **Spec divergence in belief promotion** - Code auto-promotes on single evidence, bypasses Wisdom layer. Spec requires multi-agent consensus.
2. **Prompt injection in custodian** - New `proposal_worker` and `silo_synthesis` concatenate user data unsanitized into LLM prompts.
3. **Missing timeouts/retries on LLM calls** - Synthesis agents have no UsageLimits, no timeout, no retry on rate limits.
4. **N+1 patterns in new code** - `context_get.py`, `proposal_worker.py`, `causal_invalidation.py` all have loop-per-item DB calls.
5. **Test coverage gaps on high-impact files** - `engine/protocols.py` (42 importers, 2 tests), `utils/json.py` (126 reach, 1 test).
6. **Doc staleness** - README says "Delta Prime" (rebranded Engrammic), `mcp-tool-surface.md` describes old 14-tool surface.

## Blast Radius Hotspots

| File | Importers | Risk | Test Files |
|------|-----------|------|------------|
| `engine/protocols.py` | 42 direct, 97 transitive | HIGH | 2 |
| `utils/json.py` | 24 direct, 126 transitive | HIGH | 1 |
| `config/settings.py` | 50 direct, 133 transitive | MEDIUM | 21 |
| `db/queries.py` | 32 direct, 75 transitive | MEDIUM | 4 |
| `custodian/proposal_worker.py` | 4 direct | MEDIUM | 1 |

## Regression Status (from May 6)

| ID | Status | Evidence |
|----|--------|----------|
| S-001 (Cypher injection) | **STILL OPEN** | `tombstone.py:44` still interpolates `edge_type` |
| E-005 to E-009 (Qdrant) | FIXED | All methods have try/except |
| P-006, P-007 (N+1 promotion) | FIXED | Batch UNWIND in place |

---

## Findings

### Security

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| S-001 | P0 | `engine/tombstone.py:44`, `api/routes/admin.py:55` | Cypher injection via `edge_type` - no enum constraint | Change to `Literal["CAUSES", "CORROBORATES", "PREVENTS"]` in Pydantic model | S |
| S-002 | P2 | `api/routes/admin.py:50` | `silo_id` unvalidated free-form string | Add `Field(pattern=r'^[0-9a-f-]{36}$')` | S |

### Logic & Spec Conformance

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| L-001 | P0 | `mcp/tools/context_store.py:53-54, 188-203` | Auto-promote on single assert (R1_THRESHOLD=1) violates T5 consensus spec | Require K chains from multiple agents | M |
| L-002 | P0 | `mcp/tools/context_store.py:486-530` | `context_reason` crystallizations bypass Wisdom, go directly to Knowledge | Route through T13 crystallize path | M |
| L-003 | P1 | `context/specs/mcp-tool-surface.md` | Spec lists 14 tools, implementation has 9 consolidated tools | Update spec to match implementation | S |
| L-004 | P2 | `db/queries.py:1258` | Commitment lacks `:Claim` label per spec | Add multi-label `:Claim:Commitment` | S |
| L-005 | P2 | `db/queries.py:1266` | `CRYSTALLIZED_FROM` is a property, not edge per spec | Create proper relationship edge | S |
| L-006 | P2 | `mcp/tools/context_recall.py:153-164` | Graph traversal drops `as_of` param silently | Forward `as_of` to `_context_graph` | S |
| L-007 | P2 | `mcp/tools/context_update_belief.py:31-39` | `reason` field not persisted to graph | Pass to UPDATE_WORKING_HYPOTHESIS query | S |
| L-008 | P3 | `models/mcp.py:41-52` | 4 undocumented relationship types | Update spec or remove | S |
| L-009 | P3 | `mcp/tools/context_admin.py` | provenance/history are sub-actions, not standalone tools | Document or split | S |
| L-010 | P3 | `mcp/tools/context_store.py:45` | `layer="belief"` is 6th layer, spec has 4 | Clarify in spec | S |

### Performance

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| P-001 | P1 | `mcp/tools/context_get.py:110-152` | N+1 per-node `get()` - batch method exists | Use `ctx_svc._batch_fetch_nodes()` | S |
| P-002 | P1 | `engine/causal_invalidation.py:71-99` | O(N*depth) RTTs per edge | Batch with `IN $edge_ids` and UNWIND | M |
| P-003 | P1 | `engine/compaction.py:199-209` | `batch_compact_chains` entirely serial | Use `asyncio.gather` for independent chains | M |
| P-004 | P2 | `custodian/proposal_worker.py:88-90` | N+1 in proposal detection per cluster | Compute confidence in-query | M |
| P-005 | P2 | `custodian/proposal_worker.py:130-137` | N+1 pending count check per candidate | Hoist before loop | S |
| P-006 | P2 | `engine/synthesis.py:334-366` | 3 sequential writes in merge_beliefs | Combine into single transaction | S |
| P-007 | P2 | `services/context.py:260-268` | Double write for auto-tags | Inline SET into CREATE | S |
| P-008 | P2 | `services/context.py:1507-1524` | Double write for SUPERSEDES | Merge into one Cypher | S |
| P-009 | P2 | `engine/compaction.py:117-123` | LLM provider instantiated per chain | Build once, thread through | S |
| P-010 | P2 | `services/auto_tagging.py:65-88` | Vocabulary re-embed on cache miss blocks store | Move to background/startup | M |
| P-011 | P2 | `mcp/tools/context_get.py:143-151` | N+1 reflection fetch per node | Batch with UNWIND | S |
| P-012 | P3 | `engine/synthesis.py:92-102` | Pure Python centroid loop | Use numpy.mean | S |
| P-013 | P3 | `services/context.py:416-428` | No TTL on cache write | Add explicit TTL | S |
| P-014 | P3 | `engine/memgraph_store.py:934-966` | 3 serial RTTs in upsert_agent | Combine MERGE | S |
| P-015 | P3 | `engine/memgraph_store.py:996-1019` | ON MATCH duplicates all fields | Use `SET n += $props` | S |

### Error Handling

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| E-001 | P1 | `engine/qdrant_store.py:404-421` | Race in `ensure_cluster_collection` - no lock | Add `asyncio.Lock` pattern | S |
| E-002 | P1 | `engine/qdrant_store.py:404-421` | No try/except - raw exceptions | Wrap with `QdrantOperationError` | S |
| E-003 | P1 | `engine/qdrant_store.py:511-525` | `search_clusters` unguarded | Add try/except | S |
| E-004 | P2 | `engine/qdrant_store.py:535-537` | `delete_cluster_collection` swallows all exceptions | Distinguish 404 from other errors | S |
| E-005 | P2 | `embeddings/litellm_embeddings.py:153` | `embed_single` crashes if results empty | Validate length | S |
| E-006 | P2 | `embeddings/litellm_embeddings.py:134-141` | No retry on rate limits | Add `num_retries=3` | S |
| E-007 | P2 | `embeddings/litellm_embeddings.py:135-137` | No timeout on embedding calls | Pass `request_timeout` | S |
| E-008 | P2 | `engine/synthesis.py:150-156` | No error handling around synthesis LLM call | Catch and raise `SynthesisError` | S |
| E-009 | P2 | `engine/synthesis.py:178-189` | Centroid embedding error leaves partial write | Wrap in try/except | S |
| E-010 | P3 | `engine/compaction.py:204-208` | Only catches ValueError | Broaden to Exception | S |
| E-011 | P3 | `engine/memgraph_store.py:1083-1084` | `ensure_indexes` swallows all exceptions | Log at warning | S |
| E-012 | P3 | `engine/memgraph_store.py:869,877,901` | No upper bound on export limit | Cap at MAX_EXPORT_LIMIT | S |
| E-013 | P3 | `engine/qdrant_store.py:188-190` | `upsert` inconsistent error type | Wrap in `QdrantOperationError` | S |
| E-014 | P3 | `embeddings/litellm_embeddings.py:138` | No length validation on embed response | Assert length match | S |

### AI/LLM

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| AI-001 | P1 | `custodian/proposal_worker.py:113` | Prompt injection - fact_contents unsanitized | Use `escape_for_prompt()` | S |
| AI-002 | P1 | `custodian/silo_synthesis.py:44-65` | Prompt injection - silo description unsanitized | Use `escape_for_prompt()` | S |
| AI-003 | P1 | `custodian/proposal_worker.py:104-117` | No timeout on proposal synthesis agent | Add `UsageLimits` + `asyncio.wait_for` | S |
| AI-004 | P1 | `custodian/silo_synthesis.py:125-131` | No timeout on silo synthesis agent | Add `UsageLimits` + `asyncio.wait_for` | S |
| AI-005 | P2 | `custodian/proposal_worker.py:139-146` | Unbounded fact list in synthesis prompt | Cap at 30 facts | S |
| AI-006 | P2 | `custodian/proposal_worker.py`, `silo_synthesis.py` | `with_llm_limit` not applied | Wrap agent.run calls | S |
| AI-007 | P2 | `llm/litellm_provider.py:82-90,124-132` | No retry on rate limits | Pass `num_retries=3` | S |
| AI-008 | P2 | `custodian/agents.py:32-35` | Prompt caching not enabled | Set cache_control headers | M |
| AI-009 | P3 | `custodian/proposal_worker.py:117` | LLM output stored unbounded | Truncate to 2000 chars | S |
| AI-010 | P3 | `llm/litellm_provider.py:52-53` | timeout=0 silently skipped | Change to `if timeout is not None` | S |

### Blast Radius / Architecture

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| B-001 | P1 | `engine/protocols.py` | 42 importers, only 2 test files | Add unit tests | M |
| B-002 | P1 | `utils/json.py` | 126 transitive reach, 1 test file | Add edge-case tests | M |
| B-003 | P1 | `custodian/proposal_worker.py` + `proposal_synthesis.yaml` | New, only 1 test | Add synthesis tests | M |
| B-004 | P2 | `mcp/tools/context_get.py` etc | Helper files named like tools | Rename to `_helpers/` or add note | S |

### Documentation

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| D-001 | P1 | `README.md:1` | Title says "Delta Prime" - rebranded to Engrammic | Change to `# Engrammic` | S |
| D-002 | P1 | `context/specs/mcp-tool-surface.md` | Describes 14 tools, implementation has 9 | Update to match | M |
| D-003 | P2 | `README.md` (structure) | Directory tree outdated | Update or remove | S |
| D-004 | P2 | `README.md` (auth) | Says WorkOS deferred - now API-key based | Update | S |
| D-005 | P2 | `mcp/tools/context_store.py:796` | Docstring says WorkingBelief (old name) | Change to WorkingHypothesis | S |
| D-006 | P3 | `CLAUDE.md` | `just docker-up/down` - actually separate targets | Minor fix | S |
| D-007 | P3 | `config/settings.py:788` | TODO: BEAR compression - no context | Add date/link or delete | S |
| D-008 | P3 | `auth/__init__.py:6` | TODO: WorkOS - indefinitely deferred | Add date or remove | S |
| D-009 | P3 | `CLAUDE.md` | `context_admin` param description unclear | Clarify action-specific params | S |
| D-010 | P3 | `custodian/metrics.py:70` | TODO(2026-Q3) dated reminder | No action until Q3 | S |

---

## Top 10 Priority Fixes (effort-weighted)

1. **[P0/S] S-001** `tombstone.py:44` - Cypher injection via edge_type
2. **[P0/M] L-001** `context_store.py` - Auto-promote on single assert violates spec
3. **[P0/M] L-002** `context_store.py` - context_reason bypasses Wisdom layer
4. **[P1/S] AI-001** `proposal_worker.py:113` - Prompt injection
5. **[P1/S] AI-002** `silo_synthesis.py:44-65` - Prompt injection
6. **[P1/S] P-001** `context_get.py` - N+1 (batch exists)
7. **[P1/S] AI-003/004** Synthesis agents - No timeout
8. **[P1/S] E-001/002/003** `qdrant_store.py` - Race + unguarded cluster ops
9. **[P1/S] D-001** `README.md` - Rebrand to Engrammic
10. **[P1/M] B-001** `engine/protocols.py` - Test coverage gap
