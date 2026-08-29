from __future__ import annotations

from pathlib import Path
from typing import Any

from p5_helpers import explicit_candidates
from p6_helpers import declare_and_execute, p6_fixture, task_spec

from qste.quanta import QuantaService


def _assess(
    service: QuantaService,
    candidate: dict[str, Any],
    task: dict[str, Any],
    run: dict[str, Any],
    graph: dict[str, Any] | None,
) -> dict[str, Any]:
    return service.assess(
        candidate_record_id=candidate["record_id"],
        task_record_id=task["record_id"],
        run_record_id=run["record_id"],
        refinement_graph_record_id=graph["record_id"] if graph else None,
    ).value


def test_empty_proper_set_and_unavailable_closure_cannot_qualify(tmp_path: Path) -> None:
    fixture, _, _ = p6_fixture(tmp_path / "base")
    singleton = explicit_candidates(fixture, [[[[0, 2, 4]]][0]])[0]
    service, task, run = declare_and_execute(
        fixture.workspace, singleton, None, {singleton["record_id"]: 0.8}, spec=task_spec(1)
    )
    empty = _assess(service, singleton, task, run, None)
    assert (empty["assessment_status"], empty["reason_code"]) == (
        "indeterminate",
        "empty_proper_set",
    )
    assert empty["qualification_ready"] is False

    fixture, candidate, _ = p6_fixture(tmp_path / "closure")
    service, task, run = declare_and_execute(
        fixture.workspace, candidate, None, {candidate["record_id"]: 0.8}, spec=task_spec(1)
    )
    missing = _assess(service, candidate, task, run, None)
    assert (missing["assessment_status"], missing["reason_code"]) == (
        "indeterminate",
        "closure_unavailable",
    )


def test_uncertainty_budget_calibration_controls_and_missing_evidence_are_distinct(
    tmp_path: Path,
) -> None:
    fixture, candidate, graph = p6_fixture(tmp_path)
    proper = graph["required_closure"]
    full = {candidate["record_id"]: 0.7, proper[0]: 0.0, proper[1]: 0.0}

    unavailable_spec = task_spec(3, uncertainty="unavailable")
    service, task, run = declare_and_execute(
        fixture.workspace,
        candidate,
        graph,
        {candidate["record_id"]: 0.1, proper[0]: 0.3, proper[1]: 0.0},
        spec=unavailable_spec,
        evidence_overrides={"protocol": "deterministic"},
    )
    unadjusted = _assess(service, candidate, task, run, graph)
    assert unadjusted["assessment_status"] == "indeterminate"
    assert unadjusted["reason_code"] == "uncertainty_contract_missing"
    assert unadjusted["negative_evidence_valid"] is False

    service, task, run = declare_and_execute(
        fixture.workspace,
        candidate,
        graph,
        full,
        spec=task_spec(3, maximum_evaluations=6),
    )
    assert _assess(service, candidate, task, run, graph)["reason_code"] == "budget_exhausted"

    service, task, run = declare_and_execute(
        fixture.workspace,
        candidate,
        graph,
        full,
        spec=task_spec(3, required_calibration="spl"),
    )
    assert _assess(service, candidate, task, run, graph)["reason_code"] == (
        "calibration_unavailable"
    )

    service, task, run = declare_and_execute(
        fixture.workspace,
        candidate,
        graph,
        full,
        evidence_overrides={
            "artifact_controls": {
                "resynthesis_only": False,
                "off_target": True,
                "matched_intervention": True,
                "renderer_fidelity": True,
            }
        },
    )
    assert _assess(service, candidate, task, run, graph)["reason_code"] == (
        "artifact_control_failed"
    )

    partial = {candidate["record_id"]: 0.7, proper[0]: 0.0}
    service, task, run = declare_and_execute(fixture.workspace, candidate, graph, partial)
    assert _assess(service, candidate, task, run, graph)["reason_code"] == (
        "required_evidence_unavailable"
    )


def test_invalid_dependency_cannot_support_conclusive_rejection(tmp_path: Path) -> None:
    fixture, candidate, graph = p6_fixture(tmp_path)
    proper = graph["required_closure"]
    service, task, run = declare_and_execute(
        fixture.workspace,
        candidate,
        graph,
        {candidate["record_id"]: 0.1, proper[0]: 0.3, proper[1]: 0.0},
        evidence_overrides={"dependency_validity": "invalidated"},
    )
    assessment = _assess(service, candidate, task, run, graph)
    assert assessment["assessment_status"] == "indeterminate"
    assert assessment["negative_evidence_valid"] is False
    assert assessment["reason_code"] == "required_evidence_unavailable"
