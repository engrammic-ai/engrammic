# Harness-Agnostic Memory Enforcement

> Design spec for enforcing memory discipline across any MCP-capable agent without harness-specific extensions.

## Problem

Engrammic needs to enforce memory behavior (proactive storage, validation, recall injection) across multiple harnesses (Claude Code, Pi, Codex, pydantic-ai, custom agents). Current options either require per-harness extensions (maintenance burden) or rely purely on agent compliance (weak enforcement).

## Goals

1. Enforce memory discipline without per-harness extensions
2. Work for any MCP-capable agent (harness or SDK)
3. Provide proactive guidance (not just reactive storage)
4. Support "Engrammic in your stack" customers building their own agents

## Non-Goals

- Building per-harness extensions (Pi, CC, Codex wrappers)
- Controlling harness internals or hooking into harness events
- Replacing existing MCP tools (remember, learn, believe, recall)

## Design

### Core Insight

Instead of harness-side extensions that inject context, use:
1. **Skill discipline** - onboarding skill trains agent to call tick() regularly
2. **Smart tick()** - server returns context, suggestions, and nudges

The skill becomes the "extension" - it's prompt instructions any MCP-aware agent can load.

### Architecture

```
+-------------------------------------------------------------------+
|                        Any Agent                                   |
|     (CC, Pi, Codex, pydantic-ai, custom - doesn't matter)         |
|                                                                    |
|  Loads: engrammic-onboarding skill                                |
|  Behavior: "Call tick() every 3-5 turns"                          |
|                                                                    |
+-------------------------------------------------------------------+
                               |
                               | MCP protocol (standard)
                               v
+-------------------------------------------------------------------+
|                    tick() - Smart Engagement                       |
|                                                                    |
|  Request:                                                          |
|  {                                                                 |
|    about_hint: ["auth", "oauth"],                                 |
|    session_id: "sess_abc123",                                     |
|    recent_context: "Comparing OAuth2 vs API keys"                 |
|  }                                                                 |
|                                                                    |
|  Response:                                                         |
|  {                                                                 |
|    "markers": [contradictions, stale beliefs, ...],               |
|    "context": ["Relevant: OAuth2 setup notes from May 15"],       |
|    "nudges": [                                                    |
|      {                                                            |
|        "type": "form_belief",                                     |
|        "prompt": "You've learned 3 things about OAuth...",        |
|        "suggested_tool": "believe",                               |
|        "about_nodes": ["node_a", "node_b", "node_c"]             |
|      }                                                            |
|    ]                                                              |
|  }                                                                 |
+-------------------------------------------------------------------+
```

### tick() Nudge Types

| Nudge Type | Trigger | Example Prompt |
|------------|---------|----------------|
| form_belief | 3+ related Knowledge nodes, no Wisdom | "You've learned X, Y, Z about auth. Form a belief?" |
| store_reasoning | Mid-brainstorm, no reason() calls | "You're reasoning through options. Capture with reason()?" |
| crystallize | Hypothesis open > N turns | "Hypothesis H has been stable. Ready to commit()?" |
| link_nodes | Two nodes seem related but unlinked | "Node A and B both mention OAuth. Link them?" |
| resolve_contradiction | New finding conflicts with existing | "This contradicts belief X. Reflect?" |
| checkpoint | Long session, nothing stored recently | "20 turns without storing. Checkpoint with remember()?" |

### tick() Implementation

Pure rule-based with templates. No LLM in tick() initially - add later only if agents need more natural phrasing.

**Performance target:** < 100ms p95

#### Write-Time Affinity (Critical)

Move expensive similarity checks to write time, not tick time:

```
learn/remember call:
  → Compute embedding
  → k-NN check (k=3) against existing nodes
  → If similarity > 0.85, store affinity edge
  → 300ms budget available at write time
```

tick() just queries pre-computed affinities (fast graph query).

#### tick() Flow

```
tick() request
      |
      v
+------------------+
| Check caches     |  (markers cached 30s, embeddings 60s)
+------------------+
      |
      v
+------------------+
| Rule checks      |  < 50ms total, 100ms hard timeout
| (parallel)       |
+------------------+
      |
      v
+------------------+
| Debounce filter  |  (skip if shown in last N ticks)
+------------------+
      |
      v
+------------------+
| Template nudges  |  (no LLM)
+------------------+
      |
      v
+------------------+
| Cap at 3 nudges  |  Priority: markers > stale > gaps > suggestions
+------------------+
      |
      v
tick() response (always non-empty: "context is current" if nothing)
```

#### Rule Checks

| Check | Query | Template |
|-------|-------|----------|
| Pending markers | Graph: Contradiction/StaleCommitment nodes | "You have N markers to address." |
| Stale hypotheses | Graph: Hypothesis where age > N turns | "Hypothesis X open for N turns. Commit or revise?" |
| Storage gap | Session state: last_store_turn | "Nothing stored in N turns. Consider checkpointing." |
| Related Knowledge | Graph: pre-computed affinity edges, no linking Wisdom | "3 related observations about X. Consider believe()." |
| Relevant context | Embedding search (cached) | "Relevant to your work: [node summaries]" |
| Open reasoning | Graph: ReasoningStep without conclusion | "Reasoning chain open. Conclude with reason()?" |

#### Reliability Features

**Timeouts:**
- Embedding search: 100ms hard timeout
- Graph queries: 50ms timeout each
- Total tick(): 150ms hard cap

**Caching:**
- Marker existence: 30s TTL
- Embedding search results: 60s TTL (keyed by recent_context hash)

**Debouncing:**
- Track `shown_nudges` in session state
- Don't repeat same nudge type within 3 ticks
- If agent ignores nudge 3x, suppress for session

