"""P7 calibrated projection contracts and bounded exact relation assessment."""

from __future__ import annotations

import itertools
import math
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from qste.core import canonical_json_bytes, content_digest
from qste.core.contracts import BASE_URI, ContractError
from qste.core.identity import utc_timestamp
from qste.ingress.records import bind_semantic_key, operation_receipt, record_base, record_ref
from qste.relations.models import RelationOperationOutcome
from qste.storage import RecordStore, WorkspacePaths

PROJECTION_PROFILE = "qste-cross-arm-projection/v0.1"
COMPARISON_PROFILE = "qste-cross-arm-comparison/v0.1"
RELATION_PROFILE = "qste-cross-arm-relation/v0.1"
SOLVER_PROFILE = "qste-bounded-exact-b-matching/v0.1"
MAX_UNITS_PER_SIDE = 16
MAX_EDGES = 20
MAX_SUBSETS = 1_048_576
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

RELATION_REASON = {
    "overlap": "matched_overlap",
    "split": "matched_split",
    "merge": "matched_merge",
    "omission": "target_address_absent",
    "loss": "fidelity_failed",
    "incomparable": "projection_invalid",
}


@dataclass(frozen=True, slots=True)
class UnitEvidence:
    candidate: dict[str, Any]
    footprint: tuple[float, ...]
    footprint_mass: float
    effect_interval: tuple[float, float]
    effect_point: float
    projection_status: str
    evidence_refs: tuple[dict[str, str], ...]
    perturbation_stability: str


@dataclass(frozen=True, slots=True)
class PairEvidence:
    source_id: str
    target_id: str
    source_to_target: tuple[float, float, float]
    target_to_source: tuple[float, float, float]
    effect_difference: tuple[float, float, float]
    cost: float
    state: str
    controls: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MatchResult:
    status: str
    primary_optimum: float | None
    surviving_solutions: tuple[tuple[tuple[str, str], ...], ...]
    representative: tuple[tuple[str, str], ...]
    evaluated_subsets: int
    verification_status: str


