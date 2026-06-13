# EAG Agent Instructions

Brainstorm: basic instruction set for agents using EAG (Epistemic Augmented Generation) via the Engrammic MCP surface.

---

## Part 1: The Cognitive Model

### Why memory matters

Without persistent memory, every agent session starts from zero. The agent has no context of what happened before, what was decided, what was tried and failed. This is the "cross-session memory loss" problem.

But naive memory (store everything) creates noise. The goal isn't to remember everything - it's to remember *the right things* in *the right way*.

### The memory question: "Should I remember this?"

Before storing anything, ask:

1. **Will this matter later?** If it's only relevant to this exact moment, maybe don't store it.
2. **Is this new information?** If it's already known, don't duplicate.
3. **Who else might need this?** If it's just for you, consider ephemeral. If the team needs it, consider durable.
4. **How long will it stay true?** Facts about the world change. Observations decay. Choose decay class accordingly.

**Heuristic:** If you wouldn't tell a colleague about it tomorrow, don't store it to Memory. If you would, store it.

### The knowledge question: "Is this a fact?"

Knowledge layer is for claims you can back up. Before storing to Knowledge:

1. **Do I have evidence?** No evidence = no Knowledge storage. Use Memory instead.
2. **Is this verifiable?** Opinions and preferences are not facts.
3. **Could this be wrong?** If yes, use lower confidence. The system handles uncertainty.
4. **Does this contradict something we already know?** If so, that's valuable - store it anyway, the system will surface the contradiction.

**Heuristic:** If you'd need to cite a source to defend this claim, it belongs in Knowledge with that source as evidence.

### The wisdom question: "What do I believe?"

This is the hardest layer to use well. Wisdom is synthesized understanding - patterns you've noticed, positions you've formed, beliefs that emerged from multiple facts.

**When to form a belief:**

1. **You've seen the same pattern multiple times.** One data point is memory. Multiple corroborating points are the basis for belief.
2. **You've reasoned from facts to a conclusion.** The facts live in Knowledge. The conclusion (what you think it means) lives in Wisdom.
3. **You need to take a position.** Sometimes agents must commit to an interpretation. That's a belief.

