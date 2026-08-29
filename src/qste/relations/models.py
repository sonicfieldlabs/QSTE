"""Typed outcomes for P7 projection and relation operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RelationOperationOutcome:
    """One persisted P7 result with its durable receipt and event sequence."""

    value: dict[str, Any]
    value_type: str
    receipt_record: dict[str, Any]
    event_sequence: int
