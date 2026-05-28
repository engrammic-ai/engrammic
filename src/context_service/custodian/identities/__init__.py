"""Four custodian identities per EAG transitions.

- Custodian: T2 (contradiction, supersession)
- Synthesizer: T3/T4/T10 (synthesis, revision, propose)
- Groundskeeper: T6/T9 (trace, memory GC)
- Validator: T13 (crystallize validation)
"""

from context_service.custodian.identities.base import IdentityDeps
from context_service.custodian.identities.custodian import CustodianIdentity
from context_service.custodian.identities.groundskeeper import GroundskeeperIdentity
from context_service.custodian.identities.validator import ValidatorIdentity

__all__ = [
    "IdentityDeps",
    "CustodianIdentity",
    "GroundskeeperIdentity",
    "ValidatorIdentity",
]
