"""Bounded P3 Python operations over explicit local roots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from qste.adapters import (
    BoundedEngineService,
    EcosystemAdapterService,
    ExternalRepresentationService,
)
from qste.agent import AgentHostService
from qste.core import SchemaRegistry, loads_json, new_record_id
from qste.core.contracts import BASE_URI, ContractError
from qste.experiments import ExperimentPreparationService
from qste.ingress import AudioTransform, IngressLimits, IngressService
from qste.ingress import declare_apparatus as persist_apparatus
from qste.ingress import derive_aperture as persist_aperture
from qste.model_research import ModelResearchService
from qste.policy import PolicyService
from qste.quanta import QuantaService
from qste.relations import RelationService
from qste.representations import STFTService, stft_config_from_mapping
from qste.storage import (
    ArtifactStore,
    BundleReader,
    BundleService,
    DenseStore,
    RecordStore,
    WorkspacePaths,
    verify_workspace_storage,
)
from qste.transduction import TransductionService

OperationResult = dict[str, Any]


def _agent_result(operation: str, outcome: Any) -> OperationResult:
    status = outcome.operation_status
    value = outcome.value
    value_type = outcome.value_type
    output_record_ids: list[str] = []
    if status != "completed":
        output_record_ids = [
            item["record_id"]
            for item in outcome.value.get("items", [])
            if isinstance(item, Mapping) and isinstance(item.get("record_id"), str)
        ]
        value = None
        value_type = "qste-payload/0.3.0/CapabilityAccount"
    elif value_type == "qste-payload/0.3.0/HarnessInitialization":
        value = next(
            item for item in outcome.value["items"] if item["record_type"] == "ListeningHarnessSpec"
        )
        value_type = f"{BASE_URI}/records/listening-harness-spec.schema.json"
        output_record_ids = [item["record_id"] for item in outcome.value["items"]]
    elif value_type == "qste-payload/0.3.0/InformationPayloadSet":
        value = next(
            item
            for item in outcome.value["items"]
            if item.get("qste:recordLevel") == "full_assessment"
        )
        value_type = f"{BASE_URI}/records/artifact-record.schema.json"
        output_record_ids = [item["record_id"] for item in outcome.value["items"]]
    elif value_type == "qste-payload/0.3.0/TreatmentSet":
        value = next(
            item
            for item in outcome.value["items"]
            if item.get("qste:revisionTreatment") == "authentic"
        )
        value_type = f"{BASE_URI}/records/artifact-record.schema.json"
        output_record_ids = [item["record_id"] for item in outcome.value["items"]]
    result: OperationResult = {
        "contract_id": "qste-contract/0.3.0",
        "operation": f"qste:{operation}/0.1.0",
        "value_type": value_type,
        "operation_status": status,
        "value": value,
        "reason_code": outcome.reason_code,
        "authorization_status": (
            outcome.receipt_record["authorization_status"] if status == "refused" else "permitted"
        ),
        "capability_status": "prohibited" if status == "refused" else "available",
        "receipt_id": outcome.receipt_record["record_id"],
        "diagnostics": {
            "event_sequence": outcome.event_sequence,
            "profile": "qste-evidence-dependent-revision/v0.1",
            "creative_consequence": "not_assessed",
            "output_record_ids": output_record_ids,
        },
        "cli_exit_class": 3 if status == "refused" else 0,
    }
    SchemaRegistry().validate_operation_result(result)
    return result


def agent_initialize(
    workspace: Path,
    *,
    governance_boundary_record_id: str,
    authority_record_id: str,
    source_record_id: str,
    completed_run_record_id: str,
    predecessor_record_id: str,
    specification: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    required = {
        "record_ids",
        "executor",
        "initial_state",
        "executable_action_set",
        "limits",
        "evaluation",
    }
    if set(specification) != required:
        raise ContractError("invalid_input", "agent initialization fields are not exact")
    return _agent_result(
        "initialize_harness",
        AgentHostService(workspace).initialize_harness(
            governance_boundary_record_id=governance_boundary_record_id,
            authority_record_id=authority_record_id,
            source_record_id=source_record_id,
            completed_run_record_id=completed_run_record_id,
            predecessor_record_id=predecessor_record_id,
            record_ids=list(specification["record_ids"]),
            executor=specification["executor"],
            initial_state=specification["initial_state"],
            executable_action_set=list(specification["executable_action_set"]),
            limits=specification["limits"],
            evaluation=specification["evaluation"],
            authorization_status=authorization_status,
        ),
    )


def agent_payloads(
    workspace: Path,
    *,
    assessment_record_id: str,
    specification: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    if set(specification) != {"outcome_core", "formation", "assessment"}:
        raise ContractError("invalid_input", "information payload fields are not exact")
    return _agent_result(
        "create_information_payloads",
        AgentHostService(workspace).create_payloads(
            assessment_record_id=assessment_record_id,
            outcome_core=specification["outcome_core"],
            formation=specification["formation"],
            assessment=specification["assessment"],
            authorization_status=authorization_status,
        ),
    )


def agent_treatments(
    workspace: Path,
    *,
    opportunity_record_id: str,
    authentic_payload_record_id: str,
    allocation: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _agent_result(
        "prepare_revision_treatments",
        AgentHostService(workspace).prepare_treatments(
            opportunity_record_id=opportunity_record_id,
            authentic_payload_record_id=authentic_payload_record_id,
            allocation=allocation,
            authorization_status=authorization_status,
        ),
    )


def agent_plan(
    workspace: Path,
    *,
    opportunity_record_id: str,
    treatment_record_id: str,
    proposal: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _agent_result(
        "plan",
        AgentHostService(workspace).plan(
            opportunity_record_id=opportunity_record_id,
            treatment_record_id=treatment_record_id,
            proposal=proposal,
            authorization_status=authorization_status,
        ),
    )


def agent_revise(
    workspace: Path,
    *,
    plan_record_id: str,
    authority_record_id: str,
    source_authorization_status: str,
    enforcement_mode: str,
    fixture_authorization: str,
    human_authorized: bool,
    authorization_status: str,
) -> OperationResult:
    return _agent_result(
        "revise",
        AgentHostService(workspace).revise(
            plan_record_id=plan_record_id,
            authority_record_id=authority_record_id,
            source_authorization_status=source_authorization_status,
            enforcement_mode=enforcement_mode,
            fixture_authorization=fixture_authorization,
            human_authorized=human_authorized,
            authorization_status=authorization_status,
        ),
    )


def agent_study(
    workspace: Path,
    *,
    decision_record_ids: Mapping[str, Sequence[str]],
    preregistration: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _agent_result(
        "assess_revision_study",
        AgentHostService(workspace).assess_study(
            decision_record_ids=decision_record_ids,
            preregistration=preregistration,
            authorization_status=authorization_status,
        ),
    )


def agent_utility(
    workspace: Path,
    *,
    decision_record_id: str,
    evaluation: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _agent_result(
        "evaluate_agent_utility",
        AgentHostService(workspace).evaluate_utility(
            decision_record_id=decision_record_id,
            evaluation=evaluation,
            authorization_status=authorization_status,
        ),
    )


def _adapter_result(operation: str, outcome: Any) -> OperationResult:
    result: OperationResult = {
        "contract_id": "qste-contract/0.3.0",
        "operation": f"qste:adapter_{operation}/0.1.0",
        "value_type": outcome.value_type,
        "operation_status": "completed",
        "value": outcome.value,
        "reason_code": "completed",
        "authorization_status": "permitted",
        "capability_status": "available",
        "receipt_id": outcome.receipt_record["record_id"],
        "diagnostics": {
            "event_sequence": outcome.event_sequence,
            "profile": "qste-external-representation-adapter/v0.1",
            "adapter_id": outcome.adapter_id,
        },
        "cli_exit_class": 0,
    }
    SchemaRegistry().validate_operation_result(result)
    return result


def adapter_probe(
    workspace: Path,
    *,
    adapter_id: str,
    context_record_id: str,
    specification: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _adapter_result(
        "probe",
        ExternalRepresentationService(workspace).probe(
            adapter_id=adapter_id,
            context_record_id=context_record_id,
            specification=specification,
            authorization_status=authorization_status,
        ),
    )


def adapter_encode(
    workspace: Path,
    *,
    adapter_id: str,
    artifact_record_id: str,
    aperture_record_id: str,
    capture: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _adapter_result(
        "encode",
        ExternalRepresentationService(workspace).encode_capture(
            adapter_id=adapter_id,
            artifact_record_id=artifact_record_id,
            aperture_record_id=aperture_record_id,
            capture=capture,
            authorization_status=authorization_status,
        ),
    )


def adapter_enumerate(
    workspace: Path,
    *,
    instance_record_id: str,
    candidate_rule: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _adapter_result(
        "enumerate",
        ExternalRepresentationService(workspace).enumerate(
            instance_record_id=instance_record_id,
            candidate_rule=candidate_rule,
            authorization_status=authorization_status,
        ),
    )


def adapter_operate(
    workspace: Path,
    *,
    operation: str,
    target_record_ids: list[str],
    specification: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _adapter_result(
        operation,
        ExternalRepresentationService(workspace).operate(
            operation=operation,
            target_record_ids=target_record_ids,
            specification=specification,
            authorization_status=authorization_status,
        ),
    )


def _p11_adapter_result(operation: str, outcome: Any, *, profile: str) -> OperationResult:
    result: OperationResult = {
        "contract_id": "qste-contract/0.3.0",
        "operation": f"qste:{operation}/0.1.0",
        "value_type": outcome.value_type,
        "operation_status": outcome.operation_status,
        "value": outcome.value,
        "reason_code": outcome.reason_code,
        "authorization_status": "permitted",
        "capability_status": outcome.capability_status,
        "receipt_id": outcome.receipt_record["record_id"],
        "diagnostics": {
            "event_sequence": outcome.event_sequence,
            "profile": profile,
            "target_id": outcome.target_id,
        },
        "cli_exit_class": 0,
    }
    SchemaRegistry().validate_operation_result(result)
    return result


def ecosystem_import(
    workspace: Path,
    *,
    target_id: str,
    context_record_id: str,
    payload: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _p11_adapter_result(
        "ecosystem_import",
        EcosystemAdapterService(workspace).import_payload(
            target_id=target_id,
            context_record_id=context_record_id,
            payload=payload,
            authorization_status=authorization_status,
        ),
        profile="qste-ecosystem-adapter/v0.1",
    )


def ecosystem_project(
    workspace: Path,
    *,
    target_id: str,
    context_record_id: str,
    payload: Mapping[str, Any],
    human_authorized: bool,
    authorization_status: str,
) -> OperationResult:
    return _p11_adapter_result(
        "ecosystem_project",
        EcosystemAdapterService(workspace).project_payload(
            target_id=target_id,
            context_record_id=context_record_id,
            payload=payload,
            human_authorized=human_authorized,
            authorization_status=authorization_status,
        ),
        profile="qste-ecosystem-adapter/v0.1",
    )


def ecosystem_inspect(
    workspace: Path,
    *,
    target_id: str,
    context_record_id: str,
    payload: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _p11_adapter_result(
        "ecosystem_inspect",
        EcosystemAdapterService(workspace).inspect_payload(
            target_id=target_id,
            context_record_id=context_record_id,
            payload=payload,
            authorization_status=authorization_status,
        ),
        profile="qste-ecosystem-adapter/v0.1",
    )


def ecosystem_live_loopback(
    workspace: Path,
    *,
    target_id: str,
    context_record_id: str,
    authorization_status: str,
) -> OperationResult:
    return _p11_adapter_result(
        "ecosystem_live_loopback",
        EcosystemAdapterService(workspace).live_loopback(
            target_id=target_id,
            context_record_id=context_record_id,
            authorization_status=authorization_status,
        ),
        profile="qste-ecosystem-adapter/v0.1",
    )


def ecosystem_account(
    workspace: Path,
    *,
    target_id: str,
    context_record_id: str,
    authorization_status: str,
) -> OperationResult:
    return _p11_adapter_result(
        "ecosystem_account",
        EcosystemAdapterService(workspace).account(
            target_id=target_id,
            context_record_id=context_record_id,
            authorization_status=authorization_status,
        ),
        profile="qste-ecosystem-adapter/v0.1",
    )


def engine_execute(
    workspace: Path,
    *,
    target_id: str,
    context_record_id: str,
    request: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _p11_adapter_result(
        "engine_execute",
        BoundedEngineService(workspace).execute(
            target_id=target_id,
            context_record_id=context_record_id,
            request=request,
            authorization_status=authorization_status,
        ),
        profile="qste-bounded-engine-adapter/v0.1",
    )


def engine_loopback(
    workspace: Path,
    *,
    target_id: str,
    context_record_id: str,
    request: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _p11_adapter_result(
        "engine_osc_loopback",
        BoundedEngineService(workspace).osc_loopback(
            target_id=target_id,
            context_record_id=context_record_id,
            request=request,
            authorization_status=authorization_status,
        ),
        profile="qste-bounded-engine-adapter/v0.1",
    )


def engine_account(
    workspace: Path,
    *,
    target_id: str,
    context_record_id: str,
    authorization_status: str,
) -> OperationResult:
    return _p11_adapter_result(
        "engine_account",
        BoundedEngineService(workspace).account(
            target_id=target_id,
            context_record_id=context_record_id,
            authorization_status=authorization_status,
        ),
        profile="qste-bounded-engine-adapter/v0.1",
    )


def _experiment_result(operation: str, outcome: Any) -> OperationResult:
    result: OperationResult = {
        "contract_id": "qste-contract/0.3.0",
        "operation": f"qste:{operation}/0.1.0",
        "value_type": outcome.value_type,
        "operation_status": outcome.operation_status,
        "value": outcome.value,
        "reason_code": outcome.reason_code,
        "authorization_status": "permitted",
        "capability_status": "available",
        "receipt_id": outcome.receipt_record["record_id"],
        "diagnostics": {
            "event_sequence": outcome.event_sequence,
            "profile": "qste-experiment-preparation/v0.1",
            "confirmatory_hypotheses_tested": False,
            "human_data_collected": False,
        },
        "cli_exit_class": 0,
    }
    SchemaRegistry().validate_operation_result(result)
    return result


def experiment_freeze(
    workspace: Path,
    *,
    context_record_id: str,
    packet: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _experiment_result(
        "experiment_freeze",
        ExperimentPreparationService(workspace).freeze(
            context_record_id=context_record_id,
            packet=packet,
            authorization_status=authorization_status,
        ),
    )


def experiment_pilot(
    workspace: Path,
    *,
    preparation_record_id: str,
    evidence: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _experiment_result(
        "experiment_pilot",
        ExperimentPreparationService(workspace).pilot(
            preparation_record_id=preparation_record_id,
            evidence=evidence,
            authorization_status=authorization_status,
        ),
    )


def experiment_account(
    workspace: Path,
    *,
    context_record_id: str,
    authorization_status: str,
) -> OperationResult:
    return _experiment_result(
        "experiment_account",
        ExperimentPreparationService(workspace).account(
            context_record_id=context_record_id,
            authorization_status=authorization_status,
        ),
    )


def _model_research_result(operation: str, outcome: Any) -> OperationResult:
    result: OperationResult = {
        "contract_id": "qste-contract/0.3.0",
        "operation": f"qste:{operation}/0.1.0",
        "value_type": outcome.value_type,
        "operation_status": outcome.operation_status,
        "value": outcome.value,
        "reason_code": outcome.reason_code,
        "authorization_status": "permitted",
        "capability_status": "available",
        "receipt_id": outcome.receipt_record["record_id"],
        "diagnostics": {
            "event_sequence": outcome.event_sequence,
            "profile": "qste-model-research-program/v0.1",
            "training_executed": False,
            "checkpoint_downloaded": False,
            "generation_performed": False,
            "human_data_used": False,
        },
        "cli_exit_class": 0,
    }
    SchemaRegistry().validate_operation_result(result)
    return result


def model_program_freeze(
    workspace: Path,
    *,
    context_record_id: str,
    specification: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _model_research_result(
        "model_program_freeze",
        ModelResearchService(workspace).freeze_program(
            context_record_id=context_record_id,
            specification=specification,
            authorization_status=authorization_status,
        ),
    )


def model_dataset_register(
    workspace: Path,
    *,
    program_record_id: str,
    manifest: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _model_research_result(
        "model_dataset_register",
        ModelResearchService(workspace).register_dataset_manifest(
            program_record_id=program_record_id,
            manifest=manifest,
            authorization_status=authorization_status,
        ),
    )


def model_research_account(
    workspace: Path,
    *,
    context_record_id: str,
    authorization_status: str,
) -> OperationResult:
    return _model_research_result(
        "model_research_account",
        ModelResearchService(workspace).account(
            context_record_id=context_record_id,
            authorization_status=authorization_status,
        ),
    )


def _p8_result(operation: str, outcome: Any) -> OperationResult:
    result: OperationResult = {
        "contract_id": "qste-contract/0.3.0",
        "operation": f"qste:{operation}/0.1.0",
        "value_type": outcome.value_type,
        "operation_status": outcome.operation_status,
        "value": outcome.value,
        "reason_code": outcome.reason_code,
        "authorization_status": outcome.authorization_status,
        "capability_status": "available",
        "receipt_id": outcome.receipt_record["record_id"],
        "diagnostics": {"event_sequence": outcome.event_sequence},
        "cli_exit_class": 0,
    }
    if getattr(outcome, "safety_record_ids", ()):
        result["diagnostics"]["safety_descendant_record_ids"] = list(outcome.safety_record_ids)
    repair_status = getattr(outcome, "repair_status", None)
    if repair_status is not None:
        result["domain_status"] = {"repair_status": repair_status}
    if outcome.operation_status == "partial":
        unresolved = list(outcome.unresolved_targets)
        if not unresolved:
            unresolved = ["repair_not_feasible"]
        result["unresolved_targets"] = unresolved
        result["partial_contract_id"] = "qste-repair-chain/v0.1"
        result["reason_code"] = "partial_completion"
        result["cli_exit_class"] = 6
    SchemaRegistry().validate_operation_result(result)
    return result


def mapping_declare(
    workspace: Path,
    *,
    context_record_id: str,
    specification: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _p8_result(
        "declare_mapping",
        TransductionService(workspace).declare_mapping(
            context_record_id=context_record_id,
            specification=specification,
            authorization_status=authorization_status,
        ),
    )


def transduce(
    workspace: Path,
    *,
    mode: str,
    source_record_ids: list[str],
    mapping_record_id: str,
    parameters: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _p8_result(
        f"transduce_{mode}",
        TransductionService(workspace).transduce(
            mode=mode,
            source_record_ids=source_record_ids,
            mapping_record_id=mapping_record_id,
            parameters=parameters,
            authorization_status=authorization_status,
        ),
    )


def governance_declare(
    workspace: Path,
    *,
    context_record_id: str,
    specification: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _p8_result(
        "declare_governance_boundary",
        PolicyService(workspace).declare_boundary(
            context_record_id=context_record_id,
            specification=specification,
            authorization_status=authorization_status,
        ),
    )


def appeal_open(
    workspace: Path,
    *,
    governance_boundary_record_id: str,
    appellant_record_id: str,
    responding_authority_record_id: str,
    target_record_id: str,
    specification: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _p8_result(
        "open_appeal",
        PolicyService(workspace).open_appeal(
            governance_boundary_record_id=governance_boundary_record_id,
            appellant_record_id=appellant_record_id,
            responding_authority_record_id=responding_authority_record_id,
            target_record_id=target_record_id,
            specification=specification,
            authorization_status=authorization_status,
        ),
    )


def appeal_adjudicate(
    workspace: Path,
    *,
    appeal_case_record_id: str,
    authority_record_id: str,
    outcome: str,
    evidence_record_ids: list[str],
    authorization_status: str,
) -> OperationResult:
    return _p8_result(
        "adjudicate",
        PolicyService(workspace).adjudicate(
            appeal_case_record_id=appeal_case_record_id,
            authority_record_id=authority_record_id,
            outcome=outcome,
            evidence_record_ids=evidence_record_ids,
            authorization_status=authorization_status,
        ),
    )


def repair_apply(
    workspace: Path,
    *,
    appeal_case_record_id: str,
    authority_record_id: str,
    repair_action: str,
    specification: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _p8_result(
        "apply_repair",
        PolicyService(workspace).apply_repair(
            appeal_case_record_id=appeal_case_record_id,
            authority_record_id=authority_record_id,
            repair_action=repair_action,
            specification=specification,
            authorization_status=authorization_status,
        ),
    )


def export_projection(
    workspace: Path,
    *,
    target_record_id: str,
    governance_boundary_record_id: str,
    disclosure_status: str,
    human_authorized: bool,
    authorization_status: str,
) -> OperationResult:
    return _p8_result(
        "export",
        PolicyService(workspace).export_projection(
            target_record_id=target_record_id,
            governance_boundary_record_id=governance_boundary_record_id,
            disclosure_status=disclosure_status,
            human_authorized=human_authorized,
            authorization_status=authorization_status,
        ),
    )


def _relation_result(operation: str, outcome: Any) -> OperationResult:
    value = outcome.value
    result = _completed(
        f"qste:{operation}/0.1.0",
        outcome.value_type,
        value,
        receipt_id=outcome.receipt_record["record_id"],
        diagnostics={"event_sequence": outcome.event_sequence},
    )
    if value.get("payload_type") == "RelationSet":
        status = value["data"]["comparison_status"]
        reasons = sorted({item["reason_code"] for item in value["items"]})
        result["reason_code"] = reasons[0] if len(reasons) == 1 else "completed"
        result["domain_status"] = {"comparison_status": status}
        result["cli_exit_class"] = 5 if status == "indeterminate" else 0
        SchemaRegistry().validate_operation_result(result)
    return result


def relation_declare_projection(
    workspace: Path,
    *,
    source_arm_record_id: str,
    specification: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _relation_result(
        "declare_projection",
        RelationService(workspace).declare_projection(
            source_arm_record_id=source_arm_record_id,
            specification=specification,
            authorization_status=authorization_status,
        ),
    )


def relation_declare_comparison(
    workspace: Path,
    *,
    projection_record_ids: list[str],
    specification: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _relation_result(
        "declare_comparison",
        RelationService(workspace).declare_comparison(
            projection_record_ids=projection_record_ids,
            specification=specification,
            authorization_status=authorization_status,
        ),
    )


def relation_compare(
    workspace: Path,
    *,
    comparison_spec_record_id: str,
    source_candidate_record_ids: list[str],
    target_candidate_record_ids: list[str],
    evidence: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _relation_result(
        "compare_relations",
        RelationService(workspace).compare(
            comparison_spec_record_id=comparison_spec_record_id,
            source_candidate_record_ids=source_candidate_record_ids,
            target_candidate_record_ids=target_candidate_record_ids,
            evidence=evidence,
            authorization_status=authorization_status,
        ),
    )


def relation_invalidate(
    workspace: Path,
    *,
    relation_assertion_record_id: str,
    invalidation_reason: str,
    evidence: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _relation_result(
        "invalidate_relation",
        RelationService(workspace).invalidate_relation(
            relation_assertion_record_id=relation_assertion_record_id,
            invalidation_reason=invalidation_reason,
            evidence=evidence,
            authorization_status=authorization_status,
        ),
    )


def _quanta_result(operation: str, outcome: Any) -> OperationResult:
    value = outcome.value
    result = _completed(
        f"qste:{operation}/0.1.0",
        outcome.value_type,
        value,
        receipt_id=outcome.receipt_record["record_id"],
        diagnostics={"event_sequence": outcome.event_sequence},
    )
    if value.get("record_type") == "DSQAssessment":
        status = value["assessment_status"]
        result["reason_code"] = value["reason_code"]
        result["domain_status"] = {"assessment_status": status}
        result["cli_exit_class"] = 5 if status == "indeterminate" else 0
        SchemaRegistry().validate_operation_result(result)
    return result


def task_declare(
    workspace: Path,
    *,
    candidate_record_id: str,
    refinement_graph_record_id: str | None,
    specification: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _quanta_result(
        "declare_task",
        QuantaService(workspace).declare_task(
            candidate_record_id=candidate_record_id,
            refinement_graph_record_id=refinement_graph_record_id,
            specification=specification,
            authorization_status=authorization_status,
        ),
    )


def task_execute(
    workspace: Path,
    *,
    task_record_id: str,
    score_evidence: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _quanta_result(
        "execute_task",
        QuantaService(workspace).execute_task(
            task_record_id=task_record_id,
            score_evidence=score_evidence,
            authorization_status=authorization_status,
        ),
    )


def quanta_assess(
    workspace: Path,
    *,
    candidate_record_id: str,
    task_record_id: str,
    run_record_id: str,
    refinement_graph_record_id: str | None,
    authorization_status: str,
) -> OperationResult:
    return _quanta_result(
        "assess",
        QuantaService(workspace).assess(
            candidate_record_id=candidate_record_id,
            task_record_id=task_record_id,
            run_record_id=run_record_id,
            refinement_graph_record_id=refinement_graph_record_id,
            authorization_status=authorization_status,
        ),
    )


def quanta_baseline(
    workspace: Path, *, assessment_record_id: str, authorization_status: str
) -> OperationResult:
    return _quanta_result(
        "baseline",
        QuantaService(workspace).evaluate_baselines(
            assessment_record_id=assessment_record_id,
            authorization_status=authorization_status,
        ),
    )


def quanta_invalidate(
    workspace: Path,
    *,
    assessment_record_id: str,
    invalidation_reason: str,
    evidence: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _quanta_result(
        "invalidate_dependency",
        QuantaService(workspace).invalidate_dependency(
            assessment_record_id=assessment_record_id,
            invalidation_reason=invalidation_reason,
            evidence=evidence,
            authorization_status=authorization_status,
        ),
    )


def _representation_result(operation: str, outcome: Any) -> OperationResult:
    return _completed(
        f"qste:{operation}/0.1.0",
        outcome.value_type,
        outcome.value,
        receipt_id=outcome.receipt_record["record_id"],
        diagnostics={"event_sequence": outcome.event_sequence, "profile": "qste-stft-gabor/v0.1"},
    )


def representation_encode(
    workspace: Path,
    *,
    artifact_record_id: str,
    aperture_record_id: str,
    config: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    outcome = STFTService(workspace).encode(
        artifact_record_id=artifact_record_id,
        aperture_record_id=aperture_record_id,
        config=stft_config_from_mapping(config),
        authorization_status=authorization_status,
    )
    return _representation_result("encode", outcome)


def representation_enumerate(
    workspace: Path,
    *,
    instance_record_id: str,
    candidate_rule: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _representation_result(
        "enumerate",
        STFTService(workspace).enumerate(
            instance_record_id=instance_record_id,
            candidate_rule=candidate_rule,
            authorization_status=authorization_status,
        ),
    )


def representation_refine(
    workspace: Path,
    *,
    candidate_record_id: str,
    procedure: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _representation_result(
        "refine",
        STFTService(workspace).refine(
            candidate_record_id=candidate_record_id,
            procedure=procedure,
            authorization_status=authorization_status,
        ),
    )


def representation_support(
    workspace: Path,
    *,
    candidate_record_id: str,
    support_spec: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _representation_result(
        "support",
        STFTService(workspace).support(
            candidate_record_id=candidate_record_id,
            support_spec=support_spec,
            authorization_status=authorization_status,
        ),
    )


def representation_address(
    workspace: Path,
    *,
    candidate_record_id: str,
    intervention_record_id: str,
    authorization_status: str,
) -> OperationResult:
    return _representation_result(
        "address",
        STFTService(workspace).address(
            candidate_record_id=candidate_record_id,
            intervention_record_id=intervention_record_id,
            authorization_status=authorization_status,
        ),
    )


def representation_intervene(
    workspace: Path,
    *,
    candidate_record_id: str,
    intervention_record_id: str,
    mode: str,
    control: str,
    authorization_status: str,
) -> OperationResult:
    return _representation_result(
        "intervene",
        STFTService(workspace).intervene(
            candidate_record_id=candidate_record_id,
            intervention_record_id=intervention_record_id,
            mode=mode,
            control=control,
            authorization_status=authorization_status,
        ),
    )


def representation_decode(
    workspace: Path, *, target_record_id: str, authorization_status: str
) -> OperationResult:
    return _representation_result(
        "decode",
        STFTService(workspace).decode(
            target_record_id=target_record_id,
            authorization_status=authorization_status,
        ),
    )


def representation_project(
    workspace: Path,
    *,
    candidate_record_id: str,
    projection_record_id: str,
    authorization_status: str,
) -> OperationResult:
    return _representation_result(
        "project",
        STFTService(workspace).project(
            candidate_record_id=candidate_record_id,
            projection_record_id=projection_record_id,
            authorization_status=authorization_status,
        ),
    )


def representation_measure(
    workspace: Path,
    *,
    left_candidate_record_id: str,
    right_candidate_record_id: str,
    metric_spec: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _representation_result(
        "measure",
        STFTService(workspace).measure(
            left_candidate_record_id=left_candidate_record_id,
            right_candidate_record_id=right_candidate_record_id,
            metric_spec=metric_spec,
            authorization_status=authorization_status,
        ),
    )


def representation_perturb(
    workspace: Path,
    *,
    instance_record_id: str,
    perturbation_spec: Mapping[str, Any],
    authorization_status: str,
) -> OperationResult:
    return _representation_result(
        "perturb",
        STFTService(workspace).perturb(
            instance_record_id=instance_record_id,
            perturbation_spec=perturbation_spec,
            authorization_status=authorization_status,
        ),
    )


def representation_account(
    workspace: Path, *, instance_record_id: str, authorization_status: str
) -> OperationResult:
    return _representation_result(
        "account",
        STFTService(workspace).account(
            instance_record_id=instance_record_id,
            authorization_status=authorization_status,
        ),
    )


def ingest(
    workspace: Path,
    path: Path,
    *,
    kind: str,
    apparatus_record_id: str,
    attributed_origin: str,
    rights: Mapping[str, Any],
    retention: Mapping[str, Any],
    authorization_status: str,
    allowed_roots: tuple[Path, ...],
    audio_transform: AudioTransform | None = None,
) -> OperationResult:
    """Execute one typed, bounded P4 local ingress operation."""

    outcome = IngressService(workspace, IngressLimits(allowed_roots)).ingest(
        path,
        kind=kind,
        apparatus_record_id=apparatus_record_id,
        attributed_origin=attributed_origin,
        rights=rights,
        retention=retention,
        authorization_status=authorization_status,
        audio_transform=audio_transform,
    )
    return _completed(
        "qste:ingest/0.1.0",
        outcome.acquisition_record["schema_id"],
        outcome.acquisition_record,
        receipt_id=outcome.receipt_record["record_id"],
        diagnostics={
            "source_record_id": outcome.source_record["record_id"],
            "original_artifact_record_id": outcome.original_artifact_record["record_id"],
            "result_artifact_record_id": outcome.result_artifact_record["record_id"],
            "observation_record_ids": [
                record["record_id"] for record in outcome.observation_records
            ],
            "event_sequence": outcome.event_sequence,
        },
    )


def declare_apparatus(workspace: Path, declaration: Mapping[str, Any]) -> OperationResult:
    """Validate and persist one exact P4 apparatus declaration."""

    outcome = persist_apparatus(workspace, declaration)
    return _completed(
        "qste:apparatus-validate/0.1.0",
        outcome.apparatus_record["schema_id"],
        outcome.apparatus_record,
        receipt_id=outcome.receipt_record["record_id"],
        diagnostics={"event_sequence": outcome.event_sequence},
    )


def derive_aperture(
    workspace: Path,
    *,
    apparatus_record_id: str,
    input_artifact_record_id: str,
    policy: Mapping[str, Any],
) -> OperationResult:
    """Persist the evidenced aperture for one apparatus/input/run intersection."""

    outcome = persist_aperture(
        workspace,
        apparatus_record_id=apparatus_record_id,
        input_artifact_record_id=input_artifact_record_id,
        policy=policy,
    )
    return _completed(
        "qste:aperture-derive/0.1.0",
        outcome.aperture_record["schema_id"],
        outcome.aperture_record,
        receipt_id=outcome.receipt_record["record_id"],
        diagnostics={
            "run_record_id": outcome.run_record["record_id"],
            "event_sequence": outcome.event_sequence,
        },
    )


def inspect(workspace: Path, record_id: str) -> OperationResult:
    """Return one validated stored occurrence, never a merged semantic aggregate."""

    store = _open_store(workspace)
    stored = store.get_record(record_id)
    return _completed(
        "qste:inspect/0.3.0",
        stored.record["schema_id"],
        stored.record,
        diagnostics={
            "storage_sequence": stored.storage_sequence,
            "record_digest": stored.record_digest,
        },
    )


def trace_lineage(
    workspace: Path,
    record_id: str,
    *,
    direction: str = "ancestors",
    maximum_depth: int = 64,
    maximum_edges: int | None = None,
) -> OperationResult:
    """Traverse dependency edges from one occurrence under an explicit bound."""

    store = _open_store(workspace)
    edges = store.trace_lineage(
        record_id,
        direction=direction,
        maximum_depth=maximum_depth,
        maximum_edges=maximum_edges,
    )
    value = {
        "payload_schema_id": "qste-payload/0.3.0",
        "payload_type": "TargetClosure",
        "items": [
            {
                "edge_sequence": edge.edge_sequence,
                "source_record_id": edge.source_record_id,
                "target_record_id": edge.target_record_id,
                "relation": edge.relation,
            }
            for edge in edges
        ],
        "data": {
            "root_record_id": record_id,
            "direction": direction,
            "maximum_depth": maximum_depth,
            "maximum_edges": maximum_edges,
            "edge_limit_reached": maximum_edges is not None and len(edges) == maximum_edges,
        },
    }
    return _completed("qste:lineage/0.3.0", "qste-payload/0.3.0/TargetClosure", value)


def verify(*, workspace: Path | None = None, bundle_root: Path | None = None) -> OperationResult:
    """Verify exactly one workspace or relocated bundle without repairing it."""

    if (workspace is None) == (bundle_root is None):
        raise ContractError("invalid_input", "verify requires exactly one local target")
    if bundle_root is not None:
        report = BundleReader(bundle_root).verify()
        data = {
            "target_kind": "bundle",
            "bundle_id": report.bundle_id,
            "manifest_digest": report.manifest_digest,
            "logical_state_digest": report.logical_state_digest,
            "integrity_claim": report.integrity_claim,
            "logical_replay_claim": report.logical_replay_claim,
            "numerical_reproducibility_claim": report.numerical_reproducibility_claim,
            "counts": {
                "records": report.record_count,
                "events": report.event_count,
                "edges": report.edge_count,
                "artifacts": report.artifact_count,
                "dense": report.dense_count,
            },
        }
    else:
        if workspace is None:  # defensive narrowing after the exclusive-target check above
            raise ContractError("invalid_input", "workspace target is absent")
        store = _open_store(workspace)
        verification = verify_workspace_storage(store)
        data = {
            "target_kind": "workspace",
            "counts": {
                "records": verification.record_count,
                "events": verification.event_count,
                "edges": verification.edge_count,
                "artifacts": verification.artifact_count,
                "dense": verification.dense_count,
            },
            "integrity_claim": "verified",
            "logical_replay_claim": "verified",
            "numerical_reproducibility_claim": "unavailable",
        }
    value = {
        "payload_schema_id": "qste-payload/0.3.0",
        "payload_type": "CapabilityAccount",
        "items": [],
        "data": data,
    }
    return _completed("qste:verify/0.3.0", "qste-payload/0.3.0/CapabilityAccount", value)


def bundle(
    workspace: Path,
    authority_manifest: Mapping[str, Any],
    *,
    bundle_id: str | None = None,
    retention_policy: Mapping[str, Any] | None = None,
    parent_bundle_ref: str | None = None,
    omission_manifest: list[dict[str, Any]] | None = None,
) -> OperationResult:
    """Seal and immediately verify a private, relocatable bundle."""

    store = RecordStore.initialize(workspace)
    artifacts = ArtifactStore(store.paths)
    dense = DenseStore(store.paths, store)
    path = BundleService(store.paths, store, artifacts, dense).seal_private(
        authority_manifest,
        bundle_id=bundle_id,
        retention_policy=retention_policy,
        parent_bundle_ref=parent_bundle_ref,
        omission_manifest=omission_manifest,
    )
    manifest = BundleReader(path).manifest()
    return _completed(
        "qste:bundle/0.3.0",
        f"{BASE_URI}/bundle-manifest.schema.json",
        manifest,
        diagnostics={"bundle_path": str(path)},
    )


def read_json_object(path: Path) -> dict[str, Any]:
    """Read one strict JSON object for a local command boundary."""

    if not path.is_file() or path.is_symlink():
        raise ContractError("invalid_input", f"JSON input is absent or unsafe: {path}")
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ContractError("invalid_input", "JSON input exceeds the 8 MiB command bound")
    value = loads_json(path.read_bytes())
    if not isinstance(value, dict):
        raise ContractError("invalid_input", "JSON input must be an object")
    return value


def _open_store(workspace: Path) -> RecordStore:
    return RecordStore(WorkspacePaths.open(workspace))


def failure_result(operation: str, error: ContractError) -> OperationResult:
    """Convert a bounded contract failure to the normative result/exit distinction."""

    reason = error.reason_code
    if reason == "capability_unavailable":
        status, capability, exit_class = (
            "unavailable",
            getattr(error, "capability_status", "unavailable"),
            4,
        )
    elif reason == "conformance_failed":
        status, capability, exit_class = "failed", "degraded", 8
    elif reason == "policy_refused":
        status, capability, exit_class = (
            "refused",
            getattr(error, "capability_status", "prohibited"),
            3,
        )
    elif reason == "execution_failed":
        status, capability, exit_class = "failed", "degraded", 7
    elif reason == "internal_error":
        status, capability, exit_class = "failed", "degraded", 9
    else:
        status, capability, exit_class = "failed", "available", 2
    result: OperationResult = {
        "contract_id": "qste-contract/0.3.0",
        "operation": operation,
        "value_type": "qste-payload/0.3.0/CapabilityAccount",
        "operation_status": status,
        "value": None,
        "reason_code": reason,
        "authorization_status": getattr(error, "authorization_status", "not_applicable"),
        "capability_status": capability,
        "receipt_id": getattr(error, "receipt_id", new_record_id("OperationReceipt")),
        "diagnostics": {
            "message": str(error),
            "path": list(error.path),
            **dict(getattr(error, "diagnostics_extra", {})),
        },
        "cli_exit_class": exit_class,
    }
    SchemaRegistry().validate_operation_result(result)
    return result


def _completed(
    operation: str,
    value_type: str,
    value: Any,
    *,
    diagnostics: Mapping[str, Any] | None = None,
    receipt_id: str | None = None,
) -> OperationResult:
    result: OperationResult = {
        "contract_id": "qste-contract/0.3.0",
        "operation": operation,
        "value_type": value_type,
        "operation_status": "completed",
        "value": value,
        "reason_code": "completed",
        "authorization_status": "not_applicable",
        "capability_status": "available",
        "receipt_id": receipt_id or new_record_id("OperationReceipt"),
        "diagnostics": dict(diagnostics or {}),
        "cli_exit_class": 0,
    }
    SchemaRegistry().validate_operation_result(result)
    return result
