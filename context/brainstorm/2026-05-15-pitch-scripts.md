# Pitch Scripts

Core pitch language for Engrammic. Workshopped 2026-05-15.

---

## The "We're building..." versions

**For developers/prospects (layer framing):**
> "We're building the knowledge layer for AI agents - memory that knows what to trust."

**For investors (infrastructure framing):**
> "We're building knowledge infrastructure for AI agents - memory that knows what to trust."

**With the paradigm:**
> "We're building the knowledge layer for AI agents - where observations decay, facts persist with evidence, and beliefs evolve when the world changes."

**With outcome:**
> "We're building the knowledge layer for AI agents - so they don't repeat work, don't serve stale answers, and can explain themselves."

**With human hook:**
> "We're building how agents learn like humans do - where not everything is remembered equally, facts stick, and patterns become beliefs."

---

## 50-second pitch (problem-first)

*[0-15 sec - the hook]*
"AI agents have a memory problem. They either forget everything between sessions - or they remember everything and can't tell what to trust. Both break in production."

*[15-35 sec - what you do]*
"Engrammic fixes this. We separate observations from facts from beliefs. Observations decay. Facts persist until contradicted. Beliefs evolve with evidence. Everything cites its source."

*[35-50 sec - why it matters]*
"Result: agents that don't repeat work, don't serve stale answers, and can explain themselves. MCP-native, drops into any agent stack."

---

## 50-second pitch (human-analogy)

*[0-15 sec - the hook]*
"Think about how you learn. You don't remember every conversation - but important facts stick, and over time you form beliefs from patterns. AI agents can't do this today."

*[15-35 sec - what you do]*
"Engrammic gives agents that learning architecture. Observations fade. Facts persist with evidence. Beliefs form from patterns and update when the world changes."

*[35-50 sec - why it matters]*
"It's how you build agents that actually get smarter over time - not just louder. We're the knowledge layer that sits under your agents."

---

## One-liner candidates

- "Knowledge layer for AI agents - memory that knows what to trust."
- "Agents that know what to trust."
- "Memory your agents can cite."
- "Where observations become knowledge."

---

## Outcome pitch (for buyers)

> "Agents that don't repeat work, don't serve stale answers, and can explain themselves."

---

## Developer pitch

> "You're building custom knowledge infrastructure because RAG isn't enough. We already built it. Install Engrammic, get memory that decays, facts that cite sources, and beliefs that update when evidence changes."

---

## Technical pitch (for technical investors)

> "RAG treats all information the same - a Slack message, a verified fact, a pattern from 100 observations all go in one bucket. That's the core problem. Information has structure: observations should decay, facts should persist until contradicted, conclusions should update when evidence changes. Current systems don't handle this. We do."

---

## Audience framing

