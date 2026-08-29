"""Semantic invariants for P7 cross-arm projection and relation records."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, cast

from qste.core.contracts import ContractError

PROJECTION_PROFILE = "qste-cross-arm-projection/v0.1"
COMPARISON_PROFILE = "qste-cross-arm-comparison/v0.1"
RELATION_PROFILE = "qste-cross-arm-relation/v0.1"


def validate_p7_semantics(record: Mapping[str, Any]) -> None:
    """Reject P7 records that collapse contracts, statuses, or matching evidence."""

    if record.get("qste:projectionProfile") == PROJECTION_PROFILE:
        _validate_projection(record)
    if record.get("qste:comparisonProfile") == COMPARISON_PROFILE:
        _validate_comparison(record)
    if record.get("qste:relationProfile") == RELATION_PROFILE:
        _validate_relation(record)


def _validate_projection(record: Mapping[str, Any]) -> None:
    _require_type(record, "ProjectionSpec")
    method = _object(record.get("footprint_method"), "footprint method")
    kind = method.get("kind")
    expected = "unit_integral" if kind == "expected_energy_change" else "none"
    if (
        kind not in {"expected_energy_change", "exceedance_probability"}
        or method.get("normalization") != expected
    ):
        raise ContractError("conformance_failed", "P7 footprint kind/normalization conflict")
    calibration = _object(record.get("calibration"), "calibration")
    if calibration.get("status") != "calibrated" or not calibration.get("evidence"):
        raise ContractError("conformance_failed", "P7 projection is not calibrated")
    _object(record.get("comparison_substrate"), "comparison substrate")
    _object(record.get("measure"), "measure")
    _object(record.get("qste:alignment"), "alignment")
    _object(record.get("qste:uncertaintyPropagation"), "uncertainty")
    _object(record.get("qste:effectContract"), "effect contract")


def _validate_comparison(record: Mapping[str, Any]) -> None:
    _require_type(record, "ComparisonSpec")
    projections = record.get("projection_refs")
    if not isinstance(projections, list) or len(projections) != 2:
        raise ContractError("conformance_failed", "P7 comparison requires two projections")
    threshold = record.get("coverage_threshold")
    if not _finite(threshold) or not 0 <= cast(float, threshold) <= 1:
        raise ContractError("conformance_failed", "P7 coverage threshold is invalid")
    if not _finite_nonnegative(record.get("effect_tolerance")) or not _finite_nonnegative(
        record.get("unmatched_penalty")
    ):
        raise ContractError("conformance_failed", "P7 tolerances must be finite")
    preference = record.get("cardinality_preference")
    if preference not in [["fewer_edges"], ["more_edges"]]:
        raise ContractError("conformance_failed", "P7 cardinality preference is not singular")
    if record.get("primary_objective") != "minimum_cost_b_matching":
        raise ContractError("conformance_failed", "P7 matching objective is not canonical")
    ambiguity = _object(record.get("ambiguity_rules"), "ambiguity rules")
    if ambiguity.get("evaluate_before_lexicographic_replay") is not True:
        raise ContractError("conformance_failed", "P7 ambiguity must precede replay selection")
    solver = _object(record.get("qste:solver"), "solver")
    if solver.get("id") != "qste-bounded-exact-b-matching/v0.1":
        raise ContractError("conformance_failed", "P7 solver profile is not the exact reference")
    _object(record.get("qste:effectComparison"), "effect comparison")
    _object(record.get("qste:coverageUncertainty"), "coverage uncertainty")


def _validate_relation(record: Mapping[str, Any]) -> None:
    _require_type(record, "RelationAssertion")
    status = record.get("comparison_status")
    relation = record.get("relation_type")
    reason = record.get("reason_code")
    relation_reasons = {
        "overlap": "matched_overlap",
        "split": "matched_split",
        "merge": "matched_merge",
        "omission": "target_address_absent",
        "loss": "fidelity_failed",
        "incomparable": "projection_invalid",
    }
    resolved_null = {"coverage_failed", "effect_incompatible", "unmatched_by_spec"}
    indeterminate = {
        "zero_footprint_undefined",
        "coverage_boundary_crossing",
        "effect_boundary_crossing",
        "structural_matching_ambiguity",
        "decomposition_ambiguity",
        "eligible_evidence_incomplete",
        "matching_budget_exhausted",
        "comparison_capability_unavailable",
    }
    if status == "resolved" and relation is not None:
        if relation_reasons.get(cast(str, relation)) != reason:
            raise ContractError("conformance_failed", "P7 relation/reason conflict")
    elif status == "resolved" and reason not in resolved_null:
        raise ContractError("conformance_failed", "P7 resolved null reason is invalid")
    elif status == "indeterminate" and (relation is not None or reason not in indeterminate):
        raise ContractError("conformance_failed", "P7 indeterminate relation is inconsistent")
    if record.get("qste:nativeIdentityPreserved") is not True:
        raise ContractError("conformance_failed", "P7 relation overwrites native identity")
    matching = _object(record.get("matching_contract"), "matching contract")
    if matching.get("unmatched_indicator_equivalence") != "both_directions_encoded":
        raise ContractError("conformance_failed", "P7 unmatched indicators are incomplete")
    solution = _object(record.get("solution_evidence"), "solution evidence")
    if solution.get("lexicographic_replay_is_diagnostic_only") is not True:
        raise ContractError("conformance_failed", "lexicographic replay changed evidence status")
    if (
        solution.get("primary_optimum") is not None
        and solution.get("solver_independent_verification") != "passed"
    ):
        raise ContractError(
            "conformance_failed", "P7 exact-match certificate was not independently verified"
        )
    coverage = _object(record.get("coverage"), "coverage")
    pairs = coverage.get("pairs")
    if not isinstance(pairs, list):
        raise ContractError("conformance_failed", "P7 coverage pairs are absent")
    footprint = _object(record.get("footprint_contract"), "footprint contract")
    source_contract = _object(footprint.get("source"), "source footprint")
    if source_contract.get("kind") == "expected_energy_change":
        for pair in pairs:
            if not isinstance(pair, Mapping):
                raise ContractError("conformance_failed", "P7 coverage pair is invalid")
            left = _object(pair.get("source_to_target"), "source coverage")
            right = _object(pair.get("target_to_source"), "target coverage")
            left_point = left.get("point_estimate")
            right_point = right.get("point_estimate")
            if not _finite(left_point) or not _finite(right_point):
                raise ContractError("conformance_failed", "P7 coverage point is not finite")
            if not math.isclose(
                cast(float, left_point),
                cast(float, right_point),
                rel_tol=0,
                abs_tol=1e-12,
            ):
                raise ContractError(
                    "conformance_failed", "unit-integral energy coverage must be symmetric"
                )


def _require_type(record: Mapping[str, Any], expected: str) -> None:
    if record.get("record_type") != expected:
        raise ContractError("conformance_failed", f"P7 profile requires {expected}")


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ContractError("conformance_failed", f"{name} must be a nonempty object")
    return value


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _finite_nonnegative(value: Any) -> bool:
    return _finite(value) and cast(float, value) >= 0
