from __future__ import annotations

from pathlib import Path

import numpy as np
from p5_helpers import build_p5_fixture, explicit_candidates


def test_native_support_addressability_interventions_and_controls(tmp_path: Path) -> None:
    index = np.arange(1024)
    signal = 0.7 * np.sin(2 * np.pi * 1500 * index / 48_000)
    fixture = build_p5_fixture(tmp_path, signal)
    candidate = explicit_candidates(fixture, [[[[0, 2, 5], [0, 3, 5], [0, 2, 6]]][0]])[0]
    intervention_id = fixture.instance["qste:defaultInterventionRef"]["record_id"]

    addressed = fixture.service.address(
        candidate_record_id=candidate["record_id"],
        intervention_record_id=intervention_id,
    )
    assert addressed.value["data"]["addressable"] is True

    support = fixture.service.support(
        candidate_record_id=candidate["record_id"],
        support_spec={"difference_floor": 1e-14},
    ).value["data"]
    assert support["candidate_support_is_atom_spread"] is False
    assert support["effective_intervention_support"]["time_seconds"] != "absent"
    assert support["effective_intervention_support"]["frequency_support"].startswith(
        "estimated_from_native"
    )

    for mode in ("mask", "isolate", "phase_coherent_replace"):
        state = fixture.service.intervene(
            candidate_record_id=candidate["record_id"],
            intervention_record_id=intervention_id,
            mode=mode,
        ).value
        assert state["data"]["control_diagnostics"]["passed"] is True
        decoded = fixture.service.decode(
            target_record_id=state["data"]["dense_artifact_ref"]["record_id"]
        )
        assert decoded.value["qste:reconstructionDiagnostics"]["comparison"].startswith(
            "not_applicable"
        )

    resynthesis = fixture.service.intervene(
        candidate_record_id=candidate["record_id"],
        intervention_record_id=intervention_id,
        mode="mask",
        control="resynthesis_only",
    ).value
    assert resynthesis["data"]["control_diagnostics"] == {
        "coefficient_maximum_change": 0.0,
        "applied_candidate_overlap": 0,
        "passed": True,
    }
    off_target = fixture.service.intervene(
        candidate_record_id=candidate["record_id"],
        intervention_record_id=intervention_id,
        mode="mask",
        control="off_target",
    ).value
    assert off_target["data"]["control_diagnostics"]["applied_candidate_overlap"] == 0
    assert off_target["data"]["control_diagnostics"]["passed"] is True


def test_boundary_support_is_explicitly_marked(tmp_path: Path) -> None:
    signal = np.zeros(65)
    signal[0] = 1
    fixture = build_p5_fixture(tmp_path, signal)
    candidate = explicit_candidates(fixture, [[[[0, 1, 2]]][0]])[0]
    support = fixture.service.support(
        candidate_record_id=candidate["record_id"],
        support_spec={"difference_floor": 0.0},
    ).value["data"]
    assert candidate["native_support"]["time_seconds"][0] == 0.0
    assert support["effective_intervention_support"]["boundary_affected"] is True
