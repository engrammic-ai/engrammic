# Scenario: Wisdom and Memory Research Flow

## Metadata

- **ID:** 006
- **Agents:** 3
- **Duration:** ~10 min
- **Silo:** (default)

## Setup

None (fresh session)

## Instructions

Research topic: **"Why cats purr and dogs don't"**

### Worker 1: Memory Collector

1. Store 5 ephemeral observations (memory layer) as research notes:
   ```
   mcp__engrammic__context_store(
       layer="memory",
       content="Purring originates from laryngeal muscles oscillating at 25-150 Hz",
       decay_class="ephemeral",
       tags=["purring", "physiology", "research-notes"]
   )
   ```
   
   Topics:
   - Purring mechanism (laryngeal muscles)
   - Frequency range and variations
   - Evolutionary theories (mother-kitten communication)
   - Health benefits (bone density, healing)
   - Why dogs evolved barking instead

2. Store 2 durable observations for long-term retention:
   ```
   mcp__engrammic__context_store(
       layer="memory",
       content="<key finding worth keeping>",
       decay_class="durable",
       tags=["purring", "key-finding"]
   )
   ```

3. Report all node IDs with their decay_class

### Worker 2: Wisdom Synthesizer

1. Query Worker 1's observations
2. Create 2 WorkingHypotheses based on the research:
   ```
   mcp__engrammic__context_store(
       layer="belief",
       content="Purring evolved primarily for intraspecies communication, with healing benefits as secondary adaptation",
       confidence=0.7,
       about=["<supporting_observation_ids>"],
       session_id="qa-006-session"
   )
   ```

3. Create 1 wisdom-layer commitment (high-confidence conclusion):
   ```
   mcp__engrammic__context_store(
       layer="wisdom",
       content="Cats and dogs diverged in vocalization strategies due to different social structures: solitary hunters vs pack animals",
       about=["<supporting_node_ids>"],
       reasoning="Synthesis of evolutionary and behavioral evidence"
   )
   ```

4. Report hypothesis and commitment IDs

### Worker 3: Knowledge Graph Navigator

1. Start from a memory node and traverse the graph:
   ```
   mcp__engrammic__context_recall(
       node_ids=["<memory_node_id>"],
       depth=2
   )
   ```

2. Verify the graph structure:
   - Memory nodes link to hypotheses via ABOUT
   - Hypotheses link to wisdom commitments
   - Knowledge facts have evidence chains

3. Query across layers:
   ```
   mcp__engrammic__context_recall(
       query="purring evolution",
       layers=["memory", "knowledge", "wisdom"]
   )
   ```

4. Report the knowledge graph structure found

## Success Criteria

- [ ] Worker 1 created 5 ephemeral + 2 durable memory observations
- [ ] Worker 2 created 2 WorkingHypotheses + 1 Commitment
- [ ] Hypotheses reference memory observations via ABOUT
- [ ] Commitment references supporting evidence
- [ ] Graph traversal from memory reaches wisdom layer
- [ ] Cross-layer search returns results from all specified layers
- [ ] decay_class properly stored on memory nodes

## Notes

Tests the full cognitive layer stack:
- Memory layer with decay classes (ephemeral vs durable)
- Belief layer (WorkingHypothesis) with session scoping
- Wisdom layer (Commitment) for durable conclusions
- Graph navigation across layers
- Cross-layer semantic search

This exercises the EAG paradigm: observations -> hypotheses -> commitments
