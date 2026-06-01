# Brain Transactions: Pseudocode

> Detailed transaction logic. Implements tables from brain-transactions-overview.md v3.

**Status:** DRAFT  
**Date:** 2026-06-01

---

## TX0: STORE_MEMORY

Backs the `remember` MCP tool. Simplest write path - no invariants beyond silo membership.

```
TX0_STORE_MEMORY(content, tags[], silo_id, agent_id) -> Result<node_id, Error>

PRECONDITIONS:
  - silo_id exists
  - agent has write access to silo

TRANSACTION:
  atomic {
    node_id = generate_uuid()
    
    node = Node {
      id: node_id,
      silo_id: silo_id,
      layer: MEMORY,
      type: OBSERVATION,
      content: content,
      tags: tags,
      state: ACTIVE,
      created_at: now(),
      created_by: agent_id,
      embedding: null,  # computed async
    }
    
    INSERT node
  }

POSTCONDITIONS:
  - node exists with state=ACTIVE
  - node.layer = MEMORY

ASYNC_REACTIONS:
  - ENQUEUE compute_embedding(node_id)
  - ENQUEUE update_heat(node_id, access_type=WRITE)
  - IF content.length > EXTRACTION_THRESHOLD:
      ENQUEUE check_extraction_trigger(node_id)

RETURN Ok(node_id)
```

---

## TX2: STORE_CLAIM

Backs the `learn` MCP tool. Core knowledge write with consistency enforcement.

```
TX2_STORE_CLAIM(content, evidence_refs[], silo_id, agent_id, source_tier?, supersedes?) -> Result<node_id, Error>

PRECONDITIONS:
  - silo_id exists
  - agent has write access to silo
  - evidence_refs is non-empty (INV2)
  - all evidence_refs exist in same silo (INV5)
  - at least one evidence_ref is Memory layer

VALIDATION:
  # Check evidence exists and is same-silo
  FOR ref IN evidence_refs:
    evidence_node = LOOKUP(ref)
    IF evidence_node IS NULL:
      RETURN Err(EVIDENCE_NOT_FOUND, ref)
    IF evidence_node.silo_id != silo_id:
      RETURN Err(CROSS_SILO_VIOLATION, ref)
    IF evidence_node.state = TOMBSTONED:
      RETURN Err(EVIDENCE_TOMBSTONED, ref)
  
  # Check at least one Memory layer evidence
  memory_evidence = evidence_refs.filter(r => LOOKUP(r).layer = MEMORY)
  IF memory_evidence.is_empty():
    RETURN Err(NO_MEMORY_EVIDENCE)

TRANSACTION:
  # Optimistic lock on (silo_id, subject, predicate)
  # Extract subject/predicate from content (assumed structured or via NLP)
  spo = extract_spo(content)
  
  ACQUIRE_LOCK(silo_id, spo.subject, spo.predicate) OR RETURN Err(LOCK_CONFLICT)
  
  TRY atomic {
    node_id = generate_uuid()
    
    # Check for conflicts (INV1)
    conflicts = QUERY {
      MATCH (c:Claim)
      WHERE c.silo_id = silo_id
        AND c.subject = spo.subject
        AND c.predicate = spo.predicate
        AND c.object != spo.object
        AND c.state = ACTIVE
      RETURN c
    }
    
    IF conflicts.is_not_empty() AND supersedes IS NULL:
      # Conflict detected - resolve it
      winner = RESOLVE_CONFLICT(new_claim_data, conflicts)
      IF winner != NEW_CLAIM:
        RELEASE_LOCK()
        RETURN Err(CONFLICT_DETECTED, winner_id=winner.id)
    
    # Handle explicit supersession
    IF supersedes IS NOT NULL:
      old_node = LOOKUP(supersedes)
      IF old_node IS NULL OR old_node.silo_id != silo_id:
        RELEASE_LOCK()
        RETURN Err(INVALID_SUPERSEDES_TARGET)
      # Will create SUPERSEDES edge below
    
    # Compute initial confidence
    confidence = compute_initial_confidence(evidence_refs, source_tier)
    
    # Create the node
    node = Node {
      id: node_id,
      silo_id: silo_id,
      layer: KNOWLEDGE,
      type: CLAIM,
      content: content,
      subject: spo.subject,
      predicate: spo.predicate,
      object: spo.object,
      state: ACTIVE,
      claim_status: UNPROMOTED,
      confidence: confidence,
      created_at: now(),
      created_by: agent_id,
      embedding: null,
    }
    
    INSERT node
    
    # Create DERIVED_FROM edges (INV2)
    FOR ref IN evidence_refs:
      CREATE_EDGE(node_id, ref, DERIVED_FROM)
    
    # Create SUPERSEDES edge if explicit supersession
    IF supersedes IS NOT NULL:
      CREATE_EDGE(node_id, supersedes, SUPERSEDES, reason=AUTHOR_UPDATE)
      UPDATE old_node SET state=SUPERSEDED, valid_to=now()
  }
  FINALLY {
    RELEASE_LOCK()
  }

POSTCONDITIONS:
  - node exists with state=ACTIVE
  - node has >= 1 DERIVED_FROM edge to Memory layer
  - no INV1 violation (conflicts resolved)

SYNC_REACTIONS:
  - CHECK_CORROBORATION(node_id)  # may trigger TX18 PROMOTE

ASYNC_REACTIONS:
  - ENQUEUE compute_embedding(node_id)
  - ENQUEUE update_heat(node_id, access_type=WRITE)
  - ENQUEUE update_cluster_membership(node_id)
  - IF supersedes IS NOT NULL:
      ENQUEUE cascade_staleness(supersedes, depth=1)

RETURN Ok(node_id)
```

---

## TX3: SUPERSEDE

Marks a node as superseded by another. Called by conflict resolution or explicit revision.

