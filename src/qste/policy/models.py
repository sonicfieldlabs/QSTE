"""Typed outcomes for P8 governance and repair operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    """One event-sourced P8 policy operation and its durable receipt."""

    value: dict[str, Any] | None
    value_type: str
    receipt_record: dict[str, Any]
    event_sequence: int
    operation_status: str = "completed"
    reason_code: str = "completed"
    authorization_status: str = "permitted"
    repair_status: str | None = None
    unresolved_targets: tuple[str, ...] = ()
