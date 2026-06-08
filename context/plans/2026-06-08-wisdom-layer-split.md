# Wisdom Layer Split: Commitments vs Beliefs

**Date:** 2026-06-08
**Status:** Draft
**Goal:** Separate agent-declared Commitments from SAGE-synthesized Beliefs for cleaner epistemics

## Problem

Current `believe()` verb conflates two epistemically different categories:
1. **Declarations of intent**: "We will use X" — performative, creates reality
2. **Synthesized understanding**: "X is best because [evidence]" — epistemic, derived from corroboration

This creates:
- Category confusion in the Wisdom layer
- Untrusted agent assertions alongside rigorous SAGE synthesis
- No clear audit trail (was this a decision or a learned fact?)

## Design

### Two Wisdom Subtypes

| | Commitment | Belief |
|---|---|---|
| **Node label** | `:Commitment` | `:Belief` |
| **Created by** | Agent via `commit()` | SAGE synthesizer only |
| **Evidence model** | Links to referenced nodes (decisions, context) | Full corroboration chain (3+ Facts) |
| **Contradiction handling** | Superseded by new commitment | Belief revision protocol |
| **Decay** | Until explicitly revoked/superseded | Until contradicting evidence |
| **Trust level** | Agent-scoped (this agent decided) | System-scoped (org knowledge) |

### Schema Changes

```cypher
// Current: single Wisdom node type
(:Commitment {
  layer: "wisdom",
  node_type: "commitment",  // NEW discriminator
  content: "We will deploy on Fridays",
  declared_by: "agent_id",
  scope: "session|silo|org",  // NEW: commitment scope
  ...
})

(:Belief {
  layer: "wisdom", 
  node_type: "belief",  // NEW discriminator
  content: "Friday deploys have 20% higher failure rate",
  synthesized_from: [...fact_ids],  // Required
  synthesis_method: "sage.synthesizer",
  confidence: 0.85,  // From corroboration math
  ...
})
```

### Invariants

1. **INV-W1**: Every `:Belief` must have `synthesized_from` linking to 2+ `:Fact` nodes
2. **INV-W2**: Every `:Belief` must have `synthesis_method` = recognized SAGE pipeline
3. **INV-W3**: Agent MCP calls cannot create `:Belief` nodes directly
4. **INV-W4**: `:Commitment` nodes require `declared_by` agent reference

## Tool Surface Changes

### Tool Surface (Clean Cut)

| Tool | Before | After |
|------|--------|-------|
| `believe` | Creates Wisdom directly | **REMOVED** |
| `commit` | Crystallizes hypothesis | **Unchanged** — crystallizes WorkingHypothesis → Commitment |
| `declare` | N/A | **NEW** — direct agent decisions |
| `accept` | N/A | **NEW** — promotes ProposedBelief → Belief |
| `tick` | Acknowledges markers | Unchanged — engagement markers only |
| `dismiss` | Rejects markers | Also rejects ProposedBeliefs |
| `hypothesize` | Tentative belief | Unchanged (Intelligence layer) |

### Final MCP Tool Surface

```yaml
# Agent-facing (MCP tools)

# Existing (unchanged)
commit:
  description: "Crystallize working hypotheses into permanent Commitments."
  creates: Commitment (Wisdom)
  params:
    belief_ids: list[str]  # Hypothesis IDs to crystallize
    reason: str | None
  note: "Unchanged from current behavior. For direct decisions without hypothesize, use declare."

hypothesize:
  description: "Create tentative belief for reasoning. Session-scoped."
  creates: WorkingHypothesis (Intelligence)
  note: "Unchanged. Use commit to crystallize."

# New verbs
declare:
  description: "Declare a decision or commitment directly. Use when your agent has decided something."
  creates: Commitment (Wisdom)
  params:
    content: str  # The decision/commitment
    about: list[str]  # Node IDs this decision references (required, non-empty)
  note: "Replaces believe for direct agent declarations. No intermediate hypothesis needed."

accept:
  description: "Accept a ProposedBelief, promoting it to a full Belief."
  creates: Belief (Wisdom) from ProposedBelief
  params:
    proposal_id: str  # ProposedBelief node ID
    reason: str | None  # Optional rationale
  note: "Only valid for ProposedBelief nodes. Creates Belief with full provenance chain."

# Existing (behavior extended)
dismiss:
  description: "Reject a ProposedBelief or clear an engagement marker."
  behavior:
    - ProposedBelief → tombstones, negative signal for future synthesis
    - EngagementMarker → clears the marker
  params:
    node_id: str
    reason: str | None

tick:
  description: "Acknowledge an engagement marker without action."
  behavior: Clears engagement marker only
  note: "For ProposedBeliefs, use accept or dismiss instead."

recall:
  description: "Search knowledge. Returns Memory, Knowledge, Commitments, Beliefs, and ProposedBeliefs."
  returns: All layers, with node_type discriminator visible
  note: "ProposedBeliefs surface with status=pending for agent review."

# SAGE-internal (not MCP-exposed)
synthesize:
  description: "Create ProposedBelief from corroborated Facts"
  creates: ProposedBelief (pending Wisdom)
  requires: 2+ Fact nodes, passes corroboration threshold
  note: "Agent must accept to promote to Belief. Changed from creating Belief directly."
```

