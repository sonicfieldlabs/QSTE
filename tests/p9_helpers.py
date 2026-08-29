from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from p5_helpers import P5Fixture, build_p5_fixture

from qste.adapters import ENCODEC_TARGET, SAMPLEBRAIN_TARGET, ExternalRepresentationService


@dataclass(frozen=True, slots=True)
class P9Fixture:
    base: P5Fixture
    service: ExternalRepresentationService


def build_p9_fixture(tmp_path: Path) -> P9Fixture:
    index = np.arange(64)
    signal = (0.25 * np.sin(2 * np.pi * 440 * index / 48_000))[:, None]
    base = build_p5_fixture(tmp_path, signal)
    return P9Fixture(base, ExternalRepresentationService(base.workspace))


def capture_fixture(fixture: P9Fixture, adapter_id: str) -> dict[str, Any]:
    target = SAMPLEBRAIN_TARGET if adapter_id == "samplebrain" else ENCODEC_TARGET
    native_values = (
        [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]] if adapter_id == "samplebrain" else [[12, 34], [56, 78]]
    )
    addresses = (
        [
            {"brain_session": "fixture-A", "block_index": 0},
            {"brain_session": "fixture-A", "block_index": 1},
        ]
        if adapter_id == "samplebrain"
        else [
            {"frame_index": 0, "codebook_indices": [0, 1], "token_values": [12, 34]},
            {"frame_index": 1, "codebook_indices": [0, 1], "token_values": [56, 78]},
        ]
    )
    reason = (
        "block_size_change_not_a_refinement_certificate"
        if adapter_id == "samplebrain"
        else "codebook_prefix_mapping_and_decoder_intervention_not_verified"
    )
    return {
        "profile_id": "qste-external-representation-capture/0.1",
        "adapter_id": adapter_id,
        "execution_mode": "synthetic_contract_fixture",
        "execution_status": "completed",
        "evidence_class": "synthetic_non_model_fixture",
        "target_id": target.target_id,
        "source": {
            "content_digest": fixture.base.ingress_artifact["content_digest"],
            "sample_rate_hz": 48_000,
            "channel_count": 1,
        },
        "resampling": {
            "applied": False,
            "source_hz": 48_000,
            "target_hz": 48_000,
            "method": "none",
        },
        "configuration": {
            "profile": f"{adapter_id}-synthetic-contract-fixture/0.1",
            "target_revision": target.implementation_revision,
            "block_or_frame_configuration": {"size": 32, "stride": 32},
        },
        "native_values": native_values,
        "candidates": [
            {
                "native_address": address,
                "native_support": {
                    "time_seconds": [index * 0.0005, (index + 1) * 0.0005],
                    "source_frame_range": [index * 24, (index + 1) * 24],
                    "method": "synthetic_exact_fixture_support",
                },
                "addressable": True,
            }
            for index, address in enumerate(addresses)
        ],
        "decoded_waveform": [[float(value)] for value in np.linspace(-0.1, 0.1, 32)],
        "artifact_controls": {
            "source_alignment": "exact_fixture",
            "decoder_only_control": True,
            "off_target_control": True,
        },
        "opaque_boundary": {
            "visible_fields": ["native_values", "candidate_catalog", "decoded_waveform"],
            "opaque_fields": ["internal_search_state", "hidden_encoder_activations"],
            "observability": "captured_outputs_only",
        },
        "refinement": {"status": "unavailable", "reason": reason, "graph_created": False},
    }


def encode_and_enumerate(
    fixture: P9Fixture, adapter_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    instance = fixture.service.encode_capture(
        adapter_id=adapter_id,
        artifact_record_id=fixture.base.ingress_artifact["record_id"],
        aperture_record_id=fixture.base.aperture["record_id"],
        capture=capture_fixture(fixture, adapter_id),
    ).value
    candidates = fixture.service.enumerate(
        instance_record_id=instance["record_id"],
        candidate_rule={"selection": "all_captured", "maximum_candidates": 8},
    ).value["items"]
    return instance, candidates
