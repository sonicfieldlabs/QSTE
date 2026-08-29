"""Typed P5 STFT/Gabor configuration and operation outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from qste.core.contracts import ContractError


@dataclass(frozen=True, slots=True)
class STFTConfig:
    fft_length: int = 256
    hop_length: int = 64
    window_family: Literal["hann_periodic"] = "hann_periodic"
    coefficient_dtype: Literal["complex64", "complex128"] = "complex128"
    reconstruction_atol: float = 1e-10
    reconstruction_rtol: float = 1e-10
    maximum_candidates: int = 4096
    maximum_refinement_nodes: int = 4094
    footprint_floor: float = 1e-12


@dataclass(frozen=True, slots=True)
class RepresentationOperationOutcome:
    value: dict[str, Any]
    value_type: str
    receipt_record: dict[str, Any]
    event_sequence: int


def stft_config_from_mapping(value: Mapping[str, Any]) -> STFTConfig:
    """Build an exact STFTConfig from a strict JSON-facing mapping."""

    allowed = {
        "fft_length",
        "hop_length",
        "window_family",
        "coefficient_dtype",
        "reconstruction_atol",
        "reconstruction_rtol",
        "maximum_candidates",
        "maximum_refinement_nodes",
        "footprint_floor",
    }
    if not set(value).issubset(allowed):
        raise ContractError("invalid_input", "STFT config contains unknown fields")
    try:
        return STFTConfig(
            fft_length=cast(int, value.get("fft_length", 256)),
            hop_length=cast(int, value.get("hop_length", 64)),
            window_family=cast(Any, value.get("window_family", "hann_periodic")),
            coefficient_dtype=cast(Any, value.get("coefficient_dtype", "complex128")),
            reconstruction_atol=cast(float, value.get("reconstruction_atol", 1e-10)),
            reconstruction_rtol=cast(float, value.get("reconstruction_rtol", 1e-10)),
            maximum_candidates=cast(int, value.get("maximum_candidates", 4096)),
            maximum_refinement_nodes=cast(int, value.get("maximum_refinement_nodes", 4094)),
            footprint_floor=cast(float, value.get("footprint_floor", 1e-12)),
        )
    except (TypeError, ValueError) as error:
        raise ContractError("invalid_input", "STFT config values are invalid") from error