```
TX3_SUPERSEDE(winner_id, loser_id, reason) -> Result<edge_id, Error>

REASONS:
  - CONTRADICTION: structural conflict, system resolved
  - EVIDENCE_SHIFT: underlying evidence changed
  - AUTHOR_UPDATE: same agent correcting themselves
  - EVIDENCE_ERASED: source evidence was tombstoned

PRECONDITIONS:
  - winner_id exists and state=ACTIVE
  - loser_id exists and state=ACTIVE
  - winner.silo_id = loser.silo_id (INV5)
  - no cycle would be created (INV4)

VALIDATION:
  winner = LOOKUP(winner_id)
  loser = LOOKUP(loser_id)
  
  IF winner IS NULL:
    RETURN Err(WINNER_NOT_FOUND)
  IF loser IS NULL:
    RETURN Err(LOSER_NOT_FOUND)
  IF winner.state != ACTIVE:
    RETURN Err(WINNER_NOT_ACTIVE)
  IF loser.state != ACTIVE:
    RETURN Err(LOSER_NOT_ACTIVE)
  IF winner.silo_id != loser.silo_id:
    RETURN Err(CROSS_SILO_VIOLATION)
  
  # Cycle detection (INV4)
  IF would_create_cycle(winner_id, loser_id, SUPERSEDES):
    RETURN Err(WOULD_CREATE_CYCLE)

TRANSACTION:
  ACQUIRE_LOCK(loser_id)
  
  TRY atomic {
    edge_id = generate_uuid()
    
    # Update loser state
    UPDATE loser SET
      state = SUPERSEDED,
      valid_to = now()
    
    # Create SUPERSEDES edge
    edge = Edge {
      id: edge_id,
      source: winner_id,
      target: loser_id,
      type: SUPERSEDES,
      reason: reason,
      created_at: now(),
    }
    
    INSERT edge
  }
  FINALLY {
    RELEASE_LOCK()
  }

POSTCONDITIONS:
  - loser.state = SUPERSEDED
  - loser.valid_to IS NOT NULL
  - SUPERSEDES edge exists from winner to loser

SYNC_REACTIONS:
  - None (supersession itself is often a sync reaction)

ASYNC_REACTIONS:
  - ENQUEUE cascade_staleness(loser_id, depth=1)

RETURN Ok(edge_id)
```

---

## Helper: RESOLVE_CONFLICT

Determines winner when structural conflict detected. Pure function, no side effects.

```
RESOLVE_CONFLICT(new_claim_data, existing_claims[]) -> Winner

# Score each candidate
FUNCTION score(claim):
  tier_weight = source_tier_weight(claim.source_tier)  # 1.0/0.85/0.6/0.4
  corroboration = claim.corroboration_count OR 1
  freshness = 1.0 / (1 + days_since(claim.created_at))
  
  RETURN tier_weight * log(1 + corroboration) * freshness

new_score = score(new_claim_data)

FOR existing IN existing_claims:
  existing_score = score(existing)
  
  IF new_score > existing_score:
    # New claim wins - will supersede existing
    CONTINUE
  
  IF new_score < existing_score:
    # Existing wins - reject new claim
    RETURN Winner { type: EXISTING, id: existing.id }
  
  IF new_score == existing_score:
    # Tiebreaker: check if same agent
    IF new_claim_data.agent_id == existing.created_by:
      # Same agent revising - newer wins
      CONTINUE
    ELSE:
      # Different agents, same score - older wins for stability
      RETURN Winner { type: EXISTING, id: existing.id }

# New claim wins against all existing
RETURN Winner { type: NEW_CLAIM }
```

---

## Helper: CHECK_CORROBORATION

Called after TX2. Checks if claim corroborates existing claims or is corroborated.

```
CHECK_CORROBORATION(node_id) -> void

node = LOOKUP(node_id)

# Find claims with same (s, p, o)
corroborating = QUERY {
  MATCH (c:Claim)
  WHERE c.silo_id = node.silo_id
    AND c.subject = node.subject
    AND c.predicate = node.predicate
    AND c.object = node.object
    AND c.id != node.id
    AND c.state = ACTIVE
  RETURN c
}

IF corroborating.is_empty():
  RETURN  # No corroboration

# Count distinct sources
all_claims = [node] + corroborating
distinct_sources = count_distinct_evidence_sources(all_claims)

# Update corroboration count on all related claims
FOR claim IN all_claims:
  UPDATE claim SET corroboration_count = distinct_sources

# Check promotion threshold
IF distinct_sources >= PROMOTION_THRESHOLD:  # default: 3
  FOR claim IN all_claims:
    IF claim.claim_status = UNPROMOTED:
      TX18_PROMOTE(claim.id)
```

---

## Helper: CASCADE_STALENESS

Propagates staleness to dependent nodes. Depth-limited, async after depth 1.

```
CASCADE_STALENESS(changed_node_id, depth, visited={}) -> void

IF depth > MAX_CASCADE_DEPTH:  # default: 10
  LOG warning "cascade depth limit reached" node_id=changed_node_id
  RETURN

IF changed_node_id IN visited:
  RETURN  # Already processed (diamond dedup)

visited.add(changed_node_id)

# Find dependents (nodes that reference the changed node)
dependents = QUERY {
  MATCH (d)-[e:SYNTHESIZED_FROM|DERIVED_FROM]->(changed)
  WHERE changed.id = changed_node_id
    AND d.state = ACTIVE
  RETURN d, e.type as edge_type
}

FOR dependent IN dependents:
  IF dependent.layer = WISDOM:
    # Mark belief stale
    UPDATE dependent SET synthesis_state = STALE
    ENQUEUE re_synthesis(dependent.id)  # TX5
  
  IF dependent.layer = KNOWLEDGE:
    # Recurse
    IF depth = 1:
      # Sync for depth 1
      CASCADE_STALENESS(dependent.id, depth + 1, visited)
    ELSE:
      # Async for deeper
      ENQUEUE cascade_staleness(dependent.id, depth + 1, visited)
```

---

## Helper: WOULD_CREATE_CYCLE

Checks if adding edge would create cycle in SUPERSEDES graph.

```
WOULD_CREATE_CYCLE(source_id, target_id, edge_type) -> bool

IF edge_type != SUPERSEDES:
  RETURN false  # Only check SUPERSEDES cycles

# BFS from target to see if we can reach source
visited = {}
queue = [target_id]

WHILE queue.is_not_empty():
  current = queue.pop_front()
  
  IF current = source_id:
    RETURN true  # Cycle detected
  
  IF current IN visited:
    CONTINUE
  
  visited.add(current)
  
  # Follow SUPERSEDES edges (target supersedes something)
  successors = QUERY {
    MATCH (current)-[:SUPERSEDES]->(next)
    WHERE current.id = current
    RETURN next.id
  }
  
  queue.extend(successors)

RETURN false
```

---

## TX4: SYNTHESIZE

Creates a Belief from a cluster of Facts. Can be triggered async (cluster ready) or sync (query-time lazy).

