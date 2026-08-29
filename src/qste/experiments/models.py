"""Typed P12a operation outcome."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ExperimentOutcome:
    value: dict[str, Any]
    value_type: str
    receipt_record: dict[str, Any]
    event_sequence: int
    operation_status: str = "completed"
    reason_code: str = "completed"
