# Agent Guidance

## Engagement Resolution

When recall returns an `engagement` field with markers, you have pending decisions requiring attention.

### Marker Types
- **ProposedBelief**: SAGE synthesized a belief. Use `accept` to ratify or `reject` to decline.
- **Contradiction**: Two claims conflict. Use `believe` with `supersedes` to resolve, then `dismiss` the marker.
- **StaleCommitment**: Commitment outdated by new evidence. Form updated commitment, then `dismiss` the marker.

### Soft vs Hard Mode
- **Soft mode** (`engagement.mode == "soft"`): Markers surfaced, results still available. Resolve when convenient.
- **Hard mode** (`engagement.mode == "hard"`): Results withheld until resolution. Triggered after 3+ unresolved touches.

### Proactive Checking
Call `tick` periodically if you go many turns without recall. It returns engagement state with minimal overhead.
