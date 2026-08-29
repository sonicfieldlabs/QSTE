from __future__ import annotations

from pathlib import Path

from p6_helpers import declare_and_execute, p6_fixture

from qste.storage import RecordStore, WorkspacePaths


def test_closed_meaningful_candidate_with_all_equivalent_nodes_qualifies(tmp_path: Path) -> None:
    fixture, candidate, graph = p6_fixture(tmp_path)
    effects = {candidate["record_id"]: 0.7} | {
        node_id: 0.0 for node_id in graph["required_closure"]
    }
    service, task, run = declare_and_execute(fixture.workspace, candidate, graph, effects)
    first = service.assess(
        candidate_record_id=candidate["record_id"],
        task_record_id=task["record_id"],
        run_record_id=run["record_id"],
        refinement_graph_record_id=graph["record_id"],
    ).value
    second = service.assess(
        candidate_record_id=candidate["record_id"],
        task_record_id=task["record_id"],
        run_record_id=run["record_id"],
        refinement_graph_record_id=graph["record_id"],
    ).value
    assert first["assessment_status"] == "qualified"
    assert first["reason_code"] == "meaningful_closed_equivalent"
    assert first["qualification_ready"] is True
    assert first["qste:dsqLabelEligible"] is True
    assert first["interaction_annotations"][0]["synergy_detected"] is True
    assert first["interaction_annotations"][0]["indivisibility_inference_prohibited"] is True
    assert first["record_id"] != second["record_id"]
    assert first["semantic_key"] == second["semantic_key"]


def test_valid_decisive_candidate_and_proper_node_negatives_reject(tmp_path: Path) -> None:
    fixture, candidate, graph = p6_fixture(tmp_path)
    proper = graph["required_closure"]
    service, task, run = declare_and_execute(
        fixture.workspace,
        candidate,
        graph,
        {candidate["record_id"]: 0.2, proper[0]: 0.0, proper[1]: 0.0},
    )
    rejected = service.assess(
        candidate_record_id=candidate["record_id"],
        task_record_id=task["record_id"],
        run_record_id=run["record_id"],
        refinement_graph_record_id=graph["record_id"],
    ).value
    assert (rejected["assessment_status"], rejected["reason_code"]) == (
        "rejected",
        "candidate_nonmeaningful",
    )

    service, task, run = declare_and_execute(
        fixture.workspace,
        candidate,
        graph,
        {candidate["record_id"]: 0.7, proper[0]: 0.3, proper[1]: 0.0},
    )
    rejected = service.assess(
        candidate_record_id=candidate["record_id"],
        task_record_id=task["record_id"],
        run_record_id=run["record_id"],
        refinement_graph_record_id=graph["record_id"],
    ).value
    assert (rejected["assessment_status"], rejected["reason_code"]) == (
        "rejected",
        "proper_node_nonequivalent",
    )
    assert rejected["negative_evidence_valid"] is True
    assert rejected["interaction_annotations"][0]["proper_node_point_estimates"]


def test_boundary_crossing_is_not_equivalence_or_rejection(tmp_path: Path) -> None:
    fixture, candidate, graph = p6_fixture(tmp_path)
    proper = graph["required_closure"]
    service, task, run = declare_and_execute(
        fixture.workspace,
        candidate,
        graph,
        {candidate["record_id"]: 0.5, proper[0]: 0.0, proper[1]: 0.0},
    )
    assessment = service.assess(
        candidate_record_id=candidate["record_id"],
        task_record_id=task["record_id"],
        run_record_id=run["record_id"],
        refinement_graph_record_id=graph["record_id"],
    ).value
    assert assessment["assessment_status"] == "indeterminate"
    assert assessment["reason_code"] == "candidate_boundary_crossing"

    service, task, run = declare_and_execute(
        fixture.workspace,
        candidate,
        graph,
        {candidate["record_id"]: 0.7, proper[0]: 0.1, proper[1]: 0.0},
    )
    assessment = service.assess(
        candidate_record_id=candidate["record_id"],
        task_record_id=task["record_id"],
        run_record_id=run["record_id"],
        refinement_graph_record_id=graph["record_id"],
    ).value
    assert assessment["assessment_status"] == "indeterminate"
    assert assessment["reason_code"] == "proper_node_boundary_crossing"


def test_assessment_and_candidate_remain_distinct_records(tmp_path: Path) -> None:
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
    stored_candidate = store.get_record(candidate["record_id"]).record
    assert stored_candidate["qste:dsqStatus"] == "candidate_only"
    assert assessment["record_type"] == "DSQAssessment"
    assert assessment["candidate_semantic_key"] == candidate["semantic_key"]
    assert assessment["semantic_key"] != candidate["semantic_key"]
