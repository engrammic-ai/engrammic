# Scenario: Belief Accept/Reject

## Metadata

- **ID:** 003
- **Agents:** 2
- **Duration:** ~5 min
- **Silo:** qa-test-003

## Setup

Create seed data simulating custodian-generated ProposedBeliefs. The coordinator should store 3 ProposedBeliefs before spawning workers:

```
context_store(
    layer="wisdom",
    content="Users prefer dark mode interfaces",
    node_type="ProposedBelief",
    metadata={"source": "user_survey_synthesis", "proposal_confidence": 0.8},
    silo_id="qa-test-003"
)
```

## Instructions

### Worker 1: Acceptor

1. Query for ProposedBeliefs:
   ```
   context_recall(mode="flat", layer="wisdom", silo_id="qa-test-003")
   ```

2. Accept the first ProposedBelief:
   ```
   context_accept_belief(
       belief_id="<first_proposal_id>",
       silo_id="qa-test-003"
   )
   ```

3. Verify it converted to a Belief (check node_type changed)

4. Report which proposal was accepted

### Worker 2: Rejector

1. Query for remaining ProposedBeliefs

2. Reject one with a reason:
   ```
   context_reject_belief(
       belief_id="<proposal_id>",
       reason="Insufficient sample size in source data",
       silo_id="qa-test-003"
   )
   ```

3. Reject another without a reason:
   ```
   context_reject_belief(
       belief_id="<proposal_id>",
       silo_id="qa-test-003"
   )
   ```

4. Report which proposals were rejected

## Success Criteria

- [ ] 3 ProposedBeliefs existed at start
- [ ] 1 ProposedBelief was accepted and converted to Belief
- [ ] 2 ProposedBeliefs were rejected
- [ ] Rejected proposals are marked with rejection metadata
- [ ] No ProposedBeliefs remain unprocessed

## Notes

Tests the custodian weak synthesis review flow where agents accept/reject system-generated proposals.
