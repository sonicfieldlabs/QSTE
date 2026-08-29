"""Bounded cross-arm projection, comparison, and disagreement operations."""

from qste.relations.models import RelationOperationOutcome
from qste.relations.service import RelationService

CAPABILITY_STATUS = "available"
FIRST_PHASE = "P7"

__all__ = [
    "CAPABILITY_STATUS",
    "FIRST_PHASE",
    "RelationOperationOutcome",
    "RelationService",
]
