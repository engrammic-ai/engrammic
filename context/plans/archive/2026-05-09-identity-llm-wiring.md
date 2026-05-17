# Identity LLM Wiring Plan

**Goal:** Wire pydantic-ai agents into Custodian and Synthesizer identities to enable actual contradiction detection and belief synthesis.

**Depends on:** Custodian Identity Split (complete)

**Branch:** `feat/identity-llm-wiring`

---

## Overview

The identity split created the structure but left LLM calls stubbed. This plan wires in actual LLM agents:

| Identity | Current | Target |
|----------|---------|--------|
| Custodian | Returns `has_contradiction=False` always | LLM analyzes facts for contradiction |
| Synthesizer | Finds candidates, creates nothing | LLM synthesizes facts into ProposedBeliefs |

---

## Task 1: Custodian Contradiction Agent

**File:** `src/context_service/custodian/identities/custodian.py`

### 1.1 Define result schema

```python
from pydantic import BaseModel

class ContradictionAnalysis(BaseModel):
    """LLM output for contradiction check."""
    has_contradiction: bool
    supersedes: list[str] = []  # IDs of facts the new one supersedes
    reasoning: str
    confidence: float  # 0-1
```

### 1.2 Create pydantic-ai agent

```python
from pydantic_ai import Agent

def _build_contradiction_agent(model: str) -> Agent[None, ContradictionAnalysis]:
    return Agent(
        model=model,
        result_type=ContradictionAnalysis,
        system_prompt="""You analyze facts for logical contradiction.

Given a NEW fact and EXISTING facts with the same subject/predicate:
1. Determine if the new fact contradicts any existing facts
2. If so, identify which existing facts are superseded
3. Provide brief reasoning
4. Rate your confidence (0-1)

A contradiction exists when facts cannot both be true simultaneously.
Temporal updates (newer info replacing older) count as supersession.""",
    )
```

### 1.3 Update check_contradiction method

```python
async def check_contradiction(self, fact_id: str) -> ContradictionResult:
    similar = await self.store.execute_query(SIMILAR_FACTS_QUERY, {...})
    
    if not similar:
        return ContradictionResult(has_contradiction=False)
    
    # Fetch the new fact content
    new_fact = await self.store.execute_query(
        "MATCH (f:Fact {id: $id, silo_id: $silo_id}) RETURN f.content AS content",
        {"id": fact_id, "silo_id": self.silo_id},
    )
    
    # Build prompt context
    prompt = f"""NEW FACT: {new_fact[0]["content"]}

EXISTING FACTS:
{chr(10).join(f'- [{f["fact_id"]}]: {f["content"]}' for f in similar)}

Analyze for contradiction."""

    # Run LLM
    agent = _build_contradiction_agent(self.model)
    result = await agent.run(prompt)
    
    return ContradictionResult(
        has_contradiction=result.data.has_contradiction,
        supersedes_ids=result.data.supersedes,
        reason=result.data.reasoning,
    )
```

### 1.4 Add timeout and fallback

```python
async def check_contradiction(self, fact_id: str) -> ContradictionResult:
    # ... setup ...
    
    try:
        result = await asyncio.wait_for(
            agent.run(prompt),
            timeout=self._timeout_seconds,
        )
    except TimeoutError:
        logger.warning("custodian.llm_timeout", fact_id=fact_id)
        return ContradictionResult(has_contradiction=False)  # fail-open
    except Exception as e:
        logger.error("custodian.llm_error", error=str(e))
        return ContradictionResult(has_contradiction=False)
```

---

## Task 2: Synthesizer Synthesis Agent

**File:** `src/context_service/custodian/identities/synthesizer.py`

### 2.1 Define result schema

```python
class SynthesisResult(BaseModel):
    """LLM output for belief synthesis."""
    belief_statement: str
    confidence: float  # 0-1
    supporting_fact_ids: list[str]
    reasoning: str
```

### 2.2 Create pydantic-ai agent

```python
def _build_synthesis_agent(model: str) -> Agent[None, SynthesisResult]:
    return Agent(
        model=model,
        result_type=SynthesisResult,
        system_prompt="""You synthesize related facts into belief statements.

Given a cluster of related facts:
1. Identify the common theme or assertion
2. Formulate a single belief statement that captures the synthesis
3. Rate confidence based on fact agreement (0-1)
4. List which facts directly support this belief

A belief should be:
- More general than individual facts
- Supported by multiple facts
- Stated as a confident assertion""",
    )
```

### 2.3 Update run_synthesis method

```python
async def run_synthesis(self) -> dict:
    candidates = await self.find_synthesis_candidates()
    
    if not candidates:
        return {"candidates": 0, "created": 0, "silo_id": self.silo_id}
    
    agent = _build_synthesis_agent(self.model)
    created = []
    
    for candidate in candidates:
        # Fetch facts in cluster
        facts = await self.store.execute_query(
            "MATCH (c:Cluster {id: $cluster_id})-[:CONTAINS]->(f:Fact) RETURN f.id AS id, f.content AS content",
            {"cluster_id": candidate["cluster_id"]},
        )
        
        if len(facts) < self.min_facts_for_synthesis:
            continue
        
        prompt = f"""FACTS IN CLUSTER:
{chr(10).join(f'- [{f["id"]}]: {f["content"]}' for f in facts)}

Synthesize into a belief statement."""

        try:
            result = await asyncio.wait_for(agent.run(prompt), timeout=60)
        except Exception as e:
            logger.warning("synthesizer.llm_error", cluster=candidate["cluster_id"], error=str(e))
            continue
        
        # Create ProposedBelief
        if result.data.confidence >= self._proposal_threshold:
            proposal_id = await self._create_proposed_belief(
                content=result.data.belief_statement,
                confidence=result.data.confidence,
                supporting_facts=result.data.supporting_fact_ids,
                cluster_id=candidate["cluster_id"],
            )
            if proposal_id:
                created.append(proposal_id)
    
    return {"candidates": len(candidates), "created": len(created), "silo_id": self.silo_id}
```

