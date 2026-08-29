from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from conftest import ROOT, fixture_record

from qste.core import canonical_json_bytes, content_digest
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


def _write_bundle_manifest(bundle: Path, manifest: dict[str, Any]) -> None:
    without_digest = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    manifest["manifest_digest"] = content_digest(canonical_json_bytes(without_digest))
    path = bundle / "manifest.json"
    path.chmod(0o600)
    path.write_bytes(canonical_json_bytes(manifest))


def _update_checksum(manifest: dict[str, Any], relative: str, data: bytes) -> None:
    entry = next(item for item in manifest["checksums"] if item["path"] == relative)
    entry["content_digest"] = content_digest(data)
    entry["size"] = len(data)


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


def test_bundle_refuses_unregistered_workspace_objects(tmp_path: Path) -> None:
    records, artifacts, dense = _populated_workspace(tmp_path / "workspace")
    artifacts.put_bytes(b"unregistered object")
    with pytest.raises(ContractError, match="artifact filesystem closure"):
        BundleService(records.paths, records, artifacts, dense).seal_private(_authority())


def test_bundle_rejects_self_consistent_but_semantically_undeclared_file(tmp_path: Path) -> None:
    bundle = _seal(tmp_path / "workspace")
    extra = bundle / "extra.txt"
    extra.write_bytes(b"not part of a declared bundle surface")
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["checksums"].append(
        {
            "path": "extra.txt",
            "content_digest": content_digest(extra.read_bytes()),
            "size": extra.stat().st_size,
        }
    )
    _write_bundle_manifest(bundle, manifest)
    with pytest.raises(ContractError, match="undeclared semantic file"):
        BundleReader(bundle).verify()


def test_bundle_rejects_self_consistent_dense_semantic_metadata_tampering(
    tmp_path: Path,
) -> None:
    bundle = _seal(tmp_path / "workspace")
    relative = "dense/coordinates.manifest.json"
    dense_path = bundle / relative
    dense_manifest = json.loads(dense_path.read_text())
    dense_manifest["coordinates"]["sample"]["shape"] = [4]
    dense_without_digest = {
        key: value for key, value in dense_manifest.items() if key != "manifest_digest"
    }
    dense_manifest["manifest_digest"] = content_digest(canonical_json_bytes(dense_without_digest))
    dense_bytes = canonical_json_bytes(dense_manifest)
    dense_path.chmod(0o600)
    dense_path.write_bytes(dense_bytes)

    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["dense_manifests"][0]["manifest_digest"] = dense_manifest["manifest_digest"]
    _update_checksum(manifest, relative, dense_bytes)
    _write_bundle_manifest(bundle, manifest)
    with pytest.raises(ContractError, match="coordinate metadata mismatch"):
        BundleReader(bundle).verify()


def test_bundle_rejects_boolean_checksum_size_before_identity_comparison(tmp_path: Path) -> None:
    bundle = _seal(tmp_path / "workspace")
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["checksums"][0]["size"] = True
    _write_bundle_manifest(bundle, manifest)
    with pytest.raises(ContractError, match="nonnegative integer"):
        BundleReader(bundle).verify()
