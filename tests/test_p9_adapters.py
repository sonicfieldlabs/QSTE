from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from p9_helpers import build_p9_fixture, capture_fixture, encode_and_enumerate

from qste.adapters import OPERATIONS
from qste.core import content_digest
from qste.core.contracts import ContractError
from qste.storage import RecordStore, WorkspacePaths


@pytest.mark.parametrize("adapter_id", ["samplebrain", "encodec"])
def test_probe_declares_complete_surface_without_external_execution(
    tmp_path: Path, adapter_id: str
) -> None:
    fixture = build_p9_fixture(tmp_path)
    outcome = fixture.service.probe(
        adapter_id=adapter_id,
        context_record_id=fixture.base.apparatus["record_id"],
        specification={},
    )
    data = outcome.value["data"]
    assert set(data["operation_capabilities"]) == set(OPERATIONS)
    assert data["external_execution"] == "unavailable"
    assert data["subprocess_invoked"] is False
    assert data["model_loaded"] is False
    assert outcome.receipt_record["operation_status"] == "completed"


def test_samplebrain_probe_can_verify_an_explicit_executable_without_running_it(
    tmp_path: Path,
) -> None:
    fixture = build_p9_fixture(tmp_path)
    executable = tmp_path / "samplebrain-fixture"
    executable.write_bytes(b"bounded non-executable probe fixture")
    outcome = fixture.service.probe(
        adapter_id="samplebrain",
        context_record_id=fixture.base.apparatus["record_id"],
        specification={
            "allowed_roots": [str(tmp_path)],
            "executable_path": str(executable),
            "executable_digest": content_digest(executable.read_bytes()),
        },
    )
    data = outcome.value["data"]
    assert data["external_execution"] == "available"
    assert data["probe"]["checks"]["executable"]["status"] == "available"
    assert data["subprocess_invoked"] is False


def test_policy_refusal_is_durable_and_creates_no_derivative(tmp_path: Path) -> None:
    fixture = build_p9_fixture(tmp_path)
    before = len(fixture.service.store.iter_records())
    with pytest.raises(ContractError) as caught:
        fixture.service.probe(
            adapter_id="samplebrain",
            context_record_id=fixture.base.apparatus["record_id"],
            specification={},
            authorization_status="revoked",
        )
    assert caught.value.reason_code == "policy_refused"
    assert cast(Any, caught.value).authorization_status == "refused"
    records = fixture.service.store.iter_records()
    assert len(records) == before + 1
    receipt = records[-1].record
    assert receipt["record_type"] == "OperationReceipt"
    assert receipt["operation_status"] == "refused"
    assert receipt["authorization_status"] == "refused"


@pytest.mark.parametrize("adapter_id", ["samplebrain", "encodec"])
def test_captured_arm_preserves_native_identity_and_is_candidate_only(
    tmp_path: Path, adapter_id: str
) -> None:
    fixture = build_p9_fixture(tmp_path)
    first, candidates = encode_and_enumerate(fixture, adapter_id)
    second = fixture.service.encode_capture(
        adapter_id=adapter_id,
        artifact_record_id=fixture.base.ingress_artifact["record_id"],
        aperture_record_id=fixture.base.aperture["record_id"],
        capture=capture_fixture(fixture, adapter_id),
    ).value
    assert first["record_id"] != second["record_id"]
    assert first["semantic_key"] == second["semantic_key"]
    assert first["qste:adapterId"] == adapter_id
    assert first["qste:dsqCapability"] == "candidate_only_without_closed_refinement_graph"
    assert first["qste:refinementCapability"]["graph_created"] is False
    assert candidates
    assert all(value["qste:candidateOnly"] is True for value in candidates)
    assert all(value["qste:adapterId"] == adapter_id for value in candidates)


@pytest.mark.parametrize("adapter_id", ["samplebrain", "encodec"])
def test_support_address_intervention_decode_and_account_are_bounded(
    tmp_path: Path, adapter_id: str
) -> None:
    fixture = build_p9_fixture(tmp_path)
    instance, candidates = encode_and_enumerate(fixture, adapter_id)
    candidate = candidates[0]
    support = fixture.service.operate(
        operation="support",
        target_record_ids=[candidate["record_id"]],
        specification={"method": "captured_native_support"},
    ).value
    assert support["data"]["cross_arm_identity"] is False
    address = fixture.service.operate(
        operation="address",
        target_record_ids=[candidate["record_id"]],
        specification={"intervention_mode": "mask"},
    ).value
    assert address["data"]["addressable"] is True
    intervention = fixture.service.operate(
        operation="intervene",
        target_record_ids=[candidate["record_id"]],
        specification={"mode": "mask", "control": "zero_native_value"},
    ).value
    assert intervention["data"]["external_renderer_invoked"] is False
    decoded = fixture.service.operate(
        operation="decode",
        target_record_ids=[instance["record_id"]],
        specification={"source": "captured_decoder_output"},
    ).value
    assert decoded["qste:externalDecoderInvoked"] is False
    assert decoded["qste:heardOutput"] == "not_produced"
    account = fixture.service.operate(
        operation="account",
        target_record_ids=[instance["record_id"]],
        specification={},
    ).value
    assert account["data"]["candidate_status"] == "candidate_only"
    RecordStore(WorkspacePaths.open(fixture.base.workspace)).verify()


@pytest.mark.parametrize("operation", ["refine", "project", "measure", "perturb"])
def test_unimplemented_surface_is_explicit_and_receipted(tmp_path: Path, operation: str) -> None:
    fixture = build_p9_fixture(tmp_path)
    instance, candidates = encode_and_enumerate(fixture, "encodec")
    target = candidates[0] if operation != "perturb" else instance
    with pytest.raises(ContractError) as caught:
        fixture.service.operate(
            operation=operation,
            target_record_ids=[target["record_id"]],
            specification={"attempt": "must_not_infer_hidden_state"},
        )
    assert caught.value.reason_code == "capability_unavailable"
    receipt_id = cast(Any, caught.value).receipt_id
    receipt = fixture.service.store.get_record(receipt_id).record
    assert receipt["operation_status"] == "failed"
    assert receipt["qste:operation"] == operation


@pytest.mark.parametrize("failure", ["timeout", "silent_resampling"])
def test_failed_capture_leaves_no_representation_derivative(tmp_path: Path, failure: str) -> None:
    fixture = build_p9_fixture(tmp_path)
    capture = capture_fixture(fixture, "samplebrain")
    if failure == "timeout":
        capture["execution_status"] = "timeout"
    else:
        capture["resampling"] = {
            "applied": False,
            "source_hz": 48_000,
            "target_hz": 24_000,
            "method": "none",
        }
    before = len(fixture.service.store.iter_records())
    with pytest.raises(ContractError) as caught:
        fixture.service.encode_capture(
            adapter_id="samplebrain",
            artifact_record_id=fixture.base.ingress_artifact["record_id"],
            aperture_record_id=fixture.base.aperture["record_id"],
            capture=capture,
        )
    assert caught.value.reason_code in {"execution_failed", "conformance_failed"}
    records = fixture.service.store.iter_records()
    assert len(records) == before + 1
    assert records[-1].record_type == "OperationReceipt"
    assert not any(
        value.record.get("qste:adapterId") == "samplebrain"
        and value.record_type == "RepresentationInstance"
        for value in records
    )
