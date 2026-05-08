"""Cypher queries for retention operations."""

FIND_TOMBSTONE_CANDIDATES = """
MATCH (n {silo_id: $silo_id})
WHERE n.decay_class IS NOT NULL
  AND n.tombstoned_at IS NULL
  AND n.decay_class <> 'permanent'
RETURN n.id AS id,
       n.decay_class AS decay_class,
       n.created_at AS created_at,
       coalesce(n.heat_score, 0.5) AS heat_score
"""

TOMBSTONE_NODE = """
MATCH (n {id: $id, silo_id: $silo_id})
WHERE n.tombstoned_at IS NULL
SET n.tombstoned_at = $tombstoned_at,
    n.retention_run_id = $run_id
RETURN n.id AS id
"""

FIND_HARD_DELETE_CANDIDATES = """
MATCH (n {silo_id: $silo_id})
WHERE n.tombstoned_at IS NOT NULL
  AND n.tombstoned_at < $grace_cutoff
RETURN n.id AS id
"""

HARD_DELETE_NODE = """
MATCH (n {id: $id, silo_id: $silo_id})
DETACH DELETE n
"""

FIND_EXCESS_META_OBSERVATIONS = """
MATCH (n:MetaObservation {silo_id: $silo_id})
WHERE n.tombstoned_at IS NULL
WITH n ORDER BY n.created_at DESC
SKIP $keep_count
RETURN n.id AS id
"""

MARK_HEAT_DIRTY = """
MATCH (n {silo_id: $silo_id})
WHERE n.id IN $node_ids
SET n.heat_dirty = true
"""

FIND_ORPHANED_SUMMARIES = """
MATCH (e:Event {silo_id: $silo_id})
WHERE e.event_type = 'reasoning_trace'
  AND e.source_chain_id IS NOT NULL
  AND e.tombstoned_at IS NULL
WITH e
OPTIONAL MATCH (c:ReasoningChain {id: e.source_chain_id, silo_id: $silo_id})
WHERE c IS NULL
RETURN e.id AS id
"""
