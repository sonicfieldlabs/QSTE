from __future__ import annotations

from pathlib import Path

import pytest
from p4_helpers import apparatus_declaration

from qste.core.contracts import ContractError
from qste.ingress import declare_apparatus
from qste.storage import RecordStore, WorkspacePaths


def test_apparatus_declaration_is_exact_persisted_and_receipted(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outcome = declare_apparatus(workspace, apparatus_declaration())
    assert outcome.apparatus_record["record_type"] == "ApparatusSpec"
    assert outcome.apparatus_record["qste:apparatusProfile"] == "qste-apparatus/0.1"
    assert outcome.receipt_record["operation_status"] == "completed"
    assert outcome.apparatus_record["record_id"] != outcome.receipt_record["record_id"]
    store = RecordStore(WorkspacePaths.open(workspace))
    assert store.get_event(1).receipt_record_id == outcome.receipt_record["record_id"]
    store.verify()


def test_apparatus_rejects_implicit_authority_and_missing_calibration_domains(
    tmp_path: Path,
) -> None:
    declaration = apparatus_declaration()
    declaration["authorization_status"] = "unknown"
    with pytest.raises(ContractError, match="explicit permission"):
        declare_apparatus(tmp_path / "workspace", declaration)

    declaration = apparatus_declaration()
    del declaration["acquisition_surface"]["calibration"]["level"]
    with pytest.raises(ContractError, match="frequency, level, and time"):
        declare_apparatus(tmp_path / "workspace-2", declaration)
