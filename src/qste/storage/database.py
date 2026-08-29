"""Transactional, append-only SQLite records, events, edges, and indexes."""

from __future__ import annotations

import sqlite3
import uuid
from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from qste.core import (
    SchemaRegistry,
    canonical_json_bytes,
    content_digest,
    loads_json,
    validate_reference_closure,
    validate_utc_timestamp,
)
from qste.core.contracts import ContractError
from qste.core.identity import new_record_id, utc_timestamp
from qste.storage.paths import WorkspacePaths

DATABASE_FORMAT = "qste-sqlite/0.1"
LINEAGE_RELATIONS = frozenset(
    {
        "acquired_from",
        "authorized_by",
        "corrects",
        "depends_on",
        "descendant_of",
        "derived_from",
        "invalidates",
        "produced_by",
        "references",
        "repairs",
        "succeeds",
        "supersedes",
    }
)

_EXPECTED_METADATA = {
    "database_format": DATABASE_FORMAT,
    "contract_id": "qste-contract/0.3.0",
}
_EXPECTED_COLUMNS: dict[str, tuple[tuple[str, str, int, int], ...]] = {
    "metadata": (("key", "TEXT", 1, 1), ("value", "TEXT", 1, 0)),
    "records": (
        ("storage_sequence", "INTEGER", 0, 1),
        ("record_id", "TEXT", 1, 0),
        ("record_type", "TEXT", 1, 0),
        ("schema_id", "TEXT", 1, 0),
        ("semantic_key", "TEXT", 0, 0),
        ("content_digest", "TEXT", 0, 0),
        ("created_at", "TEXT", 1, 0),
        ("record_digest", "TEXT", 1, 0),
        ("canonical_json", "BLOB", 1, 0),
    ),
    "edges": (
        ("edge_sequence", "INTEGER", 0, 1),
        ("source_record_id", "TEXT", 1, 0),
        ("target_record_id", "TEXT", 1, 0),
        ("relation", "TEXT", 1, 0),
    ),
    "events": (
        ("event_sequence", "INTEGER", 0, 1),
        ("event_id", "TEXT", 1, 0),
        ("event_type", "TEXT", 1, 0),
        ("subject_record_id", "TEXT", 1, 0),
        ("receipt_record_id", "TEXT", 0, 0),
        ("created_at", "TEXT", 1, 0),
        ("payload_digest", "TEXT", 1, 0),
        ("payload_json", "BLOB", 1, 0),
    ),
    "artifact_objects": (
        ("content_digest", "TEXT", 1, 1),
        ("size", "INTEGER", 1, 0),
        ("relative_path", "TEXT", 1, 0),
        ("media_type", "TEXT", 0, 0),
        ("registered_at", "TEXT", 1, 0),
    ),
    "dense_objects": (
        ("dense_id", "TEXT", 1, 1),
        ("manifest_digest", "TEXT", 1, 0),
        ("relative_path", "TEXT", 1, 0),
        ("registered_at", "TEXT", 1, 0),
        ("manifest_json", "BLOB", 1, 0),
    ),
}
_EXPECTED_UNIQUE_COLUMNS: dict[str, set[tuple[str, ...]]] = {
    "metadata": {("key",)},
    "records": {("record_id",)},
    "edges": {("source_record_id", "target_record_id", "relation")},
    "events": {("event_id",)},
    "artifact_objects": {("content_digest",), ("relative_path",)},
    "dense_objects": {("dense_id",), ("relative_path",)},
}
_EXPECTED_FOREIGN_KEYS = {
    "edges": {
        ("records", "source_record_id", "record_id", "NO ACTION", "NO ACTION"),
        ("records", "target_record_id", "record_id", "NO ACTION", "NO ACTION"),
    },
    "events": {
        ("records", "subject_record_id", "record_id", "NO ACTION", "NO ACTION"),
        ("records", "receipt_record_id", "record_id", "NO ACTION", "NO ACTION"),
    },
}
_EXPECTED_TRIGGERS = {
    "records_no_update": (
        "records",
        "create trigger records_no_update before update on records begin select "
        "raise(abort, 'records are immutable'); end",
    ),
    "records_no_delete": (
        "records",
        "create trigger records_no_delete before delete on records begin select "
        "raise(abort, 'records are immutable'); end",
    ),
    "edges_no_update": (
        "edges",
        "create trigger edges_no_update before update on edges begin select "
        "raise(abort, 'edges are append-only'); end",
    ),
    "edges_no_delete": (
        "edges",
        "create trigger edges_no_delete before delete on edges begin select "
        "raise(abort, 'edges are append-only'); end",
    ),
    "events_no_update": (
        "events",
        "create trigger events_no_update before update on events begin select "
        "raise(abort, 'events are append-only'); end",
    ),
    "events_no_delete": (
        "events",
        "create trigger events_no_delete before delete on events begin select "
        "raise(abort, 'events are append-only'); end",
    ),
    "artifacts_no_update": (
        "artifact_objects",
        "create trigger artifacts_no_update before update on artifact_objects begin select "
        "raise(abort, 'artifacts are immutable'); end",
    ),
    "artifacts_no_delete": (
        "artifact_objects",
        "create trigger artifacts_no_delete before delete on artifact_objects begin select "
        "raise(abort, 'artifacts are immutable'); end",
    ),
    "dense_no_update": (
        "dense_objects",
        "create trigger dense_no_update before update on dense_objects begin select "
        "raise(abort, 'dense manifests are immutable'); end",
    ),
    "dense_no_delete": (
        "dense_objects",
        "create trigger dense_no_delete before delete on dense_objects begin select "
        "raise(abort, 'dense manifests are immutable'); end",
    ),
}


