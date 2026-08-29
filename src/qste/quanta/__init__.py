"""P6 task execution, candidate assessment, baselines, and invalidation."""

from qste.quanta.models import QuantaOperationOutcome
from qste.quanta.service import QuantaService

CAPABILITY_STATUS = "available"
FIRST_PHASE = "P6"

__all__ = [
    "CAPABILITY_STATUS",
    "FIRST_PHASE",
    "QuantaOperationOutcome",
    "QuantaService",
]
