from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from conftest import ROOT, fixture_record

from qste.core.contracts import ContractError
from qste.storage import ArtifactStore, BundleReader, BundleService, DenseStore, RecordStore


def _authority() -> dict[str, Any]:
    return cast(
        dict[str, Any], json.loads((ROOT / "authority" / "authority-manifest.json").read_text())
    )


def _populated_workspace(root: Path) -> tuple[RecordStore, ArtifactStore, DenseStore]:
    records = RecordStore.initialize(root)
    source = fixture_record("SourceRecord", "withheld.valid")
    records.insert_record(source)
    records.append_event(
        "qste:event/source-registered-v1",
        source["record_id"],
        {"availability": "withheld"},
        created_at="2026-08-28T03:00:00Z",
        event_uuid=uuid.UUID("60000000-0000-4000-8000-000000000001"),
    )
    artifacts = ArtifactStore(records.paths)
    artifact = artifacts.put_bytes(b"portable artifact")
    records.register_artifact(artifact.content_digest, artifact.size, artifact.relative_path)
    dense = DenseStore(records.paths, records)
    dense.write_array(
        "coordinates",
        np.array([1.0, 2.0, 3.0]),
        chunks=(2,),
        dimension_names=("sample",),
        coordinates={"sample": [0, 1, 2]},
        created_at="2026-08-28T03:00:00Z",
    )
    return records, artifacts, dense


def _seal(root: Path) -> Path:
    records, artifacts, dense = _populated_workspace(root)
    return BundleService(records.paths, records, artifacts, dense).seal_private(
        _authority(),
        bundle_id="qste:bundle:70000000-0000-4000-8000-000000000001",
        omission_manifest=[{"state": "withheld", "reason": "redistribution_not_confirmed"}],
    )


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_private_bundle_relocates_and_verifies_offline(tmp_path: Path) -> None:
    bundle = _seal(tmp_path / "workspace")
    original = BundleReader(bundle).verify()
    relocated = tmp_path / "relocated" / "bundle"
    shutil.copytree(bundle, relocated)
    copied = BundleReader(relocated).verify()
    assert copied == original
    assert copied.integrity_claim == "verified"
    assert copied.logical_replay_claim == "verified"
    assert copied.numerical_reproducibility_claim == "unavailable"
    assert BundleReader(relocated).records()[0]["record_type"] == "AuthorityManifest"
    assert any(
        record.get("availability") == "withheld" for record in BundleReader(relocated).records()
    )


def test_bundle_export_is_deterministic_for_fixed_inputs(tmp_path: Path) -> None:
    first = _seal(tmp_path / "first")
    second = _seal(tmp_path / "second")
    assert _tree_bytes(first) == _tree_bytes(second)


def test_bundle_tampering_and_symlinks_are_detected(tmp_path: Path) -> None:
    bundle = _seal(tmp_path / "workspace")
    record = next((bundle / "records").glob("*.json"))
    record.chmod(0o600)
    record.write_bytes(record.read_bytes() + b"tamper")
    with pytest.raises(ContractError, match="checksum mismatch"):
        BundleReader(bundle).verify()

    clean = _seal(tmp_path / "clean")
    (clean / "unsafe-link").symlink_to(clean / "manifest.json")
    with pytest.raises(ContractError, match="symlink"):
        BundleReader(clean).verify()
