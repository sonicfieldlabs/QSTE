from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from p5_helpers import build_p5_fixture, explicit_candidates

from qste.cli import main
from qste.storage import RecordStore, WorkspacePaths


def test_project_measure_perturb_and_account_are_typed_and_receipted(tmp_path: Path) -> None:
    fixture = build_p5_fixture(tmp_path, np.linspace(-0.5, 0.5, 512))
    left, right = explicit_candidates(
        fixture,
        [
            [[0, 2, 4], [0, 3, 4]],
            [[0, 4, 4], [0, 5, 4]],
        ],
    )
    projection = fixture.service.project(
        candidate_record_id=left["record_id"],
        projection_record_id=fixture.instance["qste:defaultProjectionRef"]["record_id"],
    )
    assert projection.value["payload_type"] == "ProjectedFootprint"
    assert projection.value["data"]["cross_arm_relation"] == "not_computed_in_P5"
    assert projection.value["data"]["calibration"]["physical_claims"] == "prohibited"

    measure = fixture.service.measure(
        left_candidate_record_id=left["record_id"],
        right_candidate_record_id=right["record_id"],
        metric_spec={"metric": "complex_l2"},
    )
    assert measure.value["data"]["native_only"] is True
    assert measure.value["data"]["cross_arm_comparability"] is False

    perturbed = fixture.service.perturb(
        instance_record_id=fixture.instance["record_id"],
        perturbation_spec={"mode": "coefficient_gain", "gain": 0.5},
    )
    assert perturbed.value["record_type"] == "RepresentationInstance"
    assert perturbed.value["record_id"] != fixture.instance["record_id"]
    assert perturbed.value["references"][0]["relation"] == "derived_from"

    account = fixture.service.account(instance_record_id=fixture.instance["record_id"])
    assert len(account.value["data"]["available_operations"]) == 11
    assert account.value["data"]["dsq_assessment"] == "unavailable_until_P6"
    store = RecordStore(WorkspacePaths.open(fixture.workspace))
    for outcome in (projection, measure, perturbed, account):
        store.get_record(outcome.receipt_record["record_id"])


def test_representation_cli_uses_normative_envelope_and_persisted_receipt(
    tmp_path: Path, capsys: object
) -> None:
    fixture = build_p5_fixture(tmp_path, np.sin(np.arange(256) / 5))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"fft_length": 64, "hop_length": 16}))
    assert (
        main(
            [
                "representation",
                "encode",
                "--workspace",
                str(fixture.workspace),
                "--artifact",
                fixture.ingress_artifact["record_id"],
                "--aperture",
                fixture.aperture["record_id"],
                "--config",
                str(config_path),
                "--authorization",
                "permitted",
                "--json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert output["operation"] == "qste:encode/0.1.0"
    assert output["value"]["record_type"] == "RepresentationInstance"
    RecordStore(WorkspacePaths.open(fixture.workspace)).get_record(output["receipt_id"])


def test_stft_config_rejects_unfrozen_or_numerically_incoherent_values() -> None:
    from qste.core.contracts import ContractError
    from qste.representations import stft_config_from_mapping

    for config in (
        {"unknown": True},
        {"fft_length": 100},
        {"coefficient_dtype": "complex64"},
        {"maximum_candidates": True},
        {"maximum_refinement_nodes": True},
    ):
        try:
            value = stft_config_from_mapping(config)
            if "unknown" not in config:
                from qste.representations.stft import _validate_config

                _validate_config(value, 48_000)
        except ContractError:
            continue
        raise AssertionError(f"config should fail: {config}")