### 2.4 Add ProposedBelief creation helper

```python
async def _create_proposed_belief(
    self,
    content: str,
    confidence: float,
    supporting_facts: list[str],
    cluster_id: str,
) -> str | None:
    """Create ProposedBelief node with COVERS edge to cluster."""
    import uuid
    from datetime import UTC, datetime
    
    proposal_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    
    await self.store.execute_write(
        """
        CREATE (p:ProposedBelief {
            id: $id,
            silo_id: $silo_id,
            content: $content,
            confidence: $confidence,
            created_at: $created_at,
            status: 'pending'
        })
        WITH p
        MATCH (c:Cluster {id: $cluster_id, silo_id: $silo_id})
        MERGE (p)-[:COVERS]->(c)
        WITH p
        UNWIND $fact_ids AS fid
        MATCH (f:Fact {id: fid, silo_id: $silo_id})
        MERGE (p)-[:DERIVED_FROM]->(f)
        """,
        {
            "id": proposal_id,
            "silo_id": self.silo_id,
            "content": content,
            "confidence": confidence,
            "created_at": now,
            "cluster_id": cluster_id,
            "fact_ids": supporting_facts,
        },
    )
    
    logger.info(
        "synthesizer.proposed_belief_created",
        proposal_id=proposal_id,
        cluster_id=cluster_id,
        confidence=confidence,
    )
    
    return proposal_id
```

---

## Task 3: Tests

### 3.1 Custodian LLM tests

```python
# tests/custodian/identities/test_custodian_llm.py

@pytest.mark.asyncio
async def test_contradiction_detection_with_llm(mock_llm):
    """Test that LLM is called when similar facts exist."""
    mock_store = AsyncMock()
    mock_store.execute_query.side_effect = [
        [{"fact_id": "old", "content": "X is true"}],  # similar facts
        [{"content": "X is false"}],  # new fact
    ]
    
    mock_llm.return_value = ContradictionAnalysis(
        has_contradiction=True,
        supersedes=["old"],
        reasoning="Direct negation",
        confidence=0.9,
    )
    
    custodian = CustodianIdentity(store=mock_store, silo_id="test", model="test")
    result = await custodian.check_contradiction("new")
    
    assert result.has_contradiction is True
    assert "old" in result.supersedes_ids
```

### 3.2 Synthesizer LLM tests

```python
# tests/custodian/identities/test_synthesizer_llm.py

@pytest.mark.asyncio
async def test_synthesis_creates_proposed_belief(mock_llm):
    """Test that synthesis creates ProposedBelief nodes."""
    mock_store = AsyncMock()
    mock_store.execute_query.side_effect = [
        [{"cluster_id": "c1", "fact_count": 5, "confidence": 0.8}],  # candidates
        [{"id": "f1", "content": "Fact 1"}, {"id": "f2", "content": "Fact 2"}],  # facts
    ]
    
    mock_llm.return_value = SynthesisResult(
        belief_statement="Synthesized belief",
        confidence=0.85,
        supporting_fact_ids=["f1", "f2"],
        reasoning="Facts agree",
    )
    
    synthesizer = SynthesizerIdentity(store=mock_store, silo_id="test", model="test")
    result = await synthesizer.run_synthesis()
    
    assert result["created"] == 1
    mock_store.execute_write.assert_called_once()
```

---

## Task 4: Config Updates

### 4.1 Add LLM-specific settings

```python
# In settings.py CustodianIdentityConfig:

class CustodianIdentityConfig(BaseModel):
    # ... existing ...
    contradiction_prompt_version: str = "v1"
    min_confidence_for_supersession: float = 0.7


class SynthesizerIdentityConfig(BaseModel):
    # ... existing ...
    synthesis_prompt_version: str = "v1"
    proposal_confidence_threshold: float = 0.6
    max_facts_per_synthesis: int = 10
```

---

## Verification

1. Unit tests with mocked LLM responses
2. Integration test with real LLM (optional, expensive)
3. Manual test: store contradicting facts, verify SUPERSEDES edge created
4. Manual test: store related facts, verify ProposedBelief created

---

## Risks

| Risk | Mitigation |
|------|------------|
| LLM latency | Timeouts + fail-open |
| LLM cost | Batching, caching, model selection |
| Hallucinated fact IDs | Validate IDs exist before creating edges |
| Prompt injection | Facts are user content - sanitize or use structured input |

---

## Out of Scope

- Validator LLM (reasoning structure validation) - separate plan
- Groundskeeper LLM (none needed - deterministic)
- Prompt tuning and evaluation - separate spike
