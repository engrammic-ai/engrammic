# Scenario: Multi-Agent Memory Sharing

## Metadata

- **ID:** 001
- **Agents:** 3
- **Duration:** ~5 min
- **Silo:** qa-test-001

## Setup

None (fresh silo)

## Instructions

### All Workers

1. Store 3 observations to memory layer about your assigned topic:
   - Worker 1: "distributed systems"
   - Worker 2: "data consistency"
   - Worker 3: "fault tolerance"

2. Query the silo for observations from other workers using semantic search:
   ```
   context_recall(mode="search", query="<other worker's topic>", silo_id="qa-test-001")
   ```

3. Create a RELATES_TO link between one of your observations and one from another worker

4. Report back with:
   - Your node IDs
   - Node IDs you linked to
   - Any retrieval issues

## Success Criteria

- [ ] Each worker stored exactly 3 observations
- [ ] Each worker successfully retrieved observations from at least 1 other worker
- [ ] Each worker created at least 1 cross-worker link
- [ ] Total of 9 observations in silo
- [ ] At least 3 cross-worker links exist

## Notes

Tests basic multi-tenant memory operations and cross-agent discovery via semantic search.
