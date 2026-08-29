from __future__ import annotations

from pathlib import Path

import pytest
from p8_helpers import artifact_parameters, build_p8_fixture

from qste.core.contracts import ContractError
from qste.storage import RecordStore, WorkspacePaths
from qste.transduction import TransductionService


def test_all_five_transduction_modes_preserve_mapping_control_and_claim_boundaries(
    tmp_path: Path,
) -> None:
    fixture = build_p8_fixture(tmp_path)
    service = TransductionService(fixture.workspace)
    sonification = service.transduce(
        mode="sonification",
        source_record_ids=[fixture.observations[0]["record_id"]],
        mapping_record_id=fixture.mapping["record_id"],
        parameters=artifact_parameters(fixture, mode="sonification"),
    )
    assert sonification.value is not None
    assert sonification.value["qste:transductionMode"] == "sonification"
    assert sonification.value["qste:heardOutput"] == "not_produced"
    assert len(sonification.safety_record_ids) == 1
    safety = service.store.get_record(sonification.safety_record_ids[0]).record
    assert safety["qste:analyticalParentRef"]["record_id"] == sonification.value["record_id"]

    desonification = service.transduce(
        mode="desonification",
        source_record_ids=[sonification.value["record_id"]],
        mapping_record_id=fixture.mapping["record_id"],
        parameters={
            "bounded_inference": True,
            "observations": [
                {"variable": "estimated_response", "units": "normalized_score", "value": 0.3}
            ],
        },
    )
    assert desonification.value is not None
    assert desonification.value["payload_type"] == "ObservationSet"
    assert desonification.value["data"]["complete_cause_or_meaning_claim"] is False

    for mode in ("resonification", "sonic_transformation"):
        outcome = service.transduce(
            mode=mode,
            source_record_ids=[fixture.artifact["record_id"]],
            mapping_record_id=fixture.mapping["record_id"],
            parameters=artifact_parameters(fixture, mode=mode),
        )
        assert outcome.value is not None
        assert outcome.value["record_id"] != fixture.artifact["record_id"]
        assert outcome.value["qste:transductionMode"] == mode

    contrast = service.transduce(
        mode="cross_domain_contrast",
        source_record_ids=[
            fixture.artifact["record_id"],
            fixture.observations[0]["record_id"],
        ],
        mapping_record_id=fixture.mapping["record_id"],
        parameters={
            "variables": ["fixture_parameter", "response"],
            "method": "bounded_fixture_contrast/v0.1",
            "distinction": "mapping",
        },
    )
    assert contrast.value is not None
    assert contrast.value["payload_type"] == "RelationSet"
    assert contrast.value["items"] == []
    assert contrast.value["data"]["causation_claim"] is False


def test_refusal_precedes_execution_and_creates_no_authoritative_derivative(
    tmp_path: Path,
) -> None:
    fixture = build_p8_fixture(tmp_path)
    service = TransductionService(fixture.workspace)
    before = [
        value.record_id
        for value in service.store.iter_records()
        if value.record_type == "ArtifactRecord"
    ]
    with pytest.raises(ContractError) as caught:
        service.transduce(
            mode="sonification",
            source_record_ids=[fixture.observations[0]["record_id"]],
            mapping_record_id=fixture.mapping["record_id"],
            parameters=artifact_parameters(fixture, mode="sonification"),
            authorization_status="revoked",
        )
    assert caught.value.reason_code == "policy_refused"
    after = [
        value.record_id
        for value in service.store.iter_records()
        if value.record_type == "ArtifactRecord"
    ]
    assert after == before
    receipt = service.store.get_record(caught.value.receipt_id).record  # type: ignore[attr-defined]
    assert receipt["operation_status"] == "refused"
    assert receipt["outputs"] == [{"availability": "not_applicable", "reason": "policy_refused"}]


def test_cross_domain_contrast_rejects_causation_substitution(tmp_path: Path) -> None:
    fixture = build_p8_fixture(tmp_path)
    with pytest.raises(ContractError, match="causation"):
        TransductionService(fixture.workspace).transduce(
            mode="cross_domain_contrast",
            source_record_ids=[
                fixture.artifact["record_id"],
                fixture.observations[0]["record_id"],
            ],
            mapping_record_id=fixture.mapping["record_id"],
            parameters={
                "variables": ["response"],
                "method": "invalid_causal_shortcut",
                "distinction": "causation",
            },
        )
    store = RecordStore(WorkspacePaths.open(fixture.workspace))
    assert store.iter_events()[-1].event_type == "qste:transduction-failed/0.1"
