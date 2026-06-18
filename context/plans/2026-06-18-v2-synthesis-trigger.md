# V2 Synthesis Trigger

**Status:** Complete (commit 7b6982ac)  
**Branch:** feat/v2-synthesis-trigger  
**Context:** CITE v2 replaces cluster-based synthesis with direct corroboration

## Background

V1 synthesis: cluster reaches N facts -> synthesize belief from cluster members.
V2 synthesis: facts with high semantic similarity + shared entity -> synthesize directly.

CORROBORATES edges are already created during extraction (reactions/tasks.py) when
similar claims are found. V2 adds entity-based corroboration check.

## Corroboration Criteria

Two Facts corroborate when:
1. Semantic similarity >= 0.85 (embedding cosine distance)
2. Share at least one entity via MENTIONS edges

Graph query for shared entity:
```cypher
MATCH (a:Fact)-[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(b:Fact)
WHERE a.id = $fact_a_id AND b.id = $fact_b_id
RETURN count(e) > 0 AS shares_entity
```

## Independence Scoring

Each corroborating fact gets an independence score (0.2 to 1.0):

| Factor | Score Contribution |
|--------|-------------------|
| Different document | +0.3 |
| Different agent | +0.3 |
| Temporal gap > 24h | +0.2 |
| Different source tier | +0.2 |
| Base score | 0.2 |

Score is capped at 1.0.

## Synthesis Threshold

sum(independence scores) >= 2.0 triggers synthesis.

Examples:
- 2 facts from different docs/agents: 0.8 + 0.8 = 1.6 (not enough)
- 3 facts from different docs/agents: 0.8 * 3 = 2.4 (triggers)
- 2 facts + temporal gap + different tier: 1.0 + 1.0 = 2.0 (triggers)

## Deployment Tiers

| Tier | Entity Extraction | When to use |
|------|------------------|-------------|
| FULL | LLM-based | Cloud deployment |
| LITE | spaCy NER | Self-hosted, no LLM calls |
| DISABLED | None | Minimal footprint |

LITE mode uses spaCy's en_core_web_sm for NER. Entities: PERSON, ORG, GPE, DATE, etc.

## Implementation Tasks

### 1. Entity extraction service (new module)
- `src/context_service/synthesis/entities.py`
- Abstract base + FULL/LITE/DISABLED implementations
- Factory based on settings

### 2. Independence scorer
- `src/context_service/synthesis/independence.py`
- Score calculation logic
- Fetch metadata from graph

### 3. Synthesis trigger
- `src/context_service/synthesis/trigger.py`
- Query corroborating facts
- Calculate independence sum
- Emit synthesis request when threshold met

### 4. Dagster asset
- `src/context_service/pipelines/assets/synthesis_trigger.py`
- Silo-partitioned
- Scans facts, checks corroboration, triggers synthesis

### 5. Integration with extraction flow
- Update reactions/tasks.py to call entity extraction
- Create MENTIONS edges during extraction

### 6. Settings
- Add SynthesisSettings to config
- Tier selection, thresholds

## Acceptance Criteria

- [x] Entity extraction with FULL/LITE/DISABLED tiers
- [x] Independence scoring calculates correctly
- [x] Synthesis triggers at threshold
- [x] MENTIONS edges created during extraction
- [x] Dagster asset runs per-silo
- [x] `just check` passes
- [ ] Tests for each component (deferred)