```
TX4_SYNTHESIZE(cluster_id, mode=ASYNC) -> Result<belief_id | null, Error>

MODES:
  - ASYNC: background synthesis, no latency constraint
  - SYNC: query-time lazy synthesis, 2s timeout

PRECONDITIONS:
  - cluster exists
  - cluster.state = READY or STALE
  - no synthesis already in progress for this cluster

VALIDATION:
  cluster = LOOKUP_CLUSTER(cluster_id)
  
  IF cluster IS NULL:
    RETURN Err(CLUSTER_NOT_FOUND)
  
  IF cluster.state NOT IN [READY, STALE]:
    RETURN Err(CLUSTER_NOT_READY, state=cluster.state)
  
  # Check for in-progress synthesis (deduplication)
  IF cluster.synthesis_in_progress:
    IF mode = SYNC:
      # Wait for existing synthesis to complete
      RETURN WAIT_FOR_SYNTHESIS(cluster_id, timeout=2s)
    ELSE:
      RETURN Ok(null)  # Already being handled

TRANSACTION:
  ACQUIRE_LOCK(cluster_id)
  
  TRY {
    # Mark synthesis in progress
    UPDATE cluster SET synthesis_in_progress = true
    
    # Get facts in cluster
    facts = QUERY {
      MATCH (f:Fact)-[:MEMBER_OF]->(c:Cluster)
      WHERE c.id = cluster_id
        AND f.state = ACTIVE
      RETURN f
      ORDER BY f.confidence DESC
      LIMIT MAX_CLUSTER_SIZE  # default: 1000
    }
    
    IF facts.count < SYNTHESIS_THRESHOLD:  # default: 3
      UPDATE cluster SET 
        state = SPARSE,
        synthesis_in_progress = false
      RELEASE_LOCK()
      RETURN Ok(null)  # Not enough facts
    
    # Compute aggregate confidence
    aggregate_confidence = noisy_or_aggregate(facts.map(f => f.confidence))
    
    IF aggregate_confidence < SYNTHESIS_CONFIDENCE_THRESHOLD:  # default: 0.6
      LOG info "synthesis skipped - low confidence" cluster_id confidence=aggregate_confidence
      UPDATE cluster SET synthesis_in_progress = false
      RELEASE_LOCK()
      RETURN Ok(null)
    
    # Call LLM for synthesis
    IF mode = SYNC:
      synthesis_result = LLM_SYNTHESIZE(facts, timeout=2s)
      IF synthesis_result.timed_out:
        UPDATE cluster SET synthesis_in_progress = false
        RELEASE_LOCK()
        RETURN Ok(null)  # Caller gets facts + "synthesis_pending"
    ELSE:
      synthesis_result = LLM_SYNTHESIZE(facts, timeout=30s)
    
    IF synthesis_result.failed:
      UPDATE cluster SET 
        synthesis_in_progress = false,
        synthesis_failed_at = now(),
        synthesis_retry_count = cluster.synthesis_retry_count + 1
      RELEASE_LOCK()
      
      IF cluster.synthesis_retry_count < MAX_SYNTHESIS_RETRIES:  # default: 3
        ENQUEUE synthesis_retry(cluster_id, delay=exponential_backoff())
      
      RETURN Err(SYNTHESIS_FAILED, reason=synthesis_result.error)
    
    # Create Belief node
    belief_id = generate_uuid()
    
    atomic {
      belief = Node {
        id: belief_id,
        silo_id: cluster.silo_id,
        layer: WISDOM,
        type: BELIEF,
        content: synthesis_result.content,
        state: ACTIVE,
        synthesis_state: FRESH,
        confidence: aggregate_confidence,
        created_at: now(),
        source_cluster_id: cluster_id,
        embedding: null,
      }
      
      INSERT belief
      
      # Create SYNTHESIZED_FROM edges (INV3)
      FOR fact IN facts:
        CREATE_EDGE(belief_id, fact.id, SYNTHESIZED_FROM)
      
      # Update cluster state
      UPDATE cluster SET
        state = SYNTHESIZED,
        synthesis_in_progress = false,
        current_belief_id = belief_id,
        synthesized_at = now()
    }
  }
  FINALLY {
    RELEASE_LOCK()
  }

POSTCONDITIONS:
  - belief exists with state=ACTIVE, synthesis_state=FRESH
  - belief has >= N SYNTHESIZED_FROM edges to ACTIVE Facts (INV3)
  - cluster.state = SYNTHESIZED

ASYNC_REACTIONS:
  - ENQUEUE compute_embedding(belief_id)
  - ENQUEUE update_heat(belief_id, access_type=SYNTHESIS)

RETURN Ok(belief_id)
```

---

## TX5: REVISE_BELIEF

Re-synthesizes a stale Belief. Creates new Belief that supersedes the old one.

```
TX5_REVISE_BELIEF(belief_id) -> Result<new_belief_id, Error>

PRECONDITIONS:
  - belief exists
  - belief.synthesis_state = STALE

VALIDATION:
  belief = LOOKUP(belief_id)
  
  IF belief IS NULL:
    RETURN Err(BELIEF_NOT_FOUND)
  
  IF belief.state != ACTIVE:
    RETURN Err(BELIEF_NOT_ACTIVE)
  
  IF belief.synthesis_state != STALE:
    RETURN Err(BELIEF_NOT_STALE, state=belief.synthesis_state)

TRANSACTION:
  cluster_id = belief.source_cluster_id
  
  ACQUIRE_LOCK(cluster_id)
  
  TRY {
    # Get current facts in cluster (may have changed)
    facts = QUERY {
      MATCH (f:Fact)-[:MEMBER_OF]->(c:Cluster)
      WHERE c.id = cluster_id
        AND f.state = ACTIVE
      RETURN f
      ORDER BY f.confidence DESC
      LIMIT MAX_CLUSTER_SIZE
    }
    
    # Check if belief is now unsupported
    IF facts.count < SYNTHESIS_THRESHOLD:
      # Invalidate belief
      UPDATE belief SET synthesis_state = INVALIDATED
      UPDATE cluster SET state = SPARSE, current_belief_id = null
      RELEASE_LOCK()
      RETURN Ok(null)  # No new belief created
    
    # Compute new aggregate confidence
    aggregate_confidence = noisy_or_aggregate(facts.map(f => f.confidence))
    
    IF aggregate_confidence < SYNTHESIS_CONFIDENCE_THRESHOLD:
      UPDATE belief SET synthesis_state = INVALIDATED
      UPDATE cluster SET state = SPARSE, current_belief_id = null
      RELEASE_LOCK()
      RETURN Ok(null)
    
    # Call LLM for re-synthesis
    synthesis_result = LLM_SYNTHESIZE(facts, timeout=30s, previous_belief=belief.content)
    
    IF synthesis_result.failed:
      # Keep belief stale, retry later
      UPDATE cluster SET
        synthesis_retry_count = cluster.synthesis_retry_count + 1
      RELEASE_LOCK()
      
      IF cluster.synthesis_retry_count < MAX_SYNTHESIS_RETRIES:
        ENQUEUE revision_retry(belief_id, delay=exponential_backoff())
      
      RETURN Err(REVISION_FAILED, reason=synthesis_result.error)
    
    # Check if content actually changed
    IF synthesis_result.content == belief.content:
      # No change needed, just mark fresh
      UPDATE belief SET synthesis_state = FRESH
      UPDATE cluster SET state = SYNTHESIZED
      RELEASE_LOCK()
      RETURN Ok(belief_id)  # Return existing belief
    
    # Create new Belief that supersedes old
    new_belief_id = generate_uuid()
    
    atomic {
      new_belief = Node {
        id: new_belief_id,
        silo_id: belief.silo_id,
        layer: WISDOM,
        type: BELIEF,
        content: synthesis_result.content,
        state: ACTIVE,
        synthesis_state: FRESH,
        confidence: aggregate_confidence,
        created_at: now(),
        source_cluster_id: cluster_id,
        embedding: null,
      }
      
      INSERT new_belief
      
      # Create SYNTHESIZED_FROM edges
      FOR fact IN facts:
        CREATE_EDGE(new_belief_id, fact.id, SYNTHESIZED_FROM)
      
      # Supersede old belief
      CREATE_EDGE(new_belief_id, belief_id, SUPERSEDES, reason=EVIDENCE_SHIFT)
      UPDATE belief SET state = SUPERSEDED, valid_to = now()
      
      # Update cluster
      UPDATE cluster SET
        state = SYNTHESIZED,
        current_belief_id = new_belief_id,
        synthesized_at = now(),
        synthesis_retry_count = 0
    }
  }
  FINALLY {
    RELEASE_LOCK()
  }

POSTCONDITIONS:
  - new_belief exists with state=ACTIVE, synthesis_state=FRESH
  - old belief.state = SUPERSEDED
  - SUPERSEDES edge from new to old with reason=EVIDENCE_SHIFT
  - cluster.state = SYNTHESIZED

ASYNC_REACTIONS:
  - ENQUEUE compute_embedding(new_belief_id)
  - ENQUEUE update_heat(new_belief_id, access_type=SYNTHESIS)

RETURN Ok(new_belief_id)
```

