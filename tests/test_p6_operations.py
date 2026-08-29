from __future__ import annotations

import json
from pathlib import Path

from p6_helpers import declare_and_execute, p6_fixture

from qste.cli import main
from qste.operations import quanta_assess


def test_assessment_operation_and_cli_use_domain_status_and_exit_class(
    tmp_path: Path, capsys: object
) -> None:
    fixture, candidate, graph = p6_fixture(tmp_path)
    proper = graph["required_closure"]
    _service, task, run = declare_and_execute(
        fixture.workspace,
        candidate,
        graph,
        {candidate["record_id"]: 0.5, proper[0]: 0.0, proper[1]: 0.0},
    )
    result = quanta_assess(
        fixture.workspace,
        candidate_record_id=candidate["record_id"],
        task_record_id=task["record_id"],
        run_record_id=run["record_id"],
        refinement_graph_record_id=graph["record_id"],
        authorization_status="permitted",
    )
    assert result["operation_status"] == "completed"
    assert result["domain_status"] == {"assessment_status": "indeterminate"}
    assert result["reason_code"] == "candidate_boundary_crossing"
    assert result["cli_exit_class"] == 5

    exit_class = main(
        [
            "quanta",
            "assess",
            "--workspace",
            str(fixture.workspace),
            "--candidate",
            candidate["record_id"],
            "--task",
            task["record_id"],
            "--run",
            run["record_id"],
            "--graph",
            graph["record_id"],
            "--authorization",
            "permitted",
            "--json",
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert exit_class == 5
    assert payload["domain_status"]["assessment_status"] == "indeterminate"
    assert payload["receipt_id"].startswith("qste:operation-receipt:")
