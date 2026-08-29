from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from p8_helpers import P8Fixture, appeal_specification, build_p8_fixture

from qste.core import SchemaRegistry, canonical_json_bytes
from qste.core.contracts import ContractError
from qste.operations import repair_apply
from qste.policy import PolicyService


def _adjudicated_case(
    fixture: P8Fixture,
    service: PolicyService,
    *,
    action: str,
    outcome: str = "upheld",
    pause_active: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    value = fixture
    specification = appeal_specification(value, requested_action=action)
    specification["pause_requested"] = pause_active
    specification["pause_risk_threshold_met"] = pause_active
    opened = service.open_appeal(
        governance_boundary_record_id=value.boundary["record_id"],
        appellant_record_id=value.appellant["record_id"],
        responding_authority_record_id=value.authority["record_id"],
        target_record_id=value.artifact["record_id"],
        specification=specification,
    ).value
    assert opened is not None
    adjudicated = service.adjudicate(
        appeal_case_record_id=opened["record_id"],
        authority_record_id=value.authority["record_id"],
        outcome=outcome,
        evidence_record_ids=[value.observations[0]["record_id"]],
    ).value
    assert adjudicated is not None
    return opened, adjudicated


def _repair_specification(*, feasible: bool = True) -> dict[str, Any]:
    return {
        "feasible_change_or_stop": feasible,
        "retention": {"mode": "retain", "reason": "P8 conformance fixture"},
        "external_copies": [],
        "propagation_failures": [],
        "maximum_depth": 64,
    }


def test_authorized_appeal_keeps_axes_independent_and_revocation_blocks_export(
    tmp_path: Path,
) -> None:
    fixture = build_p8_fixture(tmp_path)
    service = PolicyService(fixture.workspace)
    frozen_target = canonical_json_bytes(fixture.artifact)
    opened, adjudicated = _adjudicated_case(fixture, service, action="revoke")
    assert opened["appeal_status"] == "under_review"
    assert opened["pause_status"] == "active"
    assert opened["adjudication_outcome"] == "not_decided"
    assert opened["repair_status"] == "not_requested"
    assert adjudicated["appeal_status"] == "adjudicated"
    assert adjudicated["pause_status"] == "active"
    assert adjudicated["adjudication_outcome"] == "upheld"
    assert adjudicated["repair_status"] == "not_requested"

    repaired = service.apply_repair(
        appeal_case_record_id=adjudicated["record_id"],
        authority_record_id=fixture.authority["record_id"],
        repair_action="revoke",
        specification={
            "feasible_change_or_stop": True,
            "retention": {"mode": "retain", "reason": "audit duty"},
            "external_copies": [],
            "propagation_failures": [],
            "maximum_depth": 64,
        },
    )
    assert repaired.repair_status == "applied"
    assert repaired.value is not None
    assert repaired.value["repair_status"] == "applied"
    assert repaired.value["pause_status"] == "active"
    assert service.current_authorization(fixture.artifact["record_id"]) == "revoked"
    assert (
        canonical_json_bytes(service.store.get_record(fixture.artifact["record_id"]).record)
        == frozen_target
    )
    with pytest.raises(ContractError) as caught:
        service.export_projection(
            target_record_id=fixture.artifact["record_id"],
            governance_boundary_record_id=fixture.boundary["record_id"],
            disclosure_status="project_internal",
            human_authorized=False,
        )
    assert caught.value.reason_code == "policy_refused"


def test_partial_delete_reports_retention_and_external_copy_limits(tmp_path: Path) -> None:
    fixture = build_p8_fixture(tmp_path)
    service = PolicyService(fixture.workspace)
    _opened, adjudicated = _adjudicated_case(fixture, service, action="delete", outcome="partial")
    result = repair_apply(
        fixture.workspace,
        appeal_case_record_id=adjudicated["record_id"],
        authority_record_id=fixture.authority["record_id"],
        repair_action="delete",
        specification={
            "feasible_change_or_stop": True,
            "retention": {"mode": "retain", "reason": "legal audit duty"},
            "external_copies": [{"locator": "external://copy-1", "authority": "outside_qste"}],
            "propagation_failures": [],
            "maximum_depth": 64,
        },
        authorization_status="permitted",
    )
    assert result["operation_status"] == "partial"
    assert result["cli_exit_class"] == 6
    assert result["domain_status"] == {"repair_status": "partially_applied"}
    assert "external://copy-1" in result["unresolved_targets"]
    assert "retention_duty_blocks_deletion" in result["unresolved_targets"]
    assert (
        service.store.get_record(fixture.artifact["record_id"]).record["artifact_availability"]
        == "known"
    )
    receipt = result["value"]
    assert receipt["repair_status"] == "partially_applied"
    assert receipt["external_copies"][0]["locator"] == "external://copy-1"


def test_missing_standing_and_unnamed_authority_fail_explicitly(tmp_path: Path) -> None:
    fixture = build_p8_fixture(tmp_path)
    service = PolicyService(fixture.workspace)
    invalid = appeal_specification(fixture)
    invalid["standing_verified"] = False
    with pytest.raises(ContractError) as standing:
        service.open_appeal(
            governance_boundary_record_id=fixture.boundary["record_id"],
            appellant_record_id=fixture.appellant["record_id"],
            responding_authority_record_id=fixture.authority["record_id"],
            target_record_id=fixture.artifact["record_id"],
            specification=invalid,
        )
    assert standing.value.reason_code == "standing_denied"
    with pytest.raises(ContractError) as authority:
        service.open_appeal(
            governance_boundary_record_id=fixture.boundary["record_id"],
            appellant_record_id=fixture.appellant["record_id"],
            responding_authority_record_id=fixture.appellant["record_id"],
            target_record_id=fixture.artifact["record_id"],
            specification=appeal_specification(fixture),
        )
    assert authority.value.reason_code == "authority_unresolved"
    failure_receipt_id = cast(Any, authority.value).receipt_id
    failure_receipt = service.store.get_record(failure_receipt_id).record
    assert failure_receipt["qste:operation"] == "open_appeal"
    assert failure_receipt["operation_status"] == "failed"


@pytest.mark.parametrize("action", ["pause", "restrict", "correct", "release_pause"])
def test_behavior_changing_repair_actions_emit_successors(tmp_path: Path, action: str) -> None:
    fixture = build_p8_fixture(tmp_path)
    service = PolicyService(fixture.workspace)
    pause_active = action in {"correct", "release_pause"}
    _opened, adjudicated = _adjudicated_case(
        fixture,
        service,
        action=action,
        pause_active=pause_active,
    )
    result = service.apply_repair(
        appeal_case_record_id=adjudicated["record_id"],
        authority_record_id=fixture.authority["record_id"],
        repair_action=action,
        specification=_repair_specification(),
    )
    assert result.repair_status == "applied"
    assert result.value is not None
    assert result.value["repair_status"] == "applied"
    successor = next(
        value.record
        for value in reversed(service.store.iter_records())
        if value.record_type == "SuccessorSpec"
    )
    assert successor["semantic_diff"]["semantic_or_behavioral_difference"] is True


def test_restore_follows_prior_revocation_and_impossible_repair_is_honest(
    tmp_path: Path,
) -> None:
    fixture = build_p8_fixture(tmp_path)
    service = PolicyService(fixture.workspace)
    _opened, revoked_case = _adjudicated_case(fixture, service, action="revoke")
    service.apply_repair(
        appeal_case_record_id=revoked_case["record_id"],
        authority_record_id=fixture.authority["record_id"],
        repair_action="revoke",
        specification=_repair_specification(),
    )
    assert service.current_authorization(fixture.artifact["record_id"]) == "revoked"

    _opened, restore_case = _adjudicated_case(fixture, service, action="restore")
    restored = service.apply_repair(
        appeal_case_record_id=restore_case["record_id"],
        authority_record_id=fixture.authority["record_id"],
        repair_action="restore",
        specification=_repair_specification(),
    )
    assert restored.repair_status == "applied"
    assert service.current_authorization(fixture.artifact["record_id"]) == "permitted"

    _opened, impossible_case = _adjudicated_case(
        fixture,
        service,
        action="correct",
        pause_active=False,
    )
    impossible = repair_apply(
        fixture.workspace,
        appeal_case_record_id=impossible_case["record_id"],
        authority_record_id=fixture.authority["record_id"],
        repair_action="correct",
        specification=_repair_specification(feasible=False),
        authorization_status="permitted",
    )
    assert impossible["operation_status"] == "partial"
    assert impossible["cli_exit_class"] == 6
    assert impossible["domain_status"] == {"repair_status": "impossible"}
    assert impossible["unresolved_targets"] == ["repair_not_feasible"]


def test_hash_only_repair_successor_fails_semantic_conformance(tmp_path: Path) -> None:
    fixture = build_p8_fixture(tmp_path)
    service = PolicyService(fixture.workspace)
    _opened, adjudicated = _adjudicated_case(fixture, service, action="correct")
    service.apply_repair(
        appeal_case_record_id=adjudicated["record_id"],
        authority_record_id=fixture.authority["record_id"],
        repair_action="correct",
        specification={
            "feasible_change_or_stop": True,
            "retention": {"mode": "retain"},
            "external_copies": [],
            "propagation_failures": [],
        },
    )
    successor = next(
        value.record
        for value in reversed(service.store.iter_records())
        if value.record_type == "SuccessorSpec"
    )
    invalid = {**successor, "semantic_diff": {**successor["semantic_diff"]}}
    invalid["semantic_diff"]["semantic_or_behavioral_difference"] = False
    with pytest.raises(ContractError, match="hash-only"):
        SchemaRegistry().validate_record(invalid)
