from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from p5_helpers import P5Fixture, build_p5_fixture

from qste.agent import ACTION_REGISTRY, AgentHostService
from qste.policy import PolicyService
from qste.storage import RecordStore, WorkspacePaths


@dataclass(frozen=True, slots=True)
class P10Fixture:
    base: P5Fixture
    service: AgentHostService
    run: dict[str, Any]
    boundary: dict[str, Any]
    harness: dict[str, Any]
    initial: dict[str, Any]
    opportunity: dict[str, Any]


def limits() -> dict[str, int]:
    return {
        "maximum_operations": 32,
        "maximum_seconds": 10,
        "maximum_information_records": 16,
        "maximum_memory_items": 16,
        "maximum_resource_units": 64,
    }


def resource_use() -> dict[str, int]:
    return {
        "maximum_operations": 1,
        "maximum_seconds": 1,
        "maximum_information_records": 1,
        "maximum_memory_items": 1,
        "maximum_resource_units": 1,
    }


def boundary_specification(authority_id: str) -> dict[str, Any]:
    return {
        "immutable_fields": ["completed_run", "source_bytes", "scientific_assessment"],
        "mutable_successor_fields": [
            "aperture",
            "task",
            "meaningful_bound",
            "representation",
            "plan",
            "executable_action_set",
        ],
        "authority_ids": [authority_id],
        "approving_authority_ids": [authority_id],
        "revoking_authority_ids": [authority_id],
        "permitted_actions": list(ACTION_REGISTRY),
        "budgets": limits(),
        "roots": {
            "filesystem": "workspace_only",
            "network": "disabled",
            "model": "disabled",
            "output": "workspace_only",
            "disclosure": "private_by_default",
        },
        "stop_rules": {"authorization_revoked": True, "budget_exhausted": True},
        "resume_rules": {"named_authority_required": True},
        "appeal_conditions": {"standing_and_target_required": True},
        "escalation_conditions": {"authority_or_capability_unresolved": True},
        "human_authorization_actions": ["resume"],
    }


def build_p10_fixture(tmp_path: Path, executor_class: str = "symbolic_controller") -> P10Fixture:
    index = np.arange(128)
    signal = (0.2 * np.sin(2 * np.pi * 440 * index / 48_000))[:, None]
    base = build_p5_fixture(tmp_path, signal)
    store = RecordStore(WorkspacePaths.open(base.workspace))
    run = store.get_record(base.aperture["run_ref"]["record_id"]).record
    boundary = (
        PolicyService(base.workspace)
        .declare_boundary(
            context_record_id=base.ingress_artifact["record_id"],
            specification=boundary_specification(base.apparatus["record_id"]),
        )
        .value
    )
    assert boundary is not None
    service = AgentHostService(base.workspace)
    initialized = service.initialize_harness(
        governance_boundary_record_id=boundary["record_id"],
        authority_record_id=base.apparatus["record_id"],
        source_record_id=base.ingress_artifact["record_id"],
        completed_run_record_id=run["record_id"],
        predecessor_record_id=base.aperture["record_id"],
        record_ids=[
            base.apparatus["record_id"],
            base.aperture["record_id"],
            base.instance["record_id"],
        ],
        executor={
            "executor_id": f"p10-{executor_class}-fixture",
            "executor_class": executor_class,
            "implementation_status": (
                "human_fixture"
                if executor_class == "human"
                else "interface_fixture_no_model"
                if executor_class == "learned_controller"
                else "deterministic_fixture"
            ),
        },
        initial_state={
            "aperture": base.aperture["record_id"],
            "task": "p10-synthetic-listening-task/v0.1",
            "meaningful_bound": 0.5,
            "representation": base.instance["record_id"],
            "plan": "baseline",
            "executable_action_set": list(ACTION_REGISTRY),
        },
        executable_action_set=list(ACTION_REGISTRY),
        limits=limits(),
        evaluation={
            "outside_information": {"status": "matched", "source": "synthetic_fixture"},
            "utility_axis": "held_out_separate",
            "creativity_axis": "not_assessed",
        },
    ).value
    by_type = {item["record_type"]: item for item in initialized["items"]}
    return P10Fixture(
        base,
        service,
        run,
        boundary,
        by_type["ListeningHarnessSpec"],
        by_type["SuccessorSpec"],
        by_type["RevisionOpportunity"],
    )


