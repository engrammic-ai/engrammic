# Scenario: Temporal Queries

## Metadata

- **ID:** 009
- **Agents:** 2
- **Duration:** ~7 min
- **Silo:** (default)

## Setup

None

## Instructions

### Worker 1: Timeline Builder

1. Store an initial fact:
   ```
   mcp__engrammic__context_store(
       layer="knowledge",
       content="The recommended daily water intake is 8 glasses",
       evidence=["external:health-guidelines-2020"],
       source_type="external",
       tags=["health", "hydration", "v1"]
   )
   ```

2. Note the timestamp and node_id

3. Wait briefly, then supersede with updated information:
   ```
   mcp__engrammic__context_link(
       from_node="<new_fact_id>",
       to_node="<old_fact_id>",
       relationship="SUPERSEDES",
       note="Updated based on 2024 research"
   )
   ```
   
   Where new_fact is:
   ```
   mcp__engrammic__context_store(
       layer="knowledge",
       content="Daily water intake should be personalized: 30-35ml per kg body weight",
       evidence=["external:health-guidelines-2024"],
       source_type="external",
       tags=["health", "hydration", "v2"]
   )
   ```

4. Report both node IDs and timestamps

### Worker 2: Time Traveler

1. Query current state - should return v2:
   ```
   mcp__engrammic__context_recall(
       query="daily water intake recommendation",
       top_k=5
   )
   ```

2. Query at a past timestamp (before supersession):
   ```
   mcp__engrammic__context_recall(
       node_ids=["<v1_node_id>"],
       as_of="<timestamp_before_supersession>"
   )
   ```

3. Check belief history:
   ```
   mcp__engrammic__context_admin(
       action="belief_history",
       ref="<v2_node_id>"
   )
   ```

4. Verify:
   - Current query returns v2 (superseding fact)
   - Time-travel query returns v1 as valid at that time
   - Belief history shows supersession chain

5. Report temporal query results

## Success Criteria

- [ ] v1 fact stored with valid_from timestamp
- [ ] v2 fact supersedes v1 via SUPERSEDES edge
- [ ] v1 has valid_to set after supersession
- [ ] Current search returns v2 preferentially
- [ ] as_of query returns v1 as valid at past timestamp
- [ ] belief_history shows v2 -> v1 chain

## Notes

Tests temporal/meta-memory features:
- valid_from / valid_to timestamps
- SUPERSEDES relationship
- as_of parameter for time-travel queries
- belief_history admin action
