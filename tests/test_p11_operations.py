from __future__ import annotations

import json
from pathlib import Path

from p11_helpers import FIXTURES, build_p11_fixture, fixture

from qste.cli import main
from qste.operations import ecosystem_import, engine_execute


def test_python_ecosystem_and_engine_operations_use_exact_envelopes(tmp_path: Path) -> None:
    p11 = build_p11_fixture(tmp_path)
    imported = ecosystem_import(
        p11.workspace,
        target_id="akouo",
        context_record_id=p11.context["record_id"],
        payload=fixture("akouo-route-decision.json"),
        authorization_status="permitted",
    )
    assert imported["operation"] == "qste:ecosystem_import/0.1.0"
    assert imported["operation_status"] == "completed"
    assert imported["diagnostics"]["target_id"] == "akouo"

    executed = engine_execute(
        p11.workspace,
        target_id="qste_fixture_process",
        context_record_id=p11.context["record_id"],
        request=fixture("engine-process-request.json"),
        authorization_status="permitted",
    )
    assert executed["operation"] == "qste:engine_execute/0.1.0"
    assert executed["operation_status"] == "completed"
    assert executed["diagnostics"]["profile"] == "qste-bounded-engine-adapter/v0.1"


def test_cli_reports_unavailable_untested_and_prohibited_exactly(
    tmp_path: Path, capsys: object
) -> None:
    p11 = build_p11_fixture(tmp_path)
    untested_exit = main(
        [
            "engine",
            "execute",
            "--workspace",
            str(p11.workspace),
            "--target",
            "required_untested_fixture",
            "--context",
            p11.context["record_id"],
            "--request",
            str(FIXTURES / "engine-process-request.json"),
            "--authorization",
            "permitted",
            "--json",
        ]
    )
    untested = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert untested_exit == 4
    assert untested["operation_status"] == "unavailable"
    assert untested["reason_code"] == "capability_unavailable"
    assert untested["capability_status"] == "untested"

    prohibited_exit = main(
        [
            "engine",
            "execute",
            "--workspace",
            str(p11.workspace),
            "--target",
            "prohibited_fixture",
            "--context",
            p11.context["record_id"],
            "--request",
            str(FIXTURES / "engine-process-request.json"),
            "--authorization",
            "permitted",
            "--json",
        ]
    )
    prohibited = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert prohibited_exit == 3
    assert prohibited["operation_status"] == "refused"
    assert prohibited["reason_code"] == "policy_refused"
    assert prohibited["capability_status"] == "prohibited"
