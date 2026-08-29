"""Exact database-to-filesystem closure verification for QSTE workspaces."""

from __future__ import annotations

from dataclasses import dataclass

from qste.core import canonical_json_bytes
from qste.core.contracts import ContractError
from qste.storage.artifacts import ArtifactStore
from qste.storage.database import RecordStore
from qste.storage.dense import DenseStore


@dataclass(frozen=True, slots=True)
class WorkspaceVerification:
    record_count: int
    event_count: int
    edge_count: int
    artifact_count: int
    dense_count: int


def verify_workspace_storage(
    record_store: RecordStore,
    artifact_store: ArtifactStore | None = None,
    dense_store: DenseStore | None = None,
) -> WorkspaceVerification:
    """Verify authoritative rows and require an exact registered object closure."""

    artifacts = artifact_store or ArtifactStore(record_store.paths)
    dense = dense_store or DenseStore(record_store.paths, record_store)
    record_store.verify()

    registered_artifacts = record_store.iter_artifact_registrations()
    stored_artifacts = artifacts.iter_objects()
    expected_artifacts = {
        (item.content_digest, item.size, item.relative_path) for item in registered_artifacts
    }
    actual_artifacts = {
        (item.content_digest, item.size, item.relative_path) for item in stored_artifacts
    }
    if expected_artifacts != actual_artifacts:
        raise ContractError(
            "conformance_failed",
            "artifact filesystem closure does not match authoritative registrations",
        )

    registered_dense = record_store.iter_dense_registrations()
    stored_dense = dense.iter_objects()
    expected_dense = {
        (
            item.dense_id,
            item.manifest_digest,
            item.relative_path,
            canonical_json_bytes(item.manifest),
        )
        for item in registered_dense
    }
    actual_dense = {
        (
            item.dense_id,
            item.manifest_digest,
            item.relative_path,
            canonical_json_bytes(item.manifest),
        )
        for item in stored_dense
    }
    if expected_dense != actual_dense:
        raise ContractError(
            "conformance_failed",
            "dense filesystem closure does not match authoritative registrations",
        )

    return WorkspaceVerification(
        record_count=len(record_store.iter_records()),
        event_count=len(record_store.iter_events()),
        edge_count=len(record_store.iter_edges()),
        artifact_count=len(stored_artifacts),
        dense_count=len(stored_dense),
    )
