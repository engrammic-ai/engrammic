---
name: engrammic:eag-guide
description: Proactive memory behavior + layer selection for Engrammic MCP
---

# LeAP Cognitive Guide

Layered Epistemic Agent Protocol (LeAP) guide for Engrammic MCP.

## MANDATORY PROTOCOL

Before ANY store operation:

```
1. RECALL FIRST   — recall(query="<topic>") to check existing knowledge
2. DECIDE         — Does a node exist?
                    - Yes, update:      use update() or pass supersedes=<node_id>
                    - Yes, contradicts: store your claim, system detects contradiction
                    - No:               proceed to store
3. STORE          — Use the appropriate layer (see Decision Tree below)
```

Skipping step 1 creates duplicates. The Custodian catches them but explicit supersession is better.

---

## DECISION TREE

```
Do you have a citable source (file path, URL, doc reference)?
  -> learn(claim="...", evidence=["<uri>"])

Otherwise (raw observation, no source)?
  -> remember(content="...")

Is this a reflection on your own reasoning or mistakes?
  -> remember(content="...", memory_type="reflection", about=["<node_ids>"])
```

Wisdom-layer nodes (Belief) are system-synthesized from corroborated facts. Agents write to Memory and Knowledge only.

---

## TOOL SURFACE

| Tool | Layer | When to use |
|------|-------|-------------|
| `remember` | Memory | Raw observations, preferences, no evidence needed |
| `learn` | Knowledge | Claims with evidence (file://, https://) |
| `update` | Knowledge | Supersede existing claim with new content |
| `recall` | All | Search or fetch before storing or when context needed |
| `trace` | All | Understand provenance (why I believe this) |
| `forget` | All | Remove wrong/harmful nodes (not stale ones) |
| `tick` | - | Lightweight engagement check |
| `introspect` | - | Check volatility, gaps, contributions |
| `agents` | - | List agents in silo |
| `conflicts` | - | List contradictions |
| `dismiss_conflict` | - | Mark as not-a-real-conflict |
| `escalate_conflict` | - | Flag for human review |
| `resolve_conflict` | - | Pick winner, supersede loser |

---

## CHECKPOINTS TABLE

| Moment | Required Action |
|--------|-----------------|
| Before any store | `recall(query="<topic>")` |
| Starting work in a domain you've touched before | `recall` relevant background |
| Your understanding changed or you made a mistake | `remember(..., memory_type="reflection", about=[...])` |
| Found contradicting information | Store your claim with `learn`; system detects contradiction |
| Wrapping up a session | `recall` to check for anything worth storing |
| User corrects you | Store the correction immediately |

---

## QUICK REFERENCE

```
recall first, always — before any store
supersede, don't duplicate — use update() or pass supersedes=
remember = raw observation (no evidence needed)
learn = claim with evidence (evidence= required)
update = replace existing claim (query or target + new content)
forget = wrong/harmful nodes only, not stale ones
tick = check pending markers without full recall
introspect = check volatility, gaps, provenance, contributions
conflicts = list contradictions needing resolution
```

---

## RECALL TRIGGERS

Act on these automatically:
- User mentions a person, project, term, or concept: recall what you know
- User says "before", "last time", "we discussed", "remember": recall that context
- Starting work in a domain you've touched before: recall relevant background
- Topic overlaps with prior work but you're unsure of details: recall before assuming
- User asks "what do you know about X": recall then synthesize

**Threshold:** Only recall when the result would materially change your response.

**Using results:** Treat recalled context as knowledge you already have. Don't announce "I found in memory..." Just use it naturally.

---

## STORE TRIGGERS

Store when future sessions would benefit:
- User shares a preference, constraint, or standing decision
- You learn something non-obvious about the codebase/project
- User corrects you or clarifies intent
- A task reveals a pattern or insight
- You make a decision worth remembering the rationale for

Skip: current task steps, transient state, things obvious from code.

---

## ACTION TRIGGERS (Mandatory)

**After fixing a bug:**
```
learn(
  claim="<what was wrong, why, and how it was fixed>",
  evidence=["file://<path>#L<lines>"],
  source="agent",
  tags=["bug-fix", "<relevant-domain>"]
)
```

**After discovering a codebase pattern or gotcha:**
```
learn(
  claim="<the pattern/gotcha and why it matters>",
  evidence=["file://<path>"],
  source="agent",
  tags=["pattern", "<codebase-tag>"]
)
```

**After resolving a confusing error:**
Store the error message, root cause, and fix so future sessions can recall it.

**After user teaches you something project-specific:**
Store immediately so you don't need to be taught twice.

---

## LAYER SELECTION

**Raw observation, no evidence?**
Use Memory: `remember(content="...")`

**Claim with a citable source?**
Use Knowledge: `learn(claim="...", evidence=["file://...", "https://..."])`

**Uncertain about evidence?**
Store as Memory with a note. Upgrade to Knowledge when you find the source.

**Your understanding just changed?**
Use reflection: `remember(content="I was wrong about X because Y", memory_type="reflection", about=["<node_ids>"])`

---

## SUPERSESSION PATTERN

When updating existing knowledge:

```
1. recall("topic")
2. Found node abc123 with old content
3. update(content="new content", evidence=[...], target="abc123")
   — OR —
   learn(claim="new content", evidence=[...], supersedes="abc123")
```

Use `update()` when you want semantic search to find the target. Use `supersedes=` on `learn()` when you already have the node ID.

---

## CONFLICT HANDLING

The system detects contradictions via CONTRADICTS edges. When you encounter conflicts:

```
conflicts()                          # List unresolved contradictions
resolve_conflict(conflict_id, winner_id)  # Pick winner, supersede loser
dismiss_conflict(conflict_id, reason)     # Mark as not-a-real-conflict
escalate_conflict(conflict_id, message)   # Flag for human review
```

Don't let conflicts accumulate. Resolve or escalate proactively.

---

## METACOGNITIVE QUERIES

Use `introspect()` to understand epistemic health:

```
introspect(query_type="volatility")      # Topics with high churn
introspect(query_type="gaps")            # Frequently asked, never answered
introspect(query_type="provenance", node_id="...")  # Who contributed to this belief
introspect(query_type="contributions")   # Your contribution stats
```

---

## ENGAGEMENT MARKERS

The system surfaces markers requiring attention. Check via `tick()` or the `engagement` field in `recall()` responses.

**Two modes:**

| Mode | Behavior |
|------|----------|
| `soft` | Markers are advisory. Results still returned. |
| `hard` | Results withheld until you resolve markers. |

Hard mode activates after repeated touches without resolution.

---

## WHEN TO FORGET

Use `forget()` for nodes that:
- Are factually wrong (not just outdated — those get superseded)
- Were stored in error (wrong layer, duplicate, test data)
- User explicitly asks to remove
- Contain information that should not have been stored

**Don't forget** things just because they're old. Decay handles staleness naturally.

---

## QUALITY CHECKS

**Memory:** "Would I tell a colleague about this tomorrow?"
- Yes: store
- No: skip, it's noise

**Knowledge:** "Can I point to a specific source?"
- Yes: store with evidence
- No: use Memory instead

---

## ANTI-PATTERNS

**Storing:**
- Storing everything "just in case": creates noise
- Skipping evidence on claims: ungrounded facts pollute the graph
- Storing without recalling first: creates duplicates

**Recalling:**
- Waiting to be asked: be proactive
- Skipping recall because you're "fairly sure": false confidence propagates stale context

**Engagement:**
- Ignoring soft markers until they go hard: resolve proactively
- Letting conflicts accumulate: they degrade knowledge quality
