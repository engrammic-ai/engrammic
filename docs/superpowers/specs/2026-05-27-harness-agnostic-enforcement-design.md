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

### tick() Implementation (Hybrid)

Two-layer implementation balancing speed and intelligence:

**Layer 1: Rule-based (< 50ms)**
- Pending markers (contradictions, stale commitments)
- Stale hypotheses (open > N turns)
- Session storage gaps (nothing stored in > 10 turns)
- Open reasoning chains (started but not concluded)

**Layer 2: LLM-powered (when needed, ~100-200ms)**

Triggers when rule layer detects potential:
- 3+ Knowledge nodes with overlapping tags/content, no linking Wisdom node - prompt belief formation
- `recent_context` provided and graph has > 5 nodes on related topics - surface relevant context
- Session has > 3 turns of back-and-forth on same topic without reason() calls - prompt reasoning capture

Uses `gemini-3.1-flash-lite` for LLM layer (cheap, fast). LLM generates natural language nudges from structured trigger data.

```
tick() request
      |
      v
+------------------+
| Rule-based layer |  < 50ms
| (always runs)    |
+------------------+
      |
      | if potential detected
      v
+------------------+
| LLM layer        |  ~100-200ms
| (conditional)    |
| flash-lite       |
+------------------+
      |
      v
tick() response
```

### Model Migration

Migrate from deprecated gemini-2.5-* to gemini-3.1-*:

| Component | Current | New |
|-----------|---------|-----|
| tick() nudges | N/A (new) | gemini-3.1-flash-lite |
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

### Phase 1: tick() Enhancement
1. Add `session_id`, `recent_context` parameters to tick()
2. Implement rule-based nudge detection
3. Add LLM layer for complex nudge generation
4. Update tick() response schema with `context` and `nudges` fields

### Phase 2: Model Migration
1. Update settings.py defaults to gemini-3.1-*
2. Update identities.yaml model references
3. Test SAGE pipeline with new models
4. Update documentation

### Phase 3: Skill Updates
1. Update engrammic-onboarding skill with tick() discipline
2. Add tick() frequency guidance (every 3-5 turns)
3. Document nudge handling behavior
4. Test across harnesses (CC, Pi, direct MCP)

### Phase 4: Distribution Updates
1. Simplify installer (remove harness detection)
2. Update skill installation path to ~/.agents/skills/
3. Add `engrammic doctor` CLI command
4. Update documentation site

## Success Criteria

1. tick() returns useful nudges within performance budget (< 300ms p95)
2. Agents following skill discipline store/recall appropriately
3. Works identically across CC, Pi, pydantic-ai, custom agents
4. No per-harness code to maintain

## Open Questions

1. Should tick() support a `max_nudges` parameter to limit response size?
2. How aggressively should LLM layer trigger? (cost vs intelligence tradeoff)
3. Should session_id be auto-generated server-side if not provided?

## References

- Claude Code leak analysis (March 2026) - extraction subagent patterns
- Pi extension system - pre-turn hook architecture
- Current tick() implementation: `src/context_service/mcp/tools/engagement.py`
- SAGE pipeline: `context/architecture/sage-system.md`
