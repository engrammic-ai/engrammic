# Self-Hosted Licensing and DRM

**Date:** 2026-05-20
**Status:** Reviewed (ready to implement when customer commits)

---

## Context

Customers like Complink and SmartStorify want self-hosted deployments. We need to protect subscription revenue without creating friction that kills deals.

**What we're protecting:**
- Container images (context-service, custodian workers)
- Helm charts / deployment configs
- Future: local engine binaries

**Customer segments:**
| Segment | Trust level | Air-gap? | Protection needed |
|---------|-------------|----------|-------------------|
| SaaS | N/A | No | None (we run it) |
| Hybrid | Medium | No | Registry gating |
| On-prem | Lower | Sometimes | License enforcement |
| Air-gap | High (usually gov/enterprise) | Yes | Offline license |

---

## Goals

1. Prevent "pay once, run forever" without active subscription
2. Support air-gapped deployments (no phone-home requirement)
3. Minimal engineering effort (we're pre-revenue)
4. Low customer friction (enterprise hates invasive DRM)
5. Graceful degradation, not hard cutoffs

---

## Recommended approach: Layered enforcement

### Layer 1: Registry gating (baseline)

**How it works:**
- Private container registry (GCP Artifact Registry)
- Customer gets pull credentials tied to subscription
- Subscription lapses -> credentials revoked -> no new pulls

**Pros:**
- Zero code changes
- Already have private registry
- Industry standard

**Cons:**
- They can cache images locally and run indefinitely
- Only blocks updates, not continued use

**Verdict:** Necessary but not sufficient.

---

### Layer 2: License key with offline validation

**How it works:**
- Generate signed license key (JWT or similar) at subscription start
- Key contains: customer_id, silo_ids, tier, features, expiry_date
- Service validates signature at startup (no network needed)
- Key signed with our private key, validated with embedded public key

**Key format:**
```json
{
  "iss": "engrammic",
  "sub": "complink",
  "iat": 1747699200,
  "exp": 1779235200,
  "tier": "enterprise",
  "silos": ["complink", "complink-domain"],
  "features": ["synthesis", "reasoning", "federated"],
  "seats": "unlimited"
}
```

**Validation:**
```python
# At service startup
license = load_license_from_env_or_file()
if not verify_signature(license, PUBLIC_KEY):
    raise LicenseInvalid("Invalid license signature")
if license.exp < now():
    enter_grace_period()  # or degraded mode
```

**Pros:**
- Works offline / air-gapped
- Cryptographically secure (can't forge without private key)
- Simple to implement (~1 day)
- Can encode feature flags, tier, limits

**Cons:**
- Key can be shared (mitigated by silo_id binding)
- Requires key rotation workflow

---

### Layer 3: Expiry behavior (graceful degradation)

What happens when the license expires?

| Option | Behavior | Customer impact | Risk |
|--------|----------|-----------------|------|
| **Hard stop** | Service refuses to start | High friction, support load | They hate us |
| **Read-only** | Writes disabled, reads work | Medium - can still query | Might be acceptable |
| **Grace period** | Full function for N days + warnings | Low - time to renew | Standard practice |
| **Warnings only** | Log warnings, full function | None | No enforcement |

**Recommendation:** Grace period (30 days) + read-only after

```
License expires
    |
    v
[Grace period: 30 days]
  - Full functionality
  - Warning logs on every startup
  - Warning banner in admin UI (if we have one)
    |
    v
[Read-only mode]
  - recall, trace, link work
  - remember, learn, believe, commit disabled
  - Clear error: "License expired. Contact sales@engrammic.ai"
    |
    v
[Never: hard stop]
  - We don't brick their system
  - They can always read their data
```

---

### Layer 4: License refresh workflow

**For connected deployments:**
- Auto-refresh: service phones home monthly to get fresh key
- Endpoint: `POST https://license.engrammic.ai/refresh`
- Falls back to existing key if network fails

**For air-gapped deployments:**
- Manual refresh: customer downloads new key from portal annually
- Key validity: 1 year (configurable per contract)
- Reminder emails at 60, 30, 14, 7 days before expiry

---

## Implementation phases

### Phase 0: Registry gating only (now)
- Private Artifact Registry
- Credentials in customer onboarding
- Revoke on churn
- **Effort:** Already done

### Phase 1: License key validation (when first self-hosted customer signs)
- JWT generation in admin portal (or manual for now)
- Startup validation in context-service
- Grace period + read-only degradation
- **Effort:** 1-2 days

### Phase 2: Auto-refresh (when we have multiple self-hosted)
- License refresh endpoint
- Auto-refresh in service
- **Effort:** 1 day

### Phase 3: Feature gating (if needed)
- Tie specific features to license tier
- reasoning profile requires tier >= pro
- synthesis requires tier >= pro
- **Effort:** 0.5 day (just config checks)

---

## What we're NOT doing

1. **Phone-home metering** - Too invasive, breaks air-gap, enterprise hates it
2. **Hardware binding** - Breaks container portability, painful for k8s
3. **Obfuscation/anti-tamper** - Security theater, pisses off customers
4. **Per-seat licensing** - Industry has moved away, we follow
5. **Hard service cutoff** - Never brick their system, they can always read

---

## Contract enforcement (non-technical)

License agreement should include:
- Audit rights (we can verify compliance annually)
- Usage reporting (for air-gap: self-reported quarterly)
- Transferability restrictions (can't resell/sublicense)
- Clear termination terms

For high-trust enterprise (gov, banks): contract + audit often preferred over technical DRM.

---

## Known gaps (acceptable for now)

### Clock manipulation
Customer could roll back system time to keep license valid. Not worth solving pre-revenue. Future mitigation: include `not_before` claim and track "last seen timestamp" in local state file that only moves forward.

### Key rotation on compromise
If signing key leaks, need to rotate. Playbook:
1. Generate new signing keypair
2. Re-sign all active customer keys
3. Push new image with new public key embedded
4. Notify customers to pull new image + key

Document this, don't over-engineer.

### Configurable grace period
Enterprise will negotiate 60/90 days. Make grace period a field in the JWT rather than hardcoded. No code change needed, just validation logic reads from token.

---

## Enterprise buyer perspective

### License portability (feature, not bug)
"Can we restore from backup to a new cluster?" Yes - no hardware binding. This is a selling point for k8s environments. Call it out explicitly in sales conversations.

### Audit logging
Enterprise security teams want to see license checks happen. Add structured log at startup:

```
license_validated: {customer: "complink", expiry: "2027-05-20", tier: "enterprise", silos: ["complink", "complink-domain"]}
```

Trivial to add, helps with SOC2/compliance conversations.

---

## Build vs buy

**Recommendation: Build.**

Existing license key services (Keygen.sh, Cryptlex, LicenseSpring):
- Designed for desktop software with complex needs (machine fingerprinting, floating seats, trials)
- Add dependency and cost not justified for 1-2 day implementation
- We already have the primitives (JWT signing, config validation)

**Reconsider if:** We need a full customer portal with self-service key downloads, usage dashboards, etc. Then Keygen.sh might save time. Post-revenue problem.

---

## Open questions

1. **Key distribution:** Portal download? API? Email? 
2. **Multi-cluster:** One key per cluster or one key covers all?
3. **Offline duration:** 1 year standard, longer for gov contracts?
4. **Pricing impact:** Self-hosted premium (they save us infra cost, but support cost higher)?

---

## Summary

| Layer | Mechanism | Effort | When |
|-------|-----------|--------|------|
| Registry gating | Credential revocation | Done | Now |
| License key | Signed JWT, offline validation | 1-2 days | First self-hosted deal |
| Graceful degradation | Grace period -> read-only | Included above | With license key |
| Auto-refresh | Monthly phone-home (optional) | 1 day | Multiple customers |
| Feature gating | Tier checks | 0.5 day | If needed |

**Bottom line:** Registry gating now, license key when Complink (or similar) commits. Keep it simple, keep it graceful.
