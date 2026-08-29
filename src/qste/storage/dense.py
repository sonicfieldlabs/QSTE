"""Verified Zarr v3 dense arrays with coordinate and chunk manifests."""

from __future__ import annotations

import re
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import numpy.typing as npt
import zarr

from qste.core import (
    canonical_json_bytes,
    content_digest,
    loads_json,
    utc_timestamp,
    validate_utc_timestamp,
)
from qste.core.contracts import ContractError
from qste.storage.database import RecordStore
from qste.storage.paths import WorkspacePaths, atomic_write

DENSE_FORMAT = "qste-dense/0.1"
_DENSE_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


@dataclass(frozen=True, slots=True)
class DenseObject:
    dense_id: str
    manifest_digest: str
    relative_path: str
    manifest: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DenseSlice:
    dense_id: str
    values: npt.NDArray[Any]
    coordinates: dict[str, npt.NDArray[Any]]
    manifest_digest: str


class DenseStore:
    def __init__(self, paths: WorkspacePaths, record_store: RecordStore | None = None) -> None:
        self.paths = paths
        self.record_store = record_store

    def write_array(
        self,
        dense_id: str,
        values: npt.ArrayLike,
        *,
        chunks: Sequence[int],
        dimension_names: Sequence[str],
        coordinates: Mapping[str, npt.ArrayLike],
        created_at: str | None = None,
    ) -> DenseObject:
        self._validate_dense_id(dense_id)
        array = np.asarray(values)
        if array.ndim < 1:
            raise ContractError("invalid_input", "dense values require at least one dimension")
        if any(length < 1 for length in array.shape):
            raise ContractError("invalid_input", "dense values cannot contain an empty axis")
        chunk_shape = tuple(int(value) for value in chunks)
        if len(chunk_shape) != array.ndim or any(value < 1 for value in chunk_shape):
            raise ContractError(
                "invalid_input", "chunk shape must contain one positive size per axis"
            )
        names = tuple(dimension_names)
        if len(names) != array.ndim or len(names) != len(set(names)):
            raise ContractError("invalid_input", "dimension names must be unique and match rank")
        coordinate_arrays: dict[str, npt.NDArray[Any]] = {}
        for axis, name in enumerate(names):
            if not re.fullmatch(r"[a-z][a-z0-9_.-]*", name):
                raise ContractError("invalid_input", f"invalid coordinate name: {name}")
            if name not in coordinates:
                raise ContractError("invalid_input", f"coordinate is missing: {name}")
            coordinate = np.asarray(coordinates[name])
            if coordinate.ndim != 1 or coordinate.shape[0] != array.shape[axis]:
                raise ContractError(
                    "invalid_input", f"coordinate shape does not match axis: {name}"
                )
            coordinate_arrays[name] = coordinate
        if set(coordinates) != set(names):
            raise ContractError("invalid_input", "undeclared coordinates are prohibited")
        timestamp = validate_utc_timestamp(created_at or utc_timestamp())

        target_store = self.paths.dense / f"{dense_id}.zarr"
        manifest_path = self.paths.dense / f"{dense_id}.manifest.json"
        if target_store.exists() or manifest_path.exists():
            raise ContractError("conformance_failed", f"dense ID already exists: {dense_id}")
        stage_root = self.paths.staging / f"dense-{dense_id}-{uuid.uuid4()}"
        stage_store = stage_root / f"{dense_id}.zarr"
        stage_root.mkdir(mode=0o700, parents=True)
        promoted = False
        try:
            group = zarr.open_group(str(stage_store), mode="w", zarr_format=3)
            group.create_array(
                "values",
                data=array,
                chunks=chunk_shape,
                dimension_names=names,
            )
            coordinate_group = group.create_group("coordinates")
            for name in names:
                coordinate = coordinate_arrays[name]
                coordinate_group.create_array(
                    name,
                    data=coordinate,
                    chunks=(min(chunk_shape[names.index(name)], len(coordinate)),),
                    dimension_names=(name,),
                )
            files = self._file_entries(stage_store)
            manifest_without_digest: dict[str, Any] = {
                "dense_format": DENSE_FORMAT,
                "dense_id": dense_id,
                "zarr_format": 3,
                "created_at": timestamp,
                "values": {
                    "dtype": array.dtype.str,
                    "shape": list(array.shape),
                    "chunks": list(chunk_shape),
                    "dimension_names": list(names),
                    "nonfinite_count": _nonfinite_count(array),
                },
                "coordinates": {
                    name: {
                        "dtype": coordinate_arrays[name].dtype.str,
                        "shape": list(coordinate_arrays[name].shape),
                        "nonfinite_count": _nonfinite_count(coordinate_arrays[name]),
                    }
                    for name in names
                },
                "files": files,
            }
            manifest_digest = content_digest(canonical_json_bytes(manifest_without_digest))
            manifest = manifest_without_digest | {"manifest_digest": manifest_digest}
            stage_store.rename(target_store)
            promoted = True
            atomic_write(manifest_path, canonical_json_bytes(manifest), mode=0o400)
        except Exception:
            if promoted and not manifest_path.exists() and target_store.exists():
                shutil.rmtree(target_store)
            raise
        finally:
            if stage_root.exists():
                shutil.rmtree(stage_root)
        result = DenseObject(
            dense_id=dense_id,
            manifest_digest=manifest_digest,
            relative_path=manifest_path.relative_to(self.paths.root).as_posix(),
            manifest=manifest,
        )
        self.verify(dense_id)
        if self.record_store is not None:
            self.record_store.register_dense_manifest(
                dense_id,
                manifest_digest,
                result.relative_path,
                manifest,
                registered_at=manifest["created_at"],
            )
        return result

    def manifest(self, dense_id: str) -> dict[str, Any]:
        self._validate_dense_id(dense_id)
        path = self.paths.dense / f"{dense_id}.manifest.json"
        if not path.is_file() or path.is_symlink():
            raise ContractError("capability_unavailable", f"dense manifest is absent: {dense_id}")
        value = loads_json(path.read_bytes())
        if not isinstance(value, dict):
            raise ContractError("conformance_failed", "dense manifest is not an object")
        return cast(dict[str, Any], value)

    def verify(self, dense_id: str) -> DenseObject:
        manifest = self.manifest(dense_id)
        if manifest.get("dense_format") != DENSE_FORMAT or manifest.get("dense_id") != dense_id:
            raise ContractError("conformance_failed", "dense manifest identity conflict")
        declared_digest = manifest.get("manifest_digest")
        without_digest = {key: value for key, value in manifest.items() if key != "manifest_digest"}
        if content_digest(canonical_json_bytes(without_digest)) != declared_digest:
            raise ContractError("conformance_failed", "dense manifest digest mismatch")
        store = self.paths.dense / f"{dense_id}.zarr"
        if not store.is_dir() or store.is_symlink():
            raise ContractError("capability_unavailable", f"dense Zarr store is absent: {dense_id}")
        actual_files = self._file_entries(store)
        if actual_files != manifest.get("files"):
            raise ContractError("conformance_failed", "dense Zarr file/chunk manifest mismatch")
        group = zarr.open_group(str(store), mode="r", zarr_format=3)
        values: Any = group["values"]
        declared = manifest["values"]
        if (
            list(values.shape) != declared["shape"]
            or list(values.chunks) != declared["chunks"]
            or np.dtype(values.dtype).str != declared["dtype"]
            or list(values.metadata.dimension_names) != declared["dimension_names"]
        ):
            raise ContractError("conformance_failed", "dense array metadata mismatch")
        return DenseObject(
            dense_id=dense_id,
            manifest_digest=cast(str, declared_digest),
            relative_path=(self.paths.dense / f"{dense_id}.manifest.json")
            .relative_to(self.paths.root)
            .as_posix(),
            manifest=manifest,
        )

    def resolve_slice(
        self,
        dense_id: str,
        selectors: Sequence[slice | int],
        *,
        maximum_elements: int = 1_000_000,
    ) -> DenseSlice:
        verified = self.verify(dense_id)
        shape = tuple(int(value) for value in verified.manifest["values"]["shape"])
        if len(selectors) != len(shape):
            raise ContractError("invalid_input", "slice rank does not match dense array")
        normalized: list[slice | int] = []
        result_elements = 1
        for selector, length in zip(selectors, shape, strict=True):
            if isinstance(selector, int):
                if selector < 0 or selector >= length:
                    raise ContractError("invalid_input", "dense index is out of range")
                normalized.append(selector)
                continue
            start, stop, step = selector.indices(length)
            if step != 1:
                raise ContractError("invalid_input", "dense slices require unit positive steps")
            count = max(0, stop - start)
            result_elements *= count
            normalized.append(slice(start, stop, 1))
        if result_elements > maximum_elements:
            raise ContractError("invalid_input", "dense slice exceeds the element budget")
        group = zarr.open_group(str(self.paths.dense / f"{dense_id}.zarr"), mode="r", zarr_format=3)
        values_array: Any = group["values"]
        values = np.asarray(values_array[tuple(normalized)])
        names = verified.manifest["values"]["dimension_names"]
        resolved_coordinates: dict[str, npt.NDArray[Any]] = {}
        for axis, name in enumerate(names):
            coordinate_array: Any = group[f"coordinates/{name}"]
            resolved_coordinates[name] = np.asarray(coordinate_array[normalized[axis]])
        return DenseSlice(dense_id, values, resolved_coordinates, verified.manifest_digest)

    def iter_objects(self) -> tuple[DenseObject, ...]:
        return tuple(
            self.verify(path.name.removesuffix(".manifest.json"))
            for path in sorted(self.paths.dense.glob("*.manifest.json"))
        )

    @staticmethod
    def _validate_dense_id(dense_id: str) -> None:
        if not _DENSE_ID.fullmatch(dense_id):
            raise ContractError("invalid_input", "dense ID is not canonical")

    @staticmethod
    def _file_entries(store: Path) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for path in sorted(candidate for candidate in store.rglob("*") if candidate.is_file()):
            if path.is_symlink():
                raise ContractError("conformance_failed", "dense stores cannot contain symlinks")
            data = path.read_bytes()
            relative = path.relative_to(store).as_posix()
            entries.append(
                {
                    "path": relative,
                    "content_digest": content_digest(data),
                    "size": len(data),
                    "kind": "chunk" if "/c/" in f"/{relative}" else "metadata",
                }
            )
        return entries


def _nonfinite_count(array: npt.NDArray[Any]) -> int:
    if np.issubdtype(array.dtype, np.number):
        return int(np.size(array) - np.count_nonzero(np.isfinite(array)))
    return 0
