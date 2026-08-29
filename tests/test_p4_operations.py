from __future__ import annotations

import json
from pathlib import Path

import pytest
from p4_helpers import RETENTION, RIGHTS, apparatus_declaration

from qste.cli import main
from qste.storage import RecordStore, WorkspacePaths


def test_p4_cli_returns_persisted_receipts_for_state_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    declaration = tmp_path / "apparatus.json"
    declaration.write_text(json.dumps(apparatus_declaration()))
    assert (
        main(
            [
                "apparatus",
                "validate",
                "--workspace",
                str(workspace),
                "--declaration",
                str(declaration),
                "--json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    store = RecordStore(WorkspacePaths.open(workspace))
    store.get_record(output["receipt_id"])

    source = tmp_path / "text.txt"
    source.write_text("opaque")
    rights = tmp_path / "rights.json"
    rights.write_text(json.dumps(RIGHTS))
    retention = tmp_path / "retention.json"
    retention.write_text(json.dumps(RETENTION))
    apparatus_id = output["value"]["record_id"]
    assert (
        main(
            [
                "ingest",
                "--workspace",
                str(workspace),
                "--input",
                str(source),
                "--kind",
                "text",
                "--apparatus",
                apparatus_id,
                "--origin",
                "fixture",
                "--rights",
                str(rights),
                "--retention",
                str(retention),
                "--allowed-root",
                str(tmp_path),
                "--authorization",
                "permitted",
                "--json",
            ]
        )
        == 0
    )
    ingress_output = json.loads(capsys.readouterr().out)
    store.get_record(ingress_output["receipt_id"])
