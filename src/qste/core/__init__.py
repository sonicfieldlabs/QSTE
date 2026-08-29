"""Available P2 schemas and P3 canonical identity contracts."""

from qste.core.contracts import (
    CONFORMANCE_PROFILE_ID,
    CONTRACT_ID,
    SCHEMA_SET_ID,
    ContractError,
    SchemaRegistry,
    dumps_json,
    loads_json,
    validate_bundle_closure,
    validate_reference_closure,
)
from qste.core.identity import (
    SemanticKeySpec,
    canonical_json_bytes,
    canonical_json_text,
    content_digest,
    new_record_id,
    semantic_key,
    semantic_key_from_value,
    utc_timestamp,
    validate_utc_timestamp,
    verify_content_digest,
)

CAPABILITY_STATUS = "available"
SCHEMA_CAPABILITY_STATUS = "available"
IDENTITY_STORAGE_CAPABILITY_STATUS = "available"
FIRST_PHASE = "P2"

__all__ = [
    "CAPABILITY_STATUS",
    "CONFORMANCE_PROFILE_ID",
    "CONTRACT_ID",
    "FIRST_PHASE",
    "IDENTITY_STORAGE_CAPABILITY_STATUS",
    "SCHEMA_CAPABILITY_STATUS",
    "SCHEMA_SET_ID",
    "ContractError",
    "SchemaRegistry",
    "SemanticKeySpec",
    "canonical_json_bytes",
    "canonical_json_text",
    "content_digest",
    "dumps_json",
    "loads_json",
    "new_record_id",
    "semantic_key",
    "semantic_key_from_value",
    "utc_timestamp",
    "validate_bundle_closure",
    "validate_reference_closure",
    "validate_utc_timestamp",
    "verify_content_digest",
]
