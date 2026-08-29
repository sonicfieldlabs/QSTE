"""Typed request and outcome models for bounded P4 ingress."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from qste.core.contracts import ContractError
from qste.core.p4_contracts import INGRESS_KINDS

IngressKind = Literal[
    "audio", "json_observations", "csv_observations", "text", "model_observations"
]


@dataclass(frozen=True, slots=True)
class IngressLimits:
    allowed_roots: tuple[Path, ...]
    maximum_bytes: Mapping[str, int] = field(
        default_factory=lambda: {
            "audio": 256 * 1024 * 1024,
            "json_observations": 16 * 1024 * 1024,
            "csv_observations": 16 * 1024 * 1024,
            "text": 16 * 1024 * 1024,
            "model_observations": 16 * 1024 * 1024,
        }
    )
    maximum_observations: int = 100_000
    maximum_columns: int = 64
    maximum_cell_characters: int = 65_536

    def __post_init__(self) -> None:
        if not self.allowed_roots:
            raise ValueError("ingress requires at least one explicit allowed root")
        if self.maximum_observations < 1 or self.maximum_columns < 1:
            raise ValueError("ingress row and column bounds must be positive")
        if set(self.maximum_bytes) != INGRESS_KINDS or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in self.maximum_bytes.values()
        ):
            raise ValueError("ingress byte bounds must cover every P4 kind")

    def byte_limit(self, kind: str) -> int:
        if kind not in INGRESS_KINDS:
            raise ContractError("invalid_input", f"unknown P4 ingress kind: {kind}")
        return self.maximum_bytes[kind]


@dataclass(frozen=True, slots=True)
class AudioTransform:
    target_sample_rate_hz: int | None = None
    normalization: Literal["none", "peak"] = "none"
    target_peak: float = 0.99
    output_dtype: Literal["float32", "float64"] = "float64"


@dataclass(frozen=True, slots=True)
class IngressOutcome:
    source_record: dict[str, Any]
    acquisition_record: dict[str, Any]
    original_artifact_record: dict[str, Any]
    result_artifact_record: dict[str, Any]
    derivative_artifact_records: tuple[dict[str, Any], ...]
    observation_records: tuple[dict[str, Any], ...]
    receipt_record: dict[str, Any]
    event_sequence: int


@dataclass(frozen=True, slots=True)
class ApparatusOutcome:
    apparatus_record: dict[str, Any]
    receipt_record: dict[str, Any]
    event_sequence: int


@dataclass(frozen=True, slots=True)
class ApertureOutcome:
    aperture_record: dict[str, Any]
    run_record: dict[str, Any]
    receipt_record: dict[str, Any]
    event_sequence: int