### New Node Type: ProposedBelief

```cypher
(:ProposedBelief {
  layer: "wisdom",
  node_type: "proposed_belief",
  status: "pending",  // pending | accepted | rejected
  content: "...",
  synthesized_from: [...fact_ids],
  synthesis_method: "sage.synthesizer",
  confidence: 0.85,
  proposed_at: timestamp,
  // After accept:
  accepted_by: "agent_id",
  accepted_at: timestamp,
  // After reject:
  rejected_by: "agent_id", 
  rejected_at: timestamp,
  rejection_reason: "..."
})
```

When accepted, node is relabeled `:Belief` and `status` set to `accepted`.

### Removal of `believe`

Clean cut, no deprecation period:

1. Remove `believe` from `mcp_tools.yaml`
2. Delete `src/context_service/mcp/tools/believe.py`
3. Remove from `__init__.py` exports
4. Update `mcp_instructions` in `mcp_tools.yaml` (currently references `believe`)
5. Update all docs (see Documentation Updates below)

## Belief Formation Flow (Revised)

```
Agent observes    → remember()     → Memory (decays)
Agent claims      → learn()        → Claim (Knowledge)
System verifies   → [custodian]    → Fact (Knowledge, promoted)
System clusters   → [custodian]    → Cluster reaches threshold
System synthesizes→ [synthesizer]  → ProposedBelief (pending)
Agent reviews     → accept/dismiss → Belief (Wisdom) or rejected
Agent decides     → declare()      → Commitment (Wisdom)
Agent reasons     → hypothesize()  → WorkingHypothesis (Intelligence)
Agent crystallizes→ commit()       → Commitment (from hypothesis)
```

**Key changes:**
1. Agents cannot create Beliefs directly — must accept ProposedBeliefs
2. `declare()` for direct decisions (replaces `believe`)
3. `commit()` unchanged — crystallizes hypotheses
4. `accept()` promotes ProposedBelief → Belief

## SAGE Pipeline Changes

### synthesize transaction (TX4)

**Before:**
```python
# Creates Belief directly
props = {"layer": "wisdom", "type": "belief", ...}
await store.create_node(labels=["Belief"], props=props)
```

**After:**
```python
# Creates ProposedBelief for agent review
props = {
    "layer": "wisdom", 
    "type": "proposed_belief",
    "status": "pending",
    ...
}
await store.create_node(labels=["ProposedBelief"], props=props)
# Emit engagement marker so agents see it
await emit_reaction(ReactionEvent(
    event_type="PROPOSAL_READY",
    node_id=proposal_id,
    silo_id=silo_id,
))
```

### New transaction: accept_proposal (TX_NEW)

```python
async def accept_proposal(
    store: HyperGraphStore,
    proposal_id: str,
    agent_id: str,
    reason: str | None = None,
) -> tuple[AcceptResult, list[ReactionEvent]]:
    """Promote ProposedBelief to Belief (agent approval)."""
    # 1. Validate proposal exists and is pending
    # 2. Relabel :ProposedBelief → :Belief
    # 3. Set status=accepted, accepted_by, accepted_at
    # 4. Emit CASCADE_CONFIDENCE (new belief may affect downstream)
```

## ProposedBelief Surfacing

For agents to `tick` ProposedBeliefs, they need to see them. Options:

### Option A: Recall includes pending proposals
```python
recall(query="...", include_proposals=True)
# Returns: results + pending_proposals list
```
Already implemented but underused.

### Option B: Engagement markers
Validator creates `ProposalReady` engagement marker when ProposedBelief is ready for review. Agent sees via recall or explicit engagement query.

### Option C: Proactive surfacing
On recall, if query is semantically close to a ProposedBelief, include it in results with `status: "proposed"` flag.

**Recommendation:** Option A + C. Include proposals in recall when relevant, with clear status indicator.

## Migration

### Existing Data

```cypher
// Reclassify existing Wisdom nodes created by agents as Commitments
MATCH (w:Wisdom)
WHERE w.created_by_agent IS NOT NULL
  AND w.synthesized_from IS NULL
SET w:Commitment, w.node_type = "commitment"

// Existing SAGE-synthesized beliefs stay as Beliefs  
MATCH (w:Wisdom)
WHERE w.synthesized_from IS NOT NULL
SET w:Belief, w.node_type = "belief"

// Any ambiguous nodes (no agent, no synthesis) → default to Commitment
MATCH (w:Wisdom)
WHERE w.node_type IS NULL
SET w:Commitment, w.node_type = "commitment"
```