@dataclass(frozen=True, slots=True)
class StoredRecord:
    storage_sequence: int
    record_id: str
    record_type: str
    semantic_key: str | None
    content_digest: str | None
    record_digest: str
    record: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LineageEdge:
    edge_sequence: int
    source_record_id: str
    target_record_id: str
    relation: str


@dataclass(frozen=True, slots=True)
class EventEntry:
    event_sequence: int
    event_id: str
    event_type: str
    subject_record_id: str
    receipt_record_id: str | None
    created_at: str
    payload_digest: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ArtifactRegistration:
    content_digest: str
    size: int
    relative_path: str
    media_type: str | None
    registered_at: str


@dataclass(frozen=True, slots=True)
class DenseRegistration:
    dense_id: str
    manifest_digest: str
    relative_path: str
    registered_at: str
    manifest: dict[str, Any]


class RecordStore:
    """The authoritative append-only metadata plane for one QSTE workspace."""

    def __init__(self, paths: WorkspacePaths, registry: SchemaRegistry | None = None) -> None:
        self.paths = paths
        self.registry = registry or SchemaRegistry()
        self._initialize_database()

    @classmethod
    def initialize(cls, root: Path, registry: SchemaRegistry | None = None) -> RecordStore:
        return cls(WorkspacePaths.initialize(root), registry)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.paths.database, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        if self.paths.database.exists():
            if not self.paths.database.is_file() or self.paths.database.is_symlink():
                raise ContractError("conformance_failed", "SQLite database path is unsafe")
            try:
                with sqlite3.connect(
                    f"{self.paths.database.as_uri()}?mode=ro", uri=True
                ) as existing_connection:
                    metadata = dict(
                        existing_connection.execute("SELECT key, value FROM metadata").fetchall()
                    )
            except sqlite3.Error as error:
                raise ContractError(
                    "conformance_failed",
                    "existing SQLite database has no compatible metadata plane",
                ) from error
            if metadata != _EXPECTED_METADATA:
                raise ContractError(
                    "conformance_failed",
                    "existing SQLite database requires a copy migration",
                )
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) STRICT;
                CREATE TABLE IF NOT EXISTS records (
                    storage_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL UNIQUE,
                    record_type TEXT NOT NULL,
                    schema_id TEXT NOT NULL,
                    semantic_key TEXT,
                    content_digest TEXT,
                    created_at TEXT NOT NULL,
                    record_digest TEXT NOT NULL,
                    canonical_json BLOB NOT NULL
                ) STRICT;
                CREATE INDEX IF NOT EXISTS records_semantic_key
                    ON records(record_type, semantic_key) WHERE semantic_key IS NOT NULL;
                CREATE INDEX IF NOT EXISTS records_content_digest
                    ON records(content_digest) WHERE content_digest IS NOT NULL;
                CREATE TABLE IF NOT EXISTS edges (
                    edge_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_record_id TEXT NOT NULL REFERENCES records(record_id),
                    target_record_id TEXT NOT NULL REFERENCES records(record_id),
                    relation TEXT NOT NULL,
                    UNIQUE(source_record_id, target_record_id, relation)
                ) STRICT;
                CREATE INDEX IF NOT EXISTS edges_source ON edges(source_record_id, relation);
                CREATE INDEX IF NOT EXISTS edges_target ON edges(target_record_id, relation);
                CREATE TABLE IF NOT EXISTS events (
                    event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    subject_record_id TEXT NOT NULL REFERENCES records(record_id),
                    receipt_record_id TEXT REFERENCES records(record_id),
                    created_at TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    payload_json BLOB NOT NULL
                ) STRICT;
                CREATE INDEX IF NOT EXISTS events_subject
                    ON events(subject_record_id, event_sequence);
                CREATE TABLE IF NOT EXISTS artifact_objects (
                    content_digest TEXT PRIMARY KEY,
                    size INTEGER NOT NULL CHECK(size >= 0),
                    relative_path TEXT NOT NULL UNIQUE,
                    media_type TEXT,
                    registered_at TEXT NOT NULL
                ) STRICT;
                CREATE TABLE IF NOT EXISTS dense_objects (
                    dense_id TEXT PRIMARY KEY,
                    manifest_digest TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    registered_at TEXT NOT NULL,
                    manifest_json BLOB NOT NULL
                ) STRICT;
                CREATE TRIGGER IF NOT EXISTS records_no_update
                    BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT, 'records are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS records_no_delete
                    BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT, 'records are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS edges_no_update
                    BEFORE UPDATE ON edges BEGIN SELECT RAISE(ABORT, 'edges are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS edges_no_delete
                    BEFORE DELETE ON edges BEGIN SELECT RAISE(ABORT, 'edges are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_update
                    BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete
                    BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS artifacts_no_update
                    BEFORE UPDATE ON artifact_objects BEGIN SELECT RAISE(ABORT, 'artifacts are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS artifacts_no_delete
                    BEFORE DELETE ON artifact_objects BEGIN SELECT RAISE(ABORT, 'artifacts are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS dense_no_update
                    BEFORE UPDATE ON dense_objects BEGIN SELECT RAISE(ABORT, 'dense manifests are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS dense_no_delete
                    BEFORE DELETE ON dense_objects BEGIN SELECT RAISE(ABORT, 'dense manifests are immutable'); END;
                INSERT OR IGNORE INTO metadata(key, value) VALUES ('database_format', 'qste-sqlite/0.1');
                INSERT OR IGNORE INTO metadata(key, value) VALUES ('contract_id', 'qste-contract/0.3.0');
                COMMIT;
                """
            )
            metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
            if metadata != _EXPECTED_METADATA:
                raise ContractError("conformance_failed", "SQLite storage format conflict")

    def insert_record(self, record: Mapping[str, Any]) -> StoredRecord:
        return self.insert_records([record])[0]

    def insert_records(self, records: Iterable[Mapping[str, Any]]) -> tuple[StoredRecord, ...]:
        materialized = [dict(record) for record in records]
        if not materialized:
            return ()
        prepared: list[tuple[dict[str, Any], bytes, str]] = []
        ids: set[str] = set()
        for record in materialized:
            self.registry.validate_record(record)
            record_id = cast(str, record["record_id"])
            if record_id in ids:
                raise ContractError("conformance_failed", f"duplicate batch record ID: {record_id}")
            ids.add(record_id)
            canonical = canonical_json_bytes(record)
            prepared.append((record, canonical, content_digest(canonical)))

        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = _existing_record_bytes(connection, ids)
                for record, canonical, record_digest in prepared:
                    record_id = cast(str, record["record_id"])
                    prior = existing.get(record_id)
                    if prior is not None:
                        if prior != canonical:
                            raise ContractError(
                                "conformance_failed",
                                f"immutable record ID has different bytes: {record_id}",
                            )
                        continue
                    connection.execute(
                        """
                        INSERT INTO records(
                            record_id, record_type, schema_id, semantic_key,
                            content_digest, created_at, record_digest, canonical_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record_id,
                            record["record_type"],
                            record["schema_id"],
                            record.get("semantic_key"),
                            record.get("content_digest"),
                            record["created_at"],
                            record_digest,
                            canonical,
                        ),
                    )
                _validate_reference_targets(connection, materialized)
                for record in materialized:
                    source_id = cast(str, record["record_id"])
                    for reference in _walk_internal_references(record):
                        connection.execute(
                            "INSERT OR IGNORE INTO edges(source_record_id, target_record_id, relation) VALUES (?, ?, ?)",
                            (source_id, reference["record_id"], reference["relation"]),
                        )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise ContractError(
                    "conformance_failed", f"record transaction rejected: {error}"
                ) from error
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return tuple(self.get_record(cast(str, record["record_id"])) for record in materialized)

    def insert_records_with_event(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        domain_event_record_id: str | None,
        event_type: str,
        subject_record_id: str,
        payload: Mapping[str, Any],
        receipt_record_id: str | None = None,
        created_at: str | None = None,
        event_uuid: uuid.UUID | None = None,
    ) -> tuple[tuple[StoredRecord, ...], EventEntry]:
        """Atomically insert a record closure and its append-only event.

        When ``domain_event_record_id`` is supplied, that record receives the
        exact SQLite event sequence before validation and canonicalization.
        This keeps serialized ``AcquisitionEvent`` order and the metadata log
        in one transaction.
        """

        if not event_type or not event_type.startswith("qste:"):
            raise ContractError("invalid_input", "event type must be a versioned qste: identifier")
        timestamp = validate_utc_timestamp(created_at or utc_timestamp())
        event_id = new_record_id("Event", uuid_value=event_uuid)
        payload_value = dict(payload)
        payload_canonical = canonical_json_bytes(payload_value)
        materialized = [dict(record) for record in records]
        if not materialized:
            raise ContractError("invalid_input", "an event transaction requires records")

        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                next_sequence = cast(
                    int,
                    connection.execute(
                        "SELECT COALESCE(MAX(event_sequence), 0) + 1 FROM events"
                    ).fetchone()[0],
                )
                if domain_event_record_id is not None:
                    matches = [
                        record
                        for record in materialized
                        if record.get("record_id") == domain_event_record_id
                    ]
                    if len(matches) != 1 or matches[0].get("record_type") != "AcquisitionEvent":
                        raise ContractError(
                            "invalid_input",
                            "domain event ID must select one AcquisitionEvent in the batch",
                        )
                    matches[0]["event_sequence"] = next_sequence

                prepared: list[tuple[dict[str, Any], bytes, str]] = []
                ids: set[str] = set()
                for record in materialized:
                    self.registry.validate_record(record)
                    record_id = cast(str, record["record_id"])
                    if record_id in ids:
                        raise ContractError(
                            "conformance_failed", f"duplicate batch record ID: {record_id}"
                        )
                    ids.add(record_id)
                    canonical = canonical_json_bytes(record)
                    prepared.append((record, canonical, content_digest(canonical)))

                existing = _existing_record_bytes(connection, ids)
                for record, canonical, record_digest in prepared:
                    record_id = cast(str, record["record_id"])
                    prior = existing.get(record_id)
                    if prior is not None:
                        if prior != canonical:
                            raise ContractError(
                                "conformance_failed",
                                f"immutable record ID has different bytes: {record_id}",
                            )
                        continue
                    connection.execute(
                        """
                        INSERT INTO records(
                            record_id, record_type, schema_id, semantic_key,
                            content_digest, created_at, record_digest, canonical_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record_id,
                            record["record_type"],
                            record["schema_id"],
                            record.get("semantic_key"),
                            record.get("content_digest"),
                            record["created_at"],
                            record_digest,
                            canonical,
                        ),
                    )
                _validate_reference_targets(connection, materialized)
                for record in materialized:
                    source_id = cast(str, record["record_id"])
                    for reference in _walk_internal_references(record):
                        connection.execute(
                            "INSERT OR IGNORE INTO edges(source_record_id, target_record_id, relation) VALUES (?, ?, ?)",
                            (source_id, reference["record_id"], reference["relation"]),
                        )
                connection.execute(
                    """
                    INSERT INTO events(
                        event_sequence, event_id, event_type, subject_record_id,
                        receipt_record_id, created_at, payload_digest, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        next_sequence,
                        event_id,
                        event_type,
                        subject_record_id,
                        receipt_record_id,
                        timestamp,
                        content_digest(payload_canonical),
                        payload_canonical,
                    ),
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise ContractError(
                    "conformance_failed", f"record/event transaction rejected: {error}"
                ) from error
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        stored = tuple(self.get_record(cast(str, record["record_id"])) for record in materialized)
        return stored, self.get_event(next_sequence)

    def get_record(self, record_id: str) -> StoredRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM records WHERE record_id = ?", (record_id,)
            ).fetchone()
        if row is None:
            raise ContractError("capability_unavailable", f"record is absent: {record_id}")
        return _stored_record(row)

    def iter_records(self) -> tuple[StoredRecord, ...]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM records ORDER BY storage_sequence").fetchall()
        return tuple(_stored_record(row) for row in rows)

    def recent_records(self, maximum_records: int) -> tuple[StoredRecord, ...]:
        if (
            not isinstance(maximum_records, int)
            or isinstance(maximum_records, bool)
            or maximum_records < 1
            or maximum_records > 100_000
        ):
            raise ContractError("invalid_input", "record limit must be between 1 and 100000")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM records ORDER BY storage_sequence DESC LIMIT ?",
                (maximum_records,),
            ).fetchall()
        return tuple(_stored_record(row) for row in reversed(rows))

    def record_count(self) -> int:
        with self._connection() as connection:
            return cast(int, connection.execute("SELECT COUNT(*) FROM records").fetchone()[0])

    def record_type_counts(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT record_type, COUNT(*) AS count FROM records GROUP BY record_type "
                "ORDER BY record_type"
            ).fetchall()
        return {cast(str, row["record_type"]): cast(int, row["count"]) for row in rows}

    def occurrences(self, record_type: str, semantic_key: str) -> tuple[StoredRecord, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM records WHERE record_type = ? AND semantic_key = ? ORDER BY storage_sequence",
                (record_type, semantic_key),
            ).fetchall()
        return tuple(_stored_record(row) for row in rows)

    def add_edge(self, source_record_id: str, target_record_id: str, relation: str) -> LineageEdge:
        if relation not in LINEAGE_RELATIONS:
            raise ContractError("invalid_input", f"unknown P3 lineage relation: {relation}")
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "INSERT INTO edges(source_record_id, target_record_id, relation) VALUES (?, ?, ?)",
                    (source_record_id, target_record_id, relation),
                )
                sequence = cast(int, cursor.lastrowid)
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise ContractError(
                    "conformance_failed", f"lineage edge rejected: {error}"
                ) from error
        return LineageEdge(sequence, source_record_id, target_record_id, relation)

    def create_descendant(
        self,
        parent_record_id: str,
        descendant: Mapping[str, Any],
        *,
        relation: str = "descendant_of",
    ) -> StoredRecord:
        if relation not in LINEAGE_RELATIONS:
            raise ContractError("invalid_input", f"unknown P3 lineage relation: {relation}")
        record = dict(descendant)
        self.registry.validate_record(record)
        child_id = cast(str, record["record_id"])
        if child_id == parent_record_id:
            raise ContractError("conformance_failed", "a descendant requires a new occurrence ID")
        canonical = canonical_json_bytes(record)
        record_digest = content_digest(canonical)
        references = _referenced_ids([record])
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if (
                    connection.execute(
                        "SELECT 1 FROM records WHERE record_id = ?", (parent_record_id,)
                    ).fetchone()
                    is None
                ):
                    raise ContractError(
                        "conformance_failed", f"descendant parent is absent: {parent_record_id}"
                    )
                existing = connection.execute(
                    "SELECT canonical_json FROM records WHERE record_id = ?", (child_id,)
                ).fetchone()
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO records(
                            record_id, record_type, schema_id, semantic_key,
                            content_digest, created_at, record_digest, canonical_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            child_id,
                            record["record_type"],
                            record["schema_id"],
                            record.get("semantic_key"),
                            record.get("content_digest"),
                            record["created_at"],
                            record_digest,
                            canonical,
                        ),
                    )
                elif bytes(existing["canonical_json"]) != canonical:
                    raise ContractError(
                        "conformance_failed", f"immutable record ID has different bytes: {child_id}"
                    )
                if references:
                    _validate_reference_targets(connection, [record])
                for reference in _walk_internal_references(record):
                    connection.execute(
                        "INSERT OR IGNORE INTO edges(source_record_id, target_record_id, relation) VALUES (?, ?, ?)",
                        (child_id, reference["record_id"], reference["relation"]),
                    )
                connection.execute(
                    "INSERT OR IGNORE INTO edges(source_record_id, target_record_id, relation) VALUES (?, ?, ?)",
                    (child_id, parent_record_id, relation),
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return self.get_record(child_id)

    def append_event(
        self,
        event_type: str,
        subject_record_id: str,
        payload: Mapping[str, Any],
        *,
        receipt_record_id: str | None = None,
        created_at: str | None = None,
        event_uuid: uuid.UUID | None = None,
    ) -> EventEntry:
        if not event_type or not event_type.startswith("qste:"):
            raise ContractError("invalid_input", "event type must be a versioned qste: identifier")
        canonical = canonical_json_bytes(dict(payload))
        event_id = new_record_id("Event", uuid_value=event_uuid)
        timestamp = created_at or utc_timestamp()
        validate_utc_timestamp(timestamp)
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """
                    INSERT INTO events(
                        event_id, event_type, subject_record_id, receipt_record_id,
                        created_at, payload_digest, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        event_type,
                        subject_record_id,
                        receipt_record_id,
                        timestamp,
                        content_digest(canonical),
                        canonical,
                    ),
                )
                sequence = cast(int, cursor.lastrowid)
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise ContractError("conformance_failed", f"event rejected: {error}") from error
        return self.get_event(sequence)

    def get_event(self, event_sequence: int) -> EventEntry:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM events WHERE event_sequence = ?", (event_sequence,)
            ).fetchone()
        if row is None:
            raise ContractError("capability_unavailable", f"event is absent: {event_sequence}")
        return _event_entry(row)

    def iter_events(self) -> tuple[EventEntry, ...]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM events ORDER BY event_sequence").fetchall()
        return tuple(_event_entry(row) for row in rows)

    def iter_edges(self) -> tuple[LineageEdge, ...]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM edges ORDER BY edge_sequence").fetchall()
        return tuple(
            LineageEdge(
                row["edge_sequence"],
                row["source_record_id"],
                row["target_record_id"],
                row["relation"],
            )
            for row in rows
        )

    def trace_lineage(
        self,
        record_id: str,
        *,
        direction: str = "ancestors",
        maximum_depth: int = 64,
        maximum_edges: int | None = None,
    ) -> tuple[LineageEdge, ...]:
        self.get_record(record_id)
        if direction not in {"ancestors", "descendants"}:
            raise ContractError(
                "invalid_input", "lineage direction must be ancestors or descendants"
            )
        if (
            not isinstance(maximum_depth, int)
            or isinstance(maximum_depth, bool)
            or maximum_depth < 1
            or maximum_depth > 1024
        ):
            raise ContractError("invalid_input", "lineage depth must be between 1 and 1024")
        if maximum_edges is not None and (
            not isinstance(maximum_edges, int)
            or isinstance(maximum_edges, bool)
            or maximum_edges < 1
            or maximum_edges > 100_000
        ):
            raise ContractError("invalid_input", "lineage edge limit must be between 1 and 100000")
        queue: deque[tuple[str, int]] = deque([(record_id, 0)])
        visited_nodes = {record_id}
        selected: list[LineageEdge] = []
        selected_ids: set[int] = set()
        with self._connection() as connection:
            while queue:
                node, depth = queue.popleft()
                if depth >= maximum_depth:
                    continue
                remaining = None if maximum_edges is None else maximum_edges - len(selected)
                if remaining == 0:
                    break
                query = (
                    "SELECT * FROM edges WHERE source_record_id = ? ORDER BY edge_sequence"
                    if direction == "ancestors"
                    else "SELECT * FROM edges WHERE target_record_id = ? ORDER BY edge_sequence"
                )
                parameters: tuple[Any, ...] = (node,)
                if remaining is not None:
                    query += " LIMIT ?"
                    parameters = (node, remaining)
                rows = connection.execute(query, parameters).fetchall()
                for row in rows:
                    edge = LineageEdge(
                        row["edge_sequence"],
                        row["source_record_id"],
                        row["target_record_id"],
                        row["relation"],
                    )
                    next_node = (
                        edge.target_record_id if direction == "ancestors" else edge.source_record_id
                    )
                    if edge.edge_sequence not in selected_ids:
                        selected.append(edge)
                        selected_ids.add(edge.edge_sequence)
                    if next_node not in visited_nodes:
                        visited_nodes.add(next_node)
                        queue.append((next_node, depth + 1))
        return tuple(selected)

    def register_artifact(
        self,
        digest: str,
        size: int,
        relative_path: str,
        *,
        media_type: str | None = None,
        registered_at: str | None = None,
    ) -> None:
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ContractError("invalid_input", "artifact size must be a nonnegative integer")
        if media_type is not None and (
            not isinstance(media_type, str) or not media_type.strip() or len(media_type) > 255
        ):
            raise ContractError("invalid_input", "artifact media type must be bounded text")
        expected_path = _artifact_relative_path(digest, reason_code="invalid_input")
        if relative_path != expected_path:
            raise ContractError("invalid_input", "artifact registration path is not canonical")
        timestamp = validate_utc_timestamp(registered_at or utc_timestamp())
        registration = ArtifactRegistration(digest, size, relative_path, media_type, timestamp)
        _verify_artifact_registration(self.paths, registration)
        with self._connection() as connection:
            try:
                connection.execute(
                    "INSERT INTO artifact_objects VALUES (?, ?, ?, ?, ?)",
                    (digest, size, relative_path, media_type, timestamp),
                )
            except sqlite3.IntegrityError as error:
                row = connection.execute(
                    "SELECT size, relative_path, media_type FROM artifact_objects WHERE content_digest = ?",
                    (digest,),
                ).fetchone()
                if row is None or (row["size"], row["relative_path"], row["media_type"]) != (
                    size,
                    relative_path,
                    media_type,
                ):
                    raise ContractError(
                        "conformance_failed", "artifact registration conflict"
                    ) from error

    def register_dense_manifest(
        self,
        dense_id: str,
        manifest_digest: str,
        relative_path: str,
        manifest: Mapping[str, Any],
        *,
        registered_at: str | None = None,
    ) -> None:
        expected_path = _dense_relative_path(dense_id, reason_code="invalid_input")
        if relative_path != expected_path:
            raise ContractError("invalid_input", "dense registration path is not canonical")
        _require_digest(manifest_digest, "dense manifest digest", reason_code="invalid_input")
        canonical = canonical_json_bytes(dict(manifest))
        if (
            manifest.get("dense_id") != dense_id
            or manifest.get("manifest_digest") != manifest_digest
        ):
            raise ContractError("conformance_failed", "dense registration identity mismatch")
        without_digest = {key: value for key, value in manifest.items() if key != "manifest_digest"}
        if content_digest(canonical_json_bytes(without_digest)) != manifest_digest:
            raise ContractError("conformance_failed", "dense registration digest mismatch")
        timestamp = validate_utc_timestamp(registered_at or utc_timestamp())
        registration = DenseRegistration(
            dense_id, manifest_digest, relative_path, timestamp, dict(manifest)
        )
        _verify_dense_registration(self.paths, registration)
        with self._connection() as connection:
            try:
                connection.execute(
                    "INSERT INTO dense_objects VALUES (?, ?, ?, ?, ?)",
                    (
                        dense_id,
                        manifest_digest,
                        relative_path,
                        timestamp,
                        canonical,
                    ),
                )
            except sqlite3.IntegrityError as error:
                row = connection.execute(
                    "SELECT manifest_digest, relative_path, manifest_json FROM dense_objects WHERE dense_id = ?",
                    (dense_id,),
                ).fetchone()
                if row is None or (
                    row["manifest_digest"],
                    row["relative_path"],
                    bytes(row["manifest_json"]),
                ) != (manifest_digest, relative_path, canonical):
                    raise ContractError(
                        "conformance_failed", "dense registration conflict"
                    ) from error

    def iter_artifact_registrations(self) -> tuple[ArtifactRegistration, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM artifact_objects ORDER BY content_digest"
            ).fetchall()
        return tuple(
            ArtifactRegistration(
                content_digest=row["content_digest"],
                size=row["size"],
                relative_path=row["relative_path"],
                media_type=row["media_type"],
                registered_at=row["registered_at"],
            )
            for row in rows
        )

    def iter_dense_registrations(self) -> tuple[DenseRegistration, ...]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM dense_objects ORDER BY dense_id").fetchall()
        registrations: list[DenseRegistration] = []
        for row in rows:
            value = loads_json(bytes(row["manifest_json"]))
            if not isinstance(value, dict):
                raise ContractError(
                    "conformance_failed", "registered dense manifest is not an object"
                )
            registrations.append(
                DenseRegistration(
                    dense_id=row["dense_id"],
                    manifest_digest=row["manifest_digest"],
                    relative_path=row["relative_path"],
                    registered_at=row["registered_at"],
                    manifest=cast(dict[str, Any], value),
                )
            )
        return tuple(registrations)

    def checkpoint(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def verify(self) -> None:
        with self._connection() as connection:
            _verify_database_structure(connection)
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise ContractError(
                    "conformance_failed", f"SQLite integrity check failed: {result}"
                )
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ContractError("conformance_failed", "SQLite foreign-key closure failed")
            record_rows = connection.execute("SELECT * FROM records").fetchall()
            edge_rows = connection.execute("SELECT * FROM edges").fetchall()
            event_rows = connection.execute("SELECT * FROM events").fetchall()
        records: list[dict[str, Any]] = []
        for row in record_rows:
            value = loads_json(bytes(row["canonical_json"]))
            if not isinstance(value, dict):
                raise ContractError("conformance_failed", "stored record is not an object")
            self.registry.validate_record(value)
            canonical = canonical_json_bytes(value)
            if (
                canonical != bytes(row["canonical_json"])
                or content_digest(canonical) != row["record_digest"]
                or value["record_id"] != row["record_id"]
                or value["record_type"] != row["record_type"]
                or value["schema_id"] != row["schema_id"]
                or value["created_at"] != row["created_at"]
                or value.get("semantic_key") != row["semantic_key"]
                or value.get("content_digest") != row["content_digest"]
            ):
                raise ContractError(
                    "conformance_failed",
                    f"record bytes or digest mismatch: {row['record_id']}",
                )
            records.append(cast(dict[str, Any], value))
        validate_reference_closure(records, registry=self.registry)
        stored_edges = {
            (row["source_record_id"], row["target_record_id"], row["relation"]) for row in edge_rows
        }
        required_edges = {
            (
                cast(str, record["record_id"]),
                cast(str, reference["record_id"]),
                cast(str, reference["relation"]),
            )
            for record in records
            for reference in _walk_internal_references(record)
        }
        if not required_edges.issubset(stored_edges):
            raise ContractError(
                "conformance_failed", "stored lineage omits an embedded record reference"
            )
        for row in edge_rows:
            if row["relation"] not in LINEAGE_RELATIONS:
                raise ContractError(
                    "conformance_failed",
                    f"stored lineage relation is invalid: {row['relation']}",
                )
        for row in event_rows:
            value = loads_json(bytes(row["payload_json"]))
            if not isinstance(value, dict):
                raise ContractError("conformance_failed", "stored event payload is not an object")
            canonical = canonical_json_bytes(value)
            if (
                canonical != bytes(row["payload_json"])
                or content_digest(canonical) != row["payload_digest"]
                or not isinstance(row["event_type"], str)
                or not row["event_type"].startswith("qste:")
            ):
                raise ContractError(
                    "conformance_failed",
                    f"event bytes or digest mismatch: {row['event_id']}",
                )
            _verify_stored_timestamp(row["created_at"], "stored event timestamp")
        sequences = [event.event_sequence for event in self.iter_events()]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ContractError("conformance_failed", "event sequence is not strictly monotonic")
        for artifact_registration in self.iter_artifact_registrations():
            _verify_artifact_registration(self.paths, artifact_registration)
        for dense_registration in self.iter_dense_registrations():
            _verify_dense_registration(self.paths, dense_registration)


def _stored_record(row: sqlite3.Row) -> StoredRecord:
    value = loads_json(bytes(row["canonical_json"]))
    if not isinstance(value, dict):
        raise ContractError("conformance_failed", "stored record is not an object")
    return StoredRecord(
        storage_sequence=row["storage_sequence"],
        record_id=row["record_id"],
        record_type=row["record_type"],
        semantic_key=row["semantic_key"],
        content_digest=row["content_digest"],
        record_digest=row["record_digest"],
        record=cast(dict[str, Any], value),
    )


def _event_entry(row: sqlite3.Row) -> EventEntry:
    value = loads_json(bytes(row["payload_json"]))
    if not isinstance(value, dict):
        raise ContractError("conformance_failed", "stored event payload is not an object")
    return EventEntry(
        event_sequence=row["event_sequence"],
        event_id=row["event_id"],
        event_type=row["event_type"],
        subject_record_id=row["subject_record_id"],
        receipt_record_id=row["receipt_record_id"],
        created_at=row["created_at"],
        payload_digest=row["payload_digest"],
        payload=cast(dict[str, Any], value),
    )


def _walk_internal_references(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if set(("record_id", "record_type", "relation")).issubset(value):
            yield value
            return
        for child in value.values():
            yield from _walk_internal_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_internal_references(child)


def _referenced_ids(records: Iterable[Mapping[str, Any]]) -> set[str]:
    return {
        cast(str, reference["record_id"])
        for record in records
        for reference in _walk_internal_references(record)
    }


def _existing_record_bytes(
    connection: sqlite3.Connection, record_ids: Iterable[str]
) -> dict[str, bytes]:
    existing: dict[str, bytes] = {}
    for record_id in sorted(record_ids):
        row = connection.execute(
            "SELECT canonical_json FROM records WHERE record_id = ?", (record_id,)
        ).fetchone()
        if row is not None:
            existing[record_id] = bytes(row["canonical_json"])
    return existing


def _verify_database_structure(connection: sqlite3.Connection) -> None:
    metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
    if metadata != _EXPECTED_METADATA:
        raise ContractError("conformance_failed", "SQLite metadata contract differs")

    table_rows = {
        row[1]: row
        for row in connection.execute("PRAGMA table_list").fetchall()
        if row[0] == "main"
    }
    for table, expected_columns in _EXPECTED_COLUMNS.items():
        table_row = table_rows.get(table)
        if table_row is None or table_row[2] != "table" or table_row[5] != 1:
            raise ContractError(
                "conformance_failed", f"SQLite table is absent or non-strict: {table}"
            )
        actual_columns = tuple(
            (row[1], row[2], row[3], row[5])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        )
        if actual_columns != expected_columns:
            raise ContractError("conformance_failed", f"SQLite table columns differ: {table}")
        unique_columns = {
            tuple(item[2] for item in connection.execute(f"PRAGMA index_info({row[1]})").fetchall())
            for row in connection.execute(f"PRAGMA index_list({table})").fetchall()
            if row[2] == 1
        }
        if not _EXPECTED_UNIQUE_COLUMNS[table].issubset(unique_columns):
            raise ContractError(
                "conformance_failed", f"SQLite uniqueness contract differs: {table}"
            )

    for table, expected in _EXPECTED_FOREIGN_KEYS.items():
        actual = {
            (row[2], row[3], row[4], row[5], row[6])
            for row in connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        }
        if actual != expected:
            raise ContractError("conformance_failed", f"SQLite foreign keys differ: {table}")

    trigger_rows = {
        row["name"]: (row["tbl_name"], " ".join(cast(str, row["sql"]).lower().split()))
        for row in connection.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    if trigger_rows != _EXPECTED_TRIGGERS:
        raise ContractError("conformance_failed", "SQLite immutability triggers differ")


def _validate_reference_targets(
    connection: sqlite3.Connection, records: Iterable[Mapping[str, Any]]
) -> None:
    expected_types: dict[str, str] = {}
    for record in records:
        for reference in _walk_internal_references(record):
            record_id = cast(str, reference["record_id"])
            record_type = cast(str, reference["record_type"])
            prior = expected_types.setdefault(record_id, record_type)
            if prior != record_type:
                raise ContractError(
                    "conformance_failed",
                    f"conflicting typed references for {record_id}: {prior} and {record_type}",
                )
    missing: list[str] = []
    for record_id, expected_type in sorted(expected_types.items()):
        row = connection.execute(
            "SELECT record_type FROM records WHERE record_id = ?", (record_id,)
        ).fetchone()
        if row is None:
            missing.append(record_id)
        elif row["record_type"] != expected_type:
            raise ContractError(
                "conformance_failed",
                f"typed reference mismatch for {record_id}: "
                f"expected {expected_type}, found {row['record_type']}",
            )
    if missing:
        raise ContractError(
            "conformance_failed", f"missing internal references: {', '.join(missing)}"
        )


def _require_digest(value: str, label: str, *, reason_code: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ContractError(reason_code, f"{label} is not canonical SHA-256")
    return value


def _verify_stored_timestamp(value: Any, label: str) -> str:
    try:
        return validate_utc_timestamp(value)
    except ContractError as error:
        raise ContractError("conformance_failed", f"{label} is invalid") from error


def _artifact_relative_path(digest: str, *, reason_code: str) -> str:
    canonical = _require_digest(digest, "artifact digest", reason_code=reason_code)
    hexdigest = canonical.removeprefix("sha256:")
    return f"artifacts/sha256/{hexdigest[:2]}/{hexdigest}"


def _dense_relative_path(dense_id: str, *, reason_code: str) -> str:
    if (
        not isinstance(dense_id, str)
        or not dense_id
        or len(dense_id) > 64
        or not dense_id[0].islower()
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_.-" for character in dense_id)
    ):
        raise ContractError(reason_code, "dense ID is not canonical")
    return f"dense/{dense_id}.manifest.json"


def _verify_artifact_registration(
    paths: WorkspacePaths, registration: ArtifactRegistration
) -> None:
    digest = _require_digest(
        registration.content_digest,
        "registered artifact digest",
        reason_code="conformance_failed",
    )
    expected_path = _artifact_relative_path(digest, reason_code="conformance_failed")
    if registration.relative_path != expected_path:
        raise ContractError("conformance_failed", "registered artifact path is not canonical")
    if (
        not isinstance(registration.size, int)
        or isinstance(registration.size, bool)
        or registration.size < 0
    ):
        raise ContractError("conformance_failed", "registered artifact size is invalid")
    if registration.media_type is not None and (
        not isinstance(registration.media_type, str)
        or not registration.media_type.strip()
        or len(registration.media_type) > 255
    ):
        raise ContractError("conformance_failed", "registered artifact media type is invalid")
    _verify_stored_timestamp(registration.registered_at, "registered artifact timestamp")
    path = paths.owned_path(registration.relative_path)
    if not path.is_file() or path.is_symlink():
        raise ContractError("conformance_failed", "registered artifact is absent or unsafe")
    data = path.read_bytes()
    if len(data) != registration.size or content_digest(data) != digest:
        raise ContractError("conformance_failed", "registered artifact identity mismatch")


def _verify_dense_registration(paths: WorkspacePaths, registration: DenseRegistration) -> None:
    expected_path = _dense_relative_path(registration.dense_id, reason_code="conformance_failed")
    if registration.relative_path != expected_path:
        raise ContractError("conformance_failed", "registered dense path is not canonical")
    _require_digest(
        registration.manifest_digest,
        "registered dense manifest digest",
        reason_code="conformance_failed",
    )
    _verify_stored_timestamp(registration.registered_at, "registered dense timestamp")
    canonical = canonical_json_bytes(registration.manifest)
    path = paths.owned_path(registration.relative_path)
    if not path.is_file() or path.is_symlink() or path.read_bytes() != canonical:
        raise ContractError("conformance_failed", "registered dense manifest path mismatch")
    without_digest = {
        key: value for key, value in registration.manifest.items() if key != "manifest_digest"
    }
    if (
        registration.manifest.get("dense_id") != registration.dense_id
        or registration.manifest.get("manifest_digest") != registration.manifest_digest
        or content_digest(canonical_json_bytes(without_digest)) != registration.manifest_digest
    ):
        raise ContractError("conformance_failed", "registered dense manifest identity mismatch")