| Audience | Lead with | Key term |
|----------|-----------|----------|
| Investors | Infrastructure, paradigm, defensibility | "knowledge infrastructure" |
| Developers | Easy adoption, plugs in, don't build it yourself | "knowledge layer" |
| Prospects | Outcomes (don't repeat work, explain themselves) | "knowledge layer" |
| Technical founders | The category error, why RAG breaks | either works |

---

## Core value (refined)

**The four questions current systems can't answer:**
- "How confident are you in this?"
- "Where did this come from?"
- "Is this still true?"
- "Did we already figure this out?"

EAG answers all four. That's the product.

**Concrete framing:**
> "AI that tracks confidence, provenance, and staleness - so it doesn't repeat work, doesn't serve outdated answers, and can explain itself."

---

## Fundraising structure (Antler pre-seed)

**Horizontal hook (opener):**
> "We're building the knowledge layer for AI systems - memory that knows what to trust.
> 
> Every team building serious AI hits the same wall: RAG retrieves but can't tell you what's true, what's stale, or where it came from. We fix that.
> 
> We're already working with teams in construction, sales, and enterprise - different domains, same problem."

**Vertical depth (follow-up when asked):**
- Construction (Complink): high-stakes procurement, audit trails, cross-project learning
- Sales (Knowzilla): cross-rep knowledge, real-time context, don't serve stale info
- Enterprise (SmartStorify): self-hosted, org-level silos, governance

Multiple verticals = proof of horizontal pull, not unfocused.

---

## ICP pattern

Not "agent memory for chatbots." 

**AI systems where being wrong is expensive** - which manifests as:
- Don't waste time (repeat research)
- Don't look stupid (wrong info to customers)
- Get smarter (learn, don't just accumulate)
- Defend decisions (explain "why did you say that?")
- Compliance (audit trail - one use case, not the whole story)

---

## Vertical Deep-Dives

### Legal (strongest fit)

**Why legal is the strongest vertical:**
Legal work is inherently epistemic. Lawyers form beliefs based on evidence, must cite sources, and update positions when precedent changes. This maps directly to EAG's architecture.

**The pain:**
- Legal AI tools retrieve documents but can't explain reasoning
- Precedent builds on precedent - you need belief formation, not just retrieval
- Laws get overturned, rulings supersede prior rulings - knowledge must evolve
- Matters run months/years - context must persist and stay current
- Everything must be citable - "where did this come from?" is constant

**EAG mapping:**

| Legal need | EAG capability |
|------------|----------------|
| Case law builds on prior cases | Wisdom layer - beliefs from facts |
| Must cite sources | Provenance on every node |
| Rulings get overturned | SUPERSEDES edges, time-travel |
| Multi-attorney matters | Org-level silos, shared knowledge |
| "Why did we conclude X?" | Reasoning chains, belief trace |

**The pitch to legal AI platforms (Legora, Harvey, etc.):**
> "Your agents do legal research. But legal reasoning isn't retrieval - it's forming positions based on evidence. Engrammic gives your agents the ability to form beliefs, cite their sources, and update their positions when the law changes. It's the difference between a search engine and a lawyer."

**Example scenario:**
Attorney A researches employment law for Client X in January. The agent stores facts about relevant precedents. In March, a new ruling supersedes one of those precedents. The agent's beliefs update automatically, and when Attorney B picks up the matter in April, they get current knowledge with full provenance of what changed and when.

---

### AI Alignment (differentiated positioning)

**Two distinct buyers:**

**1. Frontier model developers (Anthropic, OpenAI, DeepMind)**
- Pain: tracking how model reasoning evolves across training, detecting belief drift
- Need: audit trail of what the model "believed" at each checkpoint
- EAG fit: Meta-Memory was literally built for this - tracks when understanding changes and why

**2. Enterprise teams running long-horizon agents**
- Pain: agent started doing X, now doing Y - when did it drift? Why?
- Need: detect reasoning drift before it causes problems
- EAG fit: time-travel + provenance shows exactly when beliefs changed and what evidence drove the shift

**The pitch:**
> "Your agents form beliefs. Do you know when those beliefs change - and why? Engrammic gives you the audit trail: what the agent believed, when it changed its mind, and what evidence drove the shift. It's alignment infrastructure."

**Why this is differentiated:**
- Nobody else is positioning for alignment
- Meta-memory is unique - competitors don't track belief evolution
- High-value buyers (frontier labs have money, enterprise cares about governance)
- Technical moat - this requires the architecture, not just features

**EAG capabilities for alignment:**

| Alignment need | EAG capability |
|----------------|----------------|
| "What did the agent believe on March 15?" | Time-travel queries (as_of) |
| "When did it change its mind?" | Meta-Memory observation_type: belief_change |
| "Why did it conclude X?" | Reasoning chain provenance |
| "Is this belief well-founded?" | Confidence scores + evidence links |
| "Do agents disagree?" | Contradiction detection across silos |

**Example scenario (enterprise):**
A customer support agent has been running for 6 months. Suddenly CSAT drops. With EAG, you can query: "What beliefs changed in the last 30 days?" and trace back to see that a new knowledge ingestion created a fact that superseded a prior one - and that fact was wrong. You pinpoint the drift, fix the source, and beliefs cascade correctly.

---

### Construction (Complink)

**The pain:**
- Procurement decisions need audit trails
- Knowledge from one project should inform the next
- Documents, specs, vendor info scattered across systems
- Mistakes are expensive (80% of company spend is procurement)

**EAG mapping:**

| Construction need | EAG capability |
|-------------------|----------------|
| "Why did we choose this vendor?" | Provenance + reasoning chains |
| "What did we learn from the Oslo project?" | Cross-silo knowledge (project -> company level) |
| "Is this spec still current?" | Supersession, time-travel |
| "Flag conflicts early" | Contradiction detection |

**The pitch:**
> "Your procurement AI pulls from specs, drawings, and vendor docs. But it can't tell you what it learned from past projects - or why it recommended Vendor A over Vendor B. Engrammic gives your AI institutional memory that compounds across projects."

---

### Sales (Knowzilla)

**The pain:**
- Reps need account history across conversations
- What one rep learns should help other reps
- Competitive intel goes stale
- "Why did we lose that deal?" - no reasoning trail

**EAG mapping:**

| Sales need | EAG capability |
|------------|----------------|
| Cross-rep knowledge sharing | Org-level silos |
| "What works against Competitor X?" | Belief synthesis from win/loss patterns |
| Stale competitive intel | Decay classes, supersession |
| Account context over time | Memory layer with appropriate decay |

**The pitch:**
> "Your sales agents pull from CRM, Slack, and call transcripts. But the patterns - what works, what doesn't, why deals close or die - stay locked in individual conversations. Engrammic turns your agents' observations into shared knowledge your whole team can use."

---

## Use Case Scenarios (Partner Perspective)

### Legora (Legal AI Platform)

**Their product:** aOS - agentic operating system for legal teams. Research, drafting, document review. $5.6B valuation, 100+ ARR.

**Problem Legora faces building this:**
Their agents retrieve case law, but legal reasoning isn't retrieval - it's forming positions. When a user asks "What's our exposure on this employment claim?", Legora's agent needs to synthesize across precedents, form a conclusion, and cite its reasoning. RAG can't do this.

**Pain for Legora (platform builder):**
- Building custom knowledge infra to handle precedent chains and citations
- When rulings get overturned, cached knowledge becomes liability (malpractice risk for their customers)
- Multi-attorney matters need shared context - their current architecture is per-user
- Enterprise law firms demand explainability: "Why did your AI conclude X?"
- Competitive pressure from Harvey - differentiation requires smarter reasoning, not just better retrieval

**How Engrammic solves this for Legora:**
- Drop-in knowledge layer via MCP - their agents call us instead of building custom
- SUPERSEDES edges: when precedent changes, downstream beliefs update automatically
- Org-level silos: matter knowledge shared across attorneys, firm knowledge persists
- Full provenance: every conclusion traces back to specific case citations
- Time-travel: "What did we believe about this issue in January?" for audit compliance

**Value prop:** "Ship legal reasoning, not just legal search. We handle the knowledge architecture so you can focus on the legal domain."

---

### Complink (Construction Procurement)

**Their product:** AI platform automating construction procurement - connects specs, drawings, BIM models, vendor docs.

**Problem Complink faces building this:**
Their AI surfaces relevant data for procurement decisions, but can't learn across projects. Every new project starts cold. Patterns from past projects (vendor reliability, spec conflicts, pricing trends) don't compound.

**Pain for Complink (platform builder):**
- "95% of construction data not efficiently used" - their own pitch, their own problem
- Building custom ETL for every data source (Slack, ERPs, BIM) without knowledge synthesis
- GraphRAG scaling issues as document corpus grows
- Customers ask "why did your AI recommend Vendor A?" - no audit trail
- Enterprise customers require decision provenance for compliance

**How Engrammic solves this for Complink:**
- Project silos + company silo: knowledge compounds across projects automatically
- Facts about vendors, specs, pricing persist with evidence
- Cross-project queries: "What did we learn about steel suppliers on the Oslo project?"
- Contradiction detection: flag spec conflicts before they become change orders
- Audit trail for every procurement recommendation

**Value prop:** "Your AI learns from every project. We're the institutional memory that compounds."

---

### Knowzilla (Sales Execution)

**Their product:** Revenue execution layer for sales reps - live guidance, playbook recommendations, automated CRM capture. Multi-agent under the hood.

**Problem Knowzilla faces building this:**
Their agents pull from Slack, ERPs, call transcripts. But each rep's agent learns in isolation. When Rep A discovers "Competitor X dropped price 20%", Rep B's agent doesn't know. Patterns stay siloed.

**Pain for Knowzilla (platform builder):**
- Multi-agent coordination is hard - they're running separate agents per rep, no shared state
- LLM costs scale linearly with reps (each agent re-processes same competitive intel)
- "What works against Competitor X?" requires manual aggregation, not automated synthesis
- Account context needs to persist across rep handoffs (35% annual rep turnover)
- Customers ask "why did we lose that deal?" - no reasoning trail

**How Engrammic solves this for Knowzilla:**
- Org-level knowledge: what one rep's agent learns, all reps' agents can access
- Belief synthesis: patterns crystallize from observations ("Enterprise deals close faster with ROI lead")
- Decay classes: stale competitive intel fades, validated facts persist
- Cost efficiency: knowledge computed once, shared across all agents
- Win/loss reasoning chains: trace deal outcomes to contributing factors

**Value prop:** "Your agents share what they learn. One rep's insight becomes everyone's advantage."

---

### Frontier Labs (Anthropic, OpenAI, DeepMind)

**Their challenge:** Training models across many runs with evolving reasoning capabilities. Need to track what the model "believes" at each checkpoint.

**Problem labs face:**
Alignment evaluations are point-in-time snapshots. When model behavior changes between versions, there's no structured way to trace reasoning evolution or detect capability drift.

**Pain for labs:**
- "The model used to get this right" - but when did it change? No audit trail.
- Billions spent on training with limited visibility into reasoning evolution
- RLHF changes model beliefs - but which beliefs, and how?
- Alignment research requires tracking belief formation over time
- Regulatory pressure for model explainability increasing

**How Engrammic solves this for labs:**
- Store model beliefs/reasoning patterns per training checkpoint
- Track belief evolution across training runs
- Detect reasoning drift: "Confidence in X dropped after run 47"
- Compare belief structures across model versions
- Full audit trail: what did the model believe, when did it change, why?

**Value prop:** "Alignment infrastructure. Track what your models believe and how that evolves."

---

### Enterprise Agent Teams (SmartStorify, etc.)

**Their challenge:** Running long-horizon agents in production. Agents work for months, then behavior drifts. Hard to diagnose.

**Problem enterprises face:**
They deploy agents that run continuously. Over time, CSAT drops, conversion drops, error rates climb. No way to know what changed or when.

**Pain for enterprise teams:**
- "Why is the agent doing X now when it used to do Y?" - unanswerable
- Mean time to diagnose: days to weeks of manual log archaeology
- Compliance requires explainability - "the AI did it" doesn't fly
- Self-hosting requirements for data sovereignty
- 65% of enterprise AI failures from context drift, not model limitations

**How Engrammic solves this:**
- Query: "What beliefs changed in the last 30 days?"
- Trace behavior → belief → fact → evidence
- Detect bad facts that cascaded into bad beliefs
- Self-hosted option (open-core)
- Audit log for every belief formation and revision

**Value prop:** "Know when your agents drift - and why. Fix at source, not symptoms."

---

## Vision (the big picture)

### What we're really building

We're building **knowledge infrastructure for AI agents** - structured storage where information persists and evolves according to its type.

Current AI agents don't track what's true vs what's stale. They retrieve context but can't tell you where it came from or how confident to be. They're stateless, or worse, accumulate noise without structure.

**Our approach:** Separate information by how it should persist. Observations decay. Facts stick with citations. Conclusions update when evidence changes.

### What EAG actually is

EAG (Epistemic Augmented Generation) structures knowledge into layers with different persistence rules:

| Layer | What it stores | How it persists |
|-------|---------------|-----------------|
| **Memory** | Observations, events | Decays over time (7d to 18mo) |
| **Knowledge** | Facts with evidence | Persists until contradicted |
| **Wisdom** | Conclusions from facts | Updates when underlying facts change |
| **Intelligence** | Current reasoning | Session-only, ephemeral |
| **Meta-Memory** | When understanding changed | Full audit trail |

This is how you build AI that tracks what it's confident about, where each fact came from, and when information went stale.

### The pitch (Nordic-direct version)

> "We're building knowledge infrastructure for AI agents. Three pilots in construction, sales, and enterprise are using it. The core problem: AI agents either forget everything or can't tell what's true. We solve this with structured persistence - observations decay, facts stick with evidence, conclusions update when evidence changes. Sub-250ms retrieval, MCP-native, drops into existing stacks."

### Framing by audience

| Audience | Lead with |
|----------|-----------|
| Technical investors | "Structured knowledge persistence - observations decay, facts cite sources, conclusions update" |
| Pragmatic buyers | "AI that tracks confidence, provenance, and staleness" |
| Developers | "Knowledge infrastructure so you don't build it yourself" |

Same architecture, different emphasis.

---

## SF Version (for American VCs)

Keep this version for Sequoia, a16z, etc. American VCs respond to vision and category creation.

**Mission (SF):**
> "To author the conditions the next minds will rise from."

**Vision pitch (SF):**
> "We're not building better memory. We're building the cognitive architecture for machine understanding. Current AI agents don't *know* anything - they retrieve. They pattern-match. But they don't form beliefs, weigh evidence, or update their understanding when the world changes. We're building the substrate that makes true machine cognition possible."

**Category-creation language (SF):**
> "RAG was retrieval. EAG is epistemology. We're not competing in the memory category - we're creating the comprehension category."

**Why this works in SF:**
- American VCs fund category creators, not fast followers
- "Cognitive substrate" signals ambition
- Vision-first, metrics-second
- Comparisons to foundational shifts (not incremental improvements)

**Use for:** Sequoia, a16z, Benchmark, Founders Fund, Khosla, Index (US office)

---

## USP / UVP (practical positioning)

### Unique Value Proposition (what value we deliver)

**Concrete version:**
> "AI that tracks what it's confident about, where each fact came from, and when information went stale."

**Outcome version:**
> "Agents that don't repeat work, don't serve stale answers, and can explain themselves."

**Technical version:**
> "Structured knowledge storage where observations decay, facts persist with citations, and conclusions update when evidence changes."

### Unique Selling Proposition (why buy us vs alternatives)

**The difference:**
Memory products store and retrieve. We structure how information persists and evolves.

Every competitor treats all information the same - dump it in a vector DB, retrieve by similarity. Engrammic separates information by *how it should persist*:

| Information type | What should happen | What competitors do | What we do |
|------------------|-------------------|---------------------|------------|
| Casual observation | Decay over time | Persists forever or deleted manually | Memory layer with decay classes |
| Verified fact | Persist until contradicted | Same as observations | Knowledge layer with evidence links |
| Synthesized pattern | Update when evidence shifts | Doesn't exist | Wisdom layer with belief formation |
| Reasoning trace | Ephemeral, per-session | Sometimes logged | Intelligence layer, provenance-linked |
| Belief changes | Track for audit | Not tracked | Meta-Memory with full history |

**Three structural advantages:**

1. **Org-level first-class** - Silos + scope-gated retrieval as core data model, not workspace bolted on later. Competitors started single-user/single-agent; we started team-first.

2. **Curated findings, not raw chunks** - Retrieval unit is cited, evidence-linked knowledge, not raw memory dumps. Requires re-architecting the write path to copy.

3. **Belief evolution, not just storage** - We track *when* understanding changes and *why*. Time-travel, supersession, contradiction detection. Current systems don't do this.

### Why this matters to buyers

| Buyer type | Why they care |
|------------|---------------|
| Platform builders (Legora, Complink) | "Don't build knowledge infra - use ours" |
| Enterprise | "Explain yourself" + "why did behavior change?" |
| AI labs | "Track belief evolution across training" |
| Regulated industries | Audit trail is architectural, not bolted on |

---

## Competitive Objection Handling

### vs Mem0 ("Why not just use Mem0?")

**Their pitch:** Memory layer for personalized AI. $24M raised, 41K GitHub stars, AWS SDK integration.

**Where they win:**
- SDK breadth, enterprise compliance shipped
- Brand recognition, funding
- 80% prompt token reduction via compression

**Where we win:**
- Org-level architecture (their workspaces are bolt-ons)
- Graph at all tiers (theirs paywalled at $249/mo)
- Curated findings vs raw memory chunks
- Belief evolution + time-travel (they don't have this)

**Objection responses:**

*"Mem0 has more funding/traction"*
> "Mem0 makes one agent feel personalized. The moment you have two agents sharing context, or a team around them, their architecture breaks. They started single-user; we started org-first."

*"Mem0 has enterprise compliance"*
> "So do we. The difference is what you're storing - raw memories vs cited, evidence-linked knowledge. Compliance on garbage is still garbage."

*"Mem0 has graph memory"*
> "Paywalled at $249/mo. Ours is core architecture at every tier. And our graph tracks belief evolution - theirs is just relationships."

---

### vs Zep/Graphiti ("They have temporal graphs too")

**Their pitch:** Temporal knowledge graph, <200ms retrieval, academic paper (arxiv:2501.13956).

**Where they win:**
- Voice AI latency optimization
- Academic credibility
- Business data ingestion pipelines

**Where we win:**
- Multi-agent org-level sharing (they're single-agent enrichment)
- Belief synthesis, not just facts + relationships
- MCP-native (they're SDK-shaped)

**Objection responses:**

*"Zep has temporal/bi-temporal too"*
> "Temporal storage is table stakes now. The question is what you do with it. Zep stores facts with timestamps. We form beliefs from facts and track when those beliefs change. Different architecture."

*"Zep has better benchmarks"*
> "On single-agent recall. Our metric is cross-agent knowledge retention - does Agent B know what Agent A figured out? Different problem."

---

### vs Letta/MemGPT ("They're the research leader")

**Their pitch:** LLM-as-OS paradigm, MemFS, stateful agents. $10M seed, Jeff Dean backed.

**Where they win:**
- Novel OS architecture
- Research lineage (UC Berkeley)
- Git-backed memory versioning

**Where we win:**
- Runtime-agnostic (they require Letta runtime)
- Org-level sharing (they're per-agent)
- We can run *under* Letta as infrastructure

**Objection responses:**

*"Letta is more innovative"*
> "Letta is a runtime. We're infrastructure. They're not competing - we're complementary. You can run Engrammic under Letta to give their agents shared, org-level knowledge."

*"They have backing from Jeff Dean"*
> "Great for them. Different category. They're building the agent runtime; we're building the knowledge layer any runtime can use."

**Stance:** Don't attack Letta. Position as complementary.

---

### vs Google AOMA / Memory Bank ("Google is free")

**Their pitch:** Free ADK template, 27 file types, SQLite store.

**Where they win:**
- Free
- Google ecosystem integration
- Fast to start

**Where we win:**
- Production governance (silos, scope-gating, audit)
- Org-level first-class (AOMA has no team concept)
- Belief evolution, not just memory storage

**Objection responses:**

*"Google's is free, why would I pay?"*
> "Their template is single-agent, no org concept, no governance. We're what you deploy when you need production-grade knowledge across a team of agents. Free gets you started; we get you to production."

*"Google will just add these features"*
> "Maybe. But architectural decisions are expensive to change. They started single-agent; retrofitting org-level is hard. We'll move faster on the features that matter for teams."

---

### vs "Just use a vector DB" (Pinecone, Qdrant, Weaviate)

**Objection:** "I'll just store embeddings in Qdrant and retrieve them"

**Response:**
> "Vector DBs are storage. We're the intelligence layer on top. Qdrant stores embeddings; Engrammic decides what's a fact vs a belief, tracks evidence, handles supersession, detects contradictions. You'll end up building this yourself - or you use us."

**Follow-up:** "We use Qdrant under the hood. The question is what sits on top."

---

### vs "We'll build it ourselves"

**Objection:** "We have engineers, we'll build our own knowledge layer"

**Response:**
> "You absolutely can. The question is whether that's where you want to spend 6-12 months of engineering. We've already built the hard parts - belief formation, supersession, provenance, contradiction detection, time-travel. You'd be rebuilding infrastructure instead of building your product."

**Follow-up:** "What's your core differentiation? If it's not knowledge architecture, use ours."

---

### Common objections

| Objection | Response |
|-----------|----------|
| "RAG is good enough" | "For retrieval, yes. For reasoning - knowing what's true, what's stale, what changed - RAG falls over. That's why 65% of enterprise AI failures come from context drift, not model limitations." |
| "We don't need org-level yet" | "Every team says this until they have two agents that need to share context. The architecture is hard to retrofit. Start org-first, scale down is free." |
| "Too early stage for us" | "Fair. We're working with [X] teams who had the same concern. Happy to share references." |
| "What about vendor lock-in?" | "Open-core. Self-host the whole thing if you want. MCP-native, so switching is swapping a tool URL." |
| "What about latency?" | "Cached recall <20ms, search <250ms, graph traversal <500ms. Faster than most RAG pipelines." |
| "What about cost at scale?" | "Usage-based on top of tiers. At 100 customers your bill is ~$2k/mo. We've done the cost modeling." |

---

## Notes

- "Layer" implies easy adoption, plugs into existing stack
- "Infrastructure" implies foundational, defensible, bigger commitment
- First 15 seconds are critical - hook must land immediately
- Human analogy version is more memorable, problem-first is sharper