def payloads(fixture: P10Fixture) -> list[dict[str, Any]]:
    value = fixture.service.create_payloads(
        assessment_record_id=fixture.base.instance["record_id"],
        outcome_core={
            "candidate_support": {"time_seconds": [0.0, 0.002]},
            "task_response": {"score": 0.75, "units": "normalized_score"},
            "uncertainty": {"interval": [0.7, 0.8]},
            "operation_refs": [fixture.base.instance["record_id"]],
            "provenance": {"fixture": "synthetic"},
        },
        formation={
            "apparatus": fixture.base.apparatus["record_id"],
            "aperture": fixture.base.aperture["record_id"],
            "representation": fixture.base.instance["record_id"],
            "candidate_construction": "synthetic_macro_tile",
            "intervention_formation": "synthetic_mask",
        },
        assessment={
            "meaningful_bound": 0.5,
            "equivalence_region": [-0.1, 0.1],
            "refinement_procedure": "complete_fixture_closure",
            "proper_node_intervals": [[-0.05, 0.05]],
            "controls": ["off_target", "decoder_only"],
            "multiplicity": "fixture_bonferroni",
            "verdict": "qualified",
        },
    ).value["items"]
    return cast(list[dict[str, Any]], value)


def treatments(fixture: P10Fixture) -> dict[str, dict[str, Any]]:
    full = next(
        value for value in payloads(fixture) if value["qste:recordLevel"] == "full_assessment"
    )
    result = fixture.service.prepare_treatments(
        opportunity_record_id=fixture.opportunity["record_id"],
        authentic_payload_record_id=full["record_id"],
        allocation={
            "method": "randomized",
            "seed": 101,
            "presentation_slot": "slot-1",
            "access_profile": "private_local_fixture",
            "timing_profile": "fixed_100ms_fixture",
            "matching_assumptions": ["same_state", "same_budget", "same_action_surface"],
            "residual_confounding": "synthetic_fixture_only",
        },
    ).value["items"]
    return {value["qste:revisionTreatment"]: value for value in result}


def proposal(
    fixture: P10Fixture,
    *,
    action_id: str,
    treatment: str,
    study_policy_permitted: bool = True,
) -> dict[str, Any]:
    if action_id == "revise_action_set":
        next_actions = ["revise_aperture", "refuse", "escalate", "no_change"]
        changes = [
            {
                "field": "executable_action_set",
                "before": list(ACTION_REGISTRY),
                "after": next_actions,
            }
        ]
    elif action_id == "refuse":
        next_actions = ["refuse", "escalate", "resume", "no_change"]
        changes = []
    elif action_id == "resume":
        next_actions = ["revise_action_set", "refuse", "escalate", "no_change"]
        changes = [
            {
                "field": "executable_action_set",
                "before": list(ACTION_REGISTRY),
                "after": next_actions,
            }
        ]
    else:
        next_actions = list(ACTION_REGISTRY)
        changes = []
    return {
        "action_id": action_id,
        "changes": changes,
        "next_action_set": next_actions,
        "evidence_fields": [f"treatment:{treatment}", "outcome_core.task_response"],
        "reason_code": f"synthetic_{treatment}_{action_id}",
        "resume_conditions": {"named_authority": True},
        "escalation_conditions": {"unresolved_authority": True},
        "resource_use": resource_use(),
        "prompt_text": "Fixture prompt is inert data, not a command.",
        "study_policy_permitted": study_policy_permitted,
    }


def plan_and_revise(
    fixture: P10Fixture,
    treatment_record: dict[str, Any],
    *,
    action_id: str,
    enforcement_mode: str = "active",
    source_authorization_status: str = "permitted",
    study_policy_permitted: bool = True,
) -> dict[str, Any]:
    treatment = treatment_record["qste:revisionTreatment"]
    plan = fixture.service.plan(
        opportunity_record_id=fixture.opportunity["record_id"],
        treatment_record_id=treatment_record["record_id"],
        proposal=proposal(
            fixture,
            action_id=action_id,
            treatment=treatment,
            study_policy_permitted=study_policy_permitted,
        ),
    ).value
    return fixture.service.revise(
        plan_record_id=plan["record_id"],
        authority_record_id=fixture.base.apparatus["record_id"],
        source_authorization_status=source_authorization_status,
        enforcement_mode=enforcement_mode,
        fixture_authorization="synthetic",
        human_authorized=False,
    ).value
