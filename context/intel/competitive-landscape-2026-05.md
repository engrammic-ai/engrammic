# Competitive Landscape (May 2026)

## Market Segments

### 1. Agent Frameworks (not memory-focused)
Build agents, not memory.

| Player | Focus | Memory Approach | Engrammic Fit |
|--------|-------|-----------------|-----------------|
| [Factory.ai](https://factory.ai/) | Autonomous SWE (Droids) | Task-specific, not persistent | **Complementary** — Droids could use DP for cross-task learning |
| CrewAI | Multi-agent orchestration | Built-in short/long-term | **Integration target** — MCP native |
| LangGraph | Complex workflows | Graph state, vector DB | **Integration target** |
| AutoGen | Custom agents | Pluggable | **Integration target** |

### 2. Memory Frameworks (storage-focused)
Store and retrieve, limited cognition.

| Player | Approach | Strengths | Gaps (vs Engrammic) |
|--------|----------|-----------|----------------------|
| [Mem0](https://mem0.ai/) | 3-tier (user/session/agent) + hybrid store | Personalization, 21+ integrations | No belief formation, no confidence tracking |
| [Zep](https://www.getzep.com/) | Temporal knowledge graph | Time-bounded facts, 63.8% LongMemEval | Storage-focused, no active synthesis |
| [Letta](https://letta.com/) | OS-inspired tiered memory | Long-running agents, context management | No epistemology, no belief management |
| LangMem | LangChain-native | Easy integration | Limited to LangChain ecosystem |

### 3. Cognitive Memory (direct competitors)
Belief management, governance, epistemics.

| Player | Approach | Overlap with Engrammic |
|--------|----------|-------------------------|
| [Pith](https://pith.run/) | Cognitive governance, contradiction detection, confidence scoring | **HIGH** — direct competitor |
| [Cognee](https://cognee.ai/) | "Model your agent's world" — knowledge graphs | Medium — more modeling, less belief |
| YantrikDB | Cognitive memory, context, decision | Unknown — limited info |

## Deep Dive: Pith (Claimed Competitor)

**What they claim:**
- Contradiction detection
- Confidence-weighted context
- Cognitive governance
- MCP integration

**Reality check (May 2026):**
- Lightweight layer on knowledge graph
- Basic governance, no formal structure
- Marketing ahead of substance
- No epistemic model, no belief synthesis

**Threat level: LOW**

| Aspect | Pith | Engrammic |
|--------|------|-------------|
| Architecture | SQLite wrapper | Graph + Vector + Redis |
| Epistemology | None (marketing term) | **Formal EAG paradigm, 4 layers** |
| Belief formation | None | **T3/T7 synthesis** |
| Governance depth | Surface-level | **Custodian, R1/R2 rules, supersession** |
| System-initiated | No | **ProposedBelief flow** |
| Enterprise-ready | No | **Yes (multi-tenant, Dagster pipelines)** |

**Conclusion:** Pith has the positioning angle but not the depth. Not a real competitor yet.

## Market Gaps (Where Engrammic Wins)

From [State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026):

> "Autonomous agents lack principled governance for contradiction handling, knowledge filtering, and quality maintenance — leading to compounding trust degradation over time."

> "The agent must maintain not just facts but confidence levels, and update them correctly as new data arrives — something most current memory systems handle poorly or not at all."

| Gap | Who addresses it? |
|-----|-------------------|
| Confidence tracking | Pith (partial), **Engrammic** (full) |
| Contradiction detection | Zep (temporal), Pith, **Engrammic** |
| Belief synthesis | **Engrammic only** |
| System-initiated proposals | **Engrammic only** |
| Multi-agent shared beliefs | **Engrammic** (silo partitioning) |
| Time-travel queries | Zep (validity windows), **Engrammic** (as_of) |
| Enterprise multi-tenancy | **Engrammic** |

## Strategic Implications

### 1. Pith is the main threat
- Same cognitive governance angle
- Simpler (local SQLite vs our stack)
- Already shipping MCP integration
- Published defensive prior art (March 2026)

**Response:** Differentiate on:
- Enterprise scale (multi-tenant, not local-only)
- Epistemic depth (T3/T7, 4 layers, formal model)
- System-initiated belief synthesis (they don't seem to do this)

### 2. Memory frameworks are partners, not competitors
- Mem0, Zep, Letta solve storage
- We solve cognition on top of storage
- Potential: Engrammic as a layer above these

### 3. Agent frameworks are distribution channels
- Factory Droids, CrewAI, LangGraph don't have cognitive memory
- MCP is the integration layer
- Be the default memory MCP server for these frameworks

## Is Engrammic Useful?

**Yes, but positioning matters.**

| Positioning | Viability |
|-------------|-----------|
| "Better vector DB" | No — commoditized, many players |
| "Memory for agents" | Weak — Mem0/Zep/Letta own this |
| "Cognitive governance" | Contested — Pith is here |
| "Epistemic runtime + belief synthesis" | **Strong** — unique |
| "Enterprise cognitive memory" | **Strong** — Pith is local-only |

**The moat:** System-initiated belief formation from memory corpus. No one else proposes beliefs — they all wait for agents to manage their own knowledge.

## Recommended Actions

1. **Ship ProposedBelief flow** — this is the differentiator
2. **Enterprise positioning** — multi-tenant, not local SQLite
3. **Integration partnerships** — CrewAI, LangGraph, Factory
4. **Publish the EAG paradigm** — establish thought leadership on epistemic agents
5. **Watch Pith closely** — they're the closest competitor

## Sources

- [Factory.ai Series C](https://tech-insider.org/factory-ai-150-million-series-c-khosla-coding-droids-2026/)
- [State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Memory Framework Comparison](https://atlan.com/know/best-ai-agent-memory-frameworks-2026/)
- [Pith Cognitive Governance](https://pith.run/)
- [Pith Defensive Publication](https://www.tdcommons.org/dpubs_series/9660/)
- [Cognee](https://cognee.ai/)