---

## Helper: LLM_SYNTHESIZE

Calls LLM to generate synthesis content from facts.

```
LLM_SYNTHESIZE(facts[], timeout, previous_belief?) -> SynthesisResult

PROMPT = """
You are synthesizing a belief from corroborated facts.

Facts:
{{FOR fact IN facts}}
- [{{fact.confidence}}] {{fact.content}}
  Source: {{fact.evidence_summary}}
{{END}}

{{IF previous_belief}}
Previous belief (now stale): {{previous_belief}}
{{END}}

Synthesize a single coherent belief that captures the consensus across these facts.
Be specific. Cite the most confident facts. Note any tensions or caveats.

Output JSON:
{
  "content": "The synthesized belief statement",
  "confidence_rationale": "Why this confidence level",
  "caveats": ["any important caveats"]
}
"""

TRY:
  response = LLM_CALL(
    model = SYNTHESIS_MODEL,  # e.g., claude-3-haiku for cost efficiency
    prompt = PROMPT,
    timeout = timeout,
    max_tokens = 500,
  )
  
  parsed = JSON_PARSE(response)
  
  RETURN SynthesisResult {
    success: true,
    content: parsed.content,
    caveats: parsed.caveats,
    timed_out: false,
  }

CATCH TimeoutError:
  RETURN SynthesisResult {
    success: false,
    timed_out: true,
    error: "synthesis timed out",
  }

CATCH error:
  RETURN SynthesisResult {
    success: false,
    timed_out: false,
    error: error.message,
  }
```

---

## Helper: WAIT_FOR_SYNTHESIS

Waits for in-progress synthesis to complete (sync mode deduplication).

```
WAIT_FOR_SYNTHESIS(cluster_id, timeout) -> Result<belief_id | null, Error>

start = now()

WHILE now() - start < timeout:
  cluster = LOOKUP_CLUSTER(cluster_id)
  
  IF NOT cluster.synthesis_in_progress:
    IF cluster.current_belief_id IS NOT NULL:
      RETURN Ok(cluster.current_belief_id)
    ELSE:
      RETURN Ok(null)  # Synthesis completed but no belief created
  
  SLEEP(100ms)

# Timeout waiting for other synthesis
RETURN Ok(null)  # Caller gets facts + "synthesis_pending"
```

---

## Helper: CHECK_SYNTHESIS_TRIGGER

Called when cluster membership changes. Checks if synthesis should be triggered.

```
CHECK_SYNTHESIS_TRIGGER(cluster_id) -> void

cluster = LOOKUP_CLUSTER(cluster_id)

IF cluster IS NULL:
  RETURN

# Count active facts in cluster
fact_count = QUERY {
  MATCH (f:Fact)-[:MEMBER_OF]->(c:Cluster)
  WHERE c.id = cluster_id
    AND f.state = ACTIVE
  RETURN count(f)
}

current_state = cluster.state

IF fact_count >= SYNTHESIS_THRESHOLD AND current_state = SPARSE:
  # Cluster is now ready for synthesis
  UPDATE cluster SET state = READY
  ENQUEUE synthesize(cluster_id)  # TX4

ELSE IF fact_count < SYNTHESIS_THRESHOLD AND current_state IN [READY, SYNTHESIZED, STALE]:
  # Cluster no longer meets threshold
  UPDATE cluster SET state = SPARSE
  
  IF cluster.current_belief_id IS NOT NULL:
    # Invalidate existing belief
    UPDATE belief SET synthesis_state = INVALIDATED
      WHERE id = cluster.current_belief_id
```

---

## TX8: COMMIT

Agent declares a stance directly (without prior hypothesis). Creates a Commitment in Wisdom layer.

```
TX8_COMMIT(content, about_refs[], silo_id, agent_id) -> Result<commitment_id, Error>

PRECONDITIONS:
  - silo_id exists
  - agent has write access to silo
  - about_refs is non-empty (commitment must be about something)
  - all about_refs exist in same silo (INV5)

VALIDATION:
  # Check about_refs exist and are same-silo
  FOR ref IN about_refs:
    node = LOOKUP(ref)
    IF node IS NULL:
      RETURN Err(ABOUT_REF_NOT_FOUND, ref)
    IF node.silo_id != silo_id:
      RETURN Err(CROSS_SILO_VIOLATION, ref)
    IF node.state = TOMBSTONED:
      RETURN Err(ABOUT_REF_TOMBSTONED, ref)

TRANSACTION:
  atomic {
    commitment_id = generate_uuid()
    
    # Compute confidence from referenced nodes
    referenced_nodes = about_refs.map(r => LOOKUP(r))
    avg_confidence = average(referenced_nodes.map(n => n.confidence OR 0.8))
    
    commitment = Node {
      id: commitment_id,
      silo_id: silo_id,
      layer: WISDOM,
      type: COMMITMENT,
      content: content,
      state: ACTIVE,
      confidence: avg_confidence,
      created_at: now(),
      created_by: agent_id,
      embedding: null,
    }
    
    INSERT commitment
    
    # Create ABOUT edges
    FOR ref IN about_refs:
      CREATE_EDGE(commitment_id, ref, ABOUT)
    
    # Create DECLARED_BY edge (INV7)
    CREATE_EDGE(commitment_id, agent_id, DECLARED_BY)
  }

POSTCONDITIONS:
  - commitment exists with state=ACTIVE
  - commitment has DECLARED_BY edge to agent (INV7)
  - commitment has ABOUT edges to all about_refs

ASYNC_REACTIONS:
  - ENQUEUE compute_embedding(commitment_id)
  - ENQUEUE update_heat(commitment_id, access_type=WRITE)

RETURN Ok(commitment_id)
```

