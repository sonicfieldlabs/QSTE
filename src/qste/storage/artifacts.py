"""Immutable content-addressed artifact storage."""

from __future__ import annotations

from dataclasses import dataclass

from qste.core.contracts import ContractError
from qste.core.identity import content_digest, verify_content_digest
from qste.storage.paths import WorkspacePaths, atomic_write


@dataclass(frozen=True, slots=True)
class ArtifactObject:
    content_digest: str
    size: int
    relative_path: str


class ArtifactStore:
    def __init__(self, paths: WorkspacePaths) -> None:
        self.paths = paths

    def put_bytes(self, data: bytes | bytearray | memoryview) -> ArtifactObject:
        payload = bytes(data)
        digest = content_digest(payload)
        relative = self.relative_path(digest)
        target = self.paths.owned_path(relative)
        atomic_write(target, payload, mode=0o400)
        if not verify_content_digest(target.read_bytes(), digest):
            raise ContractError("conformance_failed", "artifact failed its post-write digest check")
        return ArtifactObject(digest, len(payload), relative)

    def read_bytes(self, digest: str, *, maximum_bytes: int | None = None) -> bytes:
        if maximum_bytes is not None and (
            not isinstance(maximum_bytes, int)
            or isinstance(maximum_bytes, bool)
            or maximum_bytes < 0
        ):
            raise ContractError("invalid_input", "artifact read bound must be nonnegative")
        target = self.paths.owned_path(self.relative_path(digest))
        if not target.is_file() or target.is_symlink():
            raise ContractError("capability_unavailable", f"artifact is absent: {digest}")
        size = target.stat().st_size
        if maximum_bytes is not None and size > maximum_bytes:
            raise ContractError("invalid_input", "artifact exceeds the requested read bound")
        data = target.read_bytes()
        if not verify_content_digest(data, digest):
            raise ContractError("conformance_failed", f"artifact digest mismatch: {digest}")
        return data

    def verify(self, digest: str) -> bool:
        self.read_bytes(digest)
        return True

    def iter_objects(self) -> tuple[ArtifactObject, ...]:
        if not self.paths.artifacts.is_dir() or self.paths.artifacts.is_symlink():
            raise ContractError("conformance_failed", "artifact root is absent or unsafe")
        root = self.paths.artifacts / "sha256"
        for child in self.paths.artifacts.iterdir():
            if child != root or child.is_symlink() or not child.is_dir():
                raise ContractError("conformance_failed", f"unexpected artifact-root path: {child}")
        if not root.exists():
            return ()
        if not root.is_dir() or root.is_symlink():
            raise ContractError("conformance_failed", "artifact digest root is unsafe")
        objects: list[ArtifactObject] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ContractError("conformance_failed", f"artifact path is a symlink: {path}")
            relative_parts = path.relative_to(root).parts
            if path.is_dir():
                if (
                    len(relative_parts) != 1
                    or len(path.name) != 2
                    or any(character not in "0123456789abcdef" for character in path.name)
                ):
                    raise ContractError(
                        "conformance_failed", f"unexpected artifact directory: {path}"
                    )
                continue
            if not path.is_file():
                raise ContractError("conformance_failed", f"unexpected artifact object: {path}")
            hexdigest = path.name
            digest = f"sha256:{hexdigest}"
            if (
                len(relative_parts) != 2
                or path.parent.name != hexdigest[:2]
                or len(hexdigest) != 64
                or any(character not in "0123456789abcdef" for character in hexdigest)
            ):
                raise ContractError("conformance_failed", f"unexpected artifact path: {path}")
            self.verify(digest)
            objects.append(
                ArtifactObject(
                    content_digest=digest,
                    size=path.stat().st_size,
                    relative_path=path.relative_to(self.paths.root).as_posix(),
                )
            )
        return tuple(objects)

    @staticmethod
    def relative_path(digest: str) -> str:
        if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
            raise ContractError("invalid_input", "artifact digest must be canonical SHA-256")
        hexdigest = digest.removeprefix("sha256:")
        if any(character not in "0123456789abcdef" for character in hexdigest):
            raise ContractError("invalid_input", "artifact digest must be lowercase hexadecimal")
        return f"artifacts/sha256/{hexdigest[:2]}/{hexdigest}"
