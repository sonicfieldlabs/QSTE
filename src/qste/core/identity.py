"""P3 canonicalization and non-substitutable QSTE identity layers."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import rfc8785

from qste.core.contracts import ContractError

_VOLATILE_FIELDS = frozenset({"record_id", "created_at", "content_digest"})
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@dataclass(frozen=True, slots=True)
class SemanticKeySpec:
    """A versioned, typed selection of fields that define semantic identity."""

    spec_id: str
    record_type: str
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.spec_id or not self.record_type or not self.fields:
            raise ValueError("semantic-key specifications require an ID, type, and fields")
        prohibited = _VOLATILE_FIELDS.intersection(self.fields)
        if prohibited:
            names = ", ".join(sorted(prohibited))
            raise ValueError(f"volatile identity fields are prohibited: {names}")
        if len(self.fields) != len(set(self.fields)):
            raise ValueError("semantic-key fields must be unique")


def canonical_json_bytes(value: Any) -> bytes:
    """Return exact RFC 8785 bytes for an I-JSON-compatible value."""

    _validate_json_value(value)
    try:
        return bytes(rfc8785.dumps(value))
    except rfc8785.CanonicalizationError as error:
        raise ContractError("invalid_input", f"value cannot be canonicalized: {error}") from error


def canonical_json_text(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def content_digest(data: bytes | bytearray | memoryview) -> str:
    """Return byte identity; this is never a record or semantic identity."""

    return f"sha256:{hashlib.sha256(bytes(data)).hexdigest()}"


def verify_content_digest(data: bytes | bytearray | memoryview, expected: str) -> bool:
    if not _DIGEST_PATTERN.fullmatch(expected):
        return False
    return content_digest(data) == expected


def semantic_key(record: Mapping[str, Any], spec: SemanticKeySpec) -> str:
    """Hash only the typed semantic fields declared by ``spec``."""

    if record.get("record_type") != spec.record_type:
        raise ContractError(
            "invalid_input",
            f"semantic-key spec {spec.spec_id} requires {spec.record_type}",
        )
    missing = [field for field in spec.fields if field not in record]
    if missing:
        raise ContractError(
            "invalid_input",
            f"semantic-key fields are missing: {', '.join(missing)}",
        )
    typed_tuple = {
        "semantic_key_spec": spec.spec_id,
        "record_type": spec.record_type,
        "fields": {field: record[field] for field in spec.fields},
    }
    return content_digest(canonical_json_bytes(typed_tuple))


def semantic_key_from_value(type_id: str, value: Any) -> str:
    """Hash a caller-supplied typed tuple without adding occurrence metadata."""

    if not type_id:
        raise ContractError("invalid_input", "semantic identity requires a type identifier")
    return content_digest(canonical_json_bytes({"type_id": type_id, "value": value}))


def new_record_id(record_type: str, *, uuid_value: uuid.UUID | None = None) -> str:
    """Create a random UUIDv4 occurrence identity in the QSTE namespace."""

    if not record_type or not record_type[0].isalpha():
        raise ContractError("invalid_input", "record type cannot form a QSTE record ID")
    value = uuid_value or uuid.uuid4()
    if value.version != 4 or value.variant != uuid.RFC_4122:
        raise ContractError("invalid_input", "QSTE record IDs require an RFC 4122 UUIDv4")
    first_pass = re.sub(r"(.)([A-Z][a-z]+)", r"\1-\2", record_type)
    record_slug = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", first_pass).lower()
    if not re.fullmatch(r"[a-z][a-z0-9-]*", record_slug):
        raise ContractError("invalid_input", "record type cannot form a canonical QSTE slug")
    return f"qste:{record_slug}:{value}"


def utc_timestamp(value: datetime | None = None) -> str:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ContractError("invalid_input", "timestamps require an explicit timezone")
    normalized = instant.astimezone(UTC).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def validate_utc_timestamp(value: str) -> str:
    """Require the canonical UTC, whole-second timestamp used by P3 stores."""

    try:
        if not _TIMESTAMP_PATTERN.fullmatch(value):
            raise ValueError
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ContractError("invalid_input", "timestamp must be canonical UTC seconds") from error
    return value


def _validate_json_value(value: Any, path: Sequence[str | int] = ()) -> None:
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, (*path, index))
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(
                    "invalid_input",
                    "canonical JSON object keys must be strings",
                    path=path,
                )
            _validate_json_value(item, (*path, key))
        return
    location = "/".join(str(part) for part in path) or "<root>"
    raise ContractError(
        "invalid_input",
        f"non-JSON value at {location}: {type(value).__name__}",
        path=path,
    )
