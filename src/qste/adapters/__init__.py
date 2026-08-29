"""Bounded P9 representation and P11 ecosystem/engine adapters."""

from qste.adapters.contracts import (
    ADAPTER_PROFILE,
    CAPTURE_PROFILE,
    CONFORMANCE_PROFILE,
    ENCODEC_TARGET,
    OPERATIONS,
    SAMPLEBRAIN_TARGET,
)
from qste.adapters.ecosystem_contracts import (
    COMPATIBILITY_PROFILE,
    ECOSYSTEM_PROFILE,
    ENGINE_CAPABILITIES,
    ENGINE_PROFILE,
    TARGETS,
)
from qste.adapters.ecosystem_models import P11AdapterOutcome
from qste.adapters.ecosystem_service import BoundedEngineService, EcosystemAdapterService
from qste.adapters.models import AdapterOutcome
from qste.adapters.service import ExternalRepresentationService

CAPABILITY_STATUS = "available"
FIRST_PHASE = "P9"

__all__ = [
    "ADAPTER_PROFILE",
    "CAPABILITY_STATUS",
    "CAPTURE_PROFILE",
    "COMPATIBILITY_PROFILE",
    "CONFORMANCE_PROFILE",
    "ECOSYSTEM_PROFILE",
    "ENCODEC_TARGET",
    "ENGINE_CAPABILITIES",
    "ENGINE_PROFILE",
    "FIRST_PHASE",
    "OPERATIONS",
    "SAMPLEBRAIN_TARGET",
    "TARGETS",
    "AdapterOutcome",
    "BoundedEngineService",
    "EcosystemAdapterService",
    "ExternalRepresentationService",
    "P11AdapterOutcome",
]
