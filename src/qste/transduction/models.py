"""Typed outcomes for bounded P8 mapping and transduction operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TransductionOutcome:
    """One P8 operation plus its durable receipt and event sequence."""

    value: dict[str, Any] | None
    value_type: str
    receipt_record: dict[str, Any]
    event_sequence: int
    operation_status: str = "completed"
    reason_code: str = "completed"
    authorization_status: str = "permitted"
    safety_record_ids: tuple[str, ...] = ()
