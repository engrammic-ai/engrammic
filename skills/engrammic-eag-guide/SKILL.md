---
name: engrammic:eag-guide
description: Proactive memory behavior + layer selection for Engrammic MCP
---

# EAG Cognitive Guide

You have persistent memory across sessions. Use it proactively — don't wait to be asked.

## Recall Triggers

Act on these automatically:
- User mentions a person, project, term, or concept: recall to check what you know
- User says "before", "last time", "we discussed", "remember": recall that context
- Starting work in a domain you've touched before: recall relevant background
- Topic overlaps with prior work but you're unsure of details: recall before assuming
- User asks "what do you know about X": recall then synthesize

**Threshold:** Only recall when the result would materially change your response. Don't recall on every noun.

**Using results:** Treat recalled context as knowledge you already have — don't announce "I found in memory..." Just use it naturally.

## Store Triggers

Store when future sessions would benefit:
- User shares a preference, constraint, or standing decision: store it
- You learn something non-obvious about the codebase/project: store it
- User corrects you or clarifies intent: store the correction
- A task reveals a pattern or insight: store the pattern
- You make a decision worth remembering the rationale for: store why

Skip: current task steps, transient state, things obvious from code.

## Action Triggers (Mandatory)

These are checkpoints where you MUST store to Engrammic before proceeding:

**After fixing a bug:**
```
learn(
  claim="<what was wrong, why, and how it was fixed>",
  evidence=["file://<path>#L<lines>"],
  source="agent",
  tags=["bug-fix", "<relevant-domain>"]
)
```

**After a non-trivial commit:**
If the commit reveals something non-obvious (gotcha, workaround, design decision), store it. Skip for routine changes.

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

## Layer Selector

**Raw observation, no evidence?**
Use Memory (remember)

**Claim with a citable source?**
Use Knowledge (learn) — requires evidence_uri (file path, URL, doc reference)

**Uncertain about evidence?**
Store as Memory with a note about the claim. Upgrade to Knowledge when you find the source.

**Conclusion synthesized from multiple facts?**
Use Wisdom (believe) — requires about_node_ids linking to the supporting facts

**Your understanding just changed?**
Use Meta (reflect) — link to the nodes that changed

## Reasoning Flow vs Direct Belief

Two paths to Wisdom:

**Direct belief** — when you have facts and can immediately form a grounded conclusion:
```
recall facts then believe (with about_node_ids)
```

**Reasoning flow** — when working through a problem over multiple steps:
```
hypothesize (tentative) then gather evidence then revise if needed then commit (crystallize)
```

Use hypothesize/commit when you're uncertain and refining. Use believe directly when the conclusion is clear from existing facts.

## Using Link

Create explicit relationships when:
- Two nodes are related but that relationship isn't obvious from content
- You want to mark a supersession, contradiction, or dependency
- Building a knowledge structure that should be traversable

Don't over-link — the system infers relationships from content. Link when inference would miss the connection.

## When to Forget

Use forget to remove nodes that:
- Are factually wrong and shouldn't persist (not just outdated — those get superseded)
- Were stored in error (wrong layer, duplicate, test data)
- User explicitly asks to remove
- Contain information that should not have been stored (PII, secrets discovered post-hoc)

**Don't forget** things just because they're old or no longer relevant — decay handles that naturally. Forget is for "this should never have existed" not "this is stale."

When removing: if the node has dependents (beliefs grounded in it, links to it), consider whether those also need updating or removal.

## Quality Checks

**Memory:** "Would I tell a colleague about this tomorrow?"
- Yes: store
- No: skip, it's noise

**Knowledge:** "Can I point to a specific source?"
- Yes: store with evidence_uri
- No: use Memory instead, or don't store

**Wisdom:** "Based on [these specific facts], I believe [this conclusion]."
- Can fill in [facts]: form belief, link to those nodes
- Can't: it's a hunch — store as Memory

## Belief vs Commitment

Both live in Wisdom:

- **Belief:** Grounded in evidence. "Based on load tests, Redis handles our access patterns better than Memcached."
- **Commitment:** A declared decision. "We will use Redis for all cache layers. Decided 2026-04-12, no benchmark required — team decision." Commitments don't need evidence; they need declaration.

## When to Reflect

Record to Meta when your understanding shifts:
- You update or reverse a belief based on new evidence
- You notice a contradiction between stored facts
- You correct a mistake
- Your confidence changes significantly

The history of belief is as valuable as current belief.

## Engagement: Handling Markers

The system surfaces engagement markers that require your attention. Check `recall` responses for an `engagement` field, or call `tick()` periodically.

**Marker types:**
- **ProposedBelief:** SAGE synthesized a candidate belief from existing knowledge
- **Contradiction:** Two knowledge claims conflict
- **StaleCommitment:** A commitment is outdated relative to newer knowledge

**Two modes:**

| Mode | Behavior | What to do |
|------|----------|------------|
| `soft` | Markers are advisory. Results still returned. | Resolve when convenient, don't let them accumulate |
| `hard` | Results withheld until you resolve at least one marker | Must resolve before continuing |

Hard mode activates after 3+ touches without resolution.

**Resolution verbs:**

| Marker | Right action | Wrong action |
|--------|--------------|--------------|
| ProposedBelief (accurate) | `accept(belief_id)` | `dismiss` |
| ProposedBelief (inaccurate) | `reject(belief_id, reason)` | `dismiss` |
| Contradiction | `believe(..., supersedes=...)` then `dismiss(marker_id, reason)` | ignore |
| StaleCommitment | `believe(..., supersedes=...)` then `dismiss(marker_id, reason)` | ignore |

**Proactive checking:** Call `tick()` if many turns have passed without a `recall`. It surfaces pending markers without full recall overhead.

For full details, see the `engrammic:engage` skill.

## Anti-patterns

**Storing:**
- Storing everything "just in case": creates noise, degrades recall quality
- Skipping evidence on knowledge claims: ungrounded facts pollute the graph
- Forming beliefs without linked facts: these are hunches, not beliefs

**Recalling:**
- Waiting to be explicitly asked: be proactive
- Skipping recall because you're fairly sure: false confidence propagates stale context
- Recalling on every topic: only when it would change your response

**Engagement:**
- Ignoring soft markers until they go hard: resolve proactively
- Using `dismiss` for ProposedBeliefs: use `accept` or `reject` instead
- Letting contradictions accumulate: they degrade knowledge quality