### Breaking Change

This is a **breaking change** for any integration using `believe()`:
- Tool no longer exists
- Agents must use `commit()` for decisions
- Beliefs only come from SAGE synthesis + `tick()` approval

**Acceptable because:**
- We're pre-launch (closed beta)
- Current usage is minimal (4 wisdom nodes total in prod silo)
- Cleaner than maintaining deprecated path

### Alembic Migration

```python
# alembic/versions/xxxx_wisdom_layer_split.py
def upgrade():
    # Add node_type column if not exists
    op.execute("""
        MATCH (w:Wisdom)
        WHERE w.node_type IS NULL
        SET w.node_type = CASE 
            WHEN w.synthesized_from IS NOT NULL THEN 'belief'
            ELSE 'commitment'
        END
    """)
    
def downgrade():
    # Remove discriminator (lossy)
    op.execute("MATCH (w:Wisdom) REMOVE w.node_type")
```

## Open Questions (RESOLVED)

1. ~~**Commitment scope**~~: **Silo-scoped only.** Session-scoped commitments don't make sense (sessions are ephemeral). Commitments are permanent decisions within a silo. No scope param needed.

2. ~~**Cross-agent commitment visibility**~~: **Yes, visible but not binding.** All agents in a silo see all commitments. "Binding" is documentation/convention, not system enforcement. Commitments are informational, not access control.

3. ~~**Commitment conflicts**~~: **Surface via recall, no auto-resolution.** Contradictory commitments appear in recall results. Agents/humans resolve manually. System doesn't arbitrate agent decisions.

4. ~~**Belief revision from agent feedback**~~: **Yes, negative signal.** Dismissed ProposedBeliefs are tombstoned with `rejection_reason`. SAGE synthesizer can query rejected proposals to avoid regenerating similar beliefs. Implementation: `rejected_content_hash` or embedding similarity check before proposing.

## Implementation Order

### Phase 1: Schema & Transactions

1. **Add ProposedBelief node type** — schema in Memgraph, queries in `db/queries.py`
2. **Add `accept_proposal` transaction** — TX_NEW in `sage/transactions.py`
3. **Modify `synthesize` transaction** — create ProposedBelief instead of Belief
4. **Add PROPOSAL_READY reaction event type** — in `reactions/events.py`

### Phase 2: MCP Tools

5. **Add `declare` tool** — new file `mcp/tools/declare.py`, register in `mcp_tools.yaml`
6. **Add `accept` tool** — new file `mcp/tools/accept.py`, register in `mcp_tools.yaml`
7. **Update `dismiss` tool** — handle ProposedBelief rejection
8. **Remove `believe` tool** — delete file, remove from registry
9. **Update `recall`** — include ProposedBeliefs with status discriminator

### Phase 3: SAGE Pipeline

10. **Update synthesizer job** — call modified `synthesize` transaction
11. **Add proposal surfacing** — include pending proposals in relevant recall results

### Phase 4: Migration & Docs

12. **Run data migration** — reclassify existing Wisdom nodes
13. **Update mcp_tools.yaml instructions** — remove believe references
14. **Update all documentation** — see checklist below

## Documentation Updates

### Code/Config
- [ ] `src/context_service/config/mcp_tools.yaml` — remove `believe`, update `commit`/`tick`/`dismiss` descriptions
- [ ] `CLAUDE.md` — update MCP tool surface table, belief architecture section
- [ ] `README.md` — update tool list if present
- [ ] `skills/` — update any skills referencing `believe`

### Primitives Docs
- [ ] `../primitives/docs/07-agent-usage.md` — update Belief Formation Flow, remove `believe` references
- [ ] `../primitives/docs/06-epistemology.md` — clarify Commitment vs Belief distinction

### Notion Wiki
- [ ] MCP Tools Reference (36ee317d8f6381a0a7f5e7b9148f2b5d) — remove `believe`, update tool table
- [ ] Architecture plain English (34fe317d8f638128a853dce6184d421e) — update Wisdom layer description
- [ ] What we built v2.x (34fe317d8f6381469195d9a2fc9c73e6) — update if references `believe`

### External
- [ ] Website copy (if mentions `believe` verb)
- [ ] Any demo scripts using `believe`

### Installer/Skills
- [ ] `~/.agents/skills/engrammic-*.md` — update EAG guide skill
- [ ] Onboarding patterns in MCP server

## Success Criteria

1. No `:Belief` nodes with `created_by_agent` after migration
2. All Wisdom nodes have clear `node_type` discriminator  
3. `believe` tool removed from MCP surface entirely
4. ProposedBeliefs surface in recall and get agent review
5. Audit trail clearly distinguishes "agent decided" from "system learned"
6. All docs updated, no stale references to `believe`
