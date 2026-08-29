from __future__ import annotations

import json
from pathlib import Path

from p9_helpers import build_p9_fixture, capture_fixture, encode_and_enumerate

from qste.cli import main
from qste.operations import adapter_encode


def test_python_adapter_operation_returns_exact_envelope(tmp_path: Path) -> None:
    fixture = build_p9_fixture(tmp_path)
    result = adapter_encode(
        fixture.base.workspace,
        adapter_id="samplebrain",
        artifact_record_id=fixture.base.ingress_artifact["record_id"],
        aperture_record_id=fixture.base.aperture["record_id"],
        capture=capture_fixture(fixture, "samplebrain"),
        authorization_status="permitted",
    )
    assert result["operation"] == "qste:adapter_encode/0.1.0"
    assert result["operation_status"] == "completed"
    assert result["authorization_status"] == "permitted"
    assert result["diagnostics"]["adapter_id"] == "samplebrain"
    assert result["diagnostics"]["profile"] == "qste-external-representation-adapter/v0.1"


def test_cli_unavailable_operation_has_exit_four_and_durable_receipt(
    tmp_path: Path, capsys: object
) -> None:
    fixture = build_p9_fixture(tmp_path)
    _, candidates = encode_and_enumerate(fixture, "encodec")
    specification = tmp_path / "refine.json"
    specification.write_text(json.dumps({"attempt": "must_not_infer_hidden_state"}))
    exit_class = main(
        [
            "adapter",
            "run",
            "--workspace",
            str(fixture.base.workspace),
            "--operation",
            "refine",
            "--target",
            candidates[0]["record_id"],
            "--spec",
            str(specification),
            "--authorization",
            "permitted",
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert exit_class == 4
    assert result["operation_status"] == "unavailable"
    assert result["reason_code"] == "capability_unavailable"
    assert isinstance(result["receipt_id"], str)
