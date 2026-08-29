from __future__ import annotations

from pathlib import Path

from p7_helpers import (
    comparison_evidence,
    comparison_spec,
    declared_engine,
    p7_candidates,
)


def _outcome(
    service: object,
    comparison: dict[str, object],
    sources: list[dict[str, object]],
    targets: list[dict[str, object]],
    evidence: dict[str, object],
) -> tuple[str, str | None, str]:
    value = service.compare(  # type: ignore[attr-defined]
        comparison_spec_record_id=comparison["record_id"],
        source_candidate_record_ids=[str(value["record_id"]) for value in sources],
        target_candidate_record_ids=[str(value["record_id"]) for value in targets],
        evidence=evidence,
    ).value["items"][0]
    return value["comparison_status"], value["relation_type"], value["reason_code"]


def test_conclusive_null_and_boundary_outcomes_are_not_conflated(tmp_path: Path) -> None:
    fixture, sources, targets = p7_candidates(tmp_path)
    service, comparison, projections = declared_engine(fixture, sources, targets)
    source_id = sources[0]["record_id"]
    target_id = targets[0]["record_id"]

    coverage_failed = comparison_evidence(
        sources,
        targets,
        {source_id: [1.0, 0.0], target_id: [0.0, 1.0]},
    )
    effect_failed = comparison_evidence(
        sources,
        targets,
        {source_id: [1.0, 0.0], target_id: [1.0, 0.0]},
        effects={source_id: 1.0, target_id: 0.0},
    )
    zero = comparison_evidence(
        sources,
        targets,
        {source_id: [0.0, 0.0], target_id: [1.0, 0.0]},
    )
    incomplete = comparison_evidence(
        sources,
        targets,
        {source_id: [1.0, 0.0], target_id: [1.0, 0.0]},
        projection_status={source_id: "incomplete"},
    )
    unavailable = comparison_evidence(
        sources,
        targets,
        {source_id: [1.0, 0.0], target_id: [1.0, 0.0]},
        projection_status={source_id: "capability_unavailable"},
    )
    assert _outcome(service, comparison, sources, targets, coverage_failed) == (
        "resolved",
        None,
        "coverage_failed",
    )
    assert _outcome(service, comparison, sources, targets, effect_failed) == (
        "resolved",
        None,
        "effect_incompatible",
    )
    assert _outcome(service, comparison, sources, targets, zero) == (
        "indeterminate",
        None,
        "zero_footprint_undefined",
    )
    assert _outcome(service, comparison, sources, targets, incomplete) == (
        "indeterminate",
        None,
        "eligible_evidence_incomplete",
    )
    assert _outcome(service, comparison, sources, targets, unavailable) == (
        "indeterminate",
        None,
        "comparison_capability_unavailable",
    )

    boundary_spec = comparison_spec(coverage_half_width=0.1)
    boundary_comparison = service.declare_comparison(
        projection_record_ids=[value["record_id"] for value in projections],
        specification=boundary_spec,
    ).value
    coverage_boundary = comparison_evidence(
        sources,
        targets,
        {source_id: [1.0, 0.0], target_id: [0.75, 0.25]},
    )
    assert _outcome(service, boundary_comparison, sources, targets, coverage_boundary) == (
        "indeterminate",
        None,
        "coverage_boundary_crossing",
    )

    effect_boundary = comparison_evidence(
        sources,
        targets,
        {source_id: [1.0, 0.0], target_id: [1.0, 0.0]},
        effects={source_id: (0.1, 0.3, 0.2), target_id: (0.0, 0.0, 0.0)},
    )
    assert _outcome(service, comparison, sources, targets, effect_boundary) == (
        "indeterminate",
        None,
        "effect_boundary_crossing",
    )


def test_missing_pair_evidence_remains_indeterminate(tmp_path: Path) -> None:
    fixture, sources, targets = p7_candidates(tmp_path)
    service, comparison, _projections = declared_engine(fixture, sources, targets)
    source_id = sources[0]["record_id"]
    target_id = targets[0]["record_id"]
    evidence = comparison_evidence(
        sources,
        targets,
        {source_id: [1.0, 0.0], target_id: [1.0, 0.0]},
    )
    evidence["pairs"] = {}
    assert _outcome(service, comparison, sources, targets, evidence) == (
        "indeterminate",
        None,
        "eligible_evidence_incomplete",
    )
