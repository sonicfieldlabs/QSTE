"""Deterministic private bundle sealing and offline verification."""

from __future__ import annotations

import re
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from qste.core import (
    SchemaRegistry,
    canonical_json_bytes,
    content_digest,
    loads_json,
    new_record_id,
    validate_reference_closure,
)
from qste.core.contracts import ContractError
from qste.storage.artifacts import ArtifactStore
from qste.storage.database import EventEntry, LineageEdge, RecordStore
from qste.storage.dense import DenseStore
from qste.storage.paths import WorkspacePaths, atomic_write

BUNDLE_FORMAT = "qste-private-bundle/0.1"


@dataclass(frozen=True, slots=True)
class BundleVerification:
    bundle_id: str
    manifest_digest: str
    integrity_claim: str
    logical_replay_claim: str
    numerical_reproducibility_claim: str
    record_count: int
    event_count: int
    edge_count: int
    artifact_count: int
    dense_count: int
    logical_state_digest: str


class BundleService:
    """Seal one deterministic, private, relocatable P3 bundle."""

    def __init__(
        self,
        paths: WorkspacePaths,
        record_store: RecordStore,
        artifact_store: ArtifactStore,
        dense_store: DenseStore,
        registry: SchemaRegistry | None = None,
    ) -> None:
        self.paths = paths
        self.record_store = record_store
        self.artifact_store = artifact_store
        self.dense_store = dense_store
        self.registry = registry or SchemaRegistry()

    def seal_private(
        self,
        authority_manifest: Mapping[str, Any],
        *,
        bundle_id: str | None = None,
        retention_policy: Mapping[str, Any] | None = None,
        parent_bundle_ref: str | None = None,
        omission_manifest: list[dict[str, Any]] | None = None,
    ) -> Path:
        authority = dict(authority_manifest)
        self.registry.validate_record(authority)
        if authority["record_type"] != "AuthorityManifest":
            raise ContractError("invalid_input", "bundle authority must be an AuthorityManifest")
        identifier = bundle_id or new_record_id("Bundle")
        if not re.fullmatch(
            r"qste:bundle:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            identifier,
        ):
            raise ContractError("invalid_input", "bundle ID must contain a canonical UUIDv4")
        target = self.paths.bundles / identifier.rsplit(":", 1)[-1]
        if target.exists():
            raise ContractError("conformance_failed", f"bundle already exists: {identifier}")
        stage = self.paths.staging / f"bundle-{uuid.uuid4()}"
        stage.mkdir(mode=0o700, parents=True)
        try:
            records = self._records_with_authority(authority)
            record_entries, record_files = self._write_records(stage, records)
            event_entries, event_files = self._write_events(stage, self.record_store.iter_events())
            edge_path, edge_digest, edge_count = self._write_edges(
                stage, self.record_store.iter_edges()
            )
            artifact_entries = self._copy_artifacts(stage)
            dense_entries = self._copy_dense(stage)
            checksums = self._checksums(stage)
            manifest_without_digest: dict[str, Any] = {
                "container_type": "Bundle",
                "bundle_profile": "private_run_bundle",
                "bundle_id": identifier,
                "contract_id": "qste-contract/0.3.0",
                "schema_set_id": "qste-schema/0.3.0",
                "conformance_profile_id": "qste-conformance/0.3.0",
                "authority_ref": authority["record_id"],
                "code": authority["code"],
                "adapter_versions": authority["adapter_contracts"],
                "model_versions": authority["model_checkpoint_manifests"],
                "corpus_versions": authority["research_sources"],
                "experiment_profiles": authority["experiment_profiles"],
                "record_manifest": record_entries,
                "event_manifest": [
                    entry
                    for entry in record_entries
                    if entry["record_type"] in {"AcquisitionEvent", "DecisionEvent"}
                ],
                "relation_manifest": [
                    entry for entry in record_entries if entry["record_type"] == "RelationAssertion"
                ],
                "dense_manifests": dense_entries,
                "artifact_manifest": artifact_entries,
                "checksums": checksums,
                "disclosure_status": "private",
                "retention_policy": dict(retention_policy or {"mode": "project_private"}),
                "allowlist": [],
                "omission_manifest": omission_manifest or [],
                "parent_bundle_ref": parent_bundle_ref,
                "integrity_claim": "verified",
                "logical_replay_claim": "verified",
                "numerical_reproducibility_claim": "unavailable",
                "qste:bundleFormat": BUNDLE_FORMAT,
                "qste:recordFiles": record_files,
                "qste:eventLog": {
                    "entries": event_entries,
                    "files": event_files,
                },
                "qste:lineageEdges": {
                    "path": edge_path,
                    "content_digest": edge_digest,
                    "count": edge_count,
                },
            }
            manifest_digest = content_digest(canonical_json_bytes(manifest_without_digest))
            manifest = manifest_without_digest | {"manifest_digest": manifest_digest}
            atomic_write(stage / "manifest.json", canonical_json_bytes(manifest), mode=0o400)
            BundleReader(stage, self.registry).verify()
            stage.rename(target)
            return target
        except Exception:
            if stage.exists():
                shutil.rmtree(stage)
            raise

    def _records_with_authority(self, authority: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        by_id = {record.record_id: record.record for record in self.record_store.iter_records()}
        existing = by_id.get(authority["record_id"])
        if existing is not None and canonical_json_bytes(existing) != canonical_json_bytes(
            authority
        ):
            raise ContractError(
                "conformance_failed", "stored authority record conflicts with bundle authority"
            )
        by_id[authority["record_id"]] = authority
        records = tuple(by_id[key] for key in sorted(by_id))
        validate_reference_closure(records, registry=self.registry)
        return records

    @staticmethod
    def _write_records(
        stage: Path, records: tuple[dict[str, Any], ...]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        directory = stage / "records"
        directory.mkdir()
        manifest_entries: list[dict[str, Any]] = []
        file_entries: list[dict[str, Any]] = []
        for sequence, record in enumerate(records):
            data = canonical_json_bytes(record)
            relative = f"records/{sequence:08d}.json"
            atomic_write(stage / relative, data, mode=0o400)
            digest = content_digest(data)
            manifest_entries.append(
                {
                    "record_id": record["record_id"],
                    "record_type": record["record_type"],
                    "digest": digest,
                    "sequence": sequence,
                }
            )
            file_entries.append(
                {
                    "record_id": record["record_id"],
                    "path": relative,
                    "content_digest": digest,
                }
            )
        return manifest_entries, file_entries

    @staticmethod
    def _write_events(
        stage: Path, events: tuple[EventEntry, ...]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        directory = stage / "events"
        directory.mkdir()
        entries: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []
        for event in events:
            value = {
                "event_sequence": event.event_sequence,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "subject_record_id": event.subject_record_id,
                "receipt_record_id": event.receipt_record_id,
                "created_at": event.created_at,
                "payload_digest": event.payload_digest,
                "payload": event.payload,
            }
            data = canonical_json_bytes(value)
            relative = f"events/{event.event_sequence:016d}.json"
            atomic_write(stage / relative, data, mode=0o400)
            digest = content_digest(data)
            entries.append(
                {
                    "event_sequence": event.event_sequence,
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "content_digest": digest,
                }
            )
            files.append(
                {
                    "event_sequence": event.event_sequence,
                    "path": relative,
                    "content_digest": digest,
                }
            )
        return entries, files

    @staticmethod
    def _write_edges(stage: Path, edges: tuple[LineageEdge, ...]) -> tuple[str, str, int]:
        value = [
            {
                "source_record_id": edge.source_record_id,
                "target_record_id": edge.target_record_id,
                "relation": edge.relation,
            }
            for edge in sorted(
                edges,
                key=lambda item: (
                    item.source_record_id,
                    item.target_record_id,
                    item.relation,
                ),
            )
        ]
        data = canonical_json_bytes(value)
        relative = "lineage/edges.json"
        atomic_write(stage / relative, data, mode=0o400)
        return relative, content_digest(data), len(value)

    def _copy_artifacts(self, stage: Path) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for artifact in self.artifact_store.iter_objects():
            data = self.artifact_store.read_bytes(artifact.content_digest)
            atomic_write(stage / artifact.relative_path, data, mode=0o400)
            entries.append(
                {
                    "content_digest": artifact.content_digest,
                    "path": artifact.relative_path,
                    "size": artifact.size,
                }
            )
        return entries

    def _copy_dense(self, stage: Path) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for dense in self.dense_store.iter_objects():
            source_manifest = self.paths.root / dense.relative_path
            destination_manifest = stage / dense.relative_path
            atomic_write(destination_manifest, source_manifest.read_bytes(), mode=0o400)
            source_store = self.paths.dense / f"{dense.dense_id}.zarr"
            destination_store = stage / "dense" / f"{dense.dense_id}.zarr"
            _copy_tree_without_symlinks(source_store, destination_store)
            entries.append(
                {
                    "dense_id": dense.dense_id,
                    "manifest_digest": dense.manifest_digest,
                    "path": dense.relative_path,
                }
            )
        return entries

    @staticmethod
    def _checksums(stage: Path) -> list[dict[str, Any]]:
        for path in stage.rglob("*"):
            if path.is_symlink():
                raise ContractError("conformance_failed", f"cannot checksum symlink: {path}")
        return [
            {
                "path": path.relative_to(stage).as_posix(),
                "content_digest": content_digest(path.read_bytes()),
                "size": path.stat().st_size,
            }
            for path in sorted(candidate for candidate in stage.rglob("*") if candidate.is_file())
        ]


class BundleReader:
    """Read and verify a relocated bundle without a network or source checkout."""

    def __init__(self, root: Path, registry: SchemaRegistry | None = None) -> None:
        if not root.is_dir() or root.is_symlink():
            raise ContractError("invalid_input", "bundle root is absent or unsafe")
        self.root = root.resolve(strict=True)
        self.registry = registry or SchemaRegistry()

    def manifest(self) -> dict[str, Any]:
        value = loads_json(self._file("manifest.json").read_bytes())
        if not isinstance(value, dict):
            raise ContractError("conformance_failed", "bundle manifest is not an object")
        return cast(dict[str, Any], value)

    def records(self) -> tuple[dict[str, Any], ...]:
        manifest = self.manifest()
        files = sorted(manifest["qste:recordFiles"], key=lambda item: item["path"])
        records: list[dict[str, Any]] = []
        for entry in files:
            value = loads_json(self._file(entry["path"]).read_bytes())
            if not isinstance(value, dict):
                raise ContractError("conformance_failed", "bundle record is not an object")
            records.append(cast(dict[str, Any], value))
        return tuple(records)

    def events(self) -> tuple[dict[str, Any], ...]:
        manifest = self.manifest()
        entries = sorted(
            manifest["qste:eventLog"]["files"], key=lambda item: item["event_sequence"]
        )
        events: list[dict[str, Any]] = []
        for entry in entries:
            value = loads_json(self._file(entry["path"]).read_bytes())
            if not isinstance(value, dict):
                raise ContractError("conformance_failed", "bundle event is not an object")
            events.append(cast(dict[str, Any], value))
        return tuple(events)

    def edges(self) -> tuple[dict[str, Any], ...]:
        manifest = self.manifest()
        value = loads_json(self._file(manifest["qste:lineageEdges"]["path"]).read_bytes())
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ContractError("conformance_failed", "bundle lineage edges are malformed")
        return tuple(cast(list[dict[str, Any]], value))

    def verify(self) -> BundleVerification:
        manifest = self.manifest()
        self.registry.validate_bundle_manifest(manifest)
        without_digest = {key: value for key, value in manifest.items() if key != "manifest_digest"}
        computed_manifest_digest = content_digest(canonical_json_bytes(without_digest))
        if computed_manifest_digest != manifest["manifest_digest"]:
            raise ContractError("conformance_failed", "bundle manifest digest mismatch")
        declared_paths: set[str] = set()
        for entry in manifest["checksums"]:
            path_text = cast(str, entry["path"])
            if path_text in declared_paths:
                raise ContractError("conformance_failed", f"duplicate bundle path: {path_text}")
            declared_paths.add(path_text)
            path = self._file(path_text)
            data = path.read_bytes()
            if len(data) != entry["size"] or content_digest(data) != entry["content_digest"]:
                raise ContractError("conformance_failed", f"bundle checksum mismatch: {path_text}")
        all_paths = tuple(self.root.rglob("*"))
        if any(path.is_symlink() for path in all_paths):
            raise ContractError("conformance_failed", "bundle cannot contain symlinks")
        manifest_path = self.root / "manifest.json"
        actual_paths = {
            path.relative_to(self.root).as_posix()
            for path in all_paths
            if path.is_file() and path != manifest_path
        }
        if declared_paths != actual_paths:
            raise ContractError(
                "conformance_failed", "bundle file closure does not match checksums"
            )
        records = self.records()
        validate_reference_closure(records, registry=self.registry)
        by_id = {record["record_id"]: record for record in records}
        authority = by_id.get(manifest["authority_ref"])
        if authority is None or authority["record_type"] != "AuthorityManifest":
            raise ContractError("conformance_failed", "bundle authority reference does not resolve")
        ordered = manifest["record_manifest"]
        if [entry["sequence"] for entry in ordered] != list(range(len(ordered))):
            raise ContractError("conformance_failed", "bundle record sequence is not contiguous")
        record_files = sorted(manifest["qste:recordFiles"], key=lambda item: item["path"])
        if len(record_files) != len(ordered):
            raise ContractError("conformance_failed", "bundle record file count mismatch")
        for entry, file_entry, record in zip(ordered, record_files, records, strict=True):
            data = canonical_json_bytes(record)
            if (
                entry["record_id"] != record["record_id"]
                or entry["record_type"] != record["record_type"]
                or entry["digest"] != content_digest(data)
                or file_entry["record_id"] != record["record_id"]
                or file_entry["content_digest"] != content_digest(data)
            ):
                raise ContractError("conformance_failed", "bundle record manifest mismatch")
        events = self.events()
        sequences = [cast(int, event["event_sequence"]) for event in events]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ContractError("conformance_failed", "bundle event sequence is not monotonic")
        event_entries = manifest["qste:eventLog"]["entries"]
        event_files = sorted(
            manifest["qste:eventLog"]["files"], key=lambda item: item["event_sequence"]
        )
        if len(event_entries) != len(events) or len(event_files) != len(events):
            raise ContractError("conformance_failed", "bundle event manifest count mismatch")
        for entry, file_entry, event in zip(event_entries, event_files, events, strict=True):
            if event["subject_record_id"] not in by_id:
                raise ContractError("conformance_failed", "bundle event subject does not resolve")
            event_digest = content_digest(canonical_json_bytes(event))
            if (
                content_digest(canonical_json_bytes(event["payload"])) != event["payload_digest"]
                or entry["event_sequence"] != event["event_sequence"]
                or entry["event_id"] != event["event_id"]
                or entry["event_type"] != event["event_type"]
                or entry["content_digest"] != event_digest
                or file_entry["event_sequence"] != event["event_sequence"]
                or file_entry["content_digest"] != event_digest
            ):
                raise ContractError("conformance_failed", "bundle event payload digest mismatch")
        edges = self.edges()
        edge_manifest = manifest["qste:lineageEdges"]
        edge_digest = content_digest(canonical_json_bytes(list(edges)))
        if edge_manifest["count"] != len(edges) or edge_manifest["content_digest"] != edge_digest:
            raise ContractError("conformance_failed", "bundle lineage manifest mismatch")
        for edge in edges:
            if edge["source_record_id"] not in by_id or edge["target_record_id"] not in by_id:
                raise ContractError("conformance_failed", "bundle lineage edge does not resolve")
        self._verify_artifacts(manifest)
        self._verify_dense(manifest)
        logical_state = {
            "records": [content_digest(canonical_json_bytes(record)) for record in records],
            "events": list(events),
            "edges": sorted(
                edges,
                key=lambda item: (
                    item["source_record_id"],
                    item["target_record_id"],
                    item["relation"],
                ),
            ),
        }
        return BundleVerification(
            bundle_id=manifest["bundle_id"],
            manifest_digest=manifest["manifest_digest"],
            integrity_claim=manifest["integrity_claim"],
            logical_replay_claim=manifest["logical_replay_claim"],
            numerical_reproducibility_claim=manifest["numerical_reproducibility_claim"],
            record_count=len(records),
            event_count=len(events),
            edge_count=len(edges),
            artifact_count=len(manifest["artifact_manifest"]),
            dense_count=len(manifest["dense_manifests"]),
            logical_state_digest=content_digest(canonical_json_bytes(logical_state)),
        )

    def _verify_artifacts(self, manifest: Mapping[str, Any]) -> None:
        for entry in manifest["artifact_manifest"]:
            data = self._file(entry["path"]).read_bytes()
            if len(data) != entry["size"] or content_digest(data) != entry["content_digest"]:
                raise ContractError("conformance_failed", "bundle artifact identity mismatch")

    def _verify_dense(self, manifest: Mapping[str, Any]) -> None:
        for entry in manifest["dense_manifests"]:
            dense_manifest_value = loads_json(self._file(entry["path"]).read_bytes())
            if not isinstance(dense_manifest_value, dict):
                raise ContractError("conformance_failed", "bundle dense manifest is malformed")
            dense_manifest = cast(dict[str, Any], dense_manifest_value)
            without_digest = {
                key: value for key, value in dense_manifest.items() if key != "manifest_digest"
            }
            if (
                dense_manifest.get("dense_id") != entry["dense_id"]
                or dense_manifest.get("manifest_digest") != entry["manifest_digest"]
                or content_digest(canonical_json_bytes(without_digest)) != entry["manifest_digest"]
            ):
                raise ContractError("conformance_failed", "bundle dense manifest mismatch")
            store_root = self.root / "dense" / f"{entry['dense_id']}.zarr"
            for file_entry in dense_manifest["files"]:
                path = _safe_descendant(store_root, file_entry["path"])
                data = path.read_bytes()
                if (
                    len(data) != file_entry["size"]
                    or content_digest(data) != file_entry["content_digest"]
                ):
                    raise ContractError("conformance_failed", "bundle dense chunk mismatch")

    def _file(self, relative: str) -> Path:
        path = _safe_descendant(self.root, relative)
        if not path.is_file() or path.is_symlink():
            raise ContractError(
                "conformance_failed", f"bundle file is absent or unsafe: {relative}"
            )
        return path


def _safe_descendant(root: Path, relative: str) -> Path:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or not posix.parts:
        raise ContractError("conformance_failed", "bundle path escapes its root")
    path = root.joinpath(*posix.parts)
    probe = root
    for part in posix.parts:
        probe /= part
        if probe.is_symlink():
            raise ContractError("conformance_failed", "bundle path contains a symlink")
    resolved_parent = path.parent.resolve(strict=False)
    resolved_root = root.resolve(strict=True)
    if resolved_parent != resolved_root and resolved_root not in resolved_parent.parents:
        raise ContractError("conformance_failed", "bundle path escapes its root")
    return path


def _copy_tree_without_symlinks(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ContractError("conformance_failed", f"cannot bundle symlink: {path}")
    shutil.copytree(source, destination, copy_function=shutil.copyfile)
