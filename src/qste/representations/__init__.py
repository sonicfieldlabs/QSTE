"""P5 deterministic STFT/Gabor reference representation."""

from qste.representations.models import (
    RepresentationOperationOutcome,
    STFTConfig,
    stft_config_from_mapping,
)
from qste.representations.stft import STFTService

CAPABILITY_STATUS = "available"
FIRST_PHASE = "P5"

__all__ = [
    "CAPABILITY_STATUS",
    "FIRST_PHASE",
    "RepresentationOperationOutcome",
    "STFTConfig",
    "STFTService",
    "stft_config_from_mapping",
]
