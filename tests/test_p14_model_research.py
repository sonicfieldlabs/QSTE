from __future__ import annotations

from typing import Any, cast

import pytest
from p14_helpers import build_p14_fixture, fixture, registered_manifest

from qste.core.contracts import ContractError
from qste.storage import RecordStore, WorkspacePaths


def test_program_and_metadata_manifest_preserve_nonexecution_boundary(tmp_path: Any) -> None:
    p14 = build_p14_fixture(tmp_path)
    program = p14.service.freeze_program(
        context_record_id=p14.context["record_id"], specification=fixture("program.json")
    ).value
    assert program["qste:modelResearchStatus"] == "contract_frozen"
    assert program["qste:trainingStatus"] == "not_started"
    assert program["qste:checkpointStatus"] == "unavailable"
    manifest = p14.service.register_dataset_manifest(
        program_record_id=program["record_id"],
        manifest=registered_manifest(program, p14.context),
    ).value
    assert manifest["qste:datasetStatus"] == "metadata_only_unverified_bytes"
    assert manifest["qste:trainingEligibility"] == "unavailable"
    assert manifest["qste:publicProjection"] is False
    RecordStore(WorkspacePaths.open(p14.workspace)).verify()


def test_execution_flag_is_refused_with_durable_receipt(tmp_path: Any) -> None:
    p14 = build_p14_fixture(tmp_path)
    program = fixture("program.json")
    program["safety_flags"]["training_executed"] = True
    before = len(p14.service.store.iter_records())
    with pytest.raises(ContractError) as caught:
        p14.service.freeze_program(
            context_record_id=p14.context["record_id"], specification=program
        )
    assert caught.value.reason_code == "policy_refused"
    assert cast(Any, caught.value).receipt_id
    assert len(p14.service.store.iter_records()) == before + 1


def test_dataset_rights_and_consent_are_mandatory(tmp_path: Any) -> None:
    p14 = build_p14_fixture(tmp_path)
    program = p14.service.freeze_program(
        context_record_id=p14.context["record_id"], specification=fixture("program.json")
    ).value
    manifest = registered_manifest(program, p14.context)
    manifest["items"][0]["rights_status"] = "unknown"
    with pytest.raises(ContractError) as caught:
        p14.service.register_dataset_manifest(
            program_record_id=program["record_id"], manifest=manifest
        )
    assert caught.value.reason_code == "policy_refused"


def test_self_generated_items_require_generator_provenance(tmp_path: Any) -> None:
    p14 = build_p14_fixture(tmp_path)
    program = p14.service.freeze_program(
        context_record_id=p14.context["record_id"], specification=fixture("program.json")
    ).value
    manifest = registered_manifest(program, p14.context)
    manifest["items"][1]["generator_provenance"] = {}
    with pytest.raises(ContractError) as caught:
        p14.service.register_dataset_manifest(
            program_record_id=program["record_id"], manifest=manifest
        )
    assert caught.value.reason_code == "conformance_failed"


def test_dataset_splits_are_complete_and_disjoint(tmp_path: Any) -> None:
    p14 = build_p14_fixture(tmp_path)
    program = p14.service.freeze_program(
        context_record_id=p14.context["record_id"], specification=fixture("program.json")
    ).value
    manifest = registered_manifest(program, p14.context)
    manifest["splits"]["test"] = ["synthetic-train"]
    with pytest.raises(ContractError) as caught:
        p14.service.register_dataset_manifest(
            program_record_id=program["record_id"], manifest=manifest
        )
    assert caught.value.reason_code == "conformance_failed"


def test_manifest_must_bind_exact_frozen_program(tmp_path: Any) -> None:
    p14 = build_p14_fixture(tmp_path)
    program = p14.service.freeze_program(
        context_record_id=p14.context["record_id"], specification=fixture("program.json")
    ).value
    manifest = registered_manifest(program, p14.context)
    manifest["program_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ContractError) as caught:
        p14.service.register_dataset_manifest(
            program_record_id=program["record_id"], manifest=manifest
        )
    assert caught.value.reason_code == "conformance_failed"


def test_capability_account_keeps_model_gates_closed(tmp_path: Any) -> None:
    p14 = build_p14_fixture(tmp_path)
    data = p14.service.account(context_record_id=p14.context["record_id"]).value["data"]
    assert data["program_freeze"] == "available"
    assert data["dataset_manifest_registry"] == "available"
    assert data["dataset_bytes"] == "unavailable"
    assert data["fine_tuning_execution"] == "authorization_required"
    assert data["trained_model"] == "unavailable"
    assert data["learned_gain_evidence"] == "unavailable"
    assert data["custom_model"] == "unavailable"
    assert data["public_projection"] == "prohibited"


def test_program_text_arrays_are_typed_unique_and_complete(tmp_path: Any) -> None:
    p14 = build_p14_fixture(tmp_path)
    invalid_programs = []

    non_text = fixture("program.json")
    non_text["evaluation_suite"]["analysis_tasks"] = [7]
    invalid_programs.append(non_text)

    duplicate_category = fixture("program.json")
    duplicate_category["failure_analysis"]["categories"].append("overfit")
    invalid_programs.append(duplicate_category)

    duplicate_section = fixture("program.json")
    duplicate_section["model_card_template"]["required_sections"].append("identity")
    invalid_programs.append(duplicate_section)

    duplicate_stage = fixture("program.json")
    duplicate_stage["custom_model_route"]["stages"].append("separate_custom_model_authorization")
    invalid_programs.append(duplicate_stage)

    for program in invalid_programs:
        with pytest.raises(ContractError) as caught:
            p14.service.freeze_program(
                context_record_id=p14.context["record_id"], specification=program
            )
        assert caught.value.reason_code == "invalid_input"


def test_dataset_flags_consent_and_split_members_are_strict(tmp_path: Any) -> None:
    p14 = build_p14_fixture(tmp_path)
    program = p14.service.freeze_program(
        context_record_id=p14.context["record_id"], specification=fixture("program.json")
    ).value

    non_boolean = registered_manifest(program, p14.context)
    non_boolean["items"][0]["self_generated"] = "false"
    with pytest.raises(ContractError) as caught:
        p14.service.register_dataset_manifest(
            program_record_id=program["record_id"], manifest=non_boolean
        )
    assert caught.value.reason_code == "invalid_input"

    human_without_consent = registered_manifest(program, p14.context)
    human_without_consent["items"][0]["source_kind"] = "human_data"
    with pytest.raises(ContractError) as caught:
        p14.service.register_dataset_manifest(
            program_record_id=program["record_id"], manifest=human_without_consent
        )
    assert caught.value.reason_code == "policy_refused"

    non_text_split = registered_manifest(program, p14.context)
    non_text_split["splits"]["train"] = [7]
    with pytest.raises(ContractError) as caught:
        p14.service.register_dataset_manifest(
            program_record_id=program["record_id"], manifest=non_text_split
        )
    assert caught.value.reason_code == "invalid_input"
