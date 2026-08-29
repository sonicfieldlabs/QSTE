"""P4 record construction helpers with explicit identity layers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from qste.core import new_record_id, semantic_key_from_value
from qste.core.contracts import BASE_URI


def record_ref(record_id: str, record_type: str, relation: str = "depends_on") -> dict[str, str]:
    return {"record_id": record_id, "record_type": record_type, "relation": relation}


def record_base(
    record_type: str,
    *,
    created_at: str,
    producer_role: str = "executor",
    disclosure_status: str = "private",
    integrity_status: str = "verified",
    record_id: str | None = None,
    references: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    slug = "".join(
        ("-" + character.lower()) if character.isupper() else character for character in record_type
    ).lstrip("-")
    return {
        "record_type": record_type,
        "schema_id": f"{BASE_URI}/records/{slug}.schema.json",
        "contract_id": "qste-contract/0.3.0",
        "record_id": record_id or new_record_id(record_type),
        "created_at": created_at,
        "producer_role": producer_role,
        "integrity_status": integrity_status,
        "disclosure_status": disclosure_status,
        "references": [dict(reference) for reference in references],
    }


def bind_semantic_key(record: dict[str, Any], type_id: str, fields: Mapping[str, Any]) -> None:
    record["semantic_key"] = semantic_key_from_value(type_id, dict(fields))


def operation_receipt(
    *,
    created_at: str,
    request_ref: Mapping[str, Any],
    authorization_status: str,
    operation: str,
    inputs: Sequence[Any],
    parameters: Mapping[str, Any],
    outputs: Sequence[Any],
    operation_status: str = "completed",
    record_id: str | None = None,
    tool_id: str = "qste-p4-kernel",
    tool_version: str = "0.1",
) -> dict[str, Any]:
    receipt = record_base(
        "OperationReceipt",
        created_at=created_at,
        record_id=record_id,
    ) | {
        "request_ref": dict(request_ref),
        "authorization_status": authorization_status,
        "actor": "qste-local-executor",
        "tool": {"id": tool_id, "version": tool_version},
        "inputs": list(inputs),
        "parameters": dict(parameters) or {"mode": "none"},
        "outputs": list(outputs) or [{"availability": "not_applicable"}],
        "operation_status": operation_status,
        "qste:operation": operation,
    }
    bind_semantic_key(
        receipt,
        "qste-semantic-key/operation-receipt-p4-v1",
        {
            "operation": operation,
            "request_ref": dict(request_ref),
            "authorization_status": authorization_status,
            "inputs": list(inputs),
            "parameters": dict(parameters),
            "outputs": list(outputs),
            "operation_status": operation_status,
        },
    )
    return receipt
