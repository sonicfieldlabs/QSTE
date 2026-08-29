from __future__ import annotations

import json
from pathlib import Path

from p8_helpers import (
    appeal_specification,
    artifact_parameters,
    build_p8_fixture,
    mapping_specification,
)

from qste.cli import main
from qste.operations import mapping_declare, transduce
from qste.policy import PolicyService


def test_python_operations_return_exact_p8_operation_envelopes(tmp_path: Path) -> None:
    fixture = build_p8_fixture(tmp_path)
    mapping_result = mapping_declare(
        fixture.workspace,
        context_record_id=fixture.observations[0]["record_id"],
        specification=mapping_specification(),
        authorization_status="permitted",
    )
    assert mapping_result["operation"] == "qste:declare_mapping/0.1.0"
    assert mapping_result["operation_status"] == "completed"
    transduction_result = transduce(
        fixture.workspace,
        mode="sonification",
        source_record_ids=[fixture.observations[0]["record_id"]],
        mapping_record_id=mapping_result["value"]["record_id"],
        parameters=artifact_parameters(fixture, mode="sonification"),
        authorization_status="permitted",
    )
    assert transduction_result["operation"] == "qste:transduce_sonification/0.1.0"
    assert transduction_result["authorization_status"] == "permitted"
    assert transduction_result["diagnostics"]["safety_descendant_record_ids"]


def test_cli_refusal_and_partial_repair_use_distinct_exit_classes(
    tmp_path: Path, capsys: object
) -> None:
    fixture = build_p8_fixture(tmp_path)
    parameters_path = tmp_path / "parameters.json"
    parameters_path.write_text(json.dumps(artifact_parameters(fixture, mode="sonification")))
    refused_exit = main(
        [
            "transduce",
            "run",
            "--workspace",
            str(fixture.workspace),
            "--mode",
            "sonification",
            "--source",
            fixture.observations[0]["record_id"],
            "--mapping",
            fixture.mapping["record_id"],
            "--parameters",
            str(parameters_path),
            "--authorization",
            "revoked",
            "--json",
        ]
    )
    refused = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert refused_exit == 3
    assert refused["operation_status"] == "refused"
    assert refused["reason_code"] == "policy_refused"
    assert refused["authorization_status"] == "revoked"

    policy = PolicyService(fixture.workspace)
    opened = policy.open_appeal(
        governance_boundary_record_id=fixture.boundary["record_id"],
        appellant_record_id=fixture.appellant["record_id"],
        responding_authority_record_id=fixture.authority["record_id"],
        target_record_id=fixture.artifact["record_id"],
        specification=appeal_specification(fixture, requested_action="delete"),
    ).value
    assert opened is not None
    adjudicated = policy.adjudicate(
        appeal_case_record_id=opened["record_id"],
        authority_record_id=fixture.authority["record_id"],
        outcome="partial",
        evidence_record_ids=[fixture.observations[0]["record_id"]],
    ).value
    assert adjudicated is not None
    repair_spec = tmp_path / "repair.json"
    repair_spec.write_text(
        json.dumps(
            {
                "feasible_change_or_stop": True,
                "retention": {"mode": "retain", "reason": "audit duty"},
                "external_copies": [
                    {"locator": "external://uncontrolled-copy", "authority": "outside_qste"}
                ],
                "propagation_failures": [],
                "maximum_depth": 64,
            }
        )
    )
    partial_exit = main(
        [
            "repair",
            "apply",
            "--workspace",
            str(fixture.workspace),
            "--case",
            adjudicated["record_id"],
            "--authority",
            fixture.authority["record_id"],
            "--action",
            "delete",
            "--spec",
            str(repair_spec),
            "--authorization",
            "permitted",
            "--json",
        ]
    )
    partial = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert partial_exit == 6
    assert partial["operation_status"] == "partial"
    assert partial["reason_code"] == "partial_completion"
    assert partial["domain_status"] == {"repair_status": "partially_applied"}
