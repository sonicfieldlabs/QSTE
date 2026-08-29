from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from p7_helpers import comparison_evidence, declared_engine, p7_candidates


def _run(
    tmp_path: Path,
    source_count: int,
    target_count: int,
    overrides: dict[str, object],
) -> list[dict[str, Any]]:
    fixture, sources, targets = p7_candidates(
        tmp_path, source_count=source_count, target_count=target_count
    )
    service, comparison, _projections = declared_engine(
        fixture, sources, targets, comparison_overrides=overrides
    )
    footprints = {value["record_id"]: [1.0, 0.0] for value in [*sources, *targets]}
    return cast(
        list[dict[str, Any]],
        service.compare(
            comparison_spec_record_id=comparison["record_id"],
            source_candidate_record_ids=[value["record_id"] for value in sources],
            target_candidate_record_ids=[value["record_id"] for value in targets],
            evidence=comparison_evidence(sources, targets, footprints),
        ).value["items"],
    )


def test_unique_one_to_many_and_many_to_one_components_are_split_and_merge(
    tmp_path: Path,
) -> None:
    split = _run(
        tmp_path / "split",
        1,
        2,
        {
            "capacities": {
                "source_default": 2,
                "target_default": 1,
                "maximum_n": 8,
                "source_overrides": {},
                "target_overrides": {},
            },
            "cardinalities": ["1:1", "1:n"],
        },
    )
    merge = _run(
        tmp_path / "merge",
        2,
        1,
        {
            "capacities": {
                "source_default": 1,
                "target_default": 2,
                "maximum_n": 8,
                "source_overrides": {},
                "target_overrides": {},
            },
            "cardinalities": ["1:1", "n:1"],
        },
    )
    assert [(value["relation_type"], value["reason_code"]) for value in split] == [
        ("split", "matched_split")
    ]
    assert [(value["relation_type"], value["reason_code"]) for value in merge] == [
        ("merge", "matched_merge")
    ]


def test_structural_ambiguity_survives_lexicographic_replay(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        2,
        2,
        {
            "capacities": {
                "source_default": 1,
                "target_default": 1,
                "maximum_n": 8,
                "source_overrides": {},
                "target_overrides": {},
            },
        },
    )
    relation = result[0]
    assert (relation["comparison_status"], relation["reason_code"]) == (
        "indeterminate",
        "structural_matching_ambiguity",
    )
    assert relation["solution_evidence"]["surviving_optimum_count"] == 2
    assert relation["solution_evidence"]["diagnostic_representative"]
    assert relation["solution_evidence"]["solver_independent_verification"] == "passed"


def test_unique_unmatched_is_resolved_null_not_omission(tmp_path: Path) -> None:
    result = _run(tmp_path, 1, 1, {"unmatched_penalty": 0.0})
    assert len(result) == 2
    assert all(value["relation_type"] is None for value in result)
    assert all(value["comparison_status"] == "resolved" for value in result)
    assert all(value["reason_code"] == "unmatched_by_spec" for value in result)


def test_many_to_many_decomposition_and_budget_limits_remain_indeterminate(
    tmp_path: Path,
) -> None:
    decomposition = _run(
        tmp_path / "decomposition",
        2,
        2,
        {
            "capacities": {
                "source_default": 2,
                "target_default": 2,
                "maximum_n": 8,
                "source_overrides": {},
                "target_overrides": {},
            },
            "cardinalities": ["1:1", "1:n", "n:1"],
            "cardinality_preference": "more_edges",
            "ambiguity_rules": {
                "evaluate_before_lexicographic_replay": True,
                "lexicographic_native_address_order": True,
                "many_to_many_decompositions": [[], []],
            },
        },
    )[0]
    budget = _run(
        tmp_path / "budget",
        3,
        3,
        {"budget": {"maximum_edges": 4, "maximum_subsets": 16}},
    )[0]
    assert decomposition["reason_code"] == "decomposition_ambiguity"
    assert decomposition["comparison_status"] == "indeterminate"
    assert budget["reason_code"] == "matching_budget_exhausted"
    assert budget["comparison_status"] == "indeterminate"
