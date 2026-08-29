from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import fixture_record

from qste.core import SemanticKeySpec, content_digest, semantic_key
from qste.core.contracts import ContractError
from qste.storage import ArtifactStore, RecordStore, WorkspacePaths


def _source(number: int, *, locator: str = "qste://fixtures/source") -> dict[str, Any]:
    record = fixture_record("SourceRecord")
    record["record_id"] = f"qste:source-record:30000000-0000-4000-8000-{number:012d}"
    record["locator"] = locator
    return record


def test_occurrences_share_semantics_without_merging_records(
    workspace: tuple[WorkspacePaths, RecordStore],
) -> None:
    _, store = workspace
    spec = SemanticKeySpec(
        "qste-semantic-key/source-locator-v1", "SourceRecord", ("locator", "rights")
    )
    first = _source(1)
    second = _source(2)
    first["created_at"] = "2026-08-28T00:00:00Z"
    second["created_at"] = "2026-08-29T00:00:00Z"
    first["semantic_key"] = semantic_key(first, spec)
    second["semantic_key"] = semantic_key(second, spec)
    inserted = store.insert_records([first, second])
    assert inserted[0].record_id != inserted[1].record_id
    assert inserted[0].record_digest != inserted[1].record_digest
    assert len(store.occurrences("SourceRecord", first["semantic_key"])) == 2


def test_artifact_bytes_deduplicate_without_merging_occurrence_records(
    workspace: tuple[WorkspacePaths, RecordStore],
) -> None:
    paths, store = workspace
    artifacts = ArtifactStore(paths)
    first_object = artifacts.put_bytes(b"same immutable bytes")
    second_object = artifacts.put_bytes(b"same immutable bytes")
    assert first_object == second_object
    store.register_artifact(
        first_object.content_digest, first_object.size, first_object.relative_path
    )
    records = []
    for number in (1, 2):
        record = fixture_record("ArtifactRecord")
        record["record_id"] = f"qste:artifact-record:40000000-0000-4000-8000-{number:012d}"
        record["content_digest"] = first_object.content_digest
        records.append(record)
    store.insert_records(records)
    assert len(store.iter_records()) == 2
    assert len(artifacts.iter_objects()) == 1


def test_batch_reference_failure_rolls_back_every_record(
    workspace: tuple[WorkspacePaths, RecordStore],
) -> None:
    _, store = workspace
    record = _source(1)
    record["references"] = [
        {
            "record_id": "qste:source-record:30000000-0000-4000-8000-999999999999",
            "record_type": "SourceRecord",
            "relation": "derived_from",
        }
    ]
    with pytest.raises(ContractError, match="missing internal references"):
        store.insert_record(record)
    assert store.iter_records() == ()


def test_record_and_event_transaction_rolls_back_as_one_unit(
    workspace: tuple[WorkspacePaths, RecordStore],
) -> None:
    _, store = workspace
    record = _source(1)
    with pytest.raises(ContractError, match="record/event transaction rejected"):
        store.insert_records_with_event(
            [record],
            domain_event_record_id=None,
            event_type="qste:test-atomic-event/0.1",
            subject_record_id="qste:source-record:30000000-0000-4000-8000-999999999999",
            payload={"status": "must_rollback"},
        )
    assert store.iter_records() == ()
    assert store.iter_events() == ()


def test_descendants_and_events_are_atomic_ordered_and_traversable(
    workspace: tuple[WorkspacePaths, RecordStore],
) -> None:
    _, store = workspace
    parent = _source(1)
    child = _source(2, locator="qste://fixtures/child")
    with pytest.raises(ContractError, match="parent is absent"):
        store.create_descendant(parent["record_id"], child)
    assert store.iter_records() == ()
    store.insert_record(parent)
    store.create_descendant(parent["record_id"], child)
    edge = store.trace_lineage(child["record_id"], direction="ancestors")
    assert [(item.source_record_id, item.target_record_id) for item in edge] == [
        (child["record_id"], parent["record_id"])
    ]
    first = store.append_event(
        "qste:event/record-created-v1",
        parent["record_id"],
        {"status": "created"},
        created_at="2026-08-28T01:00:00Z",
        event_uuid=uuid.UUID("50000000-0000-4000-8000-000000000001"),
    )
    second = store.append_event(
        "qste:event/record-created-v1",
        child["record_id"],
        {"status": "created"},
        created_at="2026-08-28T01:00:01Z",
        event_uuid=uuid.UUID("50000000-0000-4000-8000-000000000002"),
    )
    assert (first.event_sequence, second.event_sequence) == (1, 2)
    store.verify()


def test_sqlite_authoritative_rows_cannot_be_updated_or_deleted(
    workspace: tuple[WorkspacePaths, RecordStore],
) -> None:
    paths, store = workspace
    record = _source(1)
    store.insert_record(record)
    connection = sqlite3.connect(paths.database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE records SET record_digest = ? WHERE record_id = ?",
                (content_digest(b"replacement"), record["record_id"]),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM records WHERE record_id = ?", (record["record_id"],))
    finally:
        connection.close()


def test_workspace_rejects_escape_and_symlink_paths(tmp_path: Path) -> None:
    paths = RecordStore.initialize(tmp_path / "workspace").paths
    with pytest.raises(ContractError, match="escapes"):
        paths.owned_path("../outside")
    (paths.artifacts / "redirect").symlink_to(paths.dense, target_is_directory=True)
    with pytest.raises(ContractError, match="symlink"):
        paths.owned_path("artifacts/redirect/object")


def test_open_is_noncreating_and_incompatible_databases_require_copy_migration(
    tmp_path: Path,
) -> None:
    absent = tmp_path / "absent"
    with pytest.raises(ContractError, match="absent"):
        WorkspacePaths.open(absent)
    assert not absent.exists()

    paths = WorkspacePaths.initialize(tmp_path / "legacy")
    connection = sqlite3.connect(paths.database)
    connection.execute("CREATE TABLE legacy(value TEXT)")
    connection.execute("INSERT INTO legacy VALUES ('preserve-me')")
    connection.commit()
    connection.close()
    with pytest.raises(ContractError, match="compatible metadata"):
        RecordStore(paths)
    connection = sqlite3.connect(paths.database)
    try:
        assert connection.execute("SELECT value FROM legacy").fetchone() == ("preserve-me",)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "records" not in tables
    finally:
        connection.close()


def test_events_require_canonical_utc_seconds(
    workspace: tuple[WorkspacePaths, RecordStore],
) -> None:
    _, store = workspace
    record = _source(1)
    store.insert_record(record)
    with pytest.raises(ContractError, match="canonical UTC seconds"):
        store.append_event(
            "qste:event/test-v1",
            record["record_id"],
            {},
            created_at="2026-08-28T00:00:00.123Z",
        )
    assert store.iter_events() == ()
