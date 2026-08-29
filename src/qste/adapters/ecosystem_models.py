"""Typed outcomes for P11 ecosystem and engine adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class P11AdapterOutcome:
    value: dict[str, Any]
    value_type: str
    receipt_record: dict[str, Any]
    event_sequence: int
    target_id: str
    operation_status: str = "completed"
    reason_code: str = "completed"
    capability_status: str = "available"
