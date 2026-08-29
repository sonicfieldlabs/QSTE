from __future__ import annotations

import json
from pathlib import Path

from conftest import fixture_record

from qste import inspect, trace_lineage, verify
from qste.cli import main
from qste.storage import RecordStore


def test_python_p3_operations_return_valid_structured_results(tmp_path: Path) -> None:
    store = RecordStore.initialize(tmp_path / "workspace")
    record = fixture_record("SourceRecord")
    store.insert_record(record)
    inspected = inspect(store.paths.root, record["record_id"])
    lineage = trace_lineage(store.paths.root, record["record_id"])
    verification = verify(workspace=store.paths.root)
    assert inspected["value"]["record_id"] == record["record_id"]
    assert lineage["value"]["items"] == []
    assert verification["value"]["data"]["counts"]["records"] == 1
    exit_classes = {
        inspected["cli_exit_class"],
        lineage["cli_exit_class"],
        verification["cli_exit_class"],
    }
    assert exit_classes == {0}


def test_cli_verify_and_failure_use_normative_exit_classes(tmp_path: Path, capsys: object) -> None:
    store = RecordStore.initialize(tmp_path / "workspace")
    assert main(["verify", "--workspace", str(store.paths.root), "--json"]) == 0
    completed = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert completed["operation_status"] == "completed"
    assert completed["reason_code"] == "completed"

    arguments = [
        "inspect",
        "--workspace",
        str(store.paths.root),
        "--record",
        "absent",
        "--json",
    ]
    assert main(arguments) == 4
    unavailable = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert unavailable["operation_status"] == "unavailable"
    assert unavailable["reason_code"] == "capability_unavailable"
