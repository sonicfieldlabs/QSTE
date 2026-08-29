"""Semantic invariants for P6 paired tasks and DSQ assessments."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, cast

from qste.core.contracts import ContractError

TASK_PROFILE = "qste-paired-score-task/v0.1"
TASK_RUN_PROFILE = "qste-paired-score-run/v0.1"
ASSESSMENT_PROFILE = "qste-dsq-assessment/v0.1"


def validate_p6_semantics(record: Mapping[str, Any]) -> None:
    """Reject P6 records that substitute readiness, evidence, or verdict fields."""

    if record.get("qste:taskProfile") == TASK_PROFILE:
        _validate_task(record)
    if record.get("qste:taskRunProfile") == TASK_RUN_PROFILE:
        _validate_run(record)
    if record.get("qste:assessmentProfile") == ASSESSMENT_PROFILE:
        _validate_assessment(record)
    if record.get("qste:p6AvailabilityGraph") is True:
        _validate_availability_graph(record)


def _validate_task(record: Mapping[str, Any]) -> None:
    _require_type(record, "TaskSpec")
    family = record.get("eligible_family")
    if not isinstance(family, list) or not family or len(family) != len(set(family)):
        raise ContractError("conformance_failed", "P6 eligible family must be nonempty and unique")
    multiplicity = _object(record.get("multiplicity"), "multiplicity")
    if multiplicity.get("family_size") != len(family):
        raise ContractError("conformance_failed", "multiplicity family size is not exact")
    evidence = _object(record.get("bound_validity_evidence"), "bound validity")
    if evidence.get("bound_valid") is not True:
        raise ContractError("conformance_failed", "P6 TaskSpec must record BoundValid")
    boundary = _object(record.get("boundary_semantics"), "boundary semantics")
    if boundary != {
        "qualification": "inclusive",
        "equivalence": "inclusive",
        "rejection": "strict",
    }:
        raise ContractError("conformance_failed", "P6 boundary semantics are inconsistent")


def _validate_run(record: Mapping[str, Any]) -> None:
    _require_type(record, "RunManifest")
    if record.get("qste:protocol") not in {"deterministic", "stochastic"}:
        raise ContractError("conformance_failed", "P6 score protocol is not pinned")
    intervals = record.get("qste:adjustedIntervals")
    evidence = record.get("qste:rawPairedEvidence")
    if not isinstance(intervals, list) or not isinstance(evidence, Mapping):
        raise ContractError("conformance_failed", "P6 score evidence is incomplete")
    for interval in intervals:
        if not isinstance(interval, Mapping) or not isinstance(interval.get("unit_record_id"), str):
            raise ContractError("conformance_failed", "P6 interval has no native unit identity")
        if interval.get("availability") == "known" and not _finite_interval(interval):
            raise ContractError("conformance_failed", "P6 adjusted interval is invalid")
    controls = _object(record.get("qste:artifactControlResults"), "artifact controls")
    required = {
        "resynthesis_only",
        "off_target",
        "matched_intervention",
        "renderer_fidelity",
        "alternate_intervention",
        "passed",
    }
    if set(controls) != required:
        raise ContractError("conformance_failed", "P6 control result set is incomplete")


def _validate_assessment(record: Mapping[str, Any]) -> None:
    _require_type(record, "DSQAssessment")
    status = record.get("assessment_status")
    reason = record.get("reason_code")
    label = record.get("qste:dsqLabelEligible")
    if label is not (status == "qualified"):
        raise ContractError("conformance_failed", "DSQ label eligibility disagrees with verdict")
    candidate = _object(record.get("candidate_interval"), "candidate interval")
    region = _object(record.get("equivalence_region"), "equivalence region")
    theta = record.get("meaningful_bound")
    if not _finite(theta):
        raise ContractError("conformance_failed", "assessment meaningful bound is not finite")
    lower_zero = -cast(float, region.get("epsilon_minus"))
    upper_zero = cast(float, region.get("epsilon_plus"))
    proper: list[Mapping[str, Any]] = [
        cast(Mapping[str, Any], item["interval"])
        for item in cast(list[Any], record.get("proper_node_intervals", []))
        if isinstance(item, Mapping) and isinstance(item.get("interval"), Mapping)
    ]
    if status == "qualified":
        if reason != "meaningful_closed_equivalent" or not _finite_interval(candidate):
            raise ContractError("conformance_failed", "qualified P6 assessment lacks evidence")
        if cast(float, candidate["lower"]) < cast(float, theta):
            raise ContractError("conformance_failed", "qualified candidate is not meaningful")
        if not proper or not all(
            _finite_interval(interval)
            and cast(float, interval["lower"]) >= lower_zero
            and cast(float, interval["upper"]) <= upper_zero
            for interval in proper
        ):
            raise ContractError("conformance_failed", "qualified proper nodes are not equivalent")
    elif status == "rejected":
        if record.get("negative_evidence_valid") is not True:
            raise ContractError("conformance_failed", "rejected assessment lacks valid evidence")
        candidate_negative = bool(
            reason == "candidate_nonmeaningful"
            and _finite_interval(candidate)
            and cast(float, candidate["upper"]) < cast(float, theta)
        )
        proper_negative = bool(
            reason == "proper_node_nonequivalent"
            and any(
                _finite_interval(interval)
                and (
                    cast(float, interval["upper"]) < lower_zero
                    or cast(float, interval["lower"]) > upper_zero
                )
                for interval in proper
            )
        )
        if not candidate_negative and not proper_negative:
            raise ContractError("conformance_failed", "rejection predicate is not satisfied")
    elif status == "indeterminate":
        if reason in {
            "meaningful_closed_equivalent",
            "candidate_nonmeaningful",
            "proper_node_nonequivalent",
        }:
            raise ContractError(
                "conformance_failed", "indeterminate assessment has decisive reason"
            )


def _validate_availability_graph(record: Mapping[str, Any]) -> None:
    _require_type(record, "RefinementGraph")
    certificate = _object(record.get("completion_certificate"), "completion certificate")
    if (
        record.get("closed") is not False
        or certificate.get("complete") is not False
        or certificate.get("nonempty") is not False
    ):
        raise ContractError("conformance_failed", "availability graph cannot certify closure")


def _require_type(record: Mapping[str, Any], expected: str) -> None:
    if record.get("record_type") != expected:
        raise ContractError("conformance_failed", f"P6 profile requires {expected}")


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ContractError("conformance_failed", f"{name} must be a nonempty object")
    return value


def _finite_interval(value: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and value.get("availability") == "known"
        and _finite(value.get("lower"))
        and _finite(value.get("upper"))
        and cast(float, value["lower"]) <= cast(float, value["upper"])
    )


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
