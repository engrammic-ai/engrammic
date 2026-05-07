# Engrammic memory layer overview

## What it is

A graph-based context layer that sits on top of your data. Agents write to it and read from it
via MCP. It is not a vector store. It is not a flat memory log. The core primitive is a
knowledge graph with four typed layers, a validation worker (the custodian), and a heat/signal
scoring system that keeps the graph from accumulating noise.

Stack: Memgraph (graph), Qdrant (vector index for semantic search), Redis (cache), Dagster
(pipeline), FastMCP. Python 3.12 / FastAPI. Self-hostable via Docker Compose.

---

## The graph structure

Every piece of context is a node with a type. The four types map to epistemic layers:

- **Memory** — raw observations, session context, unverified. Decay over time unless promoted.
- **Knowledge** — validated facts. Require evidence refs and pass custodian consensus (R1: single
  high-confidence source, R2: two independent sources). No decay once promoted.
- **Wisdom** — patterns derived from Knowledge clusters via graph community detection + LLM summarisation.
  Generated automatically, not written by agents directly.
- **Intelligence** — stored reasoning chains (DAGs). An agent calls `context_reason` with a
  multi-step chain; the result is stored so future agents can retrieve the conclusion without
  re-running the chain.

Edges are typed too (`CITEEdgeType` from the open-source primitives library): `SUPPORTS`,
`CONTRADICTS`, `SUPERSEDES`, `DERIVED_FROM`, `OBSERVED_IN`, etc. Supersession is explicit: when
a fact changes, the old node gets a `SUPERSEDES` edge to the new one. Nothing is mutated
in-place. Full audit trail.

---

## The custodian

The custodian is an async worker pool that visits `:Claim` nodes and decides whether to promote
them to `:Fact`. Promotion rules:

- **R1** — single source with `source_tier = authoritative` and `confidence >= 0.9`
- **R2** — two independent sources corroborating the same claim, regardless of tier

Claims that don't promote sit in Memory and decay unless new evidence arrives. Claims that
contradict an existing Fact trigger a supersession cycle rather than silently overwriting.

For Silt's use case, this handles the decision-tracking pattern directly: a decision gets
asserted as a claim, corroborated by context (who made it, what informed it), promoted to a
Fact, and if it's later reversed, the reversal creates a `SUPERSEDES` edge. The history is
always intact.

---

## Heat scoring

Every node has a heat score computed from three signals: recency (freshness decay), access
frequency (how often agents retrieve or traverse it), and corroboration (how many independent
sources point to it). Heat propagates across edges, so a cluster of related nodes pulls each
other up.

Practically this means:

- Low-heat nodes get summarised by the custodian into a single curation node rather than staying
  as individual clutter.
- Traversal during retrieval is pruned at low-heat nodes by default, which bounds the graph
  walk cost.
- At ingest, stubs get an initial heat estimate based on content; nodes that would clearly be
  noise get flagged before they even enter the graph.

---

## Layer breakdown

| Layer        | What lives here                                  | Write tool                                       | Decay                                                          | Promotion trigger                                                |
| ------------ | ------------------------------------------------ | ------------------------------------------------ | -------------------------------------------------------------- | ---------------------------------------------------------------- |
| Memory       | Raw observations, unverified session context     | `context_remember`                               | Yes (configurable: ephemeral / standard / durable / permanent) | Manual or custodian R1/R2                                        |
| Knowledge    | Validated facts with evidence refs and citations | `context_assert`                                 | No                                                             | R1 (single authoritative source) or R2 (two independent sources) |
| Wisdom       | Patterns derived from Knowledge clusters         | `context_commit` (manual) or auto via clustering | No                                                             | Graph community detection + LLM summarisation over Knowledge nodes |
| Intelligence | Stored reasoning chains (DAGs)                   | `context_reason`                                 | No                                                             | Agent submits a multi-step chain; stored on completion           |

On top of all four layers sits **meta-memory**, which is not a storage layer but an observability
layer. It tracks provenance (where did this come from?), time-travel (what did we know at time T?),
and reflection (what has the agent learned about its own reasoning?). The `context_reflect` tool
writes to meta-memory; `context_provenance` and `context_history` read from it.

Meta-memory is what makes the decision-tracking pattern useful beyond just storing facts. When a
decision is later reversed, you can query `context_history` to see what the system believed at the
time of the original decision, and `context_provenance` to trace exactly which claims informed it.
The agent can reflect on that chain via `context_reflect` and store the updated understanding.
Nothing is lost, and the reasoning behind past decisions is always recoverable.

---

## The MCP surface

13 tools. Reads and writes are separated:

```
# Reads
context_get        # fetch a specific node by ID
context_query      # semantic + graph search across a silo
context_graph      # traverse from a node up to depth N
context_history    # temporal query — what did we know at time T?
context_provenance # trace a node back to its sources

# Writes
context_remember   # Memory layer (observations, session context)
context_assert     # Knowledge layer (claims with evidence refs)
context_commit     # Wisdom layer (manually commit a pattern)
context_reason     # Intelligence layer (store a reasoning chain)
context_reflect    # Meta-memory (log agent self-reflection)

# Linking
context_link       # create a typed edge between two nodes

# Tenancy
silo_create
silo_list
```

Each silo is a fully isolated multi-tenant partition. For Silt, you'd have one silo per
org, or one per workspace — whatever the right isolation boundary is for your product.

A minimal write/read cycle looks like:

```json
// Agent writes an observation
{
  "tool": "context_remember",
  "arguments": {
    "silo_id": "silo-silt-test",
    "content": "Discussed moving auth to WorkOS in the 14 April session. Not decided yet.",
    "tags": ["auth", "workos", "decision-pending"],
    "decay_class": "durable",
    "observed_from": "agent:canvas-session-xyz"
  }
}

// Later agent queries
{
  "tool": "context_query",
  "arguments": {
    "silo_id": "silo-silt-test",
    "query": "what decisions are pending around auth?",
    "layers": ["memory", "knowledge"],
    "limit": 10
  }
}
```

---

## What's open source vs. proprietary

The base protocol and schema (`primitives` library: node types, edge types, MCP tool contracts,
epistemology specs) is open source. The heat/signal scoring and custodian consensus logic is
proprietary. The integration surface is fully inspectable — you can read every tool contract,
every query, every schema.

Repo is available to share. Happy to walk through any of it.

---

## How a trial would work

1. I spin up an instance for you (or hand you the Docker Compose stack to self-host).
2. You create a silo, point one of your canvas agents at the MCP server.
3. Write some observations via `context_remember`, assert a decision or two via `context_assert`,
   run a few queries.
4. See whether the retrieval quality, the graph structure, and the latency hold up for your use
   case.

PS: If you'd rather look at the repo first before running anything, that works too.