---

## TX14: CRYSTALLIZE

Converts a WorkingHypothesis into a permanent Commitment. Session-scoped to persistent.

```
TX14_CRYSTALLIZE(hypothesis_id, agent_id) -> Result<commitment_id, Error>

PRECONDITIONS:
  - hypothesis exists
  - hypothesis belongs to agent's current session
  - hypothesis not already crystallized

VALIDATION:
  hypothesis = LOOKUP(hypothesis_id)
  
  IF hypothesis IS NULL:
    RETURN Err(HYPOTHESIS_NOT_FOUND)
  
  IF hypothesis.type != WORKING_HYPOTHESIS:
    RETURN Err(NOT_A_HYPOTHESIS)
  
  IF hypothesis.session_id != current_session_id(agent_id):
    RETURN Err(HYPOTHESIS_WRONG_SESSION)
  
  IF hypothesis.crystallized:
    RETURN Err(ALREADY_CRYSTALLIZED)
  
  # Check about_refs still valid
  about_refs = GET_EDGES(hypothesis_id, ABOUT).map(e => e.target)
  FOR ref IN about_refs:
    node = LOOKUP(ref)
    IF node IS NULL OR node.state = TOMBSTONED:
      RETURN Err(ABOUT_REF_INVALID, ref)

TRANSACTION:
  ACQUIRE_LOCK(hypothesis_id)
  
  TRY atomic {
    commitment_id = generate_uuid()
    
    commitment = Node {
      id: commitment_id,
      silo_id: hypothesis.silo_id,
      layer: WISDOM,
      type: COMMITMENT,
      content: hypothesis.content,
      state: ACTIVE,
      confidence: hypothesis.confidence,
      created_at: now(),
      created_by: agent_id,
      source_hypothesis_id: hypothesis_id,
      embedding: null,
    }
    
    INSERT commitment
    
    # Copy ABOUT edges from hypothesis
    FOR ref IN about_refs:
      CREATE_EDGE(commitment_id, ref, ABOUT)
    
    # Create DECLARED_BY edge (INV7)
    CREATE_EDGE(commitment_id, agent_id, DECLARED_BY)
    
    # Create CRYSTALLIZED_FROM edge (provenance)
    CREATE_EDGE(commitment_id, hypothesis_id, CRYSTALLIZED_FROM)
    
    # Mark hypothesis as crystallized (still session-scoped, will expire)
    UPDATE hypothesis SET crystallized = true, crystallized_into = commitment_id
  }
  FINALLY {
    RELEASE_LOCK()
  }

POSTCONDITIONS:
  - commitment exists with state=ACTIVE
  - commitment has DECLARED_BY edge to agent (INV7)
  - commitment has CRYSTALLIZED_FROM edge to hypothesis
  - hypothesis.crystallized = true

ASYNC_REACTIONS:
  - ENQUEUE compute_embedding(commitment_id)
  - ENQUEUE update_heat(commitment_id, access_type=WRITE)

RETURN Ok(commitment_id)
```

---

## TX15: FORGET

Soft-deletes a node. Starts cancel window. Can cascade to dependents.

```
TX15_FORGET(node_id, reason?, cascade=false, agent_id) -> Result<ForgetResult, Error>

PRECONDITIONS:
  - node exists
  - node.state = ACTIVE or SUPERSEDED
  - agent has write access to node's silo

VALIDATION:
  node = LOOKUP(node_id)
  
  IF node IS NULL:
    RETURN Err(NODE_NOT_FOUND)
  
  IF node.state = TOMBSTONED:
    RETURN Err(ALREADY_TOMBSTONED)
  
  IF node.state = DELETED:
    RETURN Err(ALREADY_DELETED)

TRANSACTION:
  ACQUIRE_LOCK(node_id)
  
  TRY atomic {
    # Tombstone the node
    UPDATE node SET
      state = TOMBSTONED,
      tombstoned_at = now(),
      forget_requested_at = now(),
      forget_requested_by = agent_id,
      forget_reason = reason,
      cancel_window_expires = now() + CANCEL_WINDOW_DURATION  # default: 60 min
    
    # Count downstream references for return value
    downstream_count = COUNT_DOWNSTREAM(node_id)
  }
  FINALLY {
    RELEASE_LOCK()
  }

# Handle cascade (outside main transaction for isolation)
cascade_results = []
IF cascade:
  cascade_results = CASCADE_FORGET(node_id, reason, agent_id, visited={node_id})

POSTCONDITIONS:
  - node.state = TOMBSTONED
  - node.tombstoned_at IS NOT NULL
  - node.cancel_window_expires IS NOT NULL

ASYNC_REACTIONS:
  - ENQUEUE cascade_staleness(node_id, depth=1)
  - ENQUEUE invalidate_cache(node_id)
  - ENQUEUE schedule_hard_delete(node_id, at=cancel_window_expires)

RETURN Ok(ForgetResult {
  node_id: node_id,
  downstream_count: downstream_count,
  cascade_count: cascade_results.length,
  cancel_window_expires: node.cancel_window_expires,
})
```

---

## TX16: CANCEL_FORGET

Restores a tombstoned node within cancel window.

```
TX16_CANCEL_FORGET(node_id, agent_id) -> Result<node_id, Error>

PRECONDITIONS:
  - node exists
  - node.state = TOMBSTONED
  - cancel window not expired

VALIDATION:
  node = LOOKUP(node_id)
  
  IF node IS NULL:
    RETURN Err(NODE_NOT_FOUND)
  
  IF node.state != TOMBSTONED:
    RETURN Err(NOT_TOMBSTONED, state=node.state)
  
  IF now() > node.cancel_window_expires:
    RETURN Err(CANCEL_WINDOW_EXPIRED, expired_at=node.cancel_window_expires)

TRANSACTION:
  ACQUIRE_LOCK(node_id)
  
  TRY atomic {
    # Determine restore state
    # If node was SUPERSEDED before forget, restore to SUPERSEDED
    restore_state = node.state_before_tombstone OR ACTIVE
    
    UPDATE node SET
      state = restore_state,
      tombstoned_at = null,
      forget_requested_at = null,
      forget_requested_by = null,
      forget_reason = null,
      cancel_window_expires = null
  }
  FINALLY {
    RELEASE_LOCK()
  }

POSTCONDITIONS:
  - node.state = ACTIVE or SUPERSEDED (restored)
  - node.tombstoned_at IS NULL

ASYNC_REACTIONS:
  - ENQUEUE clear_staleness_markers(node_id)
  - ENQUEUE cancel_scheduled_hard_delete(node_id)
  # Note: cascade-tombstoned dependents are NOT auto-restored

RETURN Ok(node_id)
```

