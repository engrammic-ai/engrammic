# Future: Federated Silos

**Status:** Speculation (not scheduled)
**Trigger:** Customer commitment (Complink or similar platform operator)

---

## Problem

Platform operators (e.g., Complink serving construction companies) want:
- Isolated silos per customer for proprietary context
- Shared domain silo for curated knowledge all customers can read
- Simple config, not per-query complexity

## Proposed solution

Add `linked_silos` field to silo config:

```python
{
  "silo_id": "customer-acme",
  "linked_silos": ["complink-domain"],  # read-only includes
  "owner_org": "complink"
}
```

Service layer change: queries fan out to `[silo_id, ...linked_silos]`, merge results.

## API surface

```
POST /admin/silos/{silo_id}/link
  body: { "target_silo_id": "complink-domain", "access": "read" }

DELETE /admin/silos/{silo_id}/link/{target_silo_id}

GET /admin/silos/{silo_id}/links
```

## Effort

~0.5 day for core implementation, ~1 day with API + tests.

## Notes

- Write isolation enforced at service layer (linked silos are read-only)
- No graph-level changes needed (silo_id is just a partition key)
- Result merging already works, just needs wiring
