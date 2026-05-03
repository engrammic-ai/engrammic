"""Cypher queries for retention operations."""

FIND_TOMBSTONE_CANDIDATES = """
MATCH (n {silo_id: $silo_id})
WHERE n.decay_class IS NOT NULL
  AND NOT exists(n.tombstoned_at)
  AND n.decay_class <> 'permanent'
RETURN n.id AS id,
       n.decay_class AS decay_class,
       n.created_at AS created_at,
       coalesce(n.heat_score, 0.5) AS heat_score
"""

TOMBSTONE_NODE = """
MATCH (n {id: $id, silo_id: $silo_id})
WHERE NOT exists(n.tombstoned_at)
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
WHERE NOT exists(n.tombstoned_at)
WITH n ORDER BY n.created_at DESC
SKIP $keep_count
RETURN n.id AS id
"""

MARK_HEAT_DIRTY = """
MATCH (n {silo_id: $silo_id})
WHERE n.id IN $node_ids
SET n.heat_dirty = true
"""
