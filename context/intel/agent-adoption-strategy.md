# Agent Adoption Strategy

Research from 2026-05-07. How likely are agents to adopt Delta Prime, and how do we position for it?

## Market Context

### MCP Adoption (as of 2026)

- **Full client coverage**: Claude (native), ChatGPT, Gemini API, Cursor, Windsurf, Zed, JetBrains, Vercel AI SDK, OpenAI Agents SDK
- **500+ public MCP servers** covering databases, file storage, web scraping, messaging, project management
- **78% of enterprise AI teams** have at least one MCP-backed agent in production
- **Integration time dropped**: 18 hours (custom function-calling) -> 4.2 hours (MCP)
- **Governance**: MCP donated to Agentic AI Foundation (Linux Foundation) by Anthropic, Block, OpenAI

### Agent Framework Landscape

| Framework | Memory Approach | MCP Support | Adoption |
|-----------|-----------------|-------------|----------|
| LangChain/LangGraph | Graph state, vector DB | Yes | Highest downloads |
| CrewAI | Built-in short/long-term | Native (v1.10+) | 45k+ stars |
| AutoGen | Custom memory stores | Yes | Growing |
| OpenAI Agents SDK | MCP-native | Native | New entrant |

**Key insight**: Memory is treated as "connect a vector DB" — no framework has epistemic memory (confidence, beliefs, contradictions) built-in.

## Delta Prime's Position

### Differentiation

| Capability | Vector DBs | Anthropic Dreaming | Delta Prime |
|------------|-----------|-------------------|-------------|
| Store/retrieve | Yes | Yes | Yes |
| Semantic search | Yes | Yes | Yes |
| Confidence tracking | No | No | **Yes** |
| Belief formation | No | Pattern extraction | **Epistemic model** |
| Contradiction detection | No | Unknown | **Yes** |
| Time-travel/provenance | No | No | **Yes** |
| Cross-session synthesis | Partial | Yes | **Yes** |

We're not competing with Pinecone/Weaviate (storage). We're competing with "no belief management at all" — the current default.

### The Adoption Challenge

**Problem**: Agents won't spontaneously use belief tools.

Evidence:
- Most agents use RAG (store embeddings, retrieve by similarity)
- No framework teaches "formulate beliefs, track confidence, crystallize commitments"
- Agent prompts don't include epistemic instructions
- Even sophisticated agents (Devin, Cursor) don't manage beliefs — they manage context windows

**Implication**: If we require agents to call `context_update_belief`, adoption stays low.

## Strategy: Analyst by Default

### The Shift

| Approach | Agent Cognitive Load | Adoption Potential |
|----------|---------------------|-------------------|
| Filing cabinet (Path A) | High — must learn belief tools | Low — only sophisticated builders |
| Analyst (Path B) | Low — just write memories | High — any agent can benefit |

### How It Works

1. **Low-friction entry**: Agent calls `context_remember(content)` — same as any memory tool
2. **System does the work**: Clustering, pattern detection, belief synthesis run async
3. **Proposals surface automatically**: `context_recall` returns `proposed_beliefs` alongside memories
4. **Simple accept/reject**: `context_accept_belief(id)` or ignore

Agent never needs to understand epistemology. System handles it.

### Mitigating Unwanted Beliefs Risk

**Risk**: System proposes beliefs agent doesn't agree with, pollutes context.

**Mitigations**:

1. **High threshold for proposal**
   - Require N >= 5 supporting memories before proposing
   - Require confidence >= 0.7
   - Never propose from single observation

2. **Soft surfacing, not injection**
   - Proposed beliefs are separate from confirmed beliefs
   - Agent sees them as "suggestions", not facts
   - Never auto-promote to WorkingBelief without explicit accept

3. **Rejection learning**
   - Track rejected proposals
   - Lower weight for similar future proposals
   - Pattern: "agent rejected beliefs about X" -> reduce X-related proposals

4. **Rate limiting**
   - Max 3 proposals per session
   - Cooldown after rejection (don't re-propose same pattern)

5. **Confidence decay on proposals**
   - Unaccepted proposals decay over time
   - Old unaccepted proposals auto-archive

6. **Opt-out at silo level**
   - `silo_config.auto_synthesis = false` disables system proposals
   - For users who want pure filing cabinet mode

### Configuration Defaults

| Setting | Service Default | OSS Default | Rationale |
|---------|-----------------|-------------|-----------|
| `auto_synthesis` | `true` | `true` | Same experience everywhere |
| `synthesis_threshold` | 5 memories | 5 memories | Conservative |
| `proposal_confidence_min` | 0.7 | 0.7 | High bar |
| `max_proposals_per_session` | 3 | 3 | Avoid spam |

**Decision**: Same defaults for service and OSS. Simplifies messaging, docs, and support. Users who want filing cabinet can opt out.

## Go-to-Market Implications

### Positioning

**Not**: "Memory for AI agents" (commodity, competes with vector DBs)
**Yes**: "Cognitive runtime — your agent thinks, we help it remember what it learned"

### Integration Points (priority order)

1. **Claude Code / Claude Desktop** — native MCP, Anthropic relationship
2. **OpenAI Agents SDK** — MCP support, large user base
3. **CrewAI** — native MCP, multi-agent sweet spot
4. **LangGraph** — complex workflows, need belief state

### Developer Experience

Minimal setup:
```python
# Agent just does this:
await mcp.call("context_remember", {"content": "User prefers dark mode"})

# Later, context_recall returns:
{
  "memories": [...],
  "proposed_beliefs": [
    {"id": "...", "content": "User has strong UI preferences", "confidence": 0.74}
  ]
}

# Agent accepts (optional):
await mcp.call("context_accept_belief", {"belief_id": "..."})
```

No epistemology PhD required.

## Competitive Moat

1. **Anthropic Dreaming** — consolidation, not belief formation. Complementary.
2. **Vector DBs** — storage, not cognition. Different layer.
3. **Framework memory** — session-scoped, no cross-session synthesis. We do both.

Our moat: epistemic model + system-initiated synthesis. No one else does beliefs.

## Sources

- [MCP Adoption Statistics 2026](https://www.digitalapplied.com/blog/mcp-adoption-statistics-2026-model-context-protocol)
- [CrewAI vs LangChain 2026](https://www.nxcode.io/resources/news/crewai-vs-langchain-ai-agent-framework-comparison-2026)
- [Best AI Agent Frameworks 2026](https://arsum.com/blog/posts/ai-agent-frameworks/)
- [MCP Wikipedia](https://en.wikipedia.org/wiki/Model_Context_Protocol)
- [A Year of MCP](https://www.pento.ai/blog/a-year-of-mcp-2025-review)