---

## Helper: CASCADE_FORGET

Recursively tombstones dependent nodes.

```
CASCADE_FORGET(source_id, reason, agent_id, visited) -> ForgetResult[]

results = []

# Find nodes that depend on source (point TO source)
dependents = QUERY {
  MATCH (d)-[e:DERIVED_FROM|SYNTHESIZED_FROM]->(source)
  WHERE source.id = source_id
    AND d.state IN [ACTIVE, SUPERSEDED]
    AND d.id NOT IN visited
  RETURN d
}

FOR dependent IN dependents:
  visited.add(dependent.id)
  
  # Tombstone the dependent
  ACQUIRE_LOCK(dependent.id)
  
  atomic {
    UPDATE dependent SET
      state = TOMBSTONED,
      tombstoned_at = now(),
      forget_requested_at = now(),
      forget_requested_by = agent_id,
      forget_reason = "cascade from " + source_id,
      cancel_window_expires = now() + CANCEL_WINDOW_DURATION,
      cascade_source_id = source_id  # Track cascade origin
  }
  
  RELEASE_LOCK()
  
  results.append(ForgetResult {
    node_id: dependent.id,
    cascade_source: source_id,
  })
  
  # Recurse (depth-first)
  child_results = CASCADE_FORGET(dependent.id, reason, agent_id, visited)
  results.extend(child_results)

RETURN results
```

---

## Helper: COUNT_DOWNSTREAM

Counts nodes that depend on a given node.

```
COUNT_DOWNSTREAM(node_id) -> int

RETURN QUERY {
  MATCH (d)-[:DERIVED_FROM|SYNTHESIZED_FROM]->(source)
  WHERE source.id = node_id
    AND d.state IN [ACTIVE, SUPERSEDED]
  RETURN count(DISTINCT d)
}
```

---

## TX_HYPOTHESIZE: Create WorkingHypothesis (bonus)

Session-scoped hypothesis creation. Not in original list but needed for TX14.

```
TX_HYPOTHESIZE(content, about_refs[], silo_id, agent_id, session_id) -> Result<hypothesis_id, Error>

PRECONDITIONS:
  - silo_id exists
  - session is active
  - about_refs exist in same silo

VALIDATION:
  FOR ref IN about_refs:
    node = LOOKUP(ref)
    IF node IS NULL OR node.silo_id != silo_id:
      RETURN Err(INVALID_ABOUT_REF, ref)

TRANSACTION:
  atomic {
    hypothesis_id = generate_uuid()
    
    hypothesis = Node {
      id: hypothesis_id,
      silo_id: silo_id,
      layer: INTELLIGENCE,
      type: WORKING_HYPOTHESIS,
      content: content,
      state: ACTIVE,
      confidence: 0.5,  # Tentative
      created_at: now(),
      created_by: agent_id,
      session_id: session_id,
      crystallized: false,
      expires_at: session_expiry(session_id),  # Session-scoped
    }
    
    INSERT hypothesis
    
    FOR ref IN about_refs:
      CREATE_EDGE(hypothesis_id, ref, ABOUT)
  }

POSTCONDITIONS:
  - hypothesis exists with layer=INTELLIGENCE
  - hypothesis is session-scoped (expires with session)

RETURN Ok(hypothesis_id)
```

---

## TX10: HARD_DELETE (scheduled GC)

Permanently removes tombstoned nodes after cancel window.

```
TX10_HARD_DELETE(node_ids[]) -> Result<deleted_count, Error>

# Called by scheduled GC job, not by agents directly

VALIDATION:
  valid_ids = []
  
  FOR node_id IN node_ids:
    node = LOOKUP(node_id)
    
    IF node IS NULL:
      CONTINUE  # Already deleted
    
    IF node.state != TOMBSTONED:
      LOG warning "hard_delete called on non-tombstoned node" node_id
      CONTINUE
    
    IF now() < node.cancel_window_expires:
      LOG warning "hard_delete called before window expired" node_id
      CONTINUE
    
    valid_ids.append(node_id)

TRANSACTION:
  FOR node_id IN valid_ids:
    atomic {
      # Delete from vector store
      VECTOR_STORE.delete(node_id)
      
      # Delete edges
      DELETE_EDGES_FOR(node_id)
      
      # Delete node
      DELETE_NODE(node_id)
      
      # Log for audit
      AUDIT_LOG.append({
        action: HARD_DELETE,
        node_id: node_id,
        deleted_at: now(),
      })
    }

RETURN Ok(valid_ids.length)
```

---

## TX17: LINK

Creates an explicit typed edge between nodes. Agent-driven relationship creation.

```
TX17_LINK(source_id, target_id, edge_type, metadata?, agent_id) -> Result<edge_id, Error>

ALLOWED_EDGE_TYPES:
  - RELATED_TO: general semantic relationship
  - CONTRADICTS: explicit contradiction marker
  - SUPPORTS: evidence relationship
  - REFINES: more specific version
  - GENERALIZES: more general version
  - CAUSED_BY: causal relationship
  - TEMPORAL_BEFORE: temporal ordering
  - TEMPORAL_AFTER: temporal ordering

PRECONDITIONS:
  - source exists and state != DELETED
  - target exists and state != DELETED
  - source.silo_id = target.silo_id (INV5)
  - edge_type is allowed
  - no duplicate edge exists

VALIDATION:
  source = LOOKUP(source_id)
  target = LOOKUP(target_id)
  
  IF source IS NULL:
    RETURN Err(SOURCE_NOT_FOUND)
  
  IF target IS NULL:
    RETURN Err(TARGET_NOT_FOUND)
  
  IF source.state = DELETED OR target.state = DELETED:
    RETURN Err(NODE_DELETED)
  
  IF source.silo_id != target.silo_id:
    RETURN Err(CROSS_SILO_VIOLATION)
  
  IF edge_type NOT IN ALLOWED_EDGE_TYPES:
    RETURN Err(INVALID_EDGE_TYPE, edge_type)
  
  # Check for duplicates
  existing = QUERY {
    MATCH (s)-[e]->(t)
    WHERE s.id = source_id
      AND t.id = target_id
      AND type(e) = edge_type
    RETURN e
  }
  
  IF existing IS NOT NULL:
    RETURN Err(DUPLICATE_EDGE, existing_id=existing.id)
  
  # Cycle detection for certain edge types
  IF edge_type IN [REFINES, GENERALIZES, CAUSED_BY]:
    IF would_create_cycle(source_id, target_id, edge_type):
      RETURN Err(WOULD_CREATE_CYCLE)

TRANSACTION:
  ACQUIRE_LOCK(source_id, target_id)
  
  TRY atomic {
    edge_id = generate_uuid()
    
    edge = Edge {
      id: edge_id,
      source: source_id,
      target: target_id,
      type: edge_type,
      metadata: metadata,
      created_at: now(),
      created_by: agent_id,
    }
    
    INSERT edge
  }
  FINALLY {
    RELEASE_LOCK()
  }

POSTCONDITIONS:
  - edge exists from source to target
  - no cycle created for hierarchical edge types

ASYNC_REACTIONS:
  - ENQUEUE update_heat(source_id, target_id, access_type=LINK)
  - IF edge_type = CONTRADICTS:
      ENQUEUE flag_contradiction(source_id, target_id)

RETURN Ok(edge_id)
```

