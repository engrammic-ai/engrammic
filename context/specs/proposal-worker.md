# Proposal Worker Spec

## Purpose

Separate Custodian subworker that detects weak synthesis opportunities and creates ProposedBelief nodes for validation. Runs independently from T3 auto-synthesis.

## Trigger

Signal-driven, same as other Custodian workers. Candidates:
- Scheduled interval (e.g., every 5 minutes per silo)
- Piggyback on clustering completion events
- Heat threshold on fact clusters

## Input

For each silo:
1. Fact clusters that meet density threshold but haven't produced a Belief
2. Clusters where synthesis confidence would fall in "weak" range

## Confidence Thresholds

New silo config fields:
```python
class ValidatorThresholds:
    # Existing
    min_edge_confidence: float  # below this = reject
    
    # New
    auto_synthesis_threshold: float = 0.7  # above this = T3 auto-creates Belief
    proposal_threshold: float = 0.4        # above this but below auto = ProposedBelief
    # Below proposal_threshold = no action (too weak)
```

## Logic

```
for cluster in get_synthesis_candidates(silo_id):
    confidence = estimate_synthesis_confidence(cluster)
    
    if confidence >= auto_synthesis_threshold:
        # T3 handles this - skip
        continue
    
    if confidence >= proposal_threshold:
        # Weak but worth surfacing
        create_proposed_belief(
            content=synthesize_content(cluster),
            confidence=confidence,
            synthesized_from=cluster.fact_ids,
        )
```

## Output

ProposedBelief node (Wisdom layer) with:
- `status: 'pending'`
- `confidence`: estimated synthesis confidence
- `SYNTHESIZED_FROM` edges to source Facts

## Scheduling

Options:
1. **Cron**: Run every N minutes per silo
2. **Event-driven**: Trigger after clustering worker completes
3. **Lazy**: Check on next recall query if stale

Recommendation: Start with cron (simple), migrate to event-driven if latency matters.

## Dagster Integration

New asset or sensor in `custodian/pipeline.py`:
```python
@asset(deps=[clustering_asset])
def proposal_detection(context: AssetExecutionContext) -> MaterializeResult:
    """Detect weak synthesis opportunities and create ProposedBeliefs."""
    ...
```

## Files to Modify/Create

- `src/context_service/custodian/proposal_worker.py` (new)
- `src/context_service/custodian/pipeline.py` (add asset)
- `src/context_service/models/silo.py` (add thresholds)
- `src/context_service/config/settings.py` (add defaults)

## Decisions (from review)

1. **TTL:** 7-day expiry. Add `expires_at` field to ProposedBelief.
2. **Per-silo limit:** Max 20 pending proposals. Check before creating.
3. **Recall surfacing:** Add `include_proposals: bool = False` param to context_recall.
4. **Starting threshold:** Use 0.5 (not 0.4) for proposal_threshold initially.

## Implementation Notes

- `estimate_synthesis_confidence()` needed - average confidence of cluster facts weighted by citation count
- `synthesize_content()` - reuse LLM synthesis from `silo_synthesis.py`, but batched
- Follow pattern from `pipelines/sensors/belief_synthesis.py` for cluster detection
- Modify `_LIST_DENSE_CLUSTERS_WITHOUT_BELIEF` to also exclude clusters with pending ProposedBelief
