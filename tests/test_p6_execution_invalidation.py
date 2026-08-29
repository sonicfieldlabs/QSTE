from __future__ import annotations

from pathlib import Path

import pytest
from p6_helpers import declare_and_execute, p6_fixture, task_spec

from qste.core.contracts import ContractError
from qste.quanta import QuantaService
from qste.storage import RecordStore, WorkspacePaths


def test_seeded_stochastic_intervals_replay_and_preserve_raw_orientation(tmp_path: Path) -> None:
    fixture, candidate, graph = p6_fixture(tmp_path)
    proper = graph["required_closure"]
    effects = {
        candidate["record_id"]: [0.68, 0.7, 0.72, 0.71],
        proper[0]: [0.0, 0.01, -0.01, 0.0],
        proper[1]: [0.01, 0.0, -0.01, 0.0],
    }
    spec = task_spec(3, uncertainty="bonferroni_normal", repeats=4)
    service = QuantaService(fixture.workspace)
    task = service.declare_task(
        candidate_record_id=candidate["record_id"],
        refinement_graph_record_id=graph["record_id"],
        specification=spec,
    ).value
    from p6_helpers import paired_evidence

    evidence = paired_evidence(effects, protocol="stochastic", repeats=4)
    first = service.execute_task(task_record_id=task["record_id"], score_evidence=evidence).value
    second = service.execute_task(task_record_id=task["record_id"], score_evidence=evidence).value
    assert first["record_id"] != second["record_id"]
    assert first["semantic_key"] == second["semantic_key"]
    assert first["qste:adjustedIntervals"] == second["qste:adjustedIntervals"]
    assert (
        first["qste:rawPairedEvidence"][candidate["record_id"]]["raw_effects"]
        == effects[candidate["record_id"]]
    )
    assessment = service.assess(
        candidate_record_id=candidate["record_id"],
        task_record_id=task["record_id"],
        run_record_id=first["record_id"],
        refinement_graph_record_id=graph["record_id"],
    ).value
    assert assessment["assessment_status"] == "qualified"


def test_negative_task_direction_preserves_raw_and_normalizes_oriented_effects(
    tmp_path: Path,
) -> None:
    fixture, candidate, graph = p6_fixture(tmp_path)
    proper = graph["required_closure"]
    spec = task_spec(3)
    spec["expected_effect_direction"] = -1
    effects = {candidate["record_id"]: -0.7, proper[0]: 0.0, proper[1]: 0.0}
    service, task, run = declare_and_execute(
        fixture.workspace, candidate, graph, effects, spec=spec
    )
    evidence = run["qste:rawPairedEvidence"][candidate["record_id"]]
    assert evidence["raw_effects"] == [-0.7, -0.7, -0.7]
    assert evidence["oriented_effects"] == [0.7, 0.7, 0.7]
    assessment = service.assess(
        candidate_record_id=candidate["record_id"],
        task_record_id=task["record_id"],
        run_record_id=run["record_id"],
        refinement_graph_record_id=graph["record_id"],
    ).value
    assert assessment["assessment_status"] == "qualified"


def test_invalid_spec_fails_without_assessment_and_keeps_durable_receipt(tmp_path: Path) -> None:
    fixture, candidate, graph = p6_fixture(tmp_path)
    invalid = task_spec(3)
    invalid["meaningful_bound"] = 0.1
    invalid["equivalence_region"]["epsilon_plus"] = 0.1
    service = QuantaService(fixture.workspace)
    with pytest.raises(ContractError) as caught:
        service.declare_task(
            candidate_record_id=candidate["record_id"],
            refinement_graph_record_id=graph["record_id"],
            specification=invalid,
        )
    assert caught.value.reason_code == "invalid_assessment_spec"
    store = RecordStore(WorkspacePaths.open(fixture.workspace))
    receipt = store.get_record(caught.value.receipt_id).record
    assert receipt["operation_status"] == "failed"
    assert not any(item.record_type == "DSQAssessment" for item in store.iter_records())


def test_baselines_report_dsq_condition_and_invalidation_preserves_frozen_bytes(
    tmp_path: Path,
) -> None:
    fixture, candidate, graph = p6_fixture(tmp_path)
    effects = {candidate["record_id"]: 0.7} | {
        node_id: 0.0 for node_id in graph["required_closure"]
    }
    service, task, run = declare_and_execute(fixture.workspace, candidate, graph, effects)
    assessment = service.assess(
        candidate_record_id=candidate["record_id"],
        task_record_id=task["record_id"],
        run_record_id=run["record_id"],
        refinement_graph_record_id=graph["record_id"],
    ).value
    store = RecordStore(WorkspacePaths.open(fixture.workspace))
    frozen_digest = store.get_record(assessment["record_id"]).record_digest
    baselines = service.evaluate_baselines(assessment_record_id=assessment["record_id"]).value
    assert baselines["data"]["matching_pursuit"]["satisfies_dsq_condition"] is True
    assert baselines["data"]["perceptual_coding"]["satisfies_dsq_condition"] is True
    service.invalidate_dependency(
        assessment_record_id=assessment["record_id"],
        invalidation_reason="implementation_defect",
        evidence={"issue": "fixture-detected scorer defect"},
    )
    assert store.get_record(assessment["record_id"]).record_digest == frozen_digest
    current = service.current_dependency_validity(assessment["record_id"])
    assert current["stored_dependency_validity"] == "valid"
    assert current["current_dependency_validity"] == "invalidated"
    assert current["latest_reason"] == "implementation_defect"
