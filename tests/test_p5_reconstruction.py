from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from p5_helpers import build_p5_fixture

from qste.representations import STFTConfig
from qste.storage import DenseStore, RecordStore, WorkspacePaths


def _signal(kind: str, frames: int = 257, sample_rate: int = 48_000) -> np.ndarray:
    index = np.arange(frames)
    if kind == "impulse":
        value = np.zeros(frames)
        value[frames // 2] = 0.8
        return value
    if kind == "tone":
        return 0.7 * np.sin(2 * np.pi * 1000 * index / sample_rate)
    if kind == "chirp":
        return 0.6 * np.sin(2 * np.pi * (100 + (4000 * index / frames)) * index / sample_rate)
    if kind == "silence":
        return np.zeros(frames)
    if kind == "noise":
        return np.random.default_rng(7).normal(0, 0.1, frames)
    if kind == "boundary":
        value = np.zeros(17)
        value[[0, -1]] = [0.5, -0.5]
        return value
    if kind == "multichannel":
        return np.stack(
            [
                0.5 * np.sin(2 * np.pi * 440 * index / sample_rate),
                0.4 * np.cos(2 * np.pi * 880 * index / sample_rate),
            ],
            axis=1,
        )
    if kind == "numerical_stability":
        return np.where(index % 2, 1e-9, -0.79)
    raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind",
    [
        "impulse",
        "tone",
        "chirp",
        "silence",
        "noise",
        "boundary",
        "multichannel",
        "numerical_stability",
    ],
)
def test_phase_preserving_inverse_reconstruction_for_p5_fixture_corpus(
    tmp_path: Path, kind: str
) -> None:
    fixture = build_p5_fixture(tmp_path, _signal(kind))
    decoded = fixture.service.decode(target_record_id=fixture.instance["record_id"])
    diagnostics = decoded.value["qste:reconstructionDiagnostics"]
    assert diagnostics["passed"] is True
    assert diagnostics["maximum_absolute_error"] < 1e-12
    assert diagnostics["phase_preserved"] is True
    store = RecordStore(WorkspacePaths.open(fixture.workspace))
    store.verify()
    dense_id = fixture.instance["qste:denseId"]
    dense = DenseStore(store.paths, store).verify(dense_id)
    assert dense.manifest["values"]["dimension_names"] == [
        "channel",
        "frequency_hz",
        "frame_time_seconds",
    ]


def test_hop_density_changes_lattice_not_atom_bound_or_realized_spread(tmp_path: Path) -> None:
    signal = _signal("tone", frames=1024)
    first = build_p5_fixture(
        tmp_path / "first", signal, config=STFTConfig(fft_length=128, hop_length=32)
    )
    second = build_p5_fixture(
        tmp_path / "second", signal, config=STFTConfig(fft_length=128, hop_length=16)
    )
    first_store = RecordStore(WorkspacePaths.open(first.workspace))
    second_store = RecordStore(WorkspacePaths.open(second.workspace))
    first_spec = first_store.get_record(
        first.instance["representation_spec_ref"]["record_id"]
    ).record
    second_spec = second_store.get_record(
        second.instance["representation_spec_ref"]["record_id"]
    ).record
    assert first_spec["qste:gaborAtomBound"] == second_spec["qste:gaborAtomBound"]
    assert first_spec["qste:realizedAtomSpread"] == second_spec["qste:realizedAtomSpread"]
    assert first_spec["qste:lattice"]["hop_length"] != second_spec["qste:lattice"]["hop_length"]
    assert first_spec["qste:lattice"]["redundancy"] != second_spec["qste:lattice"]["redundancy"]
    assert first_spec["qste:separationInvariant"]["lattice_is_refinement"] is False
