"""P6 paired-task execution and ontology-faithful DSQ assessment."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from statistics import NormalDist, fmean, stdev
from typing import Any, NoReturn, cast

from qste.core import canonical_json_bytes, content_digest
from qste.core.contracts import BASE_URI, ContractError
from qste.core.identity import utc_timestamp
from qste.ingress.records import bind_semantic_key, operation_receipt, record_base, record_ref
from qste.quanta.models import QuantaOperationOutcome
from qste.storage import RecordStore, WorkspacePaths

TASK_PROFILE = "qste-paired-score-task/v0.1"
TASK_RUN_PROFILE = "qste-paired-score-run/v0.1"
ASSESSMENT_PROFILE = "qste-dsq-assessment/v0.1"
BASELINE_PROFILE = "qste-dsq-baselines/v0.1"
MAX_FAMILY_SIZE = 4096
MAX_REPEATS = 10_000
MAX_EVALUATIONS = 100_000
CONTROL_NAMES = (
    "resynthesis_only",
    "off_target",
    "matched_intervention",
    "renderer_fidelity",
)
ASSESSMENT_REASONS = (
    "meaningful_closed_equivalent",
    "candidate_nonmeaningful",
    "proper_node_nonequivalent",
    "candidate_boundary_crossing",
    "proper_node_boundary_crossing",
    "closure_unavailable",
    "empty_proper_set",
    "uncertainty_contract_missing",
    "budget_exhausted",
    "calibration_unavailable",
    "artifact_control_failed",
    "required_evidence_unavailable",
)
INVALIDATION_REASONS = frozenset(
    {
        "source_integrity_defect",
        "acquisition_or_calibration_defect",
        "representation_defect",
        "intervention_defect",
        "task_or_estimator_defect",
        "uncertainty_or_multiplicity_defect",
        "implementation_defect",
        "upstream_dependency_invalidated",
    }
)


class QuantaService:
    """Execute bounded paired-score tasks and persist immutable assessments."""

    def __init__(self, workspace: Any) -> None:
        self.store = RecordStore(WorkspacePaths.open(workspace))

    def declare_task(
        self,
        *,
        candidate_record_id: str,
        refinement_graph_record_id: str | None,
        specification: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> QuantaOperationOutcome:
        """Freeze one complete task, bound, selection, and multiplicity contract."""

        candidate = self._record(candidate_record_id, "CandidateUnit")
        self._authorize(authorization_status, "declare_task", candidate, specification)
        instance = self._record(
            cast(str, candidate["representation_instance_ref"]["record_id"]),
            "RepresentationInstance",
        )
        family = self._record(
            cast(str, instance["qste:familyRef"]["record_id"]), "RepresentationFamilySpec"
        )
        intervention = self._record(
            cast(str, instance["qste:defaultInterventionRef"]["record_id"]), "InterventionSpec"
        )
        aperture = self._record(
            cast(str, instance["instance_context"]["aperture_ref"]["record_id"]),
            "ApertureSpec",
        )
        source = self._record(
            cast(str, instance["source_artifact_ref"]["record_id"]), "ArtifactRecord"
        )
        graph: dict[str, Any] | None = None
        closure_ids: list[str] = []
        if refinement_graph_record_id is not None:
            graph = self._record(refinement_graph_record_id, "RefinementGraph")
            if graph["root_candidate_ref"]["record_id"] != candidate_record_id:
                self._invalid_task(candidate, specification, "refinement graph root mismatch")
            closure_ids = _proper_ids(graph)
        family_ids = [candidate_record_id, *closure_ids]
        if len(family_ids) > MAX_FAMILY_SIZE:
            self._invalid_task(candidate, specification, "eligible family exceeds P6 bound")
        try:
            _validate_task_input(specification, len(family_ids))
        except ContractError as caught:
            caught.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                "declare_task", candidate, specification, caught, authorization_status
            )
            raise

        timestamp = utc_timestamp()
        task = record_base(
            "TaskSpec",
            created_at=timestamp,
            references=[
                record_ref(candidate_record_id, "CandidateUnit"),
                record_ref(instance["record_id"], "RepresentationInstance"),
                record_ref(family["record_id"], "RepresentationFamilySpec"),
                record_ref(intervention["record_id"], "InterventionSpec"),
                record_ref(aperture["record_id"], "ApertureSpec"),
                *([record_ref(graph["record_id"], "RefinementGraph")] if graph is not None else []),
            ],
        ) | {
            "task_id": specification["task_id"],
            "task_version": specification["task_version"],
            "response_variable": specification["response_variable"],
            "input_refs": [record_ref(source["record_id"], "ArtifactRecord")],
            "fixed_context": dict(cast(Mapping[str, Any], specification["fixed_context"])),
            "contrast_ref": record_ref(candidate_record_id, "CandidateUnit"),
            "intervention_ref": record_ref(intervention["record_id"], "InterventionSpec"),
            "expected_effect_direction": specification["expected_effect_direction"],
            "response_units": specification["response_units"],
            "meaningful_bound": specification["meaningful_bound"],
            "equivalence_region": dict(
                cast(Mapping[str, Any], specification["equivalence_region"])
            ),
            "bound_validity_evidence": {
                "bound_valid": True,
                "predicate": "0 <= epsilon_plus < meaningful_bound and 0 <= epsilon_minus",
                "common_units": specification["response_units"],
            },
            "boundary_semantics": dict(
                cast(Mapping[str, Any], specification["boundary_semantics"])
            ),
            "estimator": dict(cast(Mapping[str, Any], specification["estimator"])),
            "repeats": specification["repeats"],
            "seeds": list(cast(Sequence[int], specification["seeds"])),
            "uncertainty": dict(cast(Mapping[str, Any], specification["uncertainty"])),
            "multiplicity": dict(cast(Mapping[str, Any], specification["multiplicity"])),
            "stopping_rules": dict(cast(Mapping[str, Any], specification["stopping_rules"])),
            "selection_confirmation": dict(
                cast(Mapping[str, Any], specification["selection_confirmation"])
            ),
            "eligible_family": family_ids,
            "artifact_controls": list(cast(Sequence[Any], specification["artifact_controls"])),
            "alternate_intervention": dict(
                cast(Mapping[str, Any], specification["alternate_intervention"])
            ),
            "compute_budget": dict(cast(Mapping[str, Any], specification["compute_budget"])),
            "success_criterion": dict(cast(Mapping[str, Any], specification["success_criterion"])),
            "failure_reasons": list(ASSESSMENT_REASONS),
            "qste:taskProfile": TASK_PROFILE,
            "qste:candidateRef": record_ref(candidate_record_id, "CandidateUnit"),
            "qste:representationInstanceRef": record_ref(
                instance["record_id"], "RepresentationInstance"
            ),
            "qste:representationFamilyRef": record_ref(
                family["record_id"], "RepresentationFamilySpec"
            ),
            "qste:apertureRef": record_ref(aperture["record_id"], "ApertureSpec"),
            "qste:refinementGraphRef": (
                record_ref(graph["record_id"], "RefinementGraph")
                if graph is not None
                else {"availability": "unavailable"}
            ),
            "qste:requiredCalibration": specification.get(
                "required_calibration", "digital_sample_domain"
            ),
        }
        bind_semantic_key(
            task,
            "qste-semantic-key/task-spec-paired-score-v1",
            {
                "candidate_semantic_key": candidate["semantic_key"],
                "representation_instance_semantic_key": instance["semantic_key"],
                "family_semantic_key": family["semantic_key"],
                "intervention_semantic_key": intervention["semantic_key"],
                "aperture_semantic_key": aperture["semantic_key"],
                "refinement_graph_semantic_key": graph.get("semantic_key") if graph else None,
                "task_contract": {
                    key: task[key]
                    for key in (
                        "task_id",
                        "task_version",
                        "response_variable",
                        "fixed_context",
                        "expected_effect_direction",
                        "response_units",
                        "meaningful_bound",
                        "equivalence_region",
                        "boundary_semantics",
                        "estimator",
                        "repeats",
                        "seeds",
                        "uncertainty",
                        "multiplicity",
                        "stopping_rules",
                        "selection_confirmation",
                        "eligible_family",
                        "artifact_controls",
                        "alternate_intervention",
                        "compute_budget",
                    )
                },
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(candidate_record_id, "CandidateUnit"),
            authorization_status=authorization_status,
            operation="declare_task",
            inputs=[record_ref(candidate_record_id, "CandidateUnit")],
            parameters={"task_id": task["task_id"], "task_version": task["task_version"]},
            outputs=[record_ref(task["record_id"], "TaskSpec", "produced_by")],
            tool_id="qste-p6-task-engine",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [task, receipt],
            domain_event_record_id=None,
            event_type="qste:task-declared/0.1",
            subject_record_id=task["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"profile": TASK_PROFILE, "eligible_family_size": len(family_ids)},
            created_at=timestamp,
        )
        return QuantaOperationOutcome(
            task, f"{BASE_URI}/records/task-spec.schema.json", receipt, event.event_sequence
        )

    def execute_task(
        self,
        *,
        task_record_id: str,
        score_evidence: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> QuantaOperationOutcome:
        """Execute the frozen deterministic or seeded stochastic paired-score protocol."""

        task = self._record(task_record_id, "TaskSpec")
        self._authorize(authorization_status, "execute_task", task, score_evidence)
        if task.get("qste:taskProfile") != TASK_PROFILE:
            self._invalid_task(task, score_evidence, "task profile is not executable in P6")
        evidence_units = score_evidence.get("units")
        if not isinstance(evidence_units, Mapping):
            self._invalid_task(task, score_evidence, "score evidence units must be an object")
        protocol = score_evidence.get("protocol")
        uncertainty = cast(Mapping[str, Any], task["uncertainty"])
        expected_protocol = (
            "deterministic"
            if uncertainty.get("method") == "deterministic_tolerance"
            else "stochastic"
        )
        if uncertainty.get("method") == "unavailable":
            expected_protocol = cast(str, protocol)
        if protocol not in {"deterministic", "stochastic"} or protocol != expected_protocol:
            self._invalid_task(task, score_evidence, "score protocol conflicts with TaskSpec")
        if protocol == "stochastic" and score_evidence.get("seeds") != task["seeds"]:
            self._invalid_task(
                task, score_evidence, "stochastic evidence seeds do not match TaskSpec"
            )
        controls = score_evidence.get("artifact_controls")
        if not isinstance(controls, Mapping) or set(controls) != set(CONTROL_NAMES):
            self._invalid_task(task, score_evidence, "artifact-control result set is incomplete")
        if not all(isinstance(controls[name], bool) for name in CONTROL_NAMES):
            self._invalid_task(task, score_evidence, "artifact-control results must be boolean")
        alternate = score_evidence.get("alternate_intervention_passed")
        if not isinstance(alternate, bool):
            self._invalid_task(task, score_evidence, "alternate intervention result is required")
        dependency = score_evidence.get("dependency_validity", "valid")
        if dependency not in {"valid", "invalidated"}:
            self._invalid_task(task, score_evidence, "dependency validity is invalid")

        repeats = cast(int, task["repeats"])
        eligible = cast(list[str], task["eligible_family"])
        supplied = set(evidence_units)
        if not supplied.issubset(set(eligible)):
            self._invalid_task(task, score_evidence, "score evidence contains an ineligible unit")
        maximum = cast(int, task["compute_budget"]["maximum_evaluations"])
        used = 0
        intervals: list[dict[str, Any]] = []
        raw_by_unit: dict[str, dict[str, Any]] = {}
        budget_exhausted = False
        for unit_id in eligible:
            unit = evidence_units.get(unit_id)
            if unit is None:
                continue
            try:
                reference, intervened = _paired_scores(unit, repeats)
            except ContractError as caught:
                caught.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                    "execute_task", task, score_evidence, caught, authorization_status
                )
                raise
            cost = len(reference) * 2
            if used + cost > maximum:
                budget_exhausted = True
                continue
            used += cost
            raw = [left - right for left, right in zip(reference, intervened, strict=True)]
            oriented = [cast(int, task["expected_effect_direction"]) * value for value in raw]
            interval = _interval(task, oriented)
            interval["unit_record_id"] = unit_id
            intervals.append(interval)
            raw_by_unit[unit_id] = {
                "reference_scores": reference,
                "intervened_scores": intervened,
                "raw_effects": raw,
                "oriented_effects": oriented,
            }
        missing = [unit_id for unit_id in eligible if unit_id not in raw_by_unit]
        if used >= maximum and missing:
            budget_exhausted = True
        aperture = self._record(cast(str, task["qste:apertureRef"]["record_id"]), "ApertureSpec")
        required_calibration = cast(str, task["qste:requiredCalibration"])
        calibration = cast(Mapping[str, Any], aperture["qste:calibrationCapabilities"]).get(
            required_calibration, {"status": "unavailable", "reason": "unknown_claim"}
        )
        calibration_available = (
            isinstance(calibration, Mapping) and calibration.get("status") == "available"
        )
        timestamp = utc_timestamp()
        candidate_id = cast(str, task["qste:candidateRef"]["record_id"])
        self._record(candidate_id, "CandidateUnit")
        instance = self._record(
            cast(str, task["qste:representationInstanceRef"]["record_id"]),
            "RepresentationInstance",
        )
        apparatus = self._record(cast(str, aperture["apparatus_ref"]["record_id"]), "ApparatusSpec")
        source_id = cast(str, instance["source_artifact_ref"]["record_id"])
        run = record_base(
            "RunManifest",
            created_at=timestamp,
            references=[
                record_ref(task_record_id, "TaskSpec"),
                record_ref(candidate_id, "CandidateUnit"),
            ],
        ) | {
            "apparatus_ref": record_ref(apparatus["record_id"], "ApparatusSpec"),
            "aperture_ref": record_ref(aperture["record_id"], "ApertureSpec"),
            "corpus_refs": [record_ref(source_id, "ArtifactRecord")],
            "spec_refs": [record_ref(task_record_id, "TaskSpec")],
            "budgets": {
                "maximum_evaluations": maximum,
                "used_evaluations": used,
                "termination": "budget_exhausted" if budget_exhausted else "completed",
            },
            "seeds": list(cast(list[int], task["seeds"])),
            "event_refs": [record_ref(candidate_id, "CandidateUnit")],
            "artifact_refs": [record_ref(source_id, "ArtifactRecord")],
            "output_refs": [record_ref(candidate_id, "CandidateUnit")],
            "frozen_versions": {
                "contract": "qste-contract/0.3.0",
                "task_profile": TASK_PROFILE,
                "run_profile": TASK_RUN_PROFILE,
                "estimator": task["estimator"],
                "uncertainty": task["uncertainty"],
                "multiplicity": task["multiplicity"],
            },
            "qste:taskRunProfile": TASK_RUN_PROFILE,
            "qste:taskRef": record_ref(task_record_id, "TaskSpec"),
            "qste:candidateRef": record_ref(candidate_id, "CandidateUnit"),
            "qste:protocol": protocol,
            "qste:rawPairedEvidence": raw_by_unit,
            "qste:adjustedIntervals": intervals,
            "qste:missingEligibleUnits": missing,
            "qste:artifactControlResults": {
                **dict(controls),
                "alternate_intervention": alternate,
                "passed": all(cast(bool, controls[name]) for name in CONTROL_NAMES) and alternate,
            },
            "qste:dependencyValidity": dependency,
            "qste:calibrationEvidence": {
                "claim": required_calibration,
                "available": calibration_available,
                "detail": dict(calibration) if isinstance(calibration, Mapping) else {},
            },
            "qste:selectionEvidence": dict(task["selection_confirmation"]),
            "qste:multiplicityEvidence": {
                "method": task["multiplicity"]["method"],
                "family_size": len(eligible),
                "eligible_family_complete": True,
                "intervals_adjusted_for_full_family": uncertainty.get("method") != "unavailable",
            },
        }
        bind_semantic_key(
            run,
            "qste-semantic-key/paired-score-run-v1",
            {
                "task_semantic_key": task["semantic_key"],
                "evidence_digest": content_digest(canonical_json_bytes(score_evidence)),
                "termination": run["budgets"]["termination"],
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(task_record_id, "TaskSpec"),
            authorization_status=authorization_status,
            operation="execute_task",
            inputs=[record_ref(task_record_id, "TaskSpec")],
            parameters={"protocol": protocol, "maximum_evaluations": maximum},
            outputs=[record_ref(run["record_id"], "RunManifest", "produced_by")],
            tool_id="qste-p6-task-engine",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [run, receipt],
            domain_event_record_id=None,
            event_type="qste:task-executed/0.1",
            subject_record_id=run["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={
                "profile": TASK_RUN_PROFILE,
                "protocol": protocol,
                "evaluated_units": len(raw_by_unit),
                "missing_units": len(missing),
                "termination": run["budgets"]["termination"],
            },
            created_at=timestamp,
        )
        return QuantaOperationOutcome(
            run, f"{BASE_URI}/records/run-manifest.schema.json", receipt, event.event_sequence
        )

    def assess(
        self,
        *,
        candidate_record_id: str,
        task_record_id: str,
        run_record_id: str,
        refinement_graph_record_id: str | None,
        authorization_status: str = "permitted",
    ) -> QuantaOperationOutcome:
        """Apply the ontology's ordered rejection, qualification, and indeterminate rules."""

        candidate = self._record(candidate_record_id, "CandidateUnit")
        self._authorize(
            authorization_status,
            "assess",
            candidate,
            {"task_record_id": task_record_id, "run_record_id": run_record_id},
        )
        task = self._record(task_record_id, "TaskSpec")
        run = self._record(run_record_id, "RunManifest")
        try:
            self._validate_assessment_links(candidate, task, run)
        except ContractError as caught:
            caught.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                "assess",
                candidate,
                {"task_record_id": task_record_id},
                caught,
                authorization_status,
            )
            raise

        availability_graph: dict[str, Any] | None = None
        if refinement_graph_record_id is None:
            empty = bool(candidate["qste:pTerminal"]["is_terminal"])
            availability_graph = self._availability_graph(candidate, task, empty=empty)
            graph = availability_graph
        else:
            graph = self._record(refinement_graph_record_id, "RefinementGraph")
            if graph["root_candidate_ref"]["record_id"] != candidate_record_id:
                failure = ContractError("invalid_assessment_spec", "refinement graph root mismatch")
                failure.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                    "assess", candidate, {}, failure, authorization_status
                )
                raise failure
        proper_ids = _proper_ids(graph)
        task_family = cast(list[str], task["eligible_family"])
        if availability_graph is None and task_family != [candidate_record_id, *proper_ids]:
            failure = ContractError(
                "invalid_assessment_spec", "TaskSpec eligible family does not match graph closure"
            )
            failure.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                "assess", candidate, {}, failure, authorization_status
            )
            raise failure
        intervals = {
            item["unit_record_id"]: item
            for item in cast(list[dict[str, Any]], run["qste:adjustedIntervals"])
            if isinstance(item.get("unit_record_id"), str)
        }
        raw = cast(dict[str, dict[str, Any]], run["qste:rawPairedEvidence"])
        candidate_interval = intervals.get(candidate_record_id)
        candidate_raw = raw.get(candidate_record_id)
        if candidate_raw is None:
            failure = ContractError(
                "invalid_assessment_spec",
                "candidate paired scores are required to serialize a DSQAssessment",
            )
            failure.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                "assess", candidate, {}, failure, authorization_status
            )
            raise failure

        multiplicity_valid = bool(
            run["qste:multiplicityEvidence"]["eligible_family_complete"]
            and run["qste:multiplicityEvidence"]["intervals_adjusted_for_full_family"]
        )
        controls_passed = bool(run["qste:artifactControlResults"]["passed"])
        calibration_available = bool(run["qste:calibrationEvidence"]["available"])
        dependency_valid = run["qste:dependencyValidity"] == "valid"
        global_negative_valid = (
            multiplicity_valid and controls_passed and calibration_available and dependency_valid
        )
        candidate_negative_valid = global_negative_valid and _finite_interval(candidate_interval)
        proper_valid = {
            node_id: global_negative_valid and _finite_interval(intervals.get(node_id))
            for node_id in proper_ids
        }
        theta = cast(float, task["meaningful_bound"])
        region = cast(Mapping[str, float], task["equivalence_region"])
        lower_zero = -region["epsilon_minus"]
        upper_zero = region["epsilon_plus"]
        candidate_upper = (
            cast(float, candidate_interval["upper"])
            if candidate_interval is not None and _finite_interval(candidate_interval)
            else None
        )
        candidate_lower = (
            cast(float, candidate_interval["lower"])
            if candidate_interval is not None and _finite_interval(candidate_interval)
            else None
        )

        candidate_nonmeaningful = bool(
            candidate_negative_valid and candidate_upper is not None and candidate_upper < theta
        )
        nonequivalent_nodes = [
            node_id
            for node_id in proper_ids
            if proper_valid[node_id] and _disjoint(intervals[node_id], lower_zero, upper_zero)
        ]
        closure_complete = bool(
            graph.get("closed") is True and graph["completion_certificate"].get("complete") is True
        )
        closure_nonempty = bool(proper_ids)
        all_evidence = candidate_interval is not None and all(
            node_id in intervals for node_id in proper_ids
        )
        selection_valid = bool(task["selection_confirmation"].get("disjoint") is True)
        qualification_ready = bool(
            closure_complete
            and closure_nonempty
            and all_evidence
            and all(proper_valid.values())
            and candidate_negative_valid
            and selection_valid
        )
        candidate_meaningful = bool(
            candidate_negative_valid and candidate_lower is not None and candidate_lower >= theta
        )
        all_equivalent = bool(
            proper_ids
            and all(
                proper_valid[node_id] and _contained(intervals[node_id], lower_zero, upper_zero)
                for node_id in proper_ids
            )
        )

        if candidate_nonmeaningful:
            status, reason = "rejected", "candidate_nonmeaningful"
        elif nonequivalent_nodes:
            status, reason = "rejected", "proper_node_nonequivalent"
        elif qualification_ready and candidate_meaningful and all_equivalent:
            status, reason = "qualified", "meaningful_closed_equivalent"
        else:
            status = "indeterminate"
            reason = self._indeterminate_reason(
                candidate,
                graph,
                run,
                candidate_interval,
                intervals,
                proper_ids,
                candidate_negative_valid,
                proper_valid,
                theta,
                lower_zero,
                upper_zero,
            )

        timestamp = utc_timestamp()
        receipt_id = cast(str, record_base("OperationReceipt", created_at=timestamp)["record_id"])
        proper_interval_records: list[Any] = [
            {
                "candidate_ref": record_ref(node_id, "CandidateUnit"),
                "interval": intervals.get(node_id, {"availability": "unavailable"}),
                "negative_evidence_valid": proper_valid[node_id],
            }
            for node_id in proper_ids
        ]
        tested_nodes: list[Any] = [
            record_ref(node_id, "CandidateUnit") for node_id in proper_ids if node_id in intervals
        ]
        if not proper_interval_records:
            marker_reason = (
                "empty_proper_set"
                if candidate["qste:pTerminal"]["is_terminal"]
                else "closure_unavailable"
            )
            proper_interval_records = [{"availability": "not_applicable", "reason": marker_reason}]
            tested_nodes = [{"availability": "not_applicable", "reason": marker_reason}]
        elif not tested_nodes:
            tested_nodes = [
                {"availability": "unavailable", "reason": "required_evidence_unavailable"}
            ]
        interaction = _interaction_annotations(candidate_interval, intervals, proper_ids)
        family = self._record(
            cast(str, task["qste:representationFamilyRef"]["record_id"]),
            "RepresentationFamilySpec",
        )
        instance = self._record(
            cast(str, task["qste:representationInstanceRef"]["record_id"]),
            "RepresentationInstance",
        )
        aperture = self._record(cast(str, task["qste:apertureRef"]["record_id"]), "ApertureSpec")
        apparatus_id = cast(str, aperture["apparatus_ref"]["record_id"])
        identity = {
            "apparatus_semantic_key": self._record(apparatus_id, "ApparatusSpec")["semantic_key"],
            "aperture_semantic_key": aperture["semantic_key"],
            "representation_family_semantic_key": family["semantic_key"],
            "representation_instance_semantic_key": instance["semantic_key"],
            "candidate_semantic_key": candidate["semantic_key"],
            "intervention_semantic_key": self._record(
                cast(str, task["intervention_ref"]["record_id"]), "InterventionSpec"
            )["semantic_key"],
            "refinement_graph_semantic_key": graph["semantic_key"],
            "task_semantic_key": task["semantic_key"],
            "fixed_context": task["fixed_context"],
            "response_variable": task["response_variable"],
            "orientation": task["expected_effect_direction"],
            "meaningful_bound": theta,
            "equivalence_region": dict(region),
            "estimator": task["estimator"],
            "uncertainty": task["uncertainty"],
            "multiplicity": task["multiplicity"],
            "selection_confirmation": task["selection_confirmation"],
            "budget": task["compute_budget"],
            "versions": {
                "contract": "qste-contract/0.3.0",
                "assessment_profile": ASSESSMENT_PROFILE,
            },
        }
        assessment = record_base(
            "DSQAssessment",
            created_at=timestamp,
            references=[
                record_ref(candidate_record_id, "CandidateUnit"),
                record_ref(task_record_id, "TaskSpec"),
                record_ref(run_record_id, "RunManifest"),
                record_ref(graph["record_id"], "RefinementGraph"),
            ],
        ) | {
            "schema_id": f"{BASE_URI}/records/dsq-assessment.schema.json",
            "assessment_identity": identity,
            "candidate_ref": record_ref(candidate_record_id, "CandidateUnit"),
            "candidate_semantic_key": candidate["semantic_key"],
            "representation_instance_ref": record_ref(
                instance["record_id"], "RepresentationInstance"
            ),
            "native_address": dict(candidate["native_address"]),
            "apparatus_ref": record_ref(apparatus_id, "ApparatusSpec"),
            "aperture_ref": record_ref(aperture["record_id"], "ApertureSpec"),
            "representation_family_ref": record_ref(
                family["record_id"], "RepresentationFamilySpec"
            ),
            "intervention_ref": dict(task["intervention_ref"]),
            "task_ref": record_ref(task_record_id, "TaskSpec"),
            "refinement_graph_ref": record_ref(graph["record_id"], "RefinementGraph"),
            "raw_effects": list(candidate_raw["raw_effects"]),
            "oriented_effects": list(candidate_raw["oriented_effects"]),
            "candidate_interval": candidate_interval
            or {"availability": "unavailable", "reason": "uncertainty_contract_missing"},
            "proper_node_intervals": proper_interval_records,
            "meaningful_bound": theta,
            "equivalence_region": dict(region),
            "comparison_operators": {
                "meaningful": "lower >= meaningful_bound",
                "equivalent": "interval contained in closed equivalence region",
                "nonmeaningful": "upper < meaningful_bound",
                "nonequivalent": "interval intersection with equivalence region is empty",
            },
            "tested_proper_nodes": tested_nodes,
            "closure_certificate": {
                **dict(graph["completion_certificate"]),
                "nonempty": closure_nonempty,
            },
            "selection_evidence": dict(run["qste:selectionEvidence"]),
            "multiplicity_evidence": dict(run["qste:multiplicityEvidence"]),
            "artifact_control_results": dict(run["qste:artifactControlResults"]),
            "well_formed": True,
            "negative_evidence_valid": candidate_negative_valid or any(proper_valid.values()),
            "qualification_ready": qualification_ready,
            "assessment_status": status,
            "reason_code": reason,
            "interaction_annotations": [interaction],
            "dependency_validity": cast(str, run["qste:dependencyValidity"]),
            "authorization_status": authorization_status,
            "evidence_refs": [record_ref(run_record_id, "RunManifest")],
            "assessor": "qste-p6-reference-assessor/v0.1",
            "versions": {
                "contract": "qste-contract/0.3.0",
                "task_profile": TASK_PROFILE,
                "assessment_profile": ASSESSMENT_PROFILE,
            },
            "receipt_refs": [record_ref(receipt_id, "OperationReceipt")],
            "qste:assessmentProfile": ASSESSMENT_PROFILE,
            "qste:currentDependencyValidityDerivedFromEvents": True,
            "qste:dsqLabelEligible": status == "qualified",
            "qste:conclusiveProperNodes": nonequivalent_nodes,
        }
        bind_semantic_key(
            assessment,
            "qste-semantic-key/dsq-assessment-v1",
            identity,
        )
        receipt = operation_receipt(
            created_at=timestamp,
            record_id=receipt_id,
            request_ref=record_ref(candidate_record_id, "CandidateUnit"),
            authorization_status=authorization_status,
            operation="assess",
            inputs=[
                record_ref(candidate_record_id, "CandidateUnit"),
                record_ref(task_record_id, "TaskSpec"),
                record_ref(run_record_id, "RunManifest"),
                record_ref(graph["record_id"], "RefinementGraph"),
            ],
            parameters={"assessment_profile": ASSESSMENT_PROFILE},
            outputs=[record_ref(assessment["record_id"], "DSQAssessment", "produced_by")],
            tool_id="qste-p6-reference-assessor",
            tool_version="v0.1",
        )
        records = [
            *([availability_graph] if availability_graph is not None else []),
            assessment,
            receipt,
        ]
        _, event = self.store.insert_records_with_event(
            records,
            domain_event_record_id=None,
            event_type="qste:dsq-assessed/0.1",
            subject_record_id=assessment["record_id"],
            receipt_record_id=receipt_id,
            payload={
                "assessment_status": status,
                "reason_code": reason,
                "qualification_ready": qualification_ready,
                "dependency_validity": assessment["dependency_validity"],
            },
            created_at=timestamp,
        )
        return QuantaOperationOutcome(
            assessment,
            f"{BASE_URI}/records/dsq-assessment.schema.json",
            receipt,
            event.event_sequence,
        )

    def evaluate_baselines(
        self,
        *,
        assessment_record_id: str,
        authorization_status: str = "permitted",
    ) -> QuantaOperationOutcome:
        """Evaluate matched stopping-rule baselines without changing the assessment."""

        assessment = self._record(assessment_record_id, "DSQAssessment")
        self._authorize(authorization_status, "baseline", assessment, {})
        candidate = cast(dict[str, Any], assessment["candidate_interval"])
        proper = [
            item["interval"]
            for item in cast(list[dict[str, Any]], assessment["proper_node_intervals"])
            if isinstance(item.get("interval"), Mapping)
            and _finite_interval(cast(Mapping[str, Any], item["interval"]))
        ]
        theta = cast(float, assessment["meaningful_bound"])
        region = cast(Mapping[str, float], assessment["equivalence_region"])
        lower_zero = -region["epsilon_minus"]
        upper_zero = region["epsilon_plus"]
        candidate_meaningful = (
            _finite_interval(candidate) and cast(float, candidate["lower"]) >= theta
        )
        required_count = assessment["closure_certificate"].get("proper_node_count")
        complete_evidence = isinstance(required_count, int) and len(proper) == required_count
        exact_dsq = bool(
            candidate_meaningful
            and proper
            and complete_evidence
            and assessment["closure_certificate"].get("complete") is True
            and assessment["closure_certificate"].get("nonempty") is True
            and all(_contained(item, lower_zero, upper_zero) for item in proper)
        )
        payload = _payload(
            "CapabilityAccount",
            data={
                "profile": BASELINE_PROFILE,
                "assessment_ref": record_ref(assessment_record_id, "DSQAssessment"),
                "matching_pursuit": {
                    "stopping_rule": "candidate meaningful; stop when no proper node is meaningful",
                    "stopped": candidate_meaningful
                    and all(cast(float, item["upper"]) < theta for item in proper),
                    "satisfies_dsq_condition": exact_dsq,
                },
                "perceptual_coding": {
                    "stopping_rule": (
                        "candidate meaningful; every proper interval inside negligible region"
                    ),
                    "stopped": candidate_meaningful
                    and complete_evidence
                    and all(_contained(item, lower_zero, upper_zero) for item in proper),
                    "satisfies_dsq_condition": exact_dsq,
                },
                "any_baseline_satisfies_dsq_condition": exact_dsq,
                "native_units_preserved": True,
            },
        )
        return self._receipt_payload(
            "baseline", assessment, {}, payload, authorization_status, BASELINE_PROFILE
        )

    def invalidate_dependency(
        self,
        *,
        assessment_record_id: str,
        invalidation_reason: str,
        evidence: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> QuantaOperationOutcome:
        """Append dependency invalidation without rewriting frozen assessment bytes."""

        assessment = self._record(assessment_record_id, "DSQAssessment")
        self._authorize(authorization_status, "invalidate_dependency", assessment, evidence)
        if invalidation_reason not in INVALIDATION_REASONS:
            failure = ContractError("invalid_input", "unknown dependency invalidation reason")
            failure.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                "invalidate_dependency",
                assessment,
                {"invalidation_reason": invalidation_reason},
                failure,
                authorization_status,
            )
            raise failure
        if not evidence:
            failure = ContractError("invalid_input", "dependency invalidation requires evidence")
            failure.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                "invalidate_dependency",
                assessment,
                {"invalidation_reason": invalidation_reason},
                failure,
                authorization_status,
            )
            raise failure
        timestamp = utc_timestamp()
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(assessment_record_id, "DSQAssessment"),
            authorization_status=authorization_status,
            operation="invalidate_dependency",
            inputs=[record_ref(assessment_record_id, "DSQAssessment")],
            parameters={"invalidation_reason": invalidation_reason, "evidence": dict(evidence)},
            outputs=[
                {
                    "assessment_record_id": assessment_record_id,
                    "current_dependency_validity": "invalidated",
                }
            ],
            tool_id="qste-p6-dependency-ledger",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:dsq-dependency-invalidated/0.1",
            subject_record_id=assessment_record_id,
            receipt_record_id=receipt["record_id"],
            payload={
                "invalidation_reason": invalidation_reason,
                "evidence": dict(evidence),
                "frozen_assessment_status": assessment["assessment_status"],
                "frozen_reason_code": assessment["reason_code"],
                "current_dependency_validity": "invalidated",
                "recomputation": "queued_not_executed",
            },
            created_at=timestamp,
        )
        payload = _payload(
            "CapabilityAccount",
            data={
                "assessment_ref": record_ref(assessment_record_id, "DSQAssessment"),
                "frozen_assessment_status": assessment["assessment_status"],
                "frozen_reason_code": assessment["reason_code"],
                "stored_dependency_validity": assessment["dependency_validity"],
                "current_dependency_validity": "invalidated",
                "invalidation_reason": invalidation_reason,
                "recomputation": "queued_not_executed",
            },
        )
        return QuantaOperationOutcome(
            payload, "qste-payload/0.3.0/CapabilityAccount", receipt, event.event_sequence
        )

    def current_dependency_validity(self, assessment_record_id: str) -> dict[str, Any]:
        """Derive current validity from append-only events without mutating assessment bytes."""

        assessment = self._record(assessment_record_id, "DSQAssessment")
        events = [
            event
            for event in self.store.iter_events()
            if event.subject_record_id == assessment_record_id
            and event.event_type == "qste:dsq-dependency-invalidated/0.1"
        ]
        if not events:
            return {
                "stored_dependency_validity": assessment["dependency_validity"],
                "current_dependency_validity": assessment["dependency_validity"],
                "invalidation_events": 0,
            }
        return {
            "stored_dependency_validity": assessment["dependency_validity"],
            "current_dependency_validity": "invalidated",
            "invalidation_events": len(events),
            "latest_reason": events[-1].payload["invalidation_reason"],
        }

    def _indeterminate_reason(
        self,
        candidate: Mapping[str, Any],
        graph: Mapping[str, Any],
        run: Mapping[str, Any],
        candidate_interval: Mapping[str, Any] | None,
        intervals: Mapping[str, Mapping[str, Any]],
        proper_ids: Sequence[str],
        candidate_valid: bool,
        proper_valid: Mapping[str, bool],
        theta: float,
        lower_zero: float,
        upper_zero: float,
    ) -> str:
        if candidate["qste:pTerminal"]["is_terminal"] and not proper_ids:
            return "empty_proper_set"
        if not run["qste:multiplicityEvidence"]["intervals_adjusted_for_full_family"]:
            return "uncertainty_contract_missing"
        if run["budgets"]["termination"] == "budget_exhausted":
            return "budget_exhausted"
        if not run["qste:calibrationEvidence"]["available"]:
            return "calibration_unavailable"
        if not run["qste:artifactControlResults"]["passed"]:
            return "artifact_control_failed"
        if run["qste:dependencyValidity"] != "valid":
            return "required_evidence_unavailable"
        if (
            graph.get("closed") is not True
            or graph["completion_certificate"].get("complete") is not True
        ):
            return "closure_unavailable"
        if candidate_interval is None:
            return "required_evidence_unavailable"
        if candidate_valid and cast(float, candidate_interval["lower"]) < theta <= cast(
            float, candidate_interval["upper"]
        ):
            return "candidate_boundary_crossing"
        if any(node_id not in intervals for node_id in proper_ids):
            return "required_evidence_unavailable"
        if any(
            proper_valid[node_id]
            and not _contained(intervals[node_id], lower_zero, upper_zero)
            and not _disjoint(intervals[node_id], lower_zero, upper_zero)
            for node_id in proper_ids
        ):
            return "proper_node_boundary_crossing"
        return "required_evidence_unavailable"

    def _availability_graph(
        self, candidate: Mapping[str, Any], task: Mapping[str, Any], *, empty: bool
    ) -> dict[str, Any]:
        timestamp = utc_timestamp()
        reason = "empty_proper_set" if empty else "closure_unavailable"
        marker = {"availability": "not_applicable" if empty else "unavailable", "reason": reason}
        graph = record_base(
            "RefinementGraph",
            created_at=timestamp,
            references=[record_ref(candidate["record_id"], "CandidateUnit")],
        ) | {
            "procedure_id": "qste-refinement/availability-record-v0.1",
            "representation_family_ref": dict(task["qste:representationFamilyRef"]),
            "intervention_ref": dict(task["intervention_ref"]),
            "root_candidate_ref": record_ref(candidate["record_id"], "CandidateUnit"),
            "nodes": [candidate["record_id"]],
            "edges": [marker],
            "required_closure": [marker],
            "completion_certificate": {
                "complete": False,
                "nonempty": False,
                "reason": reason,
                "effect_pruning": False,
            },
            "closed": False,
            "qste:p6AvailabilityGraph": True,
        }
        bind_semantic_key(
            graph,
            "qste-semantic-key/refinement-availability-v1",
            {
                "candidate_semantic_key": candidate["semantic_key"],
                "task_semantic_key": task["semantic_key"],
                "reason": reason,
            },
        )
        return graph

    def _validate_assessment_links(
        self, candidate: Mapping[str, Any], task: Mapping[str, Any], run: Mapping[str, Any]
    ) -> None:
        if task.get("qste:taskProfile") != TASK_PROFILE:
            raise ContractError("invalid_assessment_spec", "unsupported TaskSpec profile")
        if task["qste:candidateRef"]["record_id"] != candidate["record_id"]:
            raise ContractError("invalid_assessment_spec", "TaskSpec candidate mismatch")
        if run.get("qste:taskRunProfile") != TASK_RUN_PROFILE:
            raise ContractError("invalid_assessment_spec", "unsupported score-run profile")
        if run["qste:taskRef"]["record_id"] != task["record_id"]:
            raise ContractError("invalid_assessment_spec", "score run TaskSpec mismatch")

    def _record(self, record_id: str, record_type: str) -> dict[str, Any]:
        record = self.store.get_record(record_id).record
        if record["record_type"] != record_type:
            raise ContractError("invalid_input", f"expected {record_type}: {record_id}")
        return record

    def _authorize(
        self,
        status: str,
        operation: str,
        subject: Mapping[str, Any],
        parameters: Mapping[str, Any],
    ) -> None:
        if status == "permitted":
            return
        error = ContractError("policy_refused", f"{operation} requires explicit permission")
        error.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
            operation, subject, parameters, error, status
        )
        raise error

    def _invalid_task(
        self, subject: Mapping[str, Any], parameters: Mapping[str, Any], message: str
    ) -> NoReturn:
        error = ContractError("invalid_assessment_spec", message)
        error.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
            "declare_or_execute_task", subject, parameters, error, "permitted"
        )
        raise error

    def _failure_receipt(
        self,
        operation: str,
        subject: Mapping[str, Any],
        parameters: Mapping[str, Any],
        error: ContractError,
        authorization_status: str,
    ) -> str:
        timestamp = utc_timestamp()
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(subject["record_id"], subject["record_type"]),
            authorization_status=authorization_status
            if authorization_status in {"permitted", "refused"}
            else "not_applicable",
            operation=operation,
            inputs=[record_ref(subject["record_id"], subject["record_type"])],
            parameters={**dict(parameters), "failure_reason": error.reason_code},
            outputs=[{"availability": "unavailable", "reason": error.reason_code}],
            operation_status="refused" if error.reason_code == "policy_refused" else "failed",
            tool_id="qste-p6-task-engine",
            tool_version="v0.1",
        )
        _, _event = self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:p6-operation-failed/0.1",
            subject_record_id=subject["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"operation": operation, "reason_code": error.reason_code},
            created_at=timestamp,
        )
        return cast(str, receipt["record_id"])

    def _receipt_payload(
        self,
        operation: str,
        subject: Mapping[str, Any],
        parameters: Mapping[str, Any],
        payload: dict[str, Any],
        authorization_status: str,
        profile: str,
    ) -> QuantaOperationOutcome:
        timestamp = utc_timestamp()
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(subject["record_id"], subject["record_type"]),
            authorization_status=authorization_status,
            operation=operation,
            inputs=[record_ref(subject["record_id"], subject["record_type"])],
            parameters=dict(parameters) or {"profile": profile},
            outputs=[{"payload_type": payload["payload_type"], "profile": profile}],
            tool_id="qste-p6-task-engine",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type=f"qste:{operation}-completed/0.1",
            subject_record_id=subject["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"profile": profile},
            created_at=timestamp,
        )
        return QuantaOperationOutcome(
            payload,
            f"qste-payload/0.3.0/{payload['payload_type']}",
            receipt,
            event.event_sequence,
        )