**Fallbacks:**
- If any query times out, skip that check (don't block)
- Always return at least `{"status": "context is current"}`
- Log timeouts/failures for monitoring

#### Future: LLM Phrasing (Optional)

If agents complain nudges aren't actionable, add LLM phrasing layer:
- Rules still detect what to nudge
- LLM batches content-based nudges into natural language
- 500ms timeout, fall back to template if fails

Start without this. Add based on feedback.

### Model Migration

Migrate from deprecated gemini-2.5-* to gemini-3.1-*:

| Component | Current | New |
|-----------|---------|-----|
| tick() nudges | N/A | None (templates only, LLM future) |
| Custodian analysis | gemini-2.5-flash | gemini-3.1-flash-lite |
| Synthesizer beliefs | gemini-2.5-pro | gemini-3.1-pro |
| Summarization | gemini-2.5-flash | gemini-3.1-flash-lite |
| Evidence validation | gemini-2.5-flash | gemini-3.1-flash-lite |

Configuration changes:
```yaml
# settings.py / identities.yaml
flash_model: "google-vertex:gemini-3.1-flash-lite"
pro_model: "google-vertex:gemini-3.1-pro"
```

### Skill Updates

**engrammic-onboarding** skill structure:

```markdown
## Session Start
1. Call tick() to get initial context and markers
2. Incorporate any context into your awareness
3. Address any pending markers

## During Session (every 3-5 turns)
1. Call tick(recent_context="<what you're working on>")
2. Review nudges:
   - store_prompt: decide whether to remember/learn
   - form_belief: consider connecting related knowledge
   - capture_reasoning: use reason() if mid-brainstorm
3. Incorporate context into reasoning

## Before Ending Session
1. Call tick() final time
2. Store anything important with remember/learn
3. Crystallize any open hypotheses with commit()
```

### Distribution (Simplified)

No per-harness extensions means simpler distribution:

```
$ curl -sSf get.engrammic.ai | sh

Installing Engrammic MCP server... done
Skills installed to ~/.agents/skills/engrammic/

Configure your agent:
  Claude Code: Add to ~/.claude/settings.json mcpServers
  Pi: Add to ~/.pi/mcp.json
  pydantic-ai: See docs.engrammic.ai/sdk

Verify: engrammic doctor
```

**Installer responsibilities:**
1. Install MCP server (or configure cloud connection)
2. Install skills to cross-harness path (~/.agents/skills/)
3. Provide config snippets for common harnesses
4. Verify with `engrammic doctor`

### What This Eliminates

- Per-harness extensions (Pi, CC, Codex wrappers)
- Extension maintenance burden across harness updates
- Complex distribution (installer detecting harnesses, writing configs)
- Trigger timing debates (session start vs per-turn vs topic change)

### What Remains

- MCP server with storage enforcement (schema validation, evidence requirements)
- Smart tick() that surfaces context and nudges
- Skills that train agent behavior
- Works for any MCP-capable agent

## Implementation Tasks

### Phase 1: Write-Time Affinity
1. Add k-NN check (k=3, threshold=0.85) to learn/remember handlers
2. Store affinity edges in graph when similarity detected
3. Index affinity edges for fast lookup
4. Add latency instrumentation

### Phase 2: tick() Enhancement
1. Add `session_id`, `recent_context` parameters to tick()
2. Implement rule-based nudge detection (all checks)
3. Add caching layer (markers 30s, embeddings 60s)
4. Add debounce tracking in session state
5. Implement template responses for all nudge types
6. Cap nudges at 3, prioritize by type
7. Add timeout handling (100ms hard cap)
8. Ensure non-empty response always returned
9. Add metrics instrumentation

### Phase 3: Model Migration
1. Update settings.py defaults to gemini-3.1-*
2. Update identities.yaml model references
3. Test SAGE pipeline with new models
4. Update documentation

### Phase 4: Skill Updates
1. Update engrammic-onboarding skill with tick() discipline
2. Add tick() frequency guidance (every 3-5 turns)
3. Document nudge handling behavior
4. Test across harnesses (CC, Pi, direct MCP)

### Phase 5: Distribution Updates
1. Simplify installer (remove harness detection)
2. Update skill installation path to ~/.agents/skills/
3. Add `engrammic doctor` CLI command
4. Update documentation site

### Phase 6 (Future): LLM Phrasing
1. Add optional LLM layer for content-based nudges
2. Implement 500ms timeout with template fallback
3. Only pursue if agent feedback indicates need

## Success Criteria

1. tick() returns within performance budget (< 100ms p95)
2. Write-time affinity computation completes within 300ms p95
3. Agents following skill discipline store/recall appropriately
4. Works identically across CC, Pi, pydantic-ai, custom agents
5. No per-harness code to maintain
6. Nudge debouncing prevents repeated nagging

## Metrics to Instrument

- tick() latency (p50, p95, p99)
- Nudge counts by type per session
- Debounce hit rate (nudges suppressed)
- Cache hit rates (markers, embeddings)
- Timeout rates by check type
- Write-time affinity computation latency

## Open Questions

1. What's the right debounce window? (3 ticks proposed, may need tuning)
2. What similarity threshold for affinity edges? (0.85 proposed)
3. Should session_id be auto-generated server-side if not provided?
4. How many ignored nudges before session suppression? (3 proposed)

## References

- Claude Code leak analysis (March 2026) - extraction subagent patterns
- Pi extension system - pre-turn hook architecture
- Current tick() implementation: `src/context_service/mcp/tools/engagement.py`
- SAGE pipeline: `context/architecture/sage-system.md`
