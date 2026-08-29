"""Explicit-root filesystem layout and atomic-write helpers."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from qste.core.contracts import CONTRACT_ID, ContractError

WORKSPACE_FORMAT = "qste-workspace/0.1"


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    root: Path
    database: Path
    artifacts: Path
    dense: Path
    bundles: Path
    staging: Path

    @classmethod
    def initialize(cls, root: Path) -> WorkspacePaths:
        candidate = root.expanduser()
        if candidate.exists() and candidate.is_symlink():
            raise ContractError("invalid_input", "workspace root cannot be a symbolic link")
        candidate.mkdir(parents=True, exist_ok=True)
        resolved = candidate.resolve(strict=True)
        paths = cls(
            root=resolved,
            database=resolved / "qste.sqlite3",
            artifacts=resolved / "artifacts",
            dense=resolved / "dense",
            bundles=resolved / "bundles",
            staging=resolved / ".staging",
        )
        for directory in (paths.artifacts, paths.dense, paths.bundles, paths.staging):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if directory.is_symlink():
                raise ContractError(
                    "conformance_failed", f"workspace directory is a symlink: {directory}"
                )
        marker = resolved / "workspace.json"
        expected = {
            "contract_id": CONTRACT_ID,
            "workspace_format": WORKSPACE_FORMAT,
        }
        if marker.exists():
            if marker.is_symlink() or not marker.is_file():
                raise ContractError("conformance_failed", "workspace marker is unsafe")
            try:
                actual = json.loads(marker.read_text())
            except (OSError, json.JSONDecodeError) as error:
                raise ContractError(
                    "conformance_failed", "workspace marker is unreadable"
                ) from error
            if actual != expected:
                raise ContractError("conformance_failed", "workspace format or contract conflict")
        else:
            atomic_write(
                marker, json.dumps(expected, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            )
        return paths

    @classmethod
    def open(cls, root: Path) -> WorkspacePaths:
        candidate = root.expanduser()
        if not candidate.is_dir() or candidate.is_symlink():
            raise ContractError("invalid_input", "QSTE workspace root is absent or unsafe")
        resolved = candidate.resolve(strict=True)
        paths = cls(
            root=resolved,
            database=resolved / "qste.sqlite3",
            artifacts=resolved / "artifacts",
            dense=resolved / "dense",
            bundles=resolved / "bundles",
            staging=resolved / ".staging",
        )
        marker = resolved / "workspace.json"
        if not marker.is_file() or marker.is_symlink():
            raise ContractError("conformance_failed", "workspace marker is absent or unsafe")
        try:
            actual = json.loads(marker.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ContractError("conformance_failed", "workspace marker is unreadable") from error
        expected = {"contract_id": CONTRACT_ID, "workspace_format": WORKSPACE_FORMAT}
        if actual != expected:
            raise ContractError("conformance_failed", "workspace format or contract conflict")
        for directory in (paths.artifacts, paths.dense, paths.bundles, paths.staging):
            if not directory.is_dir() or directory.is_symlink():
                raise ContractError(
                    "conformance_failed", f"workspace directory is absent or unsafe: {directory}"
                )
        if not paths.database.is_file():
            raise ContractError("capability_unavailable", "QSTE workspace database is absent")
        if paths.database.is_symlink():
            raise ContractError("conformance_failed", "QSTE workspace database is a symlink")
        return paths

    def owned_path(self, relative: str | PurePosixPath) -> Path:
        posix = PurePosixPath(relative)
        if posix.is_absolute() or ".." in posix.parts or not posix.parts:
            raise ContractError("invalid_input", "workspace-relative path escapes its root")
        result = self.root.joinpath(*posix.parts)
        probe = self.root
        for part in posix.parts:
            probe /= part
            if probe.is_symlink():
                raise ContractError("conformance_failed", "workspace path contains a symlink")
        parent = result.parent.resolve(strict=False)
        if parent != self.root and self.root not in parent.parents:
            raise ContractError("invalid_input", "workspace-relative path escapes its root")
        return result


def atomic_write(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Create a new file atomically; never replace authoritative bytes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise ContractError("conformance_failed", f"atomic target is unsafe: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".qste-stage-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file():
                raise ContractError(
                    "conformance_failed", f"immutable path is unsafe: {path}"
                ) from None
            if path.read_bytes() != data:
                raise ContractError(
                    "conformance_failed", f"immutable path already has different bytes: {path}"
                ) from None
    finally:
        temporary.unlink(missing_ok=True)