def _validate_task_input(spec: Mapping[str, Any], family_size: int) -> None:
    required = {
        "task_id",
        "task_version",
        "response_variable",
        "fixed_context",
        "expected_effect_direction",
        "response_units",
        "meaningful_bound",
        "equivalence_region",
        "boundary_semantics",
        "estimator",
        "repeats",
        "seeds",
        "uncertainty",
        "multiplicity",
        "stopping_rules",
        "selection_confirmation",
        "artifact_controls",
        "alternate_intervention",
        "compute_budget",
        "success_criterion",
    }
    if not required.issubset(spec):
        raise ContractError("invalid_assessment_spec", "TaskSpec input is incomplete")
    for name in ("task_id", "task_version", "response_variable", "response_units"):
        if not isinstance(spec[name], str) or not spec[name]:
            raise ContractError("invalid_assessment_spec", f"{name} must be nonempty")
    if spec["expected_effect_direction"] not in {-1, 1}:
        raise ContractError("invalid_assessment_spec", "effect direction must be -1 or +1")
    theta = _finite(spec["meaningful_bound"], "meaningful bound")
    region = _mapping(spec["equivalence_region"], "equivalence region")
    epsilon_minus = _finite(region.get("epsilon_minus"), "epsilon_minus")
    epsilon_plus = _finite(region.get("epsilon_plus"), "epsilon_plus")
    if theta <= 0 or epsilon_minus < 0 or epsilon_plus < 0 or epsilon_plus >= theta:
        raise ContractError("invalid_assessment_spec", "BoundValid is false")
    if region.get("units") != spec["response_units"]:
        raise ContractError("invalid_assessment_spec", "bounds do not share response units")
    boundary = _mapping(spec["boundary_semantics"], "boundary semantics")
    if boundary != {
        "qualification": "inclusive",
        "equivalence": "inclusive",
        "rejection": "strict",
    }:
        raise ContractError("invalid_assessment_spec", "P6 boundary semantics are not canonical")
    estimator = _mapping(spec["estimator"], "estimator")
    if estimator.get("id") != "paired_mean":
        raise ContractError("invalid_assessment_spec", "P6 requires paired_mean")
    repeats = spec["repeats"]
    seeds = spec["seeds"]
    if (
        not isinstance(repeats, int)
        or isinstance(repeats, bool)
        or repeats < 1
        or repeats > MAX_REPEATS
        or not isinstance(seeds, list)
        or len(seeds) < repeats
        or not all(isinstance(seed, int) and not isinstance(seed, bool) for seed in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise ContractError("invalid_assessment_spec", "repeats/seeds are invalid")
    uncertainty = _mapping(spec["uncertainty"], "uncertainty")
    method = uncertainty.get("method")
    if method == "deterministic_tolerance":
        tolerance = _finite(uncertainty.get("tolerance"), "deterministic tolerance")
        if tolerance < 0:
            raise ContractError("invalid_assessment_spec", "tolerance must be nonnegative")
    elif method == "bonferroni_normal":
        confidence = _finite(uncertainty.get("confidence"), "confidence")
        if not 0.5 < confidence < 1 or repeats < 2:
            raise ContractError("invalid_assessment_spec", "stochastic interval contract invalid")
    elif method != "unavailable":
        raise ContractError("invalid_assessment_spec", "unknown uncertainty method")
    multiplicity = _mapping(spec["multiplicity"], "multiplicity")
    if (
        multiplicity.get("method")
        not in {
            "complete_family_bonferroni",
            "unavailable",
        }
        or multiplicity.get("family_size") != family_size
    ):
        raise ContractError("invalid_assessment_spec", "multiplicity family is not exact")
    selection = _mapping(spec["selection_confirmation"], "selection/confirmation")
    if selection.get("mode") not in {"held_out", "nested"} or selection.get("disjoint") is not True:
        raise ContractError("invalid_assessment_spec", "selection/confirmation split is invalid")
    if selection.get("selection_set") == selection.get("confirmation_set"):
        raise ContractError("invalid_assessment_spec", "selection and confirmation sets coincide")
    controls = spec["artifact_controls"]
    if not isinstance(controls, list) or set(controls) != set(CONTROL_NAMES):
        raise ContractError("invalid_assessment_spec", "artifact control contract is incomplete")
    alternate = _mapping(spec["alternate_intervention"], "alternate intervention")
    if alternate.get("required") is not True:
        raise ContractError("invalid_assessment_spec", "alternate intervention must be required")
    budget = _mapping(spec["compute_budget"], "compute budget")
    maximum = budget.get("maximum_evaluations")
    if (
        not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or maximum < 2
        or maximum > MAX_EVALUATIONS
    ):
        raise ContractError("invalid_assessment_spec", "compute budget is invalid")
    if spec.get("required_calibration", "digital_sample_domain") not in {
        "digital_sample_domain",
        "spl",
        "extra_human_frequency",
    }:
        raise ContractError("invalid_assessment_spec", "unknown calibration claim")


def _paired_scores(value: Any, repeats: int) -> tuple[list[float], list[float]]:
    unit = _mapping(value, "paired score evidence")
    reference = unit.get("reference_scores")
    intervened = unit.get("intervened_scores")
    if (
        not isinstance(reference, list)
        or not isinstance(intervened, list)
        or len(reference) != repeats
        or len(intervened) != repeats
    ):
        raise ContractError("invalid_assessment_spec", "paired score count does not match repeats")
    return (
        [_finite(value, "reference score") for value in reference],
        [_finite(value, "intervened score") for value in intervened],
    )


def _interval(task: Mapping[str, Any], effects: list[float]) -> dict[str, Any]:
    uncertainty = cast(Mapping[str, Any], task["uncertainty"])
    method = uncertainty["method"]
    mean = fmean(effects)
    if method == "unavailable":
        return {
            "availability": "unavailable",
            "reason": "uncertainty_contract_missing",
            "point_estimate": mean,
            "raw_count": len(effects),
        }
    if method == "deterministic_tolerance":
        half_width = cast(float, uncertainty["tolerance"])
        confidence: float | str = "deterministic_tolerance"
    else:
        confidence = cast(float, uncertainty["confidence"])
        family_size = cast(int, task["multiplicity"]["family_size"])
        alpha = 1.0 - confidence
        quantile = NormalDist().inv_cdf(1.0 - alpha / (2.0 * family_size))
        half_width = quantile * stdev(effects) / math.sqrt(len(effects))
    return {
        "availability": "known",
        "lower": mean - half_width,
        "upper": mean + half_width,
        "point_estimate": mean,
        "raw_count": len(effects),
        "uncertainty_method": method,
        "confidence": confidence,
        "multiplicity_method": task["multiplicity"]["method"],
        "multiplicity_family_size": task["multiplicity"]["family_size"],
    }


def _proper_ids(graph: Mapping[str, Any]) -> list[str]:
    values = graph.get("required_closure")
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str)]


