from __future__ import annotations

import json
from pathlib import Path

from p14_helpers import FIXTURES, build_p14_fixture, fixture, registered_manifest

from qste.cli import main
from qste.operations import model_program_freeze, model_research_account


def test_python_operations_return_exact_nonexecution_envelopes(tmp_path: Path) -> None:
    p14 = build_p14_fixture(tmp_path)
    frozen = model_program_freeze(
        p14.workspace,
        context_record_id=p14.context["record_id"],
        specification=fixture("program.json"),
        authorization_status="permitted",
    )
    assert frozen["operation"] == "qste:model_program_freeze/0.1.0"
    assert frozen["diagnostics"]["training_executed"] is False
    assert frozen["diagnostics"]["checkpoint_downloaded"] is False
    assert frozen["diagnostics"]["generation_performed"] is False
    account = model_research_account(
        p14.workspace,
        context_record_id=p14.context["record_id"],
        authorization_status="permitted",
    )
    assert account["value"]["data"]["trained_model"] == "unavailable"


def test_cli_freeze_and_account(tmp_path: Path, capsys: object) -> None:
    p14 = build_p14_fixture(tmp_path)
    assert (
        main(
            [
                "model",
                "freeze",
                "--workspace",
                str(p14.workspace),
                "--context",
                p14.context["record_id"],
                "--program",
                str(FIXTURES / "program.json"),
                "--authorization",
                "permitted",
                "--json",
            ]
        )
        == 0
    )
    frozen = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert frozen["operation"] == "qste:model_program_freeze/0.1.0"
    assert (
        main(
            [
                "model",
                "account",
                "--workspace",
                str(p14.workspace),
                "--context",
                p14.context["record_id"],
                "--authorization",
                "permitted",
                "--json",
            ]
        )
        == 0
    )
    account = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert account["value"]["data"]["checkpoint_download"] == "unavailable"


def test_cli_registers_metadata_only_dataset_manifest(tmp_path: Path, capsys: object) -> None:
    p14 = build_p14_fixture(tmp_path)
    program = p14.service.freeze_program(
        context_record_id=p14.context["record_id"], specification=fixture("program.json")
    ).value
    manifest_path = tmp_path / "dataset-manifest.json"
    manifest_path.write_text(
        json.dumps(registered_manifest(program, p14.context), sort_keys=True) + "\n"
    )
    assert (
        main(
            [
                "model",
                "dataset",
                "--workspace",
                str(p14.workspace),
                "--program-record",
                program["record_id"],
                "--manifest",
                str(manifest_path),
                "--authorization",
                "permitted",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert result["value"]["qste:datasetStatus"] == "metadata_only_unverified_bytes"
    assert result["diagnostics"]["training_executed"] is False
