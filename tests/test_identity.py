from __future__ import annotations

import math
import uuid

import pytest

from qste.core import (
    SemanticKeySpec,
    canonical_json_bytes,
    content_digest,
    new_record_id,
    semantic_key,
    semantic_key_from_value,
)
from qste.core.contracts import ContractError


def test_rfc8785_canonicalization_is_order_and_number_stable() -> None:
    assert canonical_json_bytes({"z": 1.0, "a": "é"}) == canonical_json_bytes({"a": "é", "z": 1})
    assert canonical_json_bytes({"z": 1.0, "a": "é"}) == b'{"a":"\xc3\xa9","z":1}'


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_numbers_cannot_cross_the_canonical_boundary(value: float) -> None:
    with pytest.raises(ContractError, match="canonical"):
        canonical_json_bytes({"value": value})


def test_semantic_identity_ignores_only_declared_nonsemantic_variation() -> None:
    spec = SemanticKeySpec(
        "qste-semantic-key/source-locator-v1",
        "SourceRecord",
        ("locator", "rights"),
    )
    first = {
        "record_type": "SourceRecord",
        "record_id": new_record_id(
            "SourceRecord", uuid_value=uuid.UUID("10000000-0000-4000-8000-000000000001")
        ),
        "created_at": "2026-08-28T00:00:00Z",
        "locator": "qste://source/a",
        "rights": {"use": "fixture", "retain": True},
    }
    second = {
        "rights": {"retain": True, "use": "fixture"},
        "locator": "qste://source/a",
        "created_at": "2026-08-29T00:00:00Z",
        "record_id": new_record_id(
            "SourceRecord", uuid_value=uuid.UUID("10000000-0000-4000-8000-000000000002")
        ),
        "record_type": "SourceRecord",
    }
    assert first["record_id"] != second["record_id"]
    assert semantic_key(first, spec) == semantic_key(second, spec)
    second["locator"] = "qste://source/b"
    assert semantic_key(first, spec) != semantic_key(second, spec)


def test_occurrence_semantic_and_byte_identities_are_non_substitutable() -> None:
    record_id = new_record_id(
        "ArtifactRecord", uuid_value=uuid.UUID("20000000-0000-4000-8000-000000000001")
    )
    semantic = semantic_key_from_value("qste-test/artifact", {"role": "analysis"})
    digest = content_digest(b"analysis bytes")
    assert len({record_id, semantic, digest}) == 3


def test_semantic_key_spec_rejects_volatile_fields() -> None:
    with pytest.raises(ValueError, match="volatile"):
        SemanticKeySpec("bad", "SourceRecord", ("record_id",))
