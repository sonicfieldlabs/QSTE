from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from p4_helpers import RETENTION, RIGHTS, apparatus_declaration

from qste.ingress import IngressLimits, IngressService, declare_apparatus
from qste.policy import PolicyService
from qste.transduction import TransductionService


@dataclass(frozen=True, slots=True)
class P8Fixture:
    workspace: Path
    apparatus: dict[str, Any]
    appellant: dict[str, Any]
    authority: dict[str, Any]
    artifact: dict[str, Any]
    control_artifact: dict[str, Any]
    observations: tuple[dict[str, Any], ...]
    mapping: dict[str, Any]
    boundary: dict[str, Any]


def mapping_specification() -> dict[str, Any]:
    return {
        "source_domain": {"id": "normalized_observation", "version": "v0.1"},
        "target_domain": {"id": "normalized_sonic_parameter", "version": "v0.1"},
        "variables": [{"source": "response", "target": "fixture_parameter"}],
        "units": {"source": "normalized_score", "target": "normalized_amplitude"},
        "normalization": {"method": "linear_range"},
        "uncertainty": {"method": "absolute_bound", "absolute_bound": 0.01},
        "missing_data_behavior": "fail",
        "interpolation": {"method": "linear"},
        "range": {"source": [0.0, 1.0], "target": [-1.0, 1.0]},
        "loss": {"known": True, "description": "bounded scalar projection discards context"},
        "reversibility_claim": "partially_reversible",
        "allowed_transduction_modes": [
            "sonification",
            "desonification",
            "resonification",
            "sonic_transformation",
            "cross_domain_contrast",
        ],
    }


def boundary_specification(authority_id: str) -> dict[str, Any]:
    return {
        "immutable_fields": ["completed_run", "source_bytes", "scientific_assessment"],
        "mutable_successor_fields": [
            "authorization_status",
            "pause_status",
            "permitted_actions",
            "successor_spec",
        ],
        "authority_ids": [authority_id],
        "approving_authority_ids": [authority_id],
        "revoking_authority_ids": [authority_id],
        "permitted_actions": [
            "transduce",
            "export",
            "appeal",
            "adjudicate",
            "pause",
            "correct",
            "revoke",
            "delete",
            "restrict",
            "restore",
            "release_pause",
        ],
        "budgets": {"maximum_operations": 256, "maximum_seconds": 30},
        "roots": {
            "filesystem": "workspace_only",
            "network": "disabled",
            "model": "disabled",
            "output": "workspace_only",
            "disclosure": "private_by_default",
        },
        "stop_rules": {"authorization_revoked": True, "pause_active": True},
        "resume_rules": {"named_authority_required": True},
        "appeal_conditions": {"standing_and_target_required": True},
        "escalation_conditions": {"jurisdiction_unresolved": True},
        "human_authorization_actions": ["export", "delete", "restore"],
    }


def build_p8_fixture(tmp_path: Path) -> P8Fixture:
    workspace = tmp_path / "workspace"
    apparatus = declare_apparatus(workspace, apparatus_declaration()).apparatus_record
    ingress = IngressService(workspace, IngressLimits((tmp_path,)))
    observations_path = tmp_path / "observations.json"
    observations_path.write_text(
        json.dumps(
            {
                "profile_id": "qste-numerical-observations/0.1",
                "observations": [
                    {
                        "variable": "response",
                        "observation_state": "value",
                        "value": 0.25,
                        "units": "normalized_score",
                        "method": "p8-fixture/v0.1",
                        "evidence_basis": "instrumentally_derived",
                    },
                    {
                        "variable": "control_response",
                        "observation_state": "value",
                        "value": 0.5,
                        "units": "normalized_score",
                        "method": "p8-fixture/v0.1",
                        "evidence_basis": "instrumentally_derived",
                    },
                ],
            }
        )
    )
    observation_ingress = ingress.ingest(
        observations_path,
        kind="json_observations",
        apparatus_record_id=apparatus["record_id"],
        attributed_origin="P8 synthetic fixture",
        rights=RIGHTS,
        retention=RETENTION,
        authorization_status="permitted",
    )
    control_path = tmp_path / "control.txt"
    control_path.write_text("P8 bounded control fixture")
    control_ingress = ingress.ingest(
        control_path,
        kind="text",
        apparatus_record_id=apparatus["record_id"],
        attributed_origin="P8 synthetic control fixture",
        rights=RIGHTS,
        retention=RETENTION,
        authorization_status="permitted",
    )
    transducer = TransductionService(workspace)
    mapping = transducer.declare_mapping(
        context_record_id=observation_ingress.observation_records[0]["record_id"],
        specification=mapping_specification(),
    ).value
    assert mapping is not None
    policy = PolicyService(workspace)
    boundary = policy.declare_boundary(
        context_record_id=observation_ingress.result_artifact_record["record_id"],
        specification=boundary_specification(apparatus["record_id"]),
    ).value
    assert boundary is not None
    return P8Fixture(
        workspace=workspace,
        apparatus=apparatus,
        appellant=observation_ingress.source_record,
        authority=apparatus,
        artifact=observation_ingress.result_artifact_record,
        control_artifact=control_ingress.result_artifact_record,
        observations=observation_ingress.observation_records,
        mapping=mapping,
        boundary=boundary,
    )


def appeal_specification(fixture: P8Fixture, *, requested_action: str = "revoke") -> dict[str, Any]:
    return {
        "standing_basis": "authorized representative of the synthetic fixture source",
        "standing_verified": True,
        "standing_evidence_record_id": fixture.observations[0]["record_id"],
        "requested_action": requested_action,
        "deadlines": {"response_due": "2026-09-01T00:00:00Z"},
        "jurisdiction": "qste_synthetic_fixture",
        "pause_requested": True,
        "pause_risk_threshold_met": True,
        "duty_to_respond": True,
    }


def artifact_parameters(fixture: P8Fixture, *, mode: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "values": [0.25, 0.5, 0.75],
        "control_record_id": fixture.control_artifact["record_id"],
        "safety_controls": {
            "maximum_normalized_peak": 0.8,
            "playback": "disabled",
            "emergency_stop": "available_if_later_rendered",
        },
    }
    if mode == "sonification":
        result["control_record_id"] = fixture.observations[1]["record_id"]
        result["target_apparatus_record_id"] = fixture.apparatus["record_id"]
    else:
        result["context_record_id"] = fixture.artifact["record_id"]
    return result
