from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import numpy.typing as npt
import soundfile as sf  # type: ignore[import-untyped]

from qste.ingress import IngressLimits, IngressService, declare_apparatus, derive_aperture
from qste.representations import STFTConfig, STFTService

P5_OPERATIONS = [
    "ingest",
    "inspect",
    "lineage",
    "verify",
    "bundle",
    "decode",
    "resample",
    "normalize",
    "encode",
    "enumerate",
    "refine",
    "support",
    "address",
    "intervene",
    "project",
    "measure",
    "perturb",
    "account",
]


@dataclass(frozen=True, slots=True)
class P5Fixture:
    workspace: Path
    service: STFTService
    apparatus: dict[str, Any]
    ingress_artifact: dict[str, Any]
    aperture: dict[str, Any]
    instance: dict[str, Any]


def build_p5_fixture(
    tmp_path: Path,
    samples: npt.ArrayLike,
    *,
    config: STFTConfig | None = None,
    sample_rate: int = 48_000,
) -> P5Fixture:
    array = np.asarray(samples, dtype=np.float64)
    if array.ndim == 1:
        array = array[:, None]
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source.wav"
    sf.write(source, array, sample_rate, subtype="DOUBLE")
    channels = [
        {"source_index": index, "label": f"channel_{index + 1}"} for index in range(array.shape[1])
    ]
    declaration = {
        "apparatus_version": "p5-test/0.1",
        "configuration": {"execution": "local_offline"},
        "acquisition_surface": {
            "media_kinds": ["audio"],
            "timebase": {"kind": "sample_clock", "sample_rates_hz": [sample_rate]},
            "channel_map": channels,
            "calibration": {
                "frequency": {"status": "uncalibrated"},
                "level": {"status": "uncalibrated"},
                "time": {"status": "uncalibrated"},
            },
        },
        "computation_surface": {
            "numeric_dtypes": ["float64"],
            "preprocessing_operations": ["decode"],
        },
        "action_surface": {
            "permitted_operations": P5_OPERATIONS,
            "network_access": False,
        },
        "authorization_status": "permitted",
    }
    workspace = tmp_path / "workspace"
    apparatus = declare_apparatus(workspace, declaration).apparatus_record
    ingress = IngressService(workspace, IngressLimits((tmp_path,))).ingest(
        source,
        kind="audio",
        apparatus_record_id=apparatus["record_id"],
        attributed_origin="generated P5 fixture",
        rights={"use": "research", "redistribution": "prohibited"},
        retention={"mode": "retain", "redistribution": "prohibited"},
        authorization_status="permitted",
    )
    aperture = derive_aperture(
        workspace,
        apparatus_record_id=apparatus["record_id"],
        input_artifact_record_id=ingress.result_artifact_record["record_id"],
        policy={
            "authorization_status": "permitted",
            "allowed_operations": P5_OPERATIONS,
        },
    ).aperture_record
    service = STFTService(workspace)
    encoded = service.encode(
        artifact_record_id=ingress.result_artifact_record["record_id"],
        aperture_record_id=aperture["record_id"],
        config=config or STFTConfig(fft_length=64, hop_length=16),
    )
    return P5Fixture(
        workspace,
        service,
        apparatus,
        ingress.result_artifact_record,
        aperture,
        encoded.value,
    )


def explicit_candidates(fixture: P5Fixture, masks: list[list[list[int]]]) -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        fixture.service.enumerate(
            instance_record_id=fixture.instance["record_id"],
            candidate_rule={"rule_id": "explicit_masks/0.1", "masks": masks},
        ).value["items"],
    )