---

## TX18: PROMOTE

Promotes an unpromoted Claim to Fact status when corroboration threshold met.

```
TX18_PROMOTE(claim_id) -> Result<claim_id, Error>

PRECONDITIONS:
  - claim exists
  - claim.state = ACTIVE
  - claim.claim_status = UNPROMOTED
  - claim.corroboration_count >= PROMOTION_THRESHOLD

VALIDATION:
  claim = LOOKUP(claim_id)
  
  IF claim IS NULL:
    RETURN Err(CLAIM_NOT_FOUND)
  
  IF claim.state != ACTIVE:
    RETURN Err(CLAIM_NOT_ACTIVE)
  
  IF claim.type != CLAIM:
    RETURN Err(NOT_A_CLAIM)
  
  IF claim.claim_status = PROMOTED:
    RETURN Ok(claim_id)  # Already promoted, idempotent
  
  IF claim.corroboration_count < PROMOTION_THRESHOLD:
    RETURN Err(INSUFFICIENT_CORROBORATION, 
      count=claim.corroboration_count, 
      threshold=PROMOTION_THRESHOLD)

TRANSACTION:
  ACQUIRE_LOCK(claim_id)
  
  TRY atomic {
    # Update claim to Fact status
    UPDATE claim SET
      type = FACT,  # Multi-label: Claim becomes Claim:Fact
      claim_status = PROMOTED,
      promoted_at = now(),
      confidence = recompute_confidence(claim)  # Boost from corroboration
  }
  FINALLY {
    RELEASE_LOCK()
  }

POSTCONDITIONS:
  - claim.claim_status = PROMOTED
  - claim.type includes FACT label

SYNC_REACTIONS:
  - CHECK_SYNTHESIS_TRIGGER for affected clusters

ASYNC_REACTIONS:
  - ENQUEUE update_cluster_membership(claim_id)

RETURN Ok(claim_id)
```

---

## TX19: DEMOTE

Demotes a Fact back to unpromoted Claim when evidence is withdrawn.

```
TX19_DEMOTE(fact_id) -> Result<fact_id, Error>

PRECONDITIONS:
  - fact exists
  - fact.state = ACTIVE
  - fact.claim_status = PROMOTED
  - fact.corroboration_count < PROMOTION_THRESHOLD (evidence withdrawn)

VALIDATION:
  fact = LOOKUP(fact_id)
  
  IF fact IS NULL:
    RETURN Err(FACT_NOT_FOUND)
  
  IF fact.state != ACTIVE:
    RETURN Err(FACT_NOT_ACTIVE)
  
  IF fact.claim_status != PROMOTED:
    RETURN Ok(fact_id)  # Already demoted, idempotent
  
  # Recount corroboration (may have changed)
  current_corroboration = recount_corroboration(fact_id)
  
  IF current_corroboration >= PROMOTION_THRESHOLD:
    RETURN Ok(fact_id)  # Still has enough corroboration

TRANSACTION:
  ACQUIRE_LOCK(fact_id)
  
  TRY atomic {
    UPDATE fact SET
      type = CLAIM,  # Remove FACT label
      claim_status = UNPROMOTED,
      demoted_at = now(),
      confidence = recompute_confidence(fact)  # Reduce without corroboration boost
  }
  FINALLY {
    RELEASE_LOCK()
  }

POSTCONDITIONS:
  - fact.claim_status = UNPROMOTED
  - fact.type = CLAIM (no longer FACT)

ASYNC_REACTIONS:
  - ENQUEUE cascade_staleness(fact_id, depth=1)  # Beliefs may need revision
  - ENQUEUE update_cluster_membership(fact_id)

RETURN Ok(fact_id)
```

---

## Helper: RECOUNT_CORROBORATION

Recounts corroboration for a claim after evidence changes.

```
RECOUNT_CORROBORATION(claim_id) -> int

claim = LOOKUP(claim_id)

# Find all claims with same (s, p, o)
corroborating = QUERY {
  MATCH (c:Claim)
  WHERE c.silo_id = claim.silo_id
    AND c.subject = claim.subject
    AND c.predicate = claim.predicate
    AND c.object = claim.object
    AND c.state = ACTIVE
  RETURN c
}

# Count distinct evidence sources
all_evidence = []
FOR c IN corroborating:
  evidence = GET_EDGES(c.id, DERIVED_FROM).map(e => e.target)
  all_evidence.extend(evidence)

distinct_sources = count_distinct_documents(all_evidence)

# Update all related claims
FOR c IN corroborating:
  UPDATE c SET corroboration_count = distinct_sources

RETURN distinct_sources
```

---

## RECALL: Query Transaction

The read path. Returns nodes matching query with epistemic metadata.

