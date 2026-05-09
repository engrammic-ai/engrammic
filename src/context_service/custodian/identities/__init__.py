"""Four custodian identities per EAG transitions.

- Custodian: T2 (contradiction, supersession)
- Synthesizer: T3/T4/T10 (synthesis, revision, propose)
- Groundskeeper: T6/T9 (trace, memory GC)
- Validator: T13 (crystallize validation)
"""

from context_service.custodian.identities.base import IdentityDeps

__all__ = ["IdentityDeps"]