def _finite_interval(value: Mapping[str, Any] | None) -> bool:
    return bool(
        isinstance(value, Mapping)
        and value.get("availability") == "known"
        and isinstance(value.get("lower"), (int, float))
        and isinstance(value.get("upper"), (int, float))
        and math.isfinite(cast(float, value["lower"]))
        and math.isfinite(cast(float, value["upper"]))
        and cast(float, value["lower"]) <= cast(float, value["upper"])
    )


def _contained(interval: Mapping[str, Any], lower: float, upper: float) -> bool:
    return cast(float, interval["lower"]) >= lower and cast(float, interval["upper"]) <= upper


def _disjoint(interval: Mapping[str, Any], lower: float, upper: float) -> bool:
    return cast(float, interval["upper"]) < lower or cast(float, interval["lower"]) > upper


def _interaction_annotations(
    candidate: Mapping[str, Any] | None,
    intervals: Mapping[str, Mapping[str, Any]],
    proper_ids: Sequence[str],
) -> dict[str, Any]:
    candidate_mean = None
    if candidate is not None and _finite_interval(candidate):
        candidate_mean = cast(float, candidate["point_estimate"])
    proper_means = [
        cast(float, intervals[node_id]["point_estimate"])
        for node_id in proper_ids
        if node_id in intervals and _finite_interval(intervals[node_id])
    ]
    nonmonotone = bool(
        candidate_mean is not None and any(value > candidate_mean for value in proper_means)
    )
    synergy = bool(
        candidate_mean is not None
        and proper_means
        and candidate_mean > sum(max(0.0, value) for value in proper_means)
    )
    return {
        "nonmonotone_effects_preserved": nonmonotone,
        "synergy_detected": synergy,
        "proper_node_point_estimates": proper_means,
        "indivisibility_inference_prohibited": True,
    }


def _payload(payload_type: str, *, data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "payload_schema_id": "qste-payload/0.3.0",
        "payload_type": payload_type,
        "items": [],
        "data": dict(data),
    }


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ContractError("invalid_assessment_spec", f"{name} must be a nonempty object")
    return value


def _finite(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ContractError("invalid_assessment_spec", f"{name} must be finite")
    return float(value)