**Belief formation is not:**
- Restating a single fact (that's just Knowledge)
- Guessing without evidence (that's speculation, store to Memory with low confidence)
- Declaring something true because you want it to be (beliefs need grounding)

**The belief test:** "Based on [these facts], I believe [this conclusion]." If you can't fill in [these facts], you don't have a belief - you have a hunch. Store hunches to Memory, not Wisdom.

### Commitment vs Belief

Wisdom holds both:
- **Beliefs** - things you think are true based on evidence
- **Commitments** - positions you've declared regardless of evidence

Commitments are different. A commitment says "this is our stance" - it might be a design decision, a policy, a value. Commitments don't need evidence, they need declaration.

Example:
- Belief: "Based on benchmarks, React 19 is faster than React 18" (grounded in facts)
- Commitment: "We will use React for all new frontend work" (a declared position)

Both live in Wisdom, but they're different cognitive acts.

### The reflection question: "Has my understanding changed?"

Meta-Memory exists because beliefs change. When you:
- Update a belief based on new evidence
- Notice a contradiction you hadn't seen before
- Correct a mistake
- Shift confidence in something

...record that to Meta. This creates the audit trail that lets you (or others) understand *why* the system believes what it believes.

**Heuristic:** If you're changing your mind, note it. If you're uncertain about something you were certain about, note it. The history of belief is as valuable as current belief.

---

## Part 2: The Four Layers

EAG organizes knowledge into four cognitive layers, each with different semantics:

| Layer | What lives here | Persistence | Core property |
|-------|-----------------|-------------|---------------|
| **Memory** | Raw observations, documents, events | Decays (7d to 5y) | Freshness-scored |
| **Knowledge** | Facts and claims with evidence | Indefinite, supersession | Evidence-backed |
| **Wisdom** | Beliefs, patterns, commitments | Indefinite | Synthesized from facts |
| **Intelligence** | Reasoning chains, working hypotheses | Session-only | Ephemeral |

Plus **Meta-Memory** (cross-cutting): provenance, reflections, audit trail. Never decays.

---

## Part 2.5: When to Level Up

### Memory -> Knowledge

**Trigger:** You have a claim with evidence.

```
# Instead of:
remember("The API uses OAuth2")

# Do:
learn("The API uses OAuth2", evidence=["file://src/auth/config.py:15"])
```

### Knowledge -> Wisdom

**Trigger:** You've stored 2+ related facts and see a pattern.

```
# After storing facts about API auth:
recall("API authentication")
# Response shows 3 facts about OAuth2 + PKCE

# Form the belief:
decide(
    decision="Our API authentication uses OAuth2 with PKCE for all client types",
    about=["fact-id-1", "fact-id-2", "fact-id-3"]
)
```

**Watch for hints:** Recall may return `hints.belief_candidate` suggesting this.

### Working Through Problems -> Intelligence

**Trigger:** Multi-step reasoning where you want to preserve the chain.

```
reason(
    steps=[
        {"step": 1, "reasoning": "User reports 500 errors on /api/users"},
        {"step": 2, "reasoning": "Logs show DB connection timeout"},
        {"step": 3, "reasoning": "Connection pool exhausted - max_connections=10"},
    ],
    conclusion="Need to increase DB connection pool size",
    evidence_used=["memory-id-logs", "fact-id-config"]
)
```

**Continue prior chains:** If recall returns `hints.chain_continuation`, you can extend it:

```
reason(
    steps=[{"step": 4, "reasoning": "Increased pool to 50, errors resolved"}],
    parent_chain_id="prior-chain-id"
)
```

### Tentative -> Committed

**Trigger:** Uncertain conclusion that may change.

```
# Form tentative belief:
hypothesize(
    hypothesis="The memory leak is in the event handler",
    about=["fact-id-heap-dump"]
)
# Returns: {belief_id: "hyp-123", session_id: "..."}

# Later, after confirming:
commit(belief_ids=["hyp-123"])
```

Hypotheses expire with the session. Commit before ending if you want them to persist.

---

## When to Write

### Memory: raw observations

Use when ingesting context that may become stale.

```
context_store(
  content: "User mentioned they prefer async communication",
  layer: "memory",
  decay_class: "standard"  # 90 days
)
```

**Decay classes:**
- `ephemeral` - 7 days (scratch, temp context)
- `standard` - 90 days (normal observations)
- `durable` - 540 days (important but not permanent)
- `permanent` - 5 years (critical reference)

### Knowledge: facts with evidence

Use when asserting something verifiable. Evidence is required.

```
context_store(
  content: "React 19 uses a compiler-based approach to reactivity",
  layer: "knowledge",
  evidence: ["https://react.dev/blog/2024/02/15/react-labs-feb-2024", "node:abc123"],
  source_type: "external",
  tags: ["react", "frontend", "architecture"]
)
```

**Evidence formats:**
- `node:<uuid>` - reference to existing node
- `https://...` - external URI (creates Document node automatically)

**Source types:** `document`, `user`, `external`, `agent`

### Wisdom: beliefs and patterns

Use when synthesizing understanding from multiple facts. Must reference the facts it's based on.

```
context_store(
  content: "Modern frontend frameworks are converging on compiler-first architectures",
  layer: "wisdom",
  about: ["fact-id-1", "fact-id-2", "fact-id-3"],
  reasoning: "React, Svelte, and Vue all moving toward compile-time optimization"
)
```

### Intelligence: reasoning chains

Use when capturing multi-step reasoning within a session. Not persisted across sessions.

```
context_store(
  content: "Conclusion: migrate to React 19 for performance gains",
  layer: "intelligence",
  steps: [
    {"step": 1, "reasoning": "Current bundle size is 2.1MB", "confidence": 0.95},
    {"step": 2, "reasoning": "React 19 compiler reduces re-renders by 40%", "confidence": 0.85},
    {"step": 3, "reasoning": "Migration cost is ~2 weeks", "confidence": 0.7}
  ]
)
```

### Meta-Memory: reflections

Use when noting changes in understanding or contradictions detected.

```
context_store(
  content: "Updated belief about caching strategy after seeing production metrics",
  layer: "meta",
  about: ["old-belief-id", "new-belief-id"],
  observation_type: "belief_change"
)
```

**Observation types:** `belief_change`, `confidence_shift`, `contradiction`, `uncertainty`, `correction`, `insight`

---

## When to Read

### Quick lookup: specific nodes

```
context_recall(
  node_ids: ["node-id-1", "node-id-2"],
  depth: 0
)
```

### Semantic search: find relevant content

```
context_recall(
  query: "authentication best practices",
  layers: ["knowledge", "wisdom"],
  top_k: 10
)
```

### Graph traversal: explore connections

```
context_recall(
  node_ids: ["starting-node"],
  depth: 2  # follow edges up to 2 hops
)
```

### Time travel: what did we believe then?

```
context_recall(
  node_ids: ["fact-id"],
  as_of: "2026-03-01T00:00:00Z"
)
```

### Layer-specific queries

| Need | Layers to query | Why |
|------|-----------------|-----|
| Recent context, events | `["memory"]` | Fresh, decaying content |
| Verified facts | `["knowledge"]` | Evidence-backed, supersession-aware |
| Team understanding | `["wisdom"]` | Synthesized beliefs and patterns |
| Current session work | `["intelligence"]` | Ephemeral reasoning |
| Audit trail | Use `include_reflections: true` | Meta-Memory observations |

---

## Linking Nodes

Create typed relationships between nodes:

```
context_link(
  from_id: "claim-about-react",
  to_id: "react-docs-node",
  relationship: "DERIVED_FROM"
)
```

### Key relationship types

**Provenance:**
- `DERIVED_FROM` - this came from that source
- `EXTRACTED_FROM` - extracted from document
- `SUPERSEDES` - this replaces that (newer understanding)
- `PROMOTED_FROM` - claim promoted to fact

**Semantic:**
- `SUPPORTS` - evidence supports claim
- `CONTRADICTS` - conflicts with
- `CORROBORATES` - same claim from different source
- `REFERENCES` - mentions or links to
- `CAUSES` / `PREVENTS` - causal relationships

---

## Decision Heuristics

### "Should I store this?"

1. Is it an observation or raw input? -> Memory
2. Is it a verifiable claim with sources? -> Knowledge (with evidence)
3. Is it a pattern or belief synthesized from facts? -> Wisdom
4. Is it reasoning I'm doing right now? -> Intelligence (or skip if trivial)
5. Am I noting a change in my understanding? -> Meta

### "What layer should I query?"

1. Need recent context or events? -> Memory
2. Need authoritative facts? -> Knowledge
3. Need team beliefs or patterns? -> Wisdom
4. Need to understand why we believe something? -> Meta (provenance)

### "Should I link these nodes?"

If there's a meaningful relationship (source, support, contradiction, causation), link them. The graph structure enables:
- Provenance tracing ("where did this fact come from?")
- Contradiction detection ("do we have conflicting facts?")
- Confidence propagation ("how well-supported is this belief?")

---

## Common Patterns

### Research and store

```
# 1. Store raw findings as memory
context_store(content: "...", layer: "memory", decay_class: "standard")

# 2. Extract facts with evidence
context_store(content: "...", layer: "knowledge", evidence: ["..."], tags: ["..."])

# 3. Synthesize into belief
context_store(content: "...", layer: "wisdom", about: ["fact-1", "fact-2"])
```

### Update understanding

```
# 1. Query existing belief
context_recall(query: "our position on X", layers: ["wisdom"])

# 2. Store new fact that changes things
new_fact = context_store(content: "...", layer: "knowledge", evidence: ["..."])

# 3. Create superseding belief
context_store(content: "updated belief", layer: "wisdom", about: [new_fact.node_id])

# 4. Link supersession
context_link(from_id: new_belief, to_id: old_belief, relationship: "SUPERSEDES")

# 5. Record the change
context_store(layer: "meta", about: [old_belief, new_belief], observation_type: "belief_change")
```

### Check for contradictions

```
# Query with contradiction detection
context_recall(
  query: "claims about X",
  layers: ["knowledge"],
  include_proposals: true  # see pending beliefs
)
# Review CONTRADICTS edges in results
```

---

---

## Part 3: Belief Formation and Evolution

### How beliefs form

Beliefs don't appear from nothing. They emerge through a process:

```
Observations (Memory)
    ↓ extraction + evidence
Claims (Knowledge)
    ↓ corroboration + promotion
Facts (Knowledge, promoted)
    ↓ synthesis across multiple facts
Beliefs (Wisdom)
```

Each transition requires something:
- Memory → Knowledge: requires evidence
- Claim → Fact: requires corroboration (multiple sources agreeing)
- Facts → Belief: requires synthesis (agent reasoning across facts)

### The corroboration threshold

A claim isn't automatically a fact. The system requires corroboration - multiple independent sources saying the same thing. Currently this threshold is 3+ evidence sources.

Why? Single sources can be wrong. Multiple independent sources agreeing is stronger signal.

As an agent, this means:
- Store claims when you have evidence, even if only one source
- The system will promote to Fact when corroboration threshold is met
- You can still query claims - they're just lower confidence than Facts

### Belief revision

Beliefs are not permanent. When new evidence arrives:

1. **Supporting evidence** - strengthens confidence, may add CORROBORATES edge
2. **Contradicting evidence** - creates tension, surfaces via CONTRADICTS edge
3. **Superseding evidence** - newer understanding replaces older via SUPERSEDES edge

The system doesn't delete old beliefs. It chains them via SUPERSEDES. This means you can always trace "what did we believe before?" Use `history(node_id)` to view the full evolution chain from oldest to newest.

### Working with uncertainty

Not everything is certain. EAG handles uncertainty through:

**Confidence scores (0.0 - 1.0):**
- Every node has a confidence
- Confidence propagates through edges
- Lower confidence = more tentative

**ProposedBelief workflow:**
- When synthesis produces low-confidence belief, it creates a ProposedBelief
- ProposedBelief requires explicit accept/reject
- This is a checkpoint for human or agent review

**Contradiction detection:**
- System surfaces when facts contradict each other
- Doesn't auto-resolve - flags for review
- This is valuable signal, not an error

### The forgetting curve

Memory layer content decays. This is intentional. Not everything should persist forever.

**Decay classes map to importance:**
- Ephemeral (7d): scratch work, temp context, things that will be stale tomorrow
- Standard (90d): normal observations, context that's relevant for a few months
- Durable (540d): important observations that should persist ~18 months
- Permanent (5y): critical reference material

**Choosing decay class:**
- Default to `standard` unless you have reason not to
- Use `ephemeral` for debugging, exploration, one-off queries
- Use `durable` for things referenced repeatedly
- Use `permanent` sparingly - only for foundational reference

### Belief lifecycle summary

```
1. OBSERVE   → Store to Memory (decays)
2. CLAIM     → Store to Knowledge with evidence
3. VERIFY    → System promotes Claim → Fact when corroborated
4. SYNTHESIZE → Form Belief linking multiple Facts
5. COMMIT    → Optionally declare Commitment
6. REVISE    → When new evidence arrives, supersede
7. REFLECT   → Record changes to Meta-Memory
```

---

## Anti-patterns

1. **Storing to Knowledge without evidence** - always provide sources
2. **Storing to Wisdom without linking to facts** - always use `about` param
3. **Expecting Intelligence layer across sessions** - it's ephemeral
4. **Ignoring supersession** - old facts aren't deleted, they're superseded
5. **Not using Meta for belief changes** - lose audit trail

---

## Confidence Guidelines

When setting `confidence` on stores:

| Confidence | Meaning | When to use |
|------------|---------|-------------|
| 0.95+ | Near certain | Multiple reliable sources, verified |
| 0.8-0.95 | Confident | Single reliable source, strong reasoning |
| 0.6-0.8 | Probable | Reasonable inference, some uncertainty |
| 0.4-0.6 | Uncertain | Plausible but unverified |
| <0.4 | Speculative | Weak evidence, tentative hypothesis |

---

## Summary

**Write:**
- Memory = raw input (decays)
- Knowledge = facts + evidence (persists)
- Wisdom = synthesized beliefs (links to facts)
- Intelligence = session reasoning (ephemeral)
- Meta = reflections on cognition (audit trail)

**Read:**
- Query the layer that matches your need
- Use depth > 0 for graph traversal
- Use as_of for time travel

**Link:**
- Provenance edges for sourcing
- Semantic edges for meaning
- SUPERSEDES for evolution
