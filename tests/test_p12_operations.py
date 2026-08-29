from __future__ import annotations

import json
from pathlib import Path

from p12_helpers import FIXTURES, build_p12_fixture, fixture

from qste.cli import main
from qste.operations import experiment_freeze, experiment_pilot


def test_python_operations_return_exact_envelopes(tmp_path: Path) -> None:
    p12 = build_p12_fixture(tmp_path)
    frozen = experiment_freeze(
        p12.workspace,
        context_record_id=p12.context["record_id"],
        packet=fixture("preparation.json"),
        authorization_status="permitted",
    )
    assert frozen["operation"] == "qste:experiment_freeze/0.1.0"
    assert frozen["diagnostics"]["human_data_collected"] is False
    pilot = experiment_pilot(
        p12.workspace,
        preparation_record_id=frozen["value"]["record_id"],
        evidence=fixture("pilot.json"),
        authorization_status="permitted",
    )
    assert pilot["operation_status"] == "completed"
    assert pilot["diagnostics"]["confirmatory_hypotheses_tested"] is False


def test_cli_freeze_and_account(tmp_path: Path, capsys: object) -> None:
    p12 = build_p12_fixture(tmp_path)
    assert (
        main(
            [
                "experiment",
                "freeze",
                "--workspace",
                str(p12.workspace),
                "--context",
                p12.context["record_id"],
                "--packet",
                str(FIXTURES / "preparation.json"),
                "--authorization",
                "permitted",
                "--json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert output["operation"] == "qste:experiment_freeze/0.1.0"
    assert (
        main(
            [
                "experiment",
                "account",
                "--workspace",
                str(p12.workspace),
                "--context",
                p12.context["record_id"],
                "--authorization",
                "permitted",
                "--json",
            ]
        )
        == 0
    )
    account = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert account["value"]["data"]["human_data_collection"] == "prohibited"
