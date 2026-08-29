from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from qste.core.contracts import ContractError
from qste.storage import DenseStore, RecordStore


def _write(root: Path, dense_id: str = "spectrogram") -> DenseStore:
    record_store = RecordStore.initialize(root)
    dense = DenseStore(record_store.paths, record_store)
    dense.write_array(
        dense_id,
        np.arange(12, dtype=np.float64).reshape(3, 4),
        chunks=(2, 2),
        dimension_names=("time", "frequency"),
        coordinates={"time": [0.0, 0.5, 1.0], "frequency": [100, 200, 300, 400]},
        created_at="2026-08-28T02:00:00Z",
    )
    return dense


def test_dense_manifest_slice_and_coordinates_are_verified(tmp_path: Path) -> None:
    dense = _write(tmp_path / "workspace")
    verified = dense.verify("spectrogram")
    resolved = dense.resolve_slice("spectrogram", (slice(1, 3), slice(0, 2)))
    np.testing.assert_array_equal(resolved.values, [[4.0, 5.0], [8.0, 9.0]])
    np.testing.assert_array_equal(resolved.coordinates["time"], [0.5, 1.0])
    np.testing.assert_array_equal(resolved.coordinates["frequency"], [100, 200])
    assert resolved.manifest_digest == verified.manifest_digest


def test_dense_writes_are_deterministic_given_fixed_identity_and_time(tmp_path: Path) -> None:
    first = _write(tmp_path / "first").verify("spectrogram")
    second = _write(tmp_path / "second").verify("spectrogram")
    assert first.manifest == second.manifest


def test_dense_tampering_is_detected_before_slicing(tmp_path: Path) -> None:
    dense = _write(tmp_path / "workspace")
    manifest = dense.manifest("spectrogram")
    chunk = next(entry for entry in manifest["files"] if entry["kind"] == "chunk")
    path = dense.paths.dense / "spectrogram.zarr" / chunk["path"]
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(ContractError, match="manifest mismatch"):
        dense.resolve_slice("spectrogram", (slice(None), slice(None)))


def test_dense_bounds_empty_axes_and_nonfinite_counts_remain_explicit(tmp_path: Path) -> None:
    store = RecordStore.initialize(tmp_path / "workspace")
    dense = DenseStore(store.paths, store)
    with pytest.raises(ContractError, match="empty axis"):
        dense.write_array(
            "empty",
            np.empty((0, 2)),
            chunks=(1, 1),
            dimension_names=("x", "y"),
            coordinates={"x": [], "y": [1, 2]},
        )
    with pytest.raises(ContractError, match="canonical UTC seconds"):
        dense.write_array(
            "bad-time",
            [1.0],
            chunks=(1,),
            dimension_names=("sample",),
            coordinates={"sample": [0]},
            created_at="not-a-time",
        )
    dense.write_array(
        "nonfinite",
        np.array([0.0, np.nan, np.inf]),
        chunks=(2,),
        dimension_names=("sample",),
        coordinates={"sample": [0, 1, 2]},
        created_at="2026-08-28T02:00:00Z",
    )
    assert dense.manifest("nonfinite")["values"]["nonfinite_count"] == 2
    with pytest.raises(ContractError, match="element budget"):
        dense.resolve_slice("nonfinite", (slice(None),), maximum_elements=2)
    with pytest.raises(ContractError, match="unit positive"):
        dense.resolve_slice("nonfinite", (slice(None, None, 2),))
