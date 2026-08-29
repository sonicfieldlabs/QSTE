from __future__ import annotations

import json
from pathlib import Path

from p10_helpers import build_p10_fixture, proposal, treatments

from qste.cli import main
from qste.operations import agent_plan, agent_revise


def test_python_plan_and_revise_return_exact_operation_envelopes(tmp_path: Path) -> None:
    fixture = build_p10_fixture(tmp_path)
    material = treatments(fixture)["authentic"]
    planned = agent_plan(
        fixture.base.workspace,
        opportunity_record_id=fixture.opportunity["record_id"],
        treatment_record_id=material["record_id"],
        proposal=proposal(fixture, action_id="revise_action_set", treatment="authentic"),
        authorization_status="permitted",
    )
    assert planned["operation"] == "qste:plan/0.1.0"
    assert planned["diagnostics"]["creative_consequence"] == "not_assessed"
    revised = agent_revise(
        fixture.base.workspace,
        plan_record_id=planned["value"]["record_id"],
        authority_record_id=fixture.base.apparatus["record_id"],
        source_authorization_status="permitted",
        enforcement_mode="active",
        fixture_authorization="synthetic",
        human_authorized=False,
        authorization_status="permitted",
    )
    assert revised["operation"] == "qste:revise/0.1.0"
    assert revised["operation_status"] == "completed"
    assert revised["value"]["data"]["successor_created"] is True


def test_cli_plan_and_revoked_source_refusal_use_zero_then_three(
    tmp_path: Path, capsys: object
) -> None:
    fixture = build_p10_fixture(tmp_path)
    material = treatments(fixture)["authentic"]
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            proposal(
                fixture,
                action_id="revise_action_set",
                treatment="authentic",
            )
        )
    )
    plan_exit = main(
        [
            "plan",
            "--workspace",
            str(fixture.base.workspace),
            "--opportunity",
            fixture.opportunity["record_id"],
            "--treatment",
            material["record_id"],
            "--proposal",
            str(proposal_path),
            "--authorization",
            "permitted",
            "--json",
        ]
    )
    plan_result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert plan_exit == 0
    revise_exit = main(
        [
            "revise",
            "--workspace",
            str(fixture.base.workspace),
            "--plan",
            plan_result["value"]["record_id"],
            "--authority",
            fixture.base.apparatus["record_id"],
            "--source-authorization",
            "revoked",
            "--enforcement-mode",
            "shadow",
            "--fixture-authorization",
            "synthetic",
            "--authorization",
            "permitted",
            "--json",
        ]
    )
    revised = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert revise_exit == 3
    assert revised["operation_status"] == "refused"
    assert revised["reason_code"] == "policy_refused"
    assert revised["value"] is None
    assert len(revised["diagnostics"]["output_record_ids"]) == 1
