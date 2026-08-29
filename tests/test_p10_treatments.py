from __future__ import annotations

from pathlib import Path

from p10_helpers import build_p10_fixture, payloads, treatments

from qste.core import loads_json


def test_information_payload_levels_share_invariant_outcome_core(tmp_path: Path) -> None:
    fixture = build_p10_fixture(tmp_path)
    records = payloads(fixture)
    assert [value["qste:recordLevel"] for value in records] == [
        "ordinary",
        "formation_only",
        "full_assessment",
    ]
    assert len({value["qste:invariantOutcomeCoreDigest"] for value in records}) == 1
    assert all(value["qste:dsqLabel"] == "not_inferred_from_payload_level" for value in records)
    contents = [
        loads_json(fixture.service.artifacts.read_bytes(value["content_digest"]))
        for value in records
    ]
    assert len({str(value["outcome_core"]) for value in contents}) == 1
    assert "assessment" not in contents[0]
    assert "assessment" not in contents[1]
    assert contents[2]["assessment"]["verdict"] == "qualified"


def test_four_treatments_are_exactly_matched_and_permission_preserving(tmp_path: Path) -> None:
    fixture = build_p10_fixture(tmp_path)
    records = treatments(fixture)
    assert set(records) == {"authentic", "absent", "placebo", "permuted"}
    assert records["absent"]["artifact_availability"] == "unavailable"
    assert records["absent"]["qste:executorPayloadSupplied"] is False
    assert records["authentic"]["qste:evidenceRelationIntact"] is True
    assert records["placebo"]["qste:evidenceRelationIntact"] is False
    assert records["permuted"]["qste:evidenceRelationIntact"] is False
    assert (
        records["authentic"]["qste:matchedExposureBytes"]
        == records["placebo"]["qste:matchedExposureBytes"]
    )
    assert (
        records["authentic"]["qste:payloadMultisetDigest"]
        == records["permuted"]["qste:payloadMultisetDigest"]
    )
    assert all(value["qste:sourceAuthorizationOverride"] is False for value in records.values())