class RelationService:
    """Persist calibrated comparison contracts and ontology-faithful relation outcomes."""

    def __init__(self, workspace: Any) -> None:
        self.store = RecordStore(WorkspacePaths.open(workspace))

    def declare_projection(
        self,
        *,
        source_arm_record_id: str,
        specification: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> RelationOperationOutcome:
        """Freeze one arm-to-substrate projection contract."""

        arm = self._record(source_arm_record_id, "RepresentationInstance")
        self._authorize(authorization_status, "declare_projection", arm, specification)
        try:
            normalized = _validate_projection_input(specification)
        except ContractError as error:
            error.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                "declare_projection", arm, specification, error, authorization_status
            )
            raise
        timestamp = utc_timestamp()
        projection = record_base(
            "ProjectionSpec",
            created_at=timestamp,
            references=[record_ref(source_arm_record_id, "RepresentationInstance")],
        ) | {
            "source_arm_ref": record_ref(source_arm_record_id, "RepresentationInstance"),
            "comparison_substrate": normalized["comparison_substrate"],
            "measure": normalized["measure"],
            "footprint_method": normalized["footprint_method"],
            "calibration": normalized["calibration"],
            "qste:projectionProfile": PROJECTION_PROFILE,
            "qste:alignment": normalized["alignment"],
            "qste:uncertaintyPropagation": normalized["uncertainty"],
            "qste:failureConditions": normalized["failure_conditions"],
            "qste:effectContract": normalized["effect_contract"],
        }
        bind_semantic_key(
            projection,
            "qste-semantic-key/cross-arm-projection-v1",
            {
                "arm_semantic_key": arm.get("semantic_key"),
                "arm_record_id": source_arm_record_id,
                "projection_contract": normalized,
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(source_arm_record_id, "RepresentationInstance"),
            authorization_status=authorization_status,
            operation="declare_projection",
            inputs=[record_ref(source_arm_record_id, "RepresentationInstance")],
            parameters={"profile": PROJECTION_PROFILE},
            outputs=[record_ref(projection["record_id"], "ProjectionSpec", "produced_by")],
            tool_id="qste-p7-relation-engine",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [projection, receipt],
            domain_event_record_id=None,
            event_type="qste:projection-declared/0.1",
            subject_record_id=projection["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"profile": PROJECTION_PROFILE, "source_arm": source_arm_record_id},
            created_at=timestamp,
        )
        return RelationOperationOutcome(
            projection,
            f"{BASE_URI}/records/projection-spec.schema.json",
            receipt,
            event.event_sequence,
        )

    def declare_comparison(
        self,
        *,
        projection_record_ids: Sequence[str],
        specification: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> RelationOperationOutcome:
        """Freeze exact projection, interval, matching, and ambiguity rules."""

        if len(projection_record_ids) != 2 or len(set(projection_record_ids)) != 2:
            raise ContractError(
                "invalid_comparison_spec", "P7 requires exactly two distinct projections"
            )
        projections = [self._record(value, "ProjectionSpec") for value in projection_record_ids]
        subject = projections[0]
        self._authorize(authorization_status, "declare_comparison", subject, specification)
        try:
            normalized = _validate_comparison_input(specification)
            _validate_projection_pair(projections, normalized)
        except ContractError as error:
            error.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                "declare_comparison", subject, specification, error, authorization_status
            )
            raise
        timestamp = utc_timestamp()
        comparison = record_base(
            "ComparisonSpec",
            created_at=timestamp,
            references=[record_ref(value, "ProjectionSpec") for value in projection_record_ids],
        ) | {
            "projection_refs": [
                record_ref(value, "ProjectionSpec") for value in projection_record_ids
            ],
            "coverage_threshold": normalized["coverage_threshold"],
            "effect_tolerance": normalized["effect_tolerance"],
            "capacities": normalized["capacities"],
            "cardinalities": normalized["cardinalities"],
            "unmatched_penalty": normalized["unmatched_penalty"],
            "estimators": normalized["estimators"],
            "primary_objective": normalized["primary_objective"],
            "cardinality_preference": [normalized["cardinality_preference"]],
            "optimization_tolerance": normalized["optimization_tolerance"],
            "ambiguity_rules": normalized["ambiguity_rules"],
            "budget": normalized["budget"],
            "qste:comparisonProfile": COMPARISON_PROFILE,
            "qste:effectComparison": normalized["effect_contract"],
            "qste:effectConversions": normalized["effect_conversions"],
            "qste:coverageUncertainty": normalized["coverage_uncertainty"],
            "qste:solver": {"id": SOLVER_PROFILE, "mode": "exhaustive_reference"},
            "qste:reasonPrecedence": [
                "projection_invalid",
                "target_address_absent",
                "fidelity_failed",
                "coverage_failed",
                "effect_incompatible",
                "boundary_or_incomplete",
                "matching",
            ],
        }
        bind_semantic_key(
            comparison,
            "qste-semantic-key/cross-arm-comparison-v1",
            {
                "projection_semantic_keys": [value["semantic_key"] for value in projections],
                "comparison_contract": normalized,
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(projection_record_ids[0], "ProjectionSpec"),
            authorization_status=authorization_status,
            operation="declare_comparison",
            inputs=[record_ref(value, "ProjectionSpec") for value in projection_record_ids],
            parameters={"profile": COMPARISON_PROFILE},
            outputs=[record_ref(comparison["record_id"], "ComparisonSpec", "produced_by")],
            tool_id="qste-p7-relation-engine",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [comparison, receipt],
            domain_event_record_id=None,
            event_type="qste:comparison-declared/0.1",
            subject_record_id=comparison["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"profile": COMPARISON_PROFILE, "projection_count": 2},
            created_at=timestamp,
        )
        return RelationOperationOutcome(
            comparison,
            f"{BASE_URI}/records/comparison-spec.schema.json",
            receipt,
            event.event_sequence,
        )

    def compare(
        self,
        *,
        comparison_spec_record_id: str,
        source_candidate_record_ids: Sequence[str],
        target_candidate_record_ids: Sequence[str],
        evidence: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> RelationOperationOutcome:
        """Assess one bounded source/target candidate family and persist every outcome."""

        comparison = self._record(comparison_spec_record_id, "ComparisonSpec")
        self._authorize(authorization_status, "compare", comparison, evidence)
        try:
            sources = self._candidate_set(source_candidate_record_ids, "source")
            targets = self._candidate_set(target_candidate_record_ids, "target")
            projections = [
                self._record(cast(str, value["record_id"]), "ProjectionSpec")
                for value in cast(list[dict[str, Any]], comparison["projection_refs"])
            ]
            _validate_candidate_arms(sources, targets, projections)
            units = self._unit_evidence(comparison, projections, sources, targets, evidence)
            pairs = _pair_evidence(comparison, projections, sources, targets, units, evidence)
            assertions = self._resolve_relations(
                comparison,
                projections,
                sources,
                targets,
                units,
                pairs,
                evidence,
                authorization_status,
            )
        except ContractError as error:
            error.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                "compare", comparison, evidence, error, authorization_status
            )
            raise
        timestamp = utc_timestamp()
        receipt_id = cast(str, record_base("OperationReceipt", created_at=timestamp)["record_id"])
        for assertion in assertions:
            assertion["references"].append(
                record_ref(receipt_id, "OperationReceipt", "produced_by")
            )
            assertion["qste:receiptRef"] = record_ref(receipt_id, "OperationReceipt")
        receipt = operation_receipt(
            created_at=timestamp,
            record_id=receipt_id,
            request_ref=record_ref(comparison_spec_record_id, "ComparisonSpec"),
            authorization_status=authorization_status,
            operation="compare",
            inputs=[
                record_ref(comparison_spec_record_id, "ComparisonSpec"),
                *[record_ref(value["record_id"], "CandidateUnit") for value in sources],
                *[record_ref(value["record_id"], "CandidateUnit") for value in targets],
            ],
            parameters={
                "profile": RELATION_PROFILE,
                "source_count": len(sources),
                "target_count": len(targets),
            },
            outputs=[
                record_ref(value["record_id"], "RelationAssertion", "produced_by")
                for value in assertions
            ],
            tool_id="qste-p7-relation-engine",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [*assertions, receipt],
            domain_event_record_id=None,
            event_type="qste:cross-arm-compared/0.1",
            subject_record_id=comparison_spec_record_id,
            receipt_record_id=receipt_id,
            payload={
                "profile": RELATION_PROFILE,
                "assertion_count": len(assertions),
                "indeterminate_count": sum(
                    value["comparison_status"] == "indeterminate" for value in assertions
                ),
            },
            created_at=timestamp,
        )
        payload = {
            "payload_schema_id": "qste-payload/0.3.0",
            "payload_type": "RelationSet",
            "items": assertions,
            "data": {
                "comparison_spec_record_id": comparison_spec_record_id,
                "source_count": len(sources),
                "target_count": len(targets),
                "comparison_status": (
                    "indeterminate"
                    if any(value["comparison_status"] == "indeterminate" for value in assertions)
                    else "resolved"
                ),
            },
        }
        return RelationOperationOutcome(
            payload,
            "qste-payload/0.3.0/RelationSet",
            receipt,
            event.event_sequence,
        )

    def invalidate_relation(
        self,
        *,
        relation_assertion_record_id: str,
        invalidation_reason: str,
        evidence: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> RelationOperationOutcome:
        """Append a relation-method defect without rewriting the frozen assertion."""

        assertion = self._record(relation_assertion_record_id, "RelationAssertion")
        self._authorize(authorization_status, "invalidate_relation", assertion, evidence)
        if invalidation_reason not in INVALIDATION_REASONS or not evidence:
            failure = ContractError(
                "invalid_input",
                "relation invalidation requires a canonical reason and evidence",
            )
            failure.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                "invalidate_relation",
                assertion,
                {"invalidation_reason": invalidation_reason},
                failure,
                authorization_status,
            )
            raise failure
        timestamp = utc_timestamp()
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(relation_assertion_record_id, "RelationAssertion"),
            authorization_status=authorization_status,
            operation="invalidate_relation",
            inputs=[record_ref(relation_assertion_record_id, "RelationAssertion")],
            parameters={"invalidation_reason": invalidation_reason, "evidence": dict(evidence)},
            outputs=[
                {
                    "relation_assertion_record_id": relation_assertion_record_id,
                    "current_dependency_validity": "invalidated",
                }
            ],
            tool_id="qste-p7-dependency-ledger",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:relation-dependency-invalidated/0.1",
            subject_record_id=relation_assertion_record_id,
            receipt_record_id=receipt["record_id"],
            payload={
                "invalidation_reason": invalidation_reason,
                "evidence": dict(evidence),
                "frozen_comparison_status": assertion["comparison_status"],
                "frozen_relation_type": assertion["relation_type"],
                "frozen_reason_code": assertion["reason_code"],
                "current_dependency_validity": "invalidated",
                "descendant_review": "queued_not_executed",
            },
            created_at=timestamp,
        )
        payload = {
            "payload_schema_id": "qste-payload/0.3.0",
            "payload_type": "CapabilityAccount",
            "items": [],
            "data": {
                "relation_assertion_ref": record_ref(
                    relation_assertion_record_id, "RelationAssertion"
                ),
                "frozen_comparison_status": assertion["comparison_status"],
                "frozen_relation_type": assertion["relation_type"],
                "frozen_reason_code": assertion["reason_code"],
                "stored_dependency_validity": assertion["qste:dependencyValidity"],
                "current_dependency_validity": "invalidated",
                "invalidation_reason": invalidation_reason,
                "descendant_review": "queued_not_executed",
            },
        }
        return RelationOperationOutcome(
            payload,
            "qste-payload/0.3.0/CapabilityAccount",
            receipt,
            event.event_sequence,
        )

    def current_dependency_validity(self, relation_assertion_record_id: str) -> dict[str, Any]:
        """Derive current relation validity from append-only invalidation events."""

        assertion = self._record(relation_assertion_record_id, "RelationAssertion")
        events = [
            event
            for event in self.store.iter_events()
            if event.subject_record_id == relation_assertion_record_id
            and event.event_type == "qste:relation-dependency-invalidated/0.1"
        ]
        stored = assertion["qste:dependencyValidity"]
        return {
            "stored_dependency_validity": stored,
            "current_dependency_validity": "invalidated" if events else stored,
            "invalidation_events": len(events),
            "latest_invalidation_reason": (
                events[-1].payload["invalidation_reason"] if events else None
            ),
        }

    def _candidate_set(self, values: Sequence[str], side: str) -> list[dict[str, Any]]:
        if not values or len(values) > MAX_UNITS_PER_SIDE or len(set(values)) != len(values):
            raise ContractError(
                "invalid_comparison_spec", f"{side} candidates must be unique and bounded"
            )
        return [self._record(value, "CandidateUnit") for value in values]

    def _unit_evidence(
        self,
        comparison: Mapping[str, Any],
        projections: Sequence[Mapping[str, Any]],
        sources: Sequence[dict[str, Any]],
        targets: Sequence[dict[str, Any]],
        evidence: Mapping[str, Any],
    ) -> dict[str, UnitEvidence]:
        raw_units = evidence.get("units")
        if not isinstance(raw_units, Mapping):
            raise ContractError("invalid_comparison_spec", "comparison evidence needs unit data")
        projection_by_arm = {
            cast(str, value["source_arm_ref"]["record_id"]): value for value in projections
        }
        result: dict[str, UnitEvidence] = {}
        for candidate in [*sources, *targets]:
            candidate_id = cast(str, candidate["record_id"])
            raw = raw_units.get(candidate_id)
            if not isinstance(raw, Mapping):
                raise ContractError(
                    "invalid_comparison_spec", f"missing unit evidence: {candidate_id}"
                )
            arm_id = cast(str, candidate["representation_instance_ref"]["record_id"])
            projection = projection_by_arm[arm_id]
            result[candidate_id] = self._prepare_unit(comparison, projection, candidate, raw)
        return result

    def _prepare_unit(
        self,
        comparison: Mapping[str, Any],
        projection: Mapping[str, Any],
        candidate: dict[str, Any],
        raw: Mapping[str, Any],
    ) -> UnitEvidence:
        status = raw.get("projection_status")
        if status not in {"valid", "invalid", "incomplete", "capability_unavailable"}:
            raise ContractError("invalid_comparison_spec", "invalid projection evidence status")
        references = raw.get("evidence_record_ids", [candidate["record_id"]])
        if not isinstance(references, list) or not references:
            raise ContractError("invalid_comparison_spec", "unit evidence references are absent")
        evidence_refs: list[dict[str, str]] = []
        for record_id in references:
            if not isinstance(record_id, str):
                raise ContractError("invalid_comparison_spec", "invalid evidence record ID")
            record = self.store.get_record(record_id).record
            evidence_refs.append(record_ref(record_id, cast(str, record["record_type"])))
        stability = raw.get("perturbation_stability", "not_tested")
        if stability not in {"stable", "unstable", "indeterminate", "not_tested"}:
            raise ContractError("invalid_comparison_spec", "invalid perturbation stability")
        if status != "valid" and "footprint" not in raw and "effect_interval" not in raw:
            return UnitEvidence(
                candidate,
                (),
                0.0,
                (0.0, 0.0),
                0.0,
                cast(str, status),
                tuple(evidence_refs),
                cast(str, stability),
            )
        raw_footprint = raw.get("footprint")
        if not isinstance(raw_footprint, list) or not raw_footprint:
            raise ContractError("invalid_comparison_spec", "footprint must be a nonempty vector")
        footprint = tuple(_finite_nonnegative(value, "footprint value") for value in raw_footprint)
        method = cast(Mapping[str, Any], projection["footprint_method"])
        if method["kind"] == "exceedance_probability" and any(value > 1 for value in footprint):
            raise ContractError("invalid_comparison_spec", "probability footprint exceeds one")
        weights = cast(Mapping[str, Any], projection["measure"]).get("weights")
        if weights is None:
            measure_weights = (1.0,) * len(footprint)
        elif isinstance(weights, list) and len(weights) == len(footprint):
            measure_weights = tuple(_finite_positive(value, "measure weight") for value in weights)
        else:
            raise ContractError("invalid_comparison_spec", "measure weights do not fit footprint")
        mass = sum(value * weight for value, weight in zip(footprint, measure_weights, strict=True))
        if method["kind"] == "expected_energy_change" and mass > 0:
            footprint = tuple(value / mass for value in footprint)
            mass = sum(
                value * weight for value, weight in zip(footprint, measure_weights, strict=True)
            )
        interval = raw.get("effect_interval")
        if not isinstance(interval, Mapping):
            raise ContractError("invalid_comparison_spec", "effect interval is required")
        lower = _finite(interval.get("lower"), "effect lower")
        upper = _finite(interval.get("upper"), "effect upper")
        point = _finite(interval.get("point_estimate"), "effect point")
        if lower > upper or not lower <= point <= upper:
            raise ContractError("invalid_comparison_spec", "effect interval is invalid")
        common_contract = comparison["qste:effectComparison"]
        if raw.get("effect_contract") != common_contract:
            raise ContractError("invalid_comparison_spec", "unit effect estimand is not comparable")
        native_effect = projection["qste:effectContract"]
        conversions = cast(Mapping[str, Any], comparison["qste:effectConversions"])
        if native_effect != common_contract:
            conversion = conversions.get(projection["record_id"])
            if not isinstance(conversion, Mapping) or raw.get("conversion_ref") != conversion.get(
                "id"
            ):
                raise ContractError(
                    "invalid_comparison_spec", "explicit effect conversion evidence is absent"
                )
        return UnitEvidence(
            candidate,
            footprint,
            mass,
            (lower, upper),
            point,
            cast(str, status),
            tuple(evidence_refs),
            cast(str, stability),
        )

    def _resolve_relations(
        self,
        comparison: Mapping[str, Any],
        projections: Sequence[Mapping[str, Any]],
        sources: Sequence[dict[str, Any]],
        targets: Sequence[dict[str, Any]],
        units: Mapping[str, UnitEvidence],
        pairs: Mapping[tuple[str, str], PairEvidence],
        evidence: Mapping[str, Any],
        authorization_status: str,
    ) -> list[dict[str, Any]]:
        source_ids = [cast(str, value["record_id"]) for value in sources]
        target_ids = [cast(str, value["record_id"]) for value in targets]
        terminal = _global_terminal(source_ids, target_ids, units, pairs)
        if terminal is not None:
            relation, status, reason, terminal_sources, terminal_targets = terminal
            return [
                self._assertion(
                    comparison,
                    projections,
                    terminal_sources,
                    terminal_targets,
                    units,
                    pairs,
                    relation,
                    status,
                    reason,
                    None,
                    evidence,
                    authorization_status,
                )
            ]
        eligible = {key: value for key, value in pairs.items() if value.state == "eligible"}
        matching = _exact_match(comparison, source_ids, target_ids, eligible)
        if matching.status == "budget_exhausted":
            return [
                self._assertion(
                    comparison,
                    projections,
                    source_ids,
                    target_ids,
                    units,
                    pairs,
                    None,
                    "indeterminate",
                    "matching_budget_exhausted",
                    matching,
                    evidence,
                    authorization_status,
                )
            ]
        if len(matching.surviving_solutions) > 1:
            return [
                self._assertion(
                    comparison,
                    projections,
                    source_ids,
                    target_ids,
                    units,
                    pairs,
                    None,
                    "indeterminate",
                    "structural_matching_ambiguity",
                    matching,
                    evidence,
                    authorization_status,
                )
            ]
        components = _components(matching.representative)
        assertions: list[dict[str, Any]] = []
        matched_sources = {source for source, _ in matching.representative}
        matched_targets = {target for _, target in matching.representative}
        for component_sources, component_targets in components:
            if len(component_sources) > 1 and len(component_targets) > 1:
                decompositions = cast(Mapping[str, Any], comparison["ambiguity_rules"]).get(
                    "many_to_many_decompositions", []
                )
                if not isinstance(decompositions, list) or len(decompositions) != 1:
                    assertions.append(
                        self._assertion(
                            comparison,
                            projections,
                            component_sources,
                            component_targets,
                            units,
                            pairs,
                            None,
                            "indeterminate",
                            "decomposition_ambiguity",
                            matching,
                            evidence,
                            authorization_status,
                        )
                    )
                    continue
                assertions.extend(
                    self._decomposed_assertions(
                        comparison,
                        projections,
                        component_sources,
                        component_targets,
                        units,
                        pairs,
                        decompositions[0],
                        matching,
                        evidence,
                        authorization_status,
                    )
                )
                continue
            relation = (
                "overlap"
                if len(component_sources) == len(component_targets) == 1
                else "split"
                if len(component_sources) == 1
                else "merge"
            )
            assertions.append(
                self._assertion(
                    comparison,
                    projections,
                    component_sources,
                    component_targets,
                    units,
                    pairs,
                    relation,
                    "resolved",
                    RELATION_REASON[relation],
                    matching,
                    evidence,
                    authorization_status,
                )
            )
        for source_id in sorted(set(source_ids) - matched_sources):
            reason, status = _unmatched_reason(source_id, target_ids, pairs, source_side=True)
            assertions.append(
                self._assertion(
                    comparison,
                    projections,
                    [source_id],
                    target_ids,
                    units,
                    pairs,
                    None,
                    status,
                    reason,
                    matching,
                    evidence,
                    authorization_status,
                )
            )
        for target_id in sorted(set(target_ids) - matched_targets):
            reason, status = _unmatched_reason(target_id, source_ids, pairs, source_side=False)
            assertions.append(
                self._assertion(
                    comparison,
                    projections,
                    source_ids,
                    [target_id],
                    units,
                    pairs,
                    None,
                    status,
                    reason,
                    matching,
                    evidence,
                    authorization_status,
                )
            )
        return assertions

    def _decomposed_assertions(
        self,
        comparison: Mapping[str, Any],
        projections: Sequence[Mapping[str, Any]],
        component_sources: Sequence[str],
        component_targets: Sequence[str],
        units: Mapping[str, UnitEvidence],
        pairs: Mapping[tuple[str, str], PairEvidence],
        decomposition: Any,
        matching: MatchResult,
        evidence: Mapping[str, Any],
        authorization_status: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(decomposition, list) or not decomposition:
            raise ContractError("invalid_comparison_spec", "decomposition must be nonempty")
        expected_edges = set(matching.representative)
        used_edges: set[tuple[str, str]] = set()
        assertions: list[dict[str, Any]] = []
        for part in decomposition:
            if not isinstance(part, Mapping):
                raise ContractError("invalid_comparison_spec", "decomposition part is invalid")
            source_ids = part.get("source_ids")
            target_ids = part.get("target_ids")
            relation = part.get("relation_type")
            if (
                not isinstance(source_ids, list)
                or not isinstance(target_ids, list)
                or relation not in {"overlap", "split", "merge"}
                or not set(source_ids).issubset(component_sources)
                or not set(target_ids).issubset(component_targets)
            ):
                raise ContractError("invalid_comparison_spec", "decomposition contract is invalid")
            part_edges = set(itertools.product(source_ids, target_ids)) & expected_edges
            if not part_edges or used_edges.intersection(part_edges):
                raise ContractError("invalid_comparison_spec", "decomposition edges are invalid")
            used_edges.update(part_edges)
            assertions.append(
                self._assertion(
                    comparison,
                    projections,
                    source_ids,
                    target_ids,
                    units,
                    pairs,
                    cast(str, relation),
                    "resolved",
                    RELATION_REASON[cast(str, relation)],
                    matching,
                    evidence,
                    authorization_status,
                )
            )
        if used_edges != expected_edges:
            raise ContractError("invalid_comparison_spec", "decomposition does not cover solution")
        return assertions

    def _assertion(
        self,
        comparison: Mapping[str, Any],
        projections: Sequence[Mapping[str, Any]],
        source_ids: Sequence[str],
        target_ids: Sequence[str],
        units: Mapping[str, UnitEvidence],
        pairs: Mapping[tuple[str, str], PairEvidence],
        relation_type: str | None,
        comparison_status: str,
        reason_code: str,
        matching: MatchResult | None,
        evidence: Mapping[str, Any],
        authorization_status: str,
    ) -> dict[str, Any]:
        timestamp = utc_timestamp()
        pair_values = [
            pairs[(source_id, target_id)]
            for source_id in source_ids
            for target_id in target_ids
            if (source_id, target_id) in pairs
        ]
        evidence_refs = _unique_refs(
            [
                *[reference for value in source_ids for reference in units[value].evidence_refs],
                *[reference for value in target_ids for reference in units[value].evidence_refs],
            ]
        )
        references = [
            record_ref(comparison["record_id"], "ComparisonSpec"),
            *[record_ref(value, "CandidateUnit") for value in source_ids],
            *[record_ref(value, "CandidateUnit") for value in target_ids],
            *[record_ref(value["record_id"], "ProjectionSpec") for value in projections],
            *evidence_refs,
        ]
        selected = list(matching.representative) if matching is not None else []
        assertion = record_base(
            "RelationAssertion", created_at=timestamp, references=references
        ) | {
            "source_refs": [record_ref(value, "CandidateUnit") for value in source_ids],
            "target_refs": [record_ref(value, "CandidateUnit") for value in target_ids],
            "direction": "source_to_target",
            "native_addresses": {
                "source": [
                    {
                        "candidate_record_id": value,
                        "address": units[value].candidate["native_address"],
                    }
                    for value in source_ids
                ],
                "target": [
                    {
                        "candidate_record_id": value,
                        "address": units[value].candidate["native_address"],
                    }
                    for value in target_ids
                ],
            },
            "comparison_substrate": dict(projections[0]["comparison_substrate"]),
            "projection_contract": {
                "source_projection_ref": record_ref(projections[0]["record_id"], "ProjectionSpec"),
                "target_projection_ref": record_ref(projections[1]["record_id"], "ProjectionSpec"),
                "exact_or_explicit_conversion": True,
            },
            "footprint_contract": {
                "source": dict(projections[0]["footprint_method"]),
                "target": dict(projections[1]["footprint_method"]),
                "comparable": _footprint_contract(projections[0])
                == _footprint_contract(projections[1]),
            },
            "effect_contract": dict(comparison["qste:effectComparison"]),
            "coverage": {
                "threshold": comparison["coverage_threshold"],
                "eligibility_uses": "adjusted_lower_bounds",
                "failure_uses": "adjusted_upper_bounds",
                "pairs": [_pair_payload(value) for value in pair_values],
            },
            "effect_difference_interval": {
                "tolerance": comparison["effect_tolerance"],
                "pairs": [
                    {
                        "source_record_id": value.source_id,
                        "target_record_id": value.target_id,
                        "lower": value.effect_difference[0],
                        "upper": value.effect_difference[1],
                        "point_estimate": value.effect_difference[2],
                    }
                    for value in pair_values
                ],
            },
            "effect_tolerance": comparison["effect_tolerance"],
            "controls": {
                "pairs": [value.controls for value in pair_values],
                "all_passed": all(
                    value.state not in {"loss", "incomplete"} for value in pair_values
                ),
            },
            "matching_contract": {
                "capacities": comparison["capacities"],
                "cardinalities": comparison["cardinalities"],
                "unmatched_penalty": comparison["unmatched_penalty"],
                "primary_objective": comparison["primary_objective"],
                "cardinality_preference": comparison["cardinality_preference"][0],
                "optimization_tolerance": comparison["optimization_tolerance"],
                "solver": comparison["qste:solver"],
                "unmatched_indicator_equivalence": "both_directions_encoded",
            },
            "solution_evidence": {
                "primary_optimum": matching.primary_optimum if matching else None,
                "surviving_optimum_count": (len(matching.surviving_solutions) if matching else 0),
                "surviving_optimum_count_kind": "exact",
                "evaluated_subsets": matching.evaluated_subsets if matching else 0,
                "solver_independent_verification": (
                    matching.verification_status if matching else "not_applicable"
                ),
                "diagnostic_representative": [list(value) for value in selected],
                "lexicographic_replay_is_diagnostic_only": True,
                "decomposition": evidence.get("decomposition_evidence", []),
            },
            "comparison_spec_ref": record_ref(comparison["record_id"], "ComparisonSpec"),
            "relation_type": relation_type,
            "comparison_status": comparison_status,
            "reason_code": reason_code,
            "perturbation_stability": _aggregate_stability(source_ids, target_ids, units),
            "evidence_refs": evidence_refs,
            "qste:relationProfile": RELATION_PROFILE,
            "qste:authorizationStatus": authorization_status,
            "qste:dependencyValidity": "valid",
            "qste:nativeIdentityPreserved": True,
        }
        bind_semantic_key(
            assertion,
            "qste-semantic-key/cross-arm-relation-v1",
            {
                "comparison_semantic_key": comparison["semantic_key"],
                "source_semantic_keys": [
                    units[value].candidate["semantic_key"] for value in source_ids
                ],
                "target_semantic_keys": [
                    units[value].candidate["semantic_key"] for value in target_ids
                ],
                "evidence_digest": content_digest(canonical_json_bytes(evidence)),
                "relation_type": relation_type,
                "comparison_status": comparison_status,
                "reason_code": reason_code,
            },
        )
        return assertion

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
            authorization_status=(
                authorization_status
                if authorization_status in {"permitted", "refused"}
                else "not_applicable"
            ),
            operation=operation,
            inputs=[record_ref(subject["record_id"], subject["record_type"])],
            parameters={**dict(parameters), "failure_reason": error.reason_code},
            outputs=[{"availability": "unavailable", "reason": error.reason_code}],
            operation_status="refused" if error.reason_code == "policy_refused" else "failed",
            tool_id="qste-p7-relation-engine",
            tool_version="v0.1",
        )
        _, _event = self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:p7-operation-failed/0.1",
            subject_record_id=subject["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"operation": operation, "reason_code": error.reason_code},
            created_at=timestamp,
        )
        return cast(str, receipt["record_id"])


def _validate_projection_input(spec: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "comparison_substrate",
        "measure",
        "footprint_method",
        "calibration",
        "alignment",
        "uncertainty",
        "failure_conditions",
        "effect_contract",
    }
    if set(spec) != required:
        raise ContractError("invalid_comparison_spec", "projection fields are not exact")
    substrate = _mapping(spec["comparison_substrate"], "comparison substrate")
    if not all(
        isinstance(substrate.get(key), str) and substrate.get(key) for key in ("id", "version")
    ):
        raise ContractError("invalid_comparison_spec", "substrate identity is incomplete")
    axes = substrate.get("axes")
    if not isinstance(axes, list) or not axes or not all(isinstance(value, str) for value in axes):
        raise ContractError("invalid_comparison_spec", "substrate axes are invalid")
    measure = _mapping(spec["measure"], "measure")
    if measure.get("id") != "weighted_sum" or not isinstance(measure.get("units"), str):
        raise ContractError("invalid_comparison_spec", "P7 measure must be weighted_sum with units")
    method = _mapping(spec["footprint_method"], "footprint method")
    kind = method.get("kind")
    if kind not in {"expected_energy_change", "exceedance_probability"}:
        raise ContractError("invalid_comparison_spec", "unknown footprint kind")
    expected_normalization = "unit_integral" if kind == "expected_energy_change" else "none"
    if method.get("normalization") != expected_normalization:
        raise ContractError("invalid_comparison_spec", "footprint normalization is inconsistent")
    floor = _finite_nonnegative(method.get("floor"), "footprint floor")
    if not isinstance(method.get("weighting"), str):
        raise ContractError("invalid_comparison_spec", "footprint weighting is absent")
    calibration = _mapping(spec["calibration"], "calibration")
    if calibration.get("status") != "calibrated" or not calibration.get("evidence"):
        raise ContractError("invalid_comparison_spec", "comparison substrate is not calibrated")
    alignment = _mapping(spec["alignment"], "alignment")
    uncertainty = _mapping(spec["uncertainty"], "uncertainty")
    failures = spec["failure_conditions"]
    if not isinstance(failures, list) or not failures:
        raise ContractError("invalid_comparison_spec", "projection failure conditions are absent")
    effect_contract = _effect_contract(spec["effect_contract"])
    return {
        "comparison_substrate": dict(substrate),
        "measure": dict(measure),
        "footprint_method": {**dict(method), "floor": floor},
        "calibration": dict(calibration),
        "alignment": dict(alignment),
        "uncertainty": dict(uncertainty),
        "failure_conditions": list(failures),
        "effect_contract": effect_contract,
    }


def _validate_comparison_input(spec: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "coverage_threshold",
        "effect_tolerance",
        "capacities",
        "cardinalities",
        "unmatched_penalty",
        "estimators",
        "primary_objective",
        "cardinality_preference",
        "optimization_tolerance",
        "ambiguity_rules",
        "budget",
        "effect_contract",
        "effect_conversions",
        "coverage_uncertainty",
    }
    if set(spec) != required:
        raise ContractError("invalid_comparison_spec", "comparison fields are not exact")
    threshold = _finite(spec["coverage_threshold"], "coverage threshold")
    effect_tolerance = _finite_nonnegative(spec["effect_tolerance"], "effect tolerance")
    penalty = _finite_nonnegative(spec["unmatched_penalty"], "unmatched penalty")
    optimization_tolerance = _finite_nonnegative(
        spec["optimization_tolerance"], "optimization tolerance"
    )
    if not 0 <= threshold <= 1:
        raise ContractError("invalid_comparison_spec", "coverage threshold is outside [0,1]")
    capacities = _mapping(spec["capacities"], "capacities")
    for key in ("source_default", "target_default", "maximum_n"):
        _bounded_positive_int(capacities.get(key), key, 1, MAX_UNITS_PER_SIDE)
    cardinalities = spec["cardinalities"]
    if (
        not isinstance(cardinalities, list)
        or not cardinalities
        or len(set(cardinalities)) != len(cardinalities)
        or not set(cardinalities).issubset({"1:1", "1:n", "n:1"})
    ):
        raise ContractError("invalid_comparison_spec", "allowed cardinalities are invalid")
    estimators = _mapping(spec["estimators"], "estimators")
    if estimators.get("coverage") != "interval_bounds" or estimators.get("edge_cost") != (
        "mean_directional_point_coverage"
    ):
        raise ContractError("invalid_comparison_spec", "P7 estimators are not canonical")
    if spec["primary_objective"] != "minimum_cost_b_matching":
        raise ContractError("invalid_comparison_spec", "P7 objective is not canonical")
    preference = spec["cardinality_preference"]
    if preference not in {"fewer_edges", "more_edges"}:
        raise ContractError("invalid_comparison_spec", "cardinality preference is invalid")
    ambiguity = _mapping(spec["ambiguity_rules"], "ambiguity rules")
    if (
        ambiguity.get("evaluate_before_lexicographic_replay") is not True
        or ambiguity.get("lexicographic_native_address_order") is not True
        or not isinstance(ambiguity.get("many_to_many_decompositions"), list)
    ):
        raise ContractError("invalid_comparison_spec", "ambiguity rules are incomplete")
    budget = _mapping(spec["budget"], "budget")
    maximum_edges = _bounded_positive_int(
        budget.get("maximum_edges"), "maximum edges", 1, MAX_EDGES
    )
    maximum_subsets = _bounded_positive_int(
        budget.get("maximum_subsets"), "maximum subsets", 1, MAX_SUBSETS
    )
    uncertainty = _mapping(spec["coverage_uncertainty"], "coverage uncertainty")
    if uncertainty.get("method") != "deterministic_tolerance":
        raise ContractError("invalid_comparison_spec", "unsupported coverage uncertainty method")
    half_width = _finite_nonnegative(uncertainty.get("half_width"), "coverage half width")
    conversions = spec["effect_conversions"]
    if not isinstance(conversions, Mapping):
        raise ContractError("invalid_comparison_spec", "effect conversions must be an object")
    for value in conversions.values():
        if not isinstance(value, Mapping) or not value.get("id") or not value.get("version"):
            raise ContractError("invalid_comparison_spec", "effect conversion is not versioned")
    return {
        "coverage_threshold": threshold,
        "effect_tolerance": effect_tolerance,
        "capacities": dict(capacities),
        "cardinalities": list(cardinalities),
        "unmatched_penalty": penalty,
        "estimators": dict(estimators),
        "primary_objective": "minimum_cost_b_matching",
        "cardinality_preference": preference,
        "optimization_tolerance": optimization_tolerance,
        "ambiguity_rules": dict(ambiguity),
        "budget": {"maximum_edges": maximum_edges, "maximum_subsets": maximum_subsets},
        "effect_contract": _effect_contract(spec["effect_contract"]),
        "effect_conversions": dict(conversions),
        "coverage_uncertainty": {"method": "deterministic_tolerance", "half_width": half_width},
    }


def _validate_projection_pair(
    projections: Sequence[Mapping[str, Any]], comparison: Mapping[str, Any]
) -> None:
    if (
        projections[0].get("qste:projectionProfile") != PROJECTION_PROFILE
        or projections[1].get("qste:projectionProfile") != PROJECTION_PROFILE
    ):
        raise ContractError("invalid_comparison_spec", "projection profile is not executable")
    if (
        projections[0]["source_arm_ref"]["record_id"]
        == projections[1]["source_arm_ref"]["record_id"]
    ):
        raise ContractError("invalid_comparison_spec", "comparison arms must be distinct")
    if _projection_substrate_contract(projections[0]) != _projection_substrate_contract(
        projections[1]
    ):
        raise ContractError("invalid_comparison_spec", "projection substrates are incompatible")
    if _footprint_contract(projections[0]) != _footprint_contract(projections[1]):
        raise ContractError("invalid_comparison_spec", "footprint contracts are incompatible")
    common = comparison["effect_contract"]
    conversions = cast(Mapping[str, Any], comparison["effect_conversions"])
    for projection in projections:
        if (
            projection["qste:effectContract"] != common
            and projection["record_id"] not in conversions
        ):
            raise ContractError("invalid_comparison_spec", "effect estimands are incompatible")


def _validate_candidate_arms(
    sources: Sequence[Mapping[str, Any]],
    targets: Sequence[Mapping[str, Any]],
    projections: Sequence[Mapping[str, Any]],
) -> None:
    source_arm = projections[0]["source_arm_ref"]["record_id"]
    target_arm = projections[1]["source_arm_ref"]["record_id"]
    if any(value["representation_instance_ref"]["record_id"] != source_arm for value in sources):
        raise ContractError("invalid_comparison_spec", "source candidate belongs to another arm")
    if any(value["representation_instance_ref"]["record_id"] != target_arm for value in targets):
        raise ContractError("invalid_comparison_spec", "target candidate belongs to another arm")


def _pair_evidence(
    comparison: Mapping[str, Any],
    projections: Sequence[Mapping[str, Any]],
    sources: Sequence[Mapping[str, Any]],
    targets: Sequence[Mapping[str, Any]],
    units: Mapping[str, UnitEvidence],
    evidence: Mapping[str, Any],
) -> dict[tuple[str, str], PairEvidence]:
    raw_pairs = evidence.get("pairs")
    if not isinstance(raw_pairs, Mapping):
        raise ContractError("invalid_comparison_spec", "pair controls are required")
    tolerance = cast(float, comparison["qste:coverageUncertainty"]["half_width"])
    threshold = cast(float, comparison["coverage_threshold"])
    effect_tolerance = cast(float, comparison["effect_tolerance"])
    weights = cast(Mapping[str, Any], projections[0]["measure"]).get("weights")
    result: dict[tuple[str, str], PairEvidence] = {}
    for source in sources:
        for target in targets:
            source_id = cast(str, source["record_id"])
            target_id = cast(str, target["record_id"])
            pair_key = f"{source_id}|{target_id}"
            raw = raw_pairs.get(pair_key)
            if not isinstance(raw, Mapping):
                state = "incomplete"
                controls: dict[str, Any] = {
                    "pair_key": pair_key,
                    "availability": "unavailable",
                }
            else:
                address = raw.get("target_address")
                fidelity = raw.get("fidelity")
                consequentiality = raw.get("consequentiality")
                artifact_controls = raw.get("artifact_controls")
                allowed = {
                    "target_address": {"exists", "absent", "incomplete"},
                    "fidelity": {"passed", "failed", "incomplete"},
                    "consequentiality": {"passed", "failed", "incomplete"},
                    "artifact_controls": {"passed", "failed", "incomplete"},
                }
                values = {
                    "target_address": address,
                    "fidelity": fidelity,
                    "consequentiality": consequentiality,
                    "artifact_controls": artifact_controls,
                }
                if any(values[key] not in allowed[key] for key in allowed):
                    raise ContractError("invalid_comparison_spec", "pair control token is invalid")
                controls = {"pair_key": pair_key, **values}
                state = "pending"
                if address == "absent":
                    state = "omission"
                elif "failed" in {fidelity, consequentiality, artifact_controls}:
                    state = "loss"
                elif "incomplete" in {address, fidelity, consequentiality, artifact_controls}:
                    state = "incomplete"
            source_unit = units[source_id]
            target_unit = units[target_id]
            if source_unit.projection_status != "valid" or target_unit.projection_status != "valid":
                projection_state = (
                    "projection_invalid"
                    if "invalid" in {source_unit.projection_status, target_unit.projection_status}
                    else "capability_unavailable"
                    if "capability_unavailable"
                    in {source_unit.projection_status, target_unit.projection_status}
                    else "incomplete"
                )
                result[(source_id, target_id)] = PairEvidence(
                    source_id,
                    target_id,
                    (0.0, 0.0, 0.0),
                    (0.0, 0.0, 0.0),
                    (0.0, 0.0, 0.0),
                    1.0,
                    projection_state,
                    controls,
                )
                continue
            source_coverage = _coverage(source_unit, target_unit, weights)
            target_coverage = _coverage(target_unit, source_unit, weights)
            source_interval = _bounded_interval(source_coverage, tolerance, 0.0, 1.0)
            target_interval = _bounded_interval(target_coverage, tolerance, 0.0, 1.0)
            effect = (
                source_unit.effect_interval[0] - target_unit.effect_interval[1],
                source_unit.effect_interval[1] - target_unit.effect_interval[0],
                source_unit.effect_point - target_unit.effect_point,
            )
            if state == "pending":
                if source_unit.footprint_mass == 0 or target_unit.footprint_mass == 0:
                    state = "zero_footprint"
                elif source_interval[0] >= threshold and target_interval[0] >= threshold:
                    if effect[0] >= -effect_tolerance and effect[1] <= effect_tolerance:
                        state = "eligible"
                    elif effect[1] < -effect_tolerance or effect[0] > effect_tolerance:
                        state = "effect_failed"
                    else:
                        state = "effect_boundary"
                elif source_interval[1] < threshold or target_interval[1] < threshold:
                    state = "coverage_failed"
                else:
                    state = "coverage_boundary"
            cost = 1.0 - (source_coverage + target_coverage) / 2.0
            result[(source_id, target_id)] = PairEvidence(
                source_id,
                target_id,
                (source_interval[0], source_interval[1], source_coverage),
                (target_interval[0], target_interval[1], target_coverage),
                effect,
                cost,
                state,
                controls,
            )
    return result


def _global_terminal(
    source_ids: Sequence[str],
    target_ids: Sequence[str],
    units: Mapping[str, UnitEvidence],
    pairs: Mapping[tuple[str, str], PairEvidence],
) -> tuple[str | None, str, str, Sequence[str], Sequence[str]] | None:
    invalid = [
        value for value in [*source_ids, *target_ids] if units[value].projection_status == "invalid"
    ]
    if invalid:
        return "incomparable", "resolved", "projection_invalid", source_ids, target_ids
    unavailable = [
        value
        for value in [*source_ids, *target_ids]
        if units[value].projection_status == "capability_unavailable"
    ]
    if unavailable:
        return None, "indeterminate", "comparison_capability_unavailable", source_ids, target_ids
    incomplete = [
        value
        for value in [*source_ids, *target_ids]
        if units[value].projection_status == "incomplete"
    ]
    if incomplete:
        return None, "indeterminate", "eligible_evidence_incomplete", source_ids, target_ids
    states = {value.state for value in pairs.values()}
    if states == {"omission"}:
        return "omission", "resolved", "target_address_absent", source_ids, target_ids
    if "loss" in states and states.issubset({"loss", "omission"}):
        return "loss", "resolved", "fidelity_failed", source_ids, target_ids
    if states == {"zero_footprint"}:
        return None, "indeterminate", "zero_footprint_undefined", source_ids, target_ids
    if states == {"incomplete"}:
        return None, "indeterminate", "eligible_evidence_incomplete", source_ids, target_ids
    return None


def _exact_match(
    comparison: Mapping[str, Any],
    source_ids: Sequence[str],
    target_ids: Sequence[str],
    eligible: Mapping[tuple[str, str], PairEvidence],
) -> MatchResult:
    edges = tuple(sorted(eligible))
    budget = cast(Mapping[str, int], comparison["budget"])
    required_subsets = 1 << len(edges)
    if len(edges) > budget["maximum_edges"] or required_subsets > budget["maximum_subsets"]:
        return MatchResult("budget_exhausted", None, (), (), 0, "not_applicable")
    capacities = cast(Mapping[str, Any], comparison["capacities"])
    source_overrides = capacities.get("source_overrides", {})
    target_overrides = capacities.get("target_overrides", {})
    source_cap = {
        value: int(source_overrides.get(value, capacities["source_default"]))
        for value in source_ids
    }
    target_cap = {
        value: int(target_overrides.get(value, capacities["target_default"]))
        for value in target_ids
    }
    solutions: list[tuple[float, tuple[tuple[str, str], ...]]] = []
    for mask in range(required_subsets):
        selected = tuple(edges[index] for index in range(len(edges)) if mask & (1 << index))
        source_degree = {value: 0 for value in source_ids}
        target_degree = {value: 0 for value in target_ids}
        for source_id, target_id in selected:
            source_degree[source_id] += 1
            target_degree[target_id] += 1
        if any(source_degree[value] > source_cap[value] for value in source_ids) or any(
            target_degree[value] > target_cap[value] for value in target_ids
        ):
            continue
        if not _cardinalities_permit(comparison, selected):
            continue
        unmatched = sum(value == 0 for value in source_degree.values()) + sum(
            value == 0 for value in target_degree.values()
        )
        objective = (
            sum(eligible[value].cost for value in selected)
            + cast(float, comparison["unmatched_penalty"]) * unmatched
        )
        solutions.append((objective, selected))
    if not solutions:
        raise ContractError("invalid_comparison_spec", "matching contract has no feasible solution")
    optimum = min(value[0] for value in solutions)
    tolerance = cast(float, comparison["optimization_tolerance"])
    primary = [value for value in solutions if value[0] <= optimum + tolerance]
    preference = comparison["cardinality_preference"][0]
    edge_count = (
        min(len(value[1]) for value in primary)
        if preference == "fewer_edges"
        else max(len(value[1]) for value in primary)
    )
    survivors = tuple(sorted(value[1] for value in primary if len(value[1]) == edge_count))
    result = MatchResult("complete", optimum, survivors, survivors[0], required_subsets, "pending")
    _verify_matching_certificate(comparison, source_ids, target_ids, eligible, result)
    return MatchResult(
        result.status,
        result.primary_optimum,
        result.surviving_solutions,
        result.representative,
        result.evaluated_subsets,
        "passed",
    )


def _verify_matching_certificate(
    comparison: Mapping[str, Any],
    source_ids: Sequence[str],
    target_ids: Sequence[str],
    eligible: Mapping[tuple[str, str], PairEvidence],
    result: MatchResult,
) -> None:
    """Recompute feasibility and objective without trusting enumerator bookkeeping."""

    if result.primary_optimum is None or not result.surviving_solutions:
        raise ContractError("conformance_failed", "exact matcher emitted no optimum certificate")
    capacities = cast(Mapping[str, Any], comparison["capacities"])
    source_overrides = capacities.get("source_overrides", {})
    target_overrides = capacities.get("target_overrides", {})
    source_cap = {
        value: int(source_overrides.get(value, capacities["source_default"]))
        for value in source_ids
    }
    target_cap = {
        value: int(target_overrides.get(value, capacities["target_default"]))
        for value in target_ids
    }
    tolerance = cast(float, comparison["optimization_tolerance"])
    preference = comparison["cardinality_preference"][0]
    expected_count = (
        min(len(value) for value in result.surviving_solutions)
        if preference == "fewer_edges"
        else max(len(value) for value in result.surviving_solutions)
    )
    for solution in result.surviving_solutions:
        if len(solution) != expected_count or not set(solution).issubset(eligible):
            raise ContractError("conformance_failed", "matching survivor set is inconsistent")
        source_degree = {value: 0 for value in source_ids}
        target_degree = {value: 0 for value in target_ids}
        for source_id, target_id in solution:
            source_degree[source_id] += 1
            target_degree[target_id] += 1
        if any(source_degree[value] > source_cap[value] for value in source_ids) or any(
            target_degree[value] > target_cap[value] for value in target_ids
        ):
            raise ContractError("conformance_failed", "matching certificate violates capacity")
        if not _cardinalities_permit(comparison, solution):
            raise ContractError("conformance_failed", "matching certificate violates cardinality")
        source_unmatched = {value: source_degree[value] == 0 for value in source_ids}
        target_unmatched = {value: target_degree[value] == 0 for value in target_ids}
        unmatched_count = sum(source_unmatched.values()) + sum(target_unmatched.values())
        objective = (
            sum(eligible[value].cost for value in solution)
            + cast(float, comparison["unmatched_penalty"]) * unmatched_count
        )
        if objective > result.primary_optimum + tolerance:
            raise ContractError("conformance_failed", "matching objective certificate is invalid")
    if result.representative != min(result.surviving_solutions):
        raise ContractError("conformance_failed", "diagnostic replay is not lexicographic")


def _cardinalities_permit(
    comparison: Mapping[str, Any], selected: Sequence[tuple[str, str]]
) -> bool:
    allowed = set(cast(Sequence[str], comparison["cardinalities"]))
    maximum_n = cast(int, comparison["capacities"]["maximum_n"])
    decompositions = cast(Mapping[str, Any], comparison["ambiguity_rules"])[
        "many_to_many_decompositions"
    ]
    for sources, targets in _components(selected):
        if len(sources) == len(targets) == 1 and "1:1" not in allowed:
            return False
        if (
            len(sources) == 1
            and len(targets) > 1
            and ("1:n" not in allowed or len(targets) > maximum_n)
        ):
            return False
        if (
            len(sources) > 1
            and len(targets) == 1
            and ("n:1" not in allowed or len(sources) > maximum_n)
        ):
            return False
        if len(sources) > 1 and len(targets) > 1 and not decompositions:
            return False
    return True


def _components(
    edges: Sequence[tuple[str, str]],
) -> list[tuple[list[str], list[str]]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        left = f"L:{source}"
        right = f"R:{target}"
        adjacency[left].add(right)
        adjacency[right].add(left)
    remaining = set(adjacency)
    result: list[tuple[list[str], list[str]]] = []
    while remaining:
        root = min(remaining)
        queue = deque([root])
        visited: set[str] = set()
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(sorted(adjacency[node] - visited))
        remaining.difference_update(visited)
        sources = sorted(value[2:] for value in visited if value.startswith("L:"))
        targets = sorted(value[2:] for value in visited if value.startswith("R:"))
        result.append((sources, targets))
    return result


def _unmatched_reason(
    unit_id: str,
    opposite_ids: Sequence[str],
    pairs: Mapping[tuple[str, str], PairEvidence],
    *,
    source_side: bool,
) -> tuple[str, str]:
    values = [
        pairs[(unit_id, other)] if source_side else pairs[(other, unit_id)]
        for other in opposite_ids
    ]
    states = {value.state for value in values}
    if "coverage_boundary" in states:
        return "coverage_boundary_crossing", "indeterminate"
    if "effect_boundary" in states:
        return "effect_boundary_crossing", "indeterminate"
    if "zero_footprint" in states:
        return "zero_footprint_undefined", "indeterminate"
    if "incomplete" in states:
        return "eligible_evidence_incomplete", "indeterminate"
    if "coverage_failed" in states:
        return "coverage_failed", "resolved"
    if "effect_failed" in states:
        return "effect_incompatible", "resolved"
    return "unmatched_by_spec", "resolved"


def _coverage(source: UnitEvidence, target: UnitEvidence, weights: Any) -> float:
    if source.footprint_mass == 0:
        return 0.0
    measure_weights = (
        tuple(cast(Sequence[float], weights))
        if isinstance(weights, list)
        else (1.0,) * len(source.footprint)
    )
    overlap = sum(
        min(left, right) * weight
        for left, right, weight in zip(
            source.footprint, target.footprint, measure_weights, strict=True
        )
    )
    return overlap / source.footprint_mass


def _bounded_interval(
    point: float, half_width: float, minimum: float, maximum: float
) -> tuple[float, float]:
    return max(minimum, point - half_width), min(maximum, point + half_width)


def _pair_payload(value: PairEvidence) -> dict[str, Any]:
    return {
        "source_record_id": value.source_id,
        "target_record_id": value.target_id,
        "source_to_target": {
            "lower": value.source_to_target[0],
            "upper": value.source_to_target[1],
            "point_estimate": value.source_to_target[2],
        },
        "target_to_source": {
            "lower": value.target_to_source[0],
            "upper": value.target_to_source[1],
            "point_estimate": value.target_to_source[2],
        },
        "edge_state": value.state,
        "edge_cost": value.cost,
    }


def _projection_substrate_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "comparison_substrate": value["comparison_substrate"],
        "measure": value["measure"],
        "calibration": value["calibration"],
        "alignment": value["qste:alignment"],
    }


def _footprint_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "comparison_substrate": value["comparison_substrate"],
        "measure": value["measure"],
        "footprint_method": value["footprint_method"],
        "calibration": value["calibration"],
        "alignment": value["qste:alignment"],
    }


def _effect_contract(value: Any) -> dict[str, Any]:
    contract = _mapping(value, "effect contract")
    required = {
        "response_variable",
        "units",
        "direction_orientation",
        "fixed_context",
        "aggregation_level",
        "estimand",
    }
    if set(contract) != required or not all(contract.get(key) is not None for key in required):
        raise ContractError("invalid_comparison_spec", "effect contract is incomplete")
    return dict(contract)


def _aggregate_stability(
    source_ids: Sequence[str], target_ids: Sequence[str], units: Mapping[str, UnitEvidence]
) -> str:
    values = {units[value].perturbation_stability for value in [*source_ids, *target_ids]}
    return values.pop() if len(values) == 1 else "indeterminate"


def _unique_refs(values: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        key = (value["record_id"], value["record_type"], value["relation"])
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ContractError("invalid_comparison_spec", f"{name} must be a nonempty object")
    return value


def _finite(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ContractError("invalid_comparison_spec", f"{name} must be finite")
    return float(value)


def _finite_nonnegative(value: Any, name: str) -> float:
    result = _finite(value, name)
    if result < 0:
        raise ContractError("invalid_comparison_spec", f"{name} must be nonnegative")
    return result


def _finite_positive(value: Any, name: str) -> float:
    result = _finite(value, name)
    if result <= 0:
        raise ContractError("invalid_comparison_spec", f"{name} must be positive")
    return result


def _bounded_positive_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum or value > maximum:
        raise ContractError(
            "invalid_comparison_spec", f"{name} must be between {minimum} and {maximum}"
        )
    return value