```
RECALL(query, silo_id, options) -> Result<RecallResult, Error>

OPTIONS:
  - top_k: max results (default: 10)
  - layers: filter by layer (default: all)
  - include_superseded: for temporal queries (default: false)
  - as_of: temporal query timestamp (default: null)
  - include_synthesis: include/trigger lazy synthesis (default: true)
  - min_confidence: filter threshold (default: 0)
  - depth: graph traversal depth (default: 0)

VALIDATION:
  IF silo_id IS NULL:
    RETURN Err(SILO_REQUIRED)
  
  IF query IS NULL OR query.is_empty():
    RETURN Err(QUERY_REQUIRED)

TRANSACTION (read-only):
  # 1. Vector search
  query_embedding = EMBED(query)
  
  candidates = VECTOR_SEARCH {
    collection: silo_id,
    vector: query_embedding,
    top_k: options.top_k * 3,  # Over-fetch for filtering
    filter: build_filter(options),
  }
  
  # 2. Apply filters
  filtered = []
  FOR candidate IN candidates:
    node = LOOKUP(candidate.id)
    
    # State filter
    IF node.state = TOMBSTONED OR node.state = DELETED:
      CONTINUE
    
    IF node.state = SUPERSEDED AND NOT options.include_superseded:
      CONTINUE
    
    # Temporal filter (as_of)
    IF options.as_of IS NOT NULL:
      IF node.created_at > options.as_of:
        CONTINUE
      IF node.valid_to IS NOT NULL AND node.valid_to < options.as_of:
        CONTINUE
    
    # Layer filter
    IF options.layers IS NOT NULL AND node.layer NOT IN options.layers:
      CONTINUE
    
    # Confidence filter
    IF node.confidence < options.min_confidence:
      CONTINUE
    
    filtered.append(node)
  
  # 3. Score by layer semantics
  scored = []
  FOR node IN filtered:
    score = compute_recall_score(node, query_embedding, options)
    scored.append({ node: node, score: score })
  
  # Sort by score
  scored.sort_by(s => s.score, DESC)
  
  # Take top_k
  results = scored.take(options.top_k)
  
  # 4. Graph traversal (if depth > 0)
  IF options.depth > 0:
    FOR result IN results:
      result.related = traverse_graph(result.node.id, options.depth)
  
  # 5. Lazy synthesis (if enabled)
  synthesis_pending = []
  IF options.include_synthesis:
    clusters = identify_clusters(results.map(r => r.node))
    
    FOR cluster IN clusters:
      IF cluster.state = READY OR cluster.state = STALE:
        IF cluster.current_belief_id IS NULL:
          # Trigger lazy synthesis
          belief_id = TX4_SYNTHESIZE(cluster.id, mode=SYNC)
          
          IF belief_id IS NULL:
            synthesis_pending.append(cluster.id)
          ELSE:
            belief = LOOKUP(belief_id)
            results.append({ node: belief, score: 1.0, synthesized: true })
  
  # 6. Build response
  RETURN Ok(RecallResult {
    results: results.map(r => format_result(r)),
    total_candidates: candidates.length,
    synthesis_pending: synthesis_pending,
    query_time_ms: elapsed(),
  })
```

---

## Helper: COMPUTE_RECALL_SCORE

Computes retrieval score with layer-specific semantics.

```
COMPUTE_RECALL_SCORE(node, query_embedding, options) -> float

# Base similarity score
similarity = cosine_similarity(node.embedding, query_embedding)

# Layer-specific adjustments
SWITCH node.layer:
  CASE MEMORY:
    # Apply freshness decay
    freshness = gaussian_decay(
      age = days_since(node.created_at),
      sigma = MEMORY_DECAY_SIGMA  # default: 90 days
    )
    layer_score = similarity * freshness
  
  CASE KNOWLEDGE:
    # Weight by confidence and corroboration
    confidence_boost = node.confidence
    corroboration_boost = log(1 + node.corroboration_count) / log(10)
    layer_score = similarity * confidence_boost * (1 + corroboration_boost * 0.2)
  
  CASE WISDOM:
    # Weight by evidence strength and freshness
    IF node.synthesis_state = STALE:
      staleness_penalty = 0.5
    ELSE:
      staleness_penalty = 1.0
    
    layer_score = similarity * node.confidence * staleness_penalty
  
  CASE INTELLIGENCE:
    # Session-scoped, no decay
    layer_score = similarity

# Apply heat boost
heat = GET_HEAT(node.id)
heat_boost = 1 + (heat * 0.1)  # Max 10% boost from heat

final_score = layer_score * heat_boost

RETURN clamp(final_score, 0, 1)
```

---

## Helper: TRAVERSE_GRAPH

Retrieves related nodes up to specified depth.

```
TRAVERSE_GRAPH(node_id, max_depth, current_depth=1, visited={}) -> RelatedNode[]

IF current_depth > max_depth:
  RETURN []

visited.add(node_id)

# Get immediate neighbors
neighbors = QUERY {
  MATCH (n)-[e]-(neighbor)
  WHERE n.id = node_id
    AND neighbor.state = ACTIVE
    AND neighbor.id NOT IN visited
  RETURN neighbor, e, 
    CASE WHEN startNode(e) = n THEN 'outgoing' ELSE 'incoming' END as direction
  LIMIT 20  # Cap per node
}

results = []
FOR neighbor IN neighbors:
  results.append(RelatedNode {
    node: neighbor.neighbor,
    edge_type: type(neighbor.e),
    direction: neighbor.direction,
    depth: current_depth,
  })
  
  # Recurse
  IF current_depth < max_depth:
    child_results = TRAVERSE_GRAPH(
      neighbor.neighbor.id, 
      max_depth, 
      current_depth + 1, 
      visited
    )
    results.extend(child_results)

RETURN results
```

---

## Helper: FORMAT_RESULT

Formats a node for recall response with epistemic metadata.

```
FORMAT_RESULT(scored_result) -> RecallItem

node = scored_result.node

RETURN RecallItem {
  node_id: node.id,
  layer: node.layer,
  type: node.type,
  content: node.content,
  
  # Epistemic metadata
  confidence: node.confidence,
  corroboration_count: node.corroboration_count,
  
  # Temporal metadata
  created_at: node.created_at,
  valid_from: node.created_at,
  valid_to: node.valid_to,
  
  # Provenance summary
  evidence_count: count_edges(node.id, DERIVED_FROM),
  source_summary: summarize_sources(node.id),
  
  # Status
  state: node.state,
  synthesis_state: node.synthesis_state,  # For Wisdom
  claim_status: node.claim_status,  # For Knowledge
  
  # Score
  relevance_score: scored_result.score,
  
  # Related (if depth > 0)
  related: scored_result.related,
  
  # Flags
  synthesized_for_query: scored_result.synthesized OR false,
}
```

---

## Summary: All Transactions Complete

| TX | Name | Status |
|----|------|--------|
| TX0 | STORE_MEMORY | Done |
| TX1 | EXTRACT | Deferred (LLM pipeline) |
| TX2 | STORE_CLAIM | Done |
| TX3 | SUPERSEDE | Done |
| TX4 | SYNTHESIZE | Done |
| TX5 | REVISE_BELIEF | Done |
| TX6 | CONSENSUS | Deferred (multi-agent) |
| TX7 | TRACE | Deferred (session cleanup) |
| TX8 | COMMIT | Done |
| TX9 | DECAY | Implicit (query-time) |
| TX10 | HARD_DELETE | Done |
| TX11-13 | PROPOSE/ACCEPT/REJECT | Eliminated |
| TX14 | CRYSTALLIZE | Done |
| TX15 | FORGET | Done |
| TX16 | CANCEL_FORGET | Done |
| TX17 | LINK | Done |
| TX18 | PROMOTE | Done |
| TX19 | DEMOTE | Done |
| RECALL | Query | Done |

**Deferred transactions** (not core to MVP):
- TX1 EXTRACT: Document ingestion pipeline, separate spec
- TX6 CONSENSUS: Multi-agent agreement, post-MVP
- TX7 TRACE: Session cleanup, can use simple expiry initially
