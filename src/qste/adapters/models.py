"""Typed outcomes for bounded P9 external-representation adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AdapterOutcome:
    """One adapter operation with a durable operation receipt."""

    value: dict[str, Any]
    value_type: str
    receipt_record: dict[str, Any]
    event_sequence: int
    adapter_id: str
