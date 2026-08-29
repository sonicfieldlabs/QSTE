from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf  # type: ignore[import-untyped]
from p4_helpers import RETENTION, RIGHTS, apparatus_declaration

from qste.core import content_digest
from qste.core.contracts import ContractError
from qste.ingress import (
    AudioTransform,
    IngressLimits,
    IngressService,
    declare_apparatus,
    derive_aperture,
    require_calibration_claim,
)
from qste.storage import RecordStore, WorkspacePaths


@pytest.mark.parametrize("calibrated", [False, True])
def test_audio_derivatives_aperture_bounds_and_calibration_gates(
    tmp_path: Path, calibrated: bool
) -> None:
    workspace = tmp_path / "workspace"
    apparatus = declare_apparatus(
        workspace, apparatus_declaration(calibrated=calibrated)
    ).apparatus_record
    source = tmp_path / "source.wav"
    samples = np.sin(2 * np.pi * 1000 * np.arange(4800) / 48_000)
    sf.write(source, samples, 48_000, subtype="PCM_16")
    before = source.read_bytes()
    outcome = IngressService(workspace, IngressLimits((tmp_path,))).ingest(
        source,
        kind="audio",
        apparatus_record_id=apparatus["record_id"],
        attributed_origin="generated fixture",
        rights=RIGHTS,
        retention=RETENTION,
        authorization_status="permitted",
        audio_transform=AudioTransform(
            target_sample_rate_hz=96_000,
            normalization="peak",
            output_dtype="float32",
        ),
    )
    assert source.read_bytes() == before
    assert outcome.original_artifact_record["content_digest"] == content_digest(before)
    assert outcome.result_artifact_record["qste:artifactRole"] == "processed_derivative"
    assert outcome.result_artifact_record["qste:derivationOperations"] == [
        "decode",
        "resample",
        "normalize",
    ]
    assert (
        outcome.original_artifact_record["record_id"] != outcome.result_artifact_record["record_id"]
    )
    assert (
        outcome.receipt_record["record_id"]
        == outcome.acquisition_record["receipt_ref"]["record_id"]
    )

    aperture = derive_aperture(
        workspace,
        apparatus_record_id=apparatus["record_id"],
        input_artifact_record_id=outcome.result_artifact_record["record_id"],
        policy={
            "authorization_status": "permitted",
            "allowed_operations": ["inspect", "normalize"],
            "maximum_frequency_hz": 30_000,
            "maximum_duration_seconds": 0.04,
        },
    ).aperture_record
    assert aperture["record_type"] == "ApertureSpec"
    assert aperture["record_id"] != apparatus["record_id"]
    assert aperture["accessible_ranges"]["digital_frequency_hz"] == [0.0, 24_000.0]
    assert aperture["accessible_ranges"]["time_seconds"] == [0.0, 0.04]
    require_calibration_claim(aperture, "digital_sample_domain")
    if calibrated:
        require_calibration_claim(aperture, "spl")
        require_calibration_claim(aperture, "extra_human_frequency")
    else:
        with pytest.raises(ContractError, match="requires calibration"):
            require_calibration_claim(aperture, "spl")
        with pytest.raises(ContractError, match="requires calibration"):
            require_calibration_claim(aperture, "extra_human_frequency")
    RecordStore(WorkspacePaths.open(workspace)).verify()
