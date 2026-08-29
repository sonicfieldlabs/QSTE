"""Typed outcomes for P6 task execution and DSQ assessment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class QuantaOperationOutcome:
    """One persisted P6 result with its durable receipt and event sequence."""

    value: dict[str, Any]
    value_type: str
    receipt_record: dict[str, Any]
    event_sequence: int
