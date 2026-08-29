#!/usr/bin/env python3
"""Generate the deterministic QSTE 0.3.0 schema and conformance corpus.

The ontology is the semantic authority.  This file is a compact implementation
index: it names every serialized record, typed payload, controlled token, and
P2 validation fixture without introducing compatibility aliases.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.3.0"
CONTRACT_ID = "qste-contract/0.3.0"
SCHEMA_SET_ID = "qste-schema/0.3.0"
CONFORMANCE_ID = "qste-conformance/0.3.0"
BASE_URI = f"https://schemas.qste.invalid/{VERSION}"
COMMON_ID = f"{BASE_URI}/common.schema.json"

Json = dict[str, Any]


VOCABULARIES: dict[str, list[str]] = {
    "producer_role": [
        "instrument",
        "model",
        "executor",
        "human",
        "external_service",
        "hybrid_procedure",
    ],
    "evidence_basis": [
        "directly_recorded",
        "calibrated_measurement",
        "instrumentally_derived",
        "model_inferred",
        "human_reported",
        "theoretically_reconstructed",
    ],
    "epistemic_status": [
        "measured",
        "derived",
        "model_inferred",
        "human_heard",
        "interpreted",
        "speculative",
        "undetermined",
    ],
    "availability": ["known", "unknown", "unavailable", "withheld", "deleted", "not_applicable"],
    "integrity_status": ["unverified", "verified", "failed", "unavailable"],
    "disclosure_status": ["private", "restricted", "project_internal", "public"],
    "consent_status": ["not_applicable", "pending", "granted", "declined", "withdrawn", "expired"],
    "assessment_status": ["qualified", "rejected", "indeterminate"],
    "dependency_validity": ["valid", "invalidated"],
    "assessment_reason": [
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
    ],
    "invalidation_reason": [
        "source_integrity_defect",
        "acquisition_or_calibration_defect",
        "representation_defect",
        "intervention_defect",
        "task_or_estimator_defect",
        "uncertainty_or_multiplicity_defect",
        "implementation_defect",
        "upstream_dependency_invalidated",
    ],
    "relation_type": ["overlap", "split", "merge", "omission", "loss", "incomparable"],
    "comparison_status": ["resolved", "indeterminate"],
    "effect_compatibility": ["compatible", "incompatible", "indeterminate"],
    "perturbation_stability": ["stable", "unstable", "indeterminate", "not_tested"],
    "comparison_reason": [
        "matched_overlap",
        "matched_split",
        "matched_merge",
        "projection_invalid",
        "target_address_absent",
        "fidelity_failed",
        "zero_footprint_undefined",
        "coverage_failed",
        "effect_incompatible",
        "unmatched_by_spec",
        "coverage_boundary_crossing",
        "effect_boundary_crossing",
        "structural_matching_ambiguity",
        "decomposition_ambiguity",
        "eligible_evidence_incomplete",
        "matching_budget_exhausted",
        "comparison_capability_unavailable",
    ],
    "decision_action": ["execute", "revise", "refuse", "escalate", "pause", "resume", "no_change"],
    "operation_status": ["completed", "refused", "unavailable", "failed", "partial"],
    "operation_reason": [
        "completed",
        "invalid_input",
        "invalid_assessment_spec",
        "invalid_comparison_spec",
        "policy_refused",
        "capability_unavailable",
        "execution_failed",
        "partial_completion",
        "internal_error",
        "conformance_failed",
    ],
    "authorization_status": ["unknown", "permitted", "refused", "deferred", "revoked", "not_applicable"],
    "capability_status": ["available", "unavailable", "degraded", "prohibited", "untested"],
    "appeal_status": ["opened", "under_review", "adjudicated", "closed"],
    "pause_status": ["not_requested", "requested", "active", "denied", "released"],
    "adjudication_outcome": ["not_decided", "upheld", "denied", "partial", "escalated", "withdrawn"],
    "repair_status": ["not_requested", "pending", "applied", "partially_applied", "impossible", "superseded"],
    "repair_action": ["pause", "correct", "revoke", "delete", "restrict", "restore", "release_pause"],
    "governance_reason": [
        "standing_unverified",
        "standing_denied",
        "authority_unresolved",
        "jurisdiction_declined",
        "pause_risk_threshold_met",
        "pause_risk_threshold_not_met",
        "appeal_withdrawn",
        "requested_remedy_upheld",
        "requested_remedy_denied",
        "requested_remedy_partial",
        "repair_completed",
        "repair_partially_completed",
        "repair_not_feasible",
        "retention_duty_blocks_deletion",
        "external_copy_out_of_scope",
        "superseded_by_successor_case",
    ],
    "transduction_mode": [
        "sonification",
        "desonification",
        "resonification",
        "sonic_transformation",
        "cross_domain_contrast",
    ],
    "record_level": ["ordinary", "formation_only", "full_assessment"],
    "revision_treatment": ["authentic", "absent", "placebo", "permuted"],
}

SERIALIZED_RECORDS = [
    "AcquisitionEvent",
    "SourceRecord",
    "ArtifactRecord",
    "ObservationRecord",
    "ApparatusSpec",
    "ApertureSpec",
    "RepresentationFamilySpec",
    "RepresentationSpec",
    "RepresentationInstance",
    "CandidateUnit",
    "InterventionSpec",
    "TaskSpec",
    "RefinementGraph",
    "DSQAssessment",
    "ProjectionSpec",
    "ComparisonSpec",
    "RelationAssertion",
    "MappingSpec",
    "ListeningHarnessSpec",
    "GovernanceBoundary",
    "RevisionOpportunity",
    "SuccessorSpec",
    "DecisionEvent",
    "AppealCase",
    "RepairAction",
    "RepairReceipt",
    "OperationReceipt",
    "ListeningAccount",
    "ClaimRecord",
    "AuthorityManifest",
    "RunManifest",
]

TYPED_PAYLOADS = [
    "AddressabilityResult",
    "AdjudicationDecision",
    "CandidateSet",
    "CapabilityAccount",
    "IntervenedState",
    "NativeMeasure",
    "ObservationSet",
    "ProjectedFootprint",
    "RelationSet",
    "RepairPropagation",
    "RevisionOutcome",
    "SupportEstimate",
    "TargetClosure",
]


def slug(name: str) -> str:
    acronym_aware = re.sub(r"(.)([A-Z][a-z]+)", r"\1-\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", acronym_aware).lower()


def schema_id(name: str) -> str:
    return f"{BASE_URI}/records/{slug(name)}.schema.json"


def field(schema: Json, sample: Any, maximal: Any | None = None) -> Json:
    return {"schema": schema, "sample": sample, "maximal": sample if maximal is None else maximal}


def text(sample: str) -> Json:
    return field({"type": "string", "minLength": 1}, sample)


def number(sample: float, *, minimum: float | None = None) -> Json:
    value: Json = {"type": "number"}
    if minimum is not None:
        value["minimum"] = minimum
    return field(value, sample)


def integer(sample: int, *, minimum: int = 0) -> Json:
    return field({"type": "integer", "minimum": minimum}, sample)


def boolean(sample: bool) -> Json:
    return field({"type": "boolean"}, sample)


def obj(sample: Json) -> Json:
    return field({"type": "object", "minProperties": 1}, sample)


def array(sample: list[Any], *, items: Json | None = None) -> Json:
    return field({"type": "array", "minItems": 1, "items": items or {}}, sample)


def enum(vocabulary: str, sample: str | None = None) -> Json:
    return field({"$ref": f"{COMMON_ID}#/$defs/{vocabulary}"}, sample or VOCABULARIES[vocabulary][0])


def ref(record_type: str, seed: int = 1) -> Json:
    return field(
        {"$ref": f"{COMMON_ID}#/$defs/recordReference"},
        {"record_id": fixture_id(record_type, seed), "record_type": record_type, "relation": "depends_on"},
    )


def refs(record_type: str, seed: int = 1) -> Json:
    return array(
        [ref(record_type, seed)["sample"]],
        items={"$ref": f"{COMMON_ID}#/$defs/recordReference"},
    )


def fixture_id(record_type: str, seed: int = 0) -> str:
    digest = bytearray(hashlib.sha256(f"{record_type}:{seed}".encode()).digest()[:16])
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    raw = digest.hex()
    value = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return f"qste:{slug(record_type)}:{value}"


def digest(char: str) -> str:
    return f"sha256:{char * 64}"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def specs() -> dict[str, Json]:
    # Required fields follow ontology §§3.2 and 16.  Objects that acquire a
    # narrower mathematical contract in later phases remain structured, never
    # flattened to an opaque string.
    return {
        "AcquisitionEvent": {"apparatus_ref": ref("ApparatusSpec"), "provider_or_channel": text("local_input"), "temporal_state": field({"type": "string", "enum": ["timed", "atemporal"]}, "timed"), "start_at": text("2026-08-28T00:00:00Z"), "end_at": text("2026-08-28T00:00:01Z"), "timebase": text("sample_clock"), "source_ref": ref("SourceRecord"), "result_ref": ref("ArtifactRecord"), "calibration": obj({"status": "declared"}), "route": obj({"kind": "import"}), "environment": obj({"location": "controlled"}), "limits": obj({"bandwidth_hz": [20, 20000]}), "authorization_status": enum("authorization_status", "permitted"), "receipt_ref": ref("OperationReceipt"), "lineage_relation": text("acquired_from"), "event_sequence": integer(1, minimum=1)},
        "SourceRecord": {"attributed_origin": text("fixture source"), "locator": text("qste://fixtures/source"), "source_availability": enum("availability", "known"), "rights": obj({"use": "fixture_only"})},
        "ArtifactRecord": {"media_type": text("application/octet-stream"), "artifact_availability": enum("availability", "known"), "byte_state": text("content_addressed")},
        "ObservationRecord": {"variable": text("response"), "observation_state": text("value"), "value": number(0.5), "units": text("normalized_score"), "method": text("fixture_measurement"), "evidence_basis": enum("evidence_basis", "instrumentally_derived"), "acquisition_ref": ref("AcquisitionEvent")},
        "ApparatusSpec": {"apparatus_version": text("apparatus/1"), "configuration": obj({"sample_rate_hz": 48000}), "acquisition_surface": obj({"channels": 1}), "computation_surface": obj({"dtype": "float64"}), "action_surface": obj({"network": False})},
        "ApertureSpec": {"apparatus_ref": ref("ApparatusSpec"), "run_ref": ref("RunManifest"), "input_ref": ref("ArtifactRecord"), "policy_state": obj({"network": "prohibited"}), "accessible_ranges": obj({"frequency_hz": [20, 20000]}), "permitted_operations": array(["validate"]), "known_exclusions": array(["unobserved_history"]), "derivation": obj({"method": "bounded_intersection"})},
        "RepresentationFamilySpec": {"family_id": text("representation-family/1"), "family_version": text("1"), "spec_refs": refs("RepresentationSpec"), "instance_refs": refs("RepresentationInstance"), "mapping_refs": refs("MappingSpec"), "permitted_refinements": array([{"order": "strict_native_subset"}])},
        "RepresentationSpec": {"representation_id": text("representation/1"), "algorithm_or_model_digest": field({"$ref": f"{COMMON_ID}#/$defs/digest"}, digest("b")), "parameters": obj({"window": 1024}), "native_unit": text("coefficient"), "metric": obj({"name": "native_l2"}), "capacity": obj({"maximum_candidates": 1024}), "renderer_or_decoder": obj({"id": "renderer/1"})},
        "RepresentationInstance": {"source_artifact_ref": ref("ArtifactRecord"), "representation_spec_ref": ref("RepresentationSpec"), "execution_receipt_ref": ref("OperationReceipt"), "dense_data_ref": ref("ArtifactRecord", 2), "instance_context": obj({"run": "fixture"})},
        "CandidateUnit": {"representation_instance_ref": ref("RepresentationInstance"), "native_address": obj({"index": 0}), "candidate_rule_version": text("candidate-rule/1"), "native_support": obj({"indices": [0]})},
        "InterventionSpec": {"operator_family": text("native_mask"), "native_operation": obj({"operation": "replace"}), "reference_distribution": obj({"kind": "zero"}), "renderer_or_decoder": obj({"id": "renderer/1"}), "controls": array(["resynthesis", "off_target", "alternate_intervention"]), "random_source": obj({"seed": 7})},
        "TaskSpec": {"task_id": text("task/1"), "task_version": text("1"), "response_variable": text("score"), "input_refs": refs("ArtifactRecord"), "fixed_context": obj({"mode": "fixture"}), "contrast_ref": ref("InterventionSpec"), "intervention_ref": ref("InterventionSpec", 2), "expected_effect_direction": field({"type": "integer", "enum": [-1, 1]}, 1), "response_units": text("normalized_score"), "meaningful_bound": number(0.5, minimum=0), "equivalence_region": obj({"epsilon_minus": 0.1, "epsilon_plus": 0.1, "units": "normalized_score"}), "bound_validity_evidence": obj({"finite": True, "disjoint": True}), "boundary_semantics": obj({"meaningful": "closed", "equivalence": "closed"}), "estimator": obj({"name": "paired_mean"}), "repeats": integer(10, minimum=1), "seeds": array([7], items={"type": "integer"}), "uncertainty": obj({"method": "simultaneous_interval"}), "multiplicity": obj({"method": "holm"}), "stopping_rules": obj({"maximum_repeats": 10}), "selection_confirmation": obj({"split": "held_out"}), "eligible_family": array(["root_and_required_proper_nodes"]), "artifact_controls": array(["resynthesis", "off_target"]), "alternate_intervention": obj({"operator": "matched_noise"}), "compute_budget": obj({"maximum_evaluations": 100}), "success_criterion": obj({"candidate": "meaningful", "proper_nodes": "equivalent"}), "failure_reasons": array(["budget_exhausted"])},
        "RefinementGraph": {"procedure_id": text("refinement/1"), "representation_family_ref": ref("RepresentationFamilySpec"), "intervention_ref": ref("InterventionSpec"), "root_candidate_ref": ref("CandidateUnit"), "nodes": array(["root", "proper-1"]), "edges": array([{"parent": "root", "child": "proper-1", "proper": True}]), "required_closure": array(["proper-1"]), "completion_certificate": obj({"complete": True, "terminal_rule": "finite_declared_closure"}), "closed": boolean(True)},
        "DSQAssessment": {"assessment_identity": obj({"candidate_semantic_key": digest("c"), "task": "task/1", "procedure": "refinement/1"}), "candidate_ref": ref("CandidateUnit"), "candidate_semantic_key": field({"$ref": f"{COMMON_ID}#/$defs/semanticKey"}, digest("c")), "representation_instance_ref": ref("RepresentationInstance"), "native_address": obj({"index": 0}), "apparatus_ref": ref("ApparatusSpec"), "aperture_ref": ref("ApertureSpec"), "representation_family_ref": ref("RepresentationFamilySpec"), "intervention_ref": ref("InterventionSpec"), "task_ref": ref("TaskSpec"), "refinement_graph_ref": ref("RefinementGraph"), "raw_effects": array([0.8, 0.7], items={"type": "number"}), "oriented_effects": array([0.8, 0.7], items={"type": "number"}), "candidate_interval": obj({"lower": 0.6, "upper": 0.9, "units": "normalized_score"}), "proper_node_intervals": array([{"node": "proper-1", "lower": -0.05, "upper": 0.05, "units": "normalized_score"}]), "meaningful_bound": number(0.5, minimum=0), "equivalence_region": obj({"epsilon_minus": 0.1, "epsilon_plus": 0.1, "units": "normalized_score"}), "comparison_operators": obj({"meaningful": ">", "equivalent": "within"}), "tested_proper_nodes": array(["proper-1"]), "closure_certificate": obj({"complete": True, "nonempty": True}), "selection_evidence": obj({"held_out": True}), "multiplicity_evidence": obj({"adjusted": True}), "artifact_control_results": obj({"passed": True}), "well_formed": boolean(True), "negative_evidence_valid": boolean(True), "qualification_ready": boolean(True), "assessment_status": enum("assessment_status", "qualified"), "reason_code": enum("assessment_reason", "meaningful_closed_equivalent"), "interaction_annotations": array(["none"]), "dependency_validity": enum("dependency_validity", "valid"), "authorization_status": enum("authorization_status", "permitted"), "evidence_refs": refs("ObservationRecord"), "assessor": text("fixture-validator"), "versions": obj({"contract": CONTRACT_ID}), "receipt_refs": refs("OperationReceipt")},
        "ProjectionSpec": {"source_arm_ref": ref("RepresentationSpec"), "comparison_substrate": obj({"id": "omega/1", "units": ["second", "hertz"]}), "measure": obj({"name": "footprint_mass"}), "footprint_method": obj({"name": "decoded_difference"}), "calibration": obj({"status": "valid"})},
        "ComparisonSpec": {"projection_refs": refs("ProjectionSpec"), "coverage_threshold": number(0.8, minimum=0), "effect_tolerance": number(0.1, minimum=0), "capacities": obj({"left": 1, "right": 1}), "cardinalities": array(["one_to_one"]), "unmatched_penalty": number(1.0, minimum=0), "estimators": obj({"coverage": "interval", "effect": "interval"}), "primary_objective": text("minimum_cost"), "cardinality_preference": array(["one_to_one", "unmatched"]), "optimization_tolerance": number(1e-9, minimum=0), "ambiguity_rules": obj({"surviving_optima": "retain_all"}), "budget": obj({"maximum_solutions": 100})},
        "RelationAssertion": {"source_refs": refs("CandidateUnit"), "target_refs": refs("CandidateUnit", 2), "direction": text("left_to_right"), "native_addresses": obj({"left": [{"index": 0}], "right": [{"index": 1}]}), "comparison_substrate": obj({"id": "omega/1"}), "projection_contract": obj({"id": "projection/1"}), "footprint_contract": obj({"measure": "nonnegative_mass"}), "effect_contract": obj({"units": "normalized_score"}), "coverage": obj({"left_to_right": [0.9, 1.0], "right_to_left": [0.8, 0.95]}), "effect_difference_interval": obj({"lower": -0.02, "upper": 0.03}), "effect_tolerance": number(0.1, minimum=0), "controls": obj({"fidelity": True, "consequential": True, "artifact": True}), "matching_contract": obj({"capacities": [1, 1], "cardinality": "one_to_one", "lambda": 1.0, "estimator": "interval", "objective": "minimum_cost", "tolerance": 1e-9, "solver": "fixture/1"}), "solution_evidence": obj({"primary_optimum": 0.0, "surviving_optima": 1, "diagnostic_representative": "edge-1", "components": ["edge-1"]}), "comparison_spec_ref": ref("ComparisonSpec"), "relation_type": field({"anyOf": [{"$ref": f"{COMMON_ID}#/$defs/relation_type"}, {"type": "null"}]}, "overlap"), "comparison_status": enum("comparison_status", "resolved"), "reason_code": enum("comparison_reason", "matched_overlap"), "perturbation_stability": enum("perturbation_stability", "stable"), "evidence_refs": refs("ObservationRecord")},
        "MappingSpec": {"source_domain": obj({"name": "normalized_score"}), "target_domain": obj({"name": "amplitude"}), "variables": array(["score", "gain"]), "units": obj({"source": "normalized", "target": "linear_gain"}), "normalization": obj({"method": "minmax"}), "uncertainty": obj({"propagation": "interval"}), "missing_data_behavior": text("refuse"), "interpolation": obj({"method": "none"}), "range": obj({"minimum": 0, "maximum": 1}), "loss": obj({"declared": True}), "reversibility_claim": text("not_reversible")},
        "ListeningHarnessSpec": {"record_refs": refs("ListeningAccount"), "routes": array(["local_fixture"]), "permissions": array(["read"]), "refusals": array(["network"]), "authority_ref": ref("AuthorityManifest"), "executor": text("local_executor"), "action_surface": obj({"write_successor_only": True})},
        "GovernanceBoundary": {"immutable_fields": array(["record_id", "created_at"]), "mutable_successor_fields": array(["parameters"]), "authority_refs": refs("AuthorityManifest"), "permitted_actions": array(["revise", "refuse"]), "budgets": obj({"maximum_revisions": 1}), "stop_rules": obj({"on_refusal": True}), "resume_rules": obj({"requires_authority": True})},
        "RevisionOpportunity": {"source_item_ref": ref("ArtifactRecord"), "completed_run_ref": ref("RunManifest"), "initial_successor_spec_ref": ref("SuccessorSpec"), "governance_boundary_ref": ref("GovernanceBoundary"), "matched_state_key": text("fixture-state-1"), "budget": obj({"maximum_actions": 1})},
        "SuccessorSpec": {"predecessor_ref": ref("SuccessorSpec", 2), "completed_run_ref": ref("RunManifest"), "semantic_diff": obj({"parameters.gain": [0.5, 0.6]}), "executable_action_set": array(["set_gain"]), "capability_requirements": array(["local_write"]), "decision_event_ref": ref("DecisionEvent"), "evidence_fields": array(["candidate_interval"]), "revision_treatment": enum("revision_treatment", "authentic"), "authority_ref": ref("AuthorityManifest"), "persistence_target": text("next_run")},
        "DecisionEvent": {"opportunity_ref": ref("RevisionOpportunity"), "revision_treatment": enum("revision_treatment", "authentic"), "alternatives": array(["revise", "no_change"]), "cited_evidence": array(["candidate_interval"]), "reason_code": text("evidence_supported_revision"), "authority_ref": ref("AuthorityManifest"), "governance_boundary_ref": ref("GovernanceBoundary"), "decision_action": enum("decision_action", "revise"), "predecessor_successor_diff": obj({"parameters.gain": [0.5, 0.6]}), "executable_consequence": obj({"operation": "set_gain"}), "next_run_ref": ref("RunManifest", 2), "budget": obj({"used": 1}), "leakage_checks": obj({"passed": True}), "receipt_ref": ref("OperationReceipt"), "event_sequence": integer(2, minimum=1)},
        "AppealCase": {"appellant_ref": ref("SourceRecord"), "standing_basis": text("authorized_representative"), "responding_authority_ref": ref("AuthorityManifest"), "target_closure": obj({"root": fixture_id("ArtifactRecord"), "descendants": []}), "reason_code": enum("governance_reason", "standing_unverified"), "requested_action": enum("repair_action", "restrict"), "deadlines": obj({"respond_by": "2026-09-01T00:00:00Z"}), "jurisdiction": text("project"), "appeal_status": enum("appeal_status", "opened"), "pause_status": enum("pause_status", "not_requested"), "adjudication_outcome": enum("adjudication_outcome", "not_decided"), "repair_status": enum("repair_status", "not_requested"), "adjudication_evidence_refs": refs("ClaimRecord"), "decision_event_refs": refs("DecisionEvent"), "successor_case_ref": field({"anyOf": [{"$ref": f"{COMMON_ID}#/$defs/recordReference"}, {"type": "null"}]}, None)},
        "RepairAction": {"appeal_case_ref": ref("AppealCase"), "adjudication_outcome": enum("adjudication_outcome", "upheld"), "authority_ref": ref("AuthorityManifest"), "repair_action": enum("repair_action", "restrict"), "target_closure": obj({"root": fixture_id("ArtifactRecord"), "descendants": []}), "operation_scope": obj({"future_use": True}), "predecessor_state": obj({"eligible": True}), "successor_state": obj({"eligible": False}), "authorization_status": enum("authorization_status", "permitted"), "execution_status": enum("operation_status", "completed"), "reason_code": enum("governance_reason", "requested_remedy_upheld"), "failures": array(["none"]), "receipt_ref": ref("OperationReceipt"), "propagation_requirement": obj({"dependent_claims": True}), "retention_semantics": obj({"bytes": "retained_restricted"})},
        "RepairReceipt": {"appeal_case_ref": ref("AppealCase"), "action_refs": refs("RepairAction"), "affected_closure": obj({"descendants": [], "claims": [], "renders": [], "bundles": [], "projections": []}), "actions_applied": array(["restrict"]), "propagation_failures": array(["none"]), "external_copies": array(["none_known"]), "unresolved_limits": array(["none"]), "repair_status": enum("repair_status", "applied"), "pause_status": enum("pause_status", "not_requested"), "successor_refs": refs("ArtifactRecord"), "final_authority_ref": ref("AuthorityManifest"), "completed_at": text("2026-08-28T00:00:00Z"), "event_sequence": integer(3, minimum=1)},
        "OperationReceipt": {"request_ref": ref("ClaimRecord"), "authorization_status": enum("authorization_status", "permitted"), "actor": text("local_executor"), "tool": obj({"id": "qste-validator", "version": VERSION}), "inputs": array([fixture_id("ClaimRecord")]), "parameters": obj({"strict": True}), "outputs": array([fixture_id("ClaimRecord", 2)]), "operation_status": enum("operation_status", "completed")},
        "ListeningAccount": {"evaluator_ref": ref("SourceRecord"), "protocol_ref": ref("TaskSpec"), "object_ref": ref("ArtifactRecord"), "apparatus_ref": ref("ApparatusSpec"), "aperture_ref": ref("ApertureSpec"), "context": obj({"room": "fixture"}), "response_fields": obj({"detection": True, "attribution": "unknown", "preference": None, "novelty_value": None, "interpretation": "fixture report"}), "report": text("fixture listening account"), "response_units": text("categorical"), "uncertainty_or_missingness": obj({"preference": "not_applicable"}), "evidence_basis": enum("evidence_basis", "human_reported"), "consent_status": enum("consent_status", "granted"), "withdrawal_event_refs": refs("DecisionEvent"), "retention_policy": obj({"duration": "fixture_only"}), "authorization_status": enum("authorization_status", "permitted"), "collection_receipt_ref": ref("OperationReceipt"), "dependent_claim_refs": refs("ClaimRecord")},
        "ClaimRecord": {"proposition": text("fixture proposition"), "evidence_basis": enum("evidence_basis", "instrumentally_derived"), "epistemic_status": enum("epistemic_status", "derived"), "scope": obj({"kind": "fixture_only"}), "subject_ref": ref("ArtifactRecord"), "evidence_refs": refs("ObservationRecord")},
        "AuthorityManifest": {"manifest_profile": text("qste-authority/0.3.0"), "semantic_contract": obj({"id": CONTRACT_ID, "path": "ontology/0.3.0/QSTE_ontology.md", "sha256": "0" * 64}), "schema_set": obj({"id": SCHEMA_SET_ID, "path": "schemas/0.3.0/schema-index.json", "sha256": "1" * 64}), "conformance_profile": obj({"id": CONFORMANCE_ID, "path": "conformance/0.3.0/conformance-profile.json", "sha256": "2" * 64}), "architecture": obj({"id": "qste-architecture/private", "availability": "private_local_not_disclosed"}), "development_plan": obj({"id": "qste-development-plan/private", "availability": "private_local_not_disclosed"}), "research_sources": array([{"id": "agentic-quanta-paper-v3", "sha256": "5" * 64, "availability": "withheld", "authorized_locator": None}]), "code": obj({"version": "0.0.0", "commit": "6" * 40, "repository": "https://github.com/sonicfieldlabs/QSTE"}), "adapter_contracts": array([{"id": "none", "availability": "not_applicable"}]), "model_checkpoint_manifests": array([{"id": "none", "availability": "not_applicable"}]), "experiment_profiles": array([{"id": "none", "availability": "not_applicable"}]), "compatibility_decision": field({"const": "exact_contract_only"}, "exact_contract_only"), "approved_rfc_refs": field({"type": "array", "maxItems": 0}, [])},
        "RunManifest": {"apparatus_ref": ref("ApparatusSpec"), "aperture_ref": ref("ApertureSpec"), "corpus_refs": refs("ArtifactRecord"), "spec_refs": refs("TaskSpec"), "budgets": obj({"compute": 100}), "seeds": array([7], items={"type": "integer"}), "event_refs": refs("AcquisitionEvent"), "artifact_refs": refs("ArtifactRecord", 2), "output_refs": refs("ClaimRecord"), "frozen_versions": obj({"contract": CONTRACT_ID, "schema": SCHEMA_SET_ID})},
    }


def common_schema() -> Json:
    record_pattern = r"^qste:[a-z][a-z0-9-]*:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    digest_pattern = r"^sha256:[0-9a-f]{64}$"
    definitions: Json = {
        name: {"type": "string", "enum": values} for name, values in VOCABULARIES.items()
    }
    definitions.update(
        {
            "recordId": {"type": "string", "pattern": record_pattern},
            "semanticKey": {"type": "string", "pattern": digest_pattern},
            "digest": {"type": "string", "pattern": digest_pattern},
            "recordReference": {
                "type": "object",
                "properties": {
                    "record_id": {"$ref": "#/$defs/recordId"},
                    "record_type": {"type": "string", "enum": SERIALIZED_RECORDS},
                    "relation": {"type": "string", "minLength": 1},
                },
                "required": ["record_id", "record_type", "relation"],
                "additionalProperties": False,
            },
            "externalReference": {
                "type": "object",
                "properties": {
                    "external_uri": {"type": "string", "format": "uri"},
                    "record_type": {"type": "string", "minLength": 1},
                    "relation": {"type": "string", "minLength": 1},
                    "authority_ref": {"$ref": "#/$defs/recordId"},
                },
                "required": ["external_uri", "record_type", "relation", "authority_ref"],
                "additionalProperties": False,
            },
            "typedReference": {
                "oneOf": [
                    {"$ref": "#/$defs/recordReference"},
                    {"$ref": "#/$defs/externalReference"},
                ]
            },
            "recordBase": {
                "type": "object",
                "properties": {
                    "record_type": {"type": "string", "enum": SERIALIZED_RECORDS},
                    "schema_id": {"type": "string", "format": "uri"},
                    "contract_id": {"const": CONTRACT_ID},
                    "record_id": {"$ref": "#/$defs/recordId"},
                    "semantic_key": {"$ref": "#/$defs/semanticKey"},
                    "content_digest": {"$ref": "#/$defs/digest"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "producer_role": {"$ref": "#/$defs/producer_role"},
                    "integrity_status": {"$ref": "#/$defs/integrity_status"},
                    "disclosure_status": {"$ref": "#/$defs/disclosure_status"},
                    "availability": {"$ref": "#/$defs/availability"},
                    "authorization_status": {"$ref": "#/$defs/authorization_status"},
                    "consent_status": {"$ref": "#/$defs/consent_status"},
                    "references": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/typedReference"},
                    },
                },
                "required": [
                    "record_type",
                    "schema_id",
                    "contract_id",
                    "record_id",
                    "created_at",
                    "producer_role",
                    "integrity_status",
                    "disclosure_status",
                    "references",
                ],
            },
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": COMMON_ID,
        "title": "QSTE 0.3.0 common contracts and exact registries",
        "$defs": definitions,
    }


def record_schema(name: str, fields: Json) -> Json:
    properties = {key: deepcopy(value["schema"]) for key, value in fields.items()}
    properties.update(
        {
            "record_type": {"const": name},
            "schema_id": {"const": schema_id(name)},
            "contract_id": {"const": CONTRACT_ID},
        }
    )
    required = list(fields)
    additional_contracts: list[Json] = []
    if name == "AcquisitionEvent":
        required.remove("start_at")
        required.remove("end_at")
        additional_contracts.append(
            {
                "oneOf": [
                    {
                        "properties": {"temporal_state": {"const": "timed"}},
                        "required": ["start_at", "end_at"],
                    },
                    {
                        "properties": {"temporal_state": {"const": "atemporal"}},
                        "not": {"anyOf": [{"required": ["start_at"]}, {"required": ["end_at"]}]},
                    },
                ]
            }
        )
    if name == "SourceRecord":
        required.remove("locator")
        additional_contracts.append(
            {
                "anyOf": [
                    {"required": ["locator"]},
                    {
                        "properties": {
                            "source_availability": {
                                "enum": ["unknown", "unavailable", "withheld", "deleted"]
                            }
                        }
                    },
                ]
            }
        )
    if name == "ObservationRecord":
        required.remove("value")
        additional_contracts.append(
            {
                "oneOf": [
                    {
                        "properties": {"observation_state": {"const": "value"}},
                        "required": ["value"],
                    },
                    {
                        "properties": {"observation_state": {"const": "absent"}},
                        "not": {"required": ["value"]},
                    },
                ]
            }
        )
    if name in {"CandidateUnit", "DSQAssessment", "SuccessorSpec"}:
        required.append("semantic_key")
    if name == "ArtifactRecord":
        additional_contracts.append(
            {
                "anyOf": [
                    {"required": ["content_digest"]},
                    {
                        "properties": {
                            "artifact_availability": {
                                "enum": ["unknown", "unavailable", "withheld", "deleted"]
                            }
                        }
                    },
                ]
            }
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id(name),
        "title": name,
        "allOf": [
            {"$ref": f"{COMMON_ID}#/$defs/recordBase"},
            {"type": "object", "properties": properties, "required": required},
            *additional_contracts,
        ],
        "patternProperties": {r"^[a-z][a-z0-9_-]*:[A-Za-z][A-Za-z0-9_.-]*$": {}},
        "unevaluatedProperties": False,
    }


def operation_result_schema() -> Json:
    reasons = sorted(
        set(VOCABULARIES["operation_reason"])
        | set(VOCABULARIES["assessment_reason"])
        | set(VOCABULARIES["comparison_reason"])
        | set(VOCABULARIES["governance_reason"])
    )
    value_types = [schema_id(name) for name in SERIALIZED_RECORDS]
    value_types.extend(f"qste-payload/0.3.0/{name}" for name in TYPED_PAYLOADS)
    value_types.append(f"{BASE_URI}/bundle-manifest.schema.json")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE_URI}/operation-result.schema.json",
        "title": "OperationResult<T>",
        "type": "object",
        "properties": {
            "contract_id": {"const": CONTRACT_ID},
            "operation": {"type": "string", "pattern": r"^qste:[a-z][a-z0-9_.-]*/[0-9]+\.[0-9]+\.[0-9]+$"},
            "value_type": {"type": "string", "enum": value_types},
            "operation_status": {"$ref": f"{COMMON_ID}#/$defs/operation_status"},
            "value": {},
            "reason_code": {"type": "string", "enum": reasons},
            "authorization_status": {"$ref": f"{COMMON_ID}#/$defs/authorization_status"},
            "capability_status": {"$ref": f"{COMMON_ID}#/$defs/capability_status"},
            "receipt_id": {"$ref": f"{COMMON_ID}#/$defs/recordId"},
            "diagnostics": {"type": "object", "maxProperties": 32},
            "domain_status": {
                "type": "object",
                "properties": {
                    "assessment_status": {"$ref": f"{COMMON_ID}#/$defs/assessment_status"},
                    "comparison_status": {"$ref": f"{COMMON_ID}#/$defs/comparison_status"},
                    "repair_status": {"$ref": f"{COMMON_ID}#/$defs/repair_status"},
                },
                "additionalProperties": False,
                "minProperties": 1,
                "maxProperties": 1,
            },
            "unresolved_targets": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "partial_contract_id": {"type": "string", "minLength": 1},
            "cli_exit_class": {"type": "integer", "enum": [0, 2, 3, 4, 5, 6, 7, 8, 9]},
        },
        "required": ["contract_id", "operation", "value_type", "operation_status", "value", "reason_code", "authorization_status", "capability_status", "receipt_id", "diagnostics", "cli_exit_class"],
        "allOf": [
            {"if": {"properties": {"operation_status": {"const": "partial"}}}, "then": {"required": ["unresolved_targets", "partial_contract_id"]}},
            {"if": {"properties": {"operation_status": {"enum": ["refused", "unavailable", "failed"]}}}, "then": {"properties": {"value": {"type": "null"}}}},
        ],
        "additionalProperties": False,
    }


def typed_payload_schema() -> Json:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE_URI}/typed-payload.schema.json",
        "title": "QSTE typed operation payload",
        "type": "object",
        "properties": {
            "payload_type": {"type": "string", "enum": TYPED_PAYLOADS},
            "payload_schema_id": {"const": "qste-payload/0.3.0"},
            "items": {"type": "array"},
            "data": {"type": "object"},
        },
        "required": ["payload_type", "payload_schema_id"],
        "anyOf": [{"required": ["items"]}, {"required": ["data"]}],
        "additionalProperties": False,
        "description": "A non-record payload. Durable identity/evidence must be embedded in or referenced by a core record and OperationReceipt.",
    }


def bundle_schema() -> Json:
    manifest_entry = {
        "type": "object",
        "properties": {
            "record_id": {"$ref": f"{COMMON_ID}#/$defs/recordId"},
            "record_type": {"type": "string", "enum": SERIALIZED_RECORDS},
            "digest": {"$ref": f"{COMMON_ID}#/$defs/digest"},
            "sequence": {"type": "integer", "minimum": 0},
        },
        "required": ["record_id", "record_type", "digest", "sequence"],
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE_URI}/bundle-manifest.schema.json",
        "title": "Bundle sealed-container manifest",
        "type": "object",
        "properties": {
            "container_type": {"const": "Bundle"},
            "bundle_profile": {"enum": ["private_run_bundle", "authorized_public_projection"]},
            "bundle_id": {"type": "string", "pattern": r"^qste:bundle:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"},
            "contract_id": {"const": CONTRACT_ID},
            "schema_set_id": {"const": SCHEMA_SET_ID},
            "conformance_profile_id": {"const": CONFORMANCE_ID},
            "authority_ref": {"$ref": f"{COMMON_ID}#/$defs/recordId"},
            "code": {"type": "object", "minProperties": 1},
            "adapter_versions": {"type": "array"},
            "model_versions": {"type": "array"},
            "corpus_versions": {"type": "array"},
            "experiment_profiles": {"type": "array"},
            "record_manifest": {"type": "array", "minItems": 1, "items": manifest_entry},
            "event_manifest": {"type": "array", "items": manifest_entry},
            "relation_manifest": {"type": "array", "items": manifest_entry},
            "dense_manifests": {"type": "array"},
            "artifact_manifest": {"type": "array"},
            "checksums": {"type": "array", "minItems": 1},
            "manifest_digest": {"$ref": f"{COMMON_ID}#/$defs/digest"},
            "disclosure_status": {"$ref": f"{COMMON_ID}#/$defs/disclosure_status"},
            "retention_policy": {"type": "object", "minProperties": 1},
            "allowlist": {"type": "array"},
            "omission_manifest": {"type": "array"},
            "parent_bundle_ref": {"anyOf": [{"type": "string", "pattern": r"^qste:bundle:"}, {"type": "null"}]},
            "integrity_claim": {"enum": ["unverified", "verified", "failed", "unavailable"]},
            "logical_replay_claim": {"enum": ["unverified", "verified", "failed", "unavailable"]},
            "numerical_reproducibility_claim": {"enum": ["unverified", "verified", "failed", "unavailable"]},
        },
        "required": ["container_type", "bundle_profile", "bundle_id", "contract_id", "schema_set_id", "conformance_profile_id", "authority_ref", "code", "adapter_versions", "model_versions", "corpus_versions", "experiment_profiles", "record_manifest", "event_manifest", "relation_manifest", "dense_manifests", "artifact_manifest", "checksums", "manifest_digest", "disclosure_status", "retention_policy", "allowlist", "omission_manifest", "parent_bundle_ref", "integrity_claim", "logical_replay_claim", "numerical_reproducibility_claim"],
        "patternProperties": {r"^[a-z][a-z0-9_-]*:[A-Za-z][A-Za-z0-9_.-]*$": {}},
        "additionalProperties": False,
    }


def base_fixture(name: str, fields: Json) -> Json:
    record: Json = {
        "record_type": name,
        "schema_id": schema_id(name),
        "contract_id": CONTRACT_ID,
        "record_id": fixture_id(name),
        "created_at": "2026-08-28T00:00:00Z",
        "producer_role": "executor",
        "integrity_status": "unverified",
        "disclosure_status": "private",
        "references": [],
    }
    if name in {"CandidateUnit", "DSQAssessment", "SuccessorSpec"}:
        record["semantic_key"] = digest("d")
    if name == "ArtifactRecord":
        record["content_digest"] = digest("a")
    record.update({key: deepcopy(value["sample"]) for key, value in fields.items()})
    return record


def maximal_fixture(name: str, fields: Json) -> Json:
    record = base_fixture(name, fields)
    record.update(
        {
            "availability": "known",
            "authorization_status": "permitted",
            "consent_status": "not_applicable",
            "ext:futureField": {"version": 1, "preserve": True},
        }
    )
    record.update({key: deepcopy(value["maximal"]) for key, value in fields.items()})
    if "semantic_key" not in record:
        record["semantic_key"] = digest("e")
    if "content_digest" not in record:
        record["content_digest"] = digest("f")
    return record


def bundle_fixture() -> Json:
    authority_id = fixture_id("AuthorityManifest")
    return {
        "container_type": "Bundle",
        "bundle_profile": "private_run_bundle",
        "bundle_id": fixture_id("Bundle").replace("qste:bundle:", "qste:bundle:"),
        "contract_id": CONTRACT_ID,
        "schema_set_id": SCHEMA_SET_ID,
        "conformance_profile_id": CONFORMANCE_ID,
        "authority_ref": authority_id,
        "code": {"commit": "6" * 40},
        "adapter_versions": [],
        "model_versions": [],
        "corpus_versions": [],
        "experiment_profiles": [],
        "record_manifest": [{"record_id": authority_id, "record_type": "AuthorityManifest", "digest": digest("1"), "sequence": 0}],
        "event_manifest": [],
        "relation_manifest": [],
        "dense_manifests": [],
        "artifact_manifest": [],
        "checksums": [{"path": "records/authority.json", "digest": digest("1")}],
        "manifest_digest": digest("2"),
        "disclosure_status": "private",
        "retention_policy": {"mode": "fixture"},
        "allowlist": [],
        "omission_manifest": [],
        "parent_bundle_ref": None,
        "integrity_claim": "unverified",
        "logical_replay_claim": "unverified",
        "numerical_reproducibility_claim": "unavailable",
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def remove_previous_generated_fixtures() -> None:
    manifest_path = ROOT / "fixtures" / "schema" / VERSION / "fixture-manifest.json"
    if not manifest_path.is_file():
        return
    previous = json.loads(manifest_path.read_text())
    for entry in previous.get("fixtures", []):
        path = (ROOT / entry["path"]).resolve()
        expected_root = (ROOT / "fixtures" / "schema" / VERSION).resolve()
        if path.is_relative_to(expected_root) and path.is_file():
            path.unlink()


def generate() -> None:
    remove_previous_generated_fixtures()
    definitions = specs()
    if set(definitions) != set(SERIALIZED_RECORDS):
        raise RuntimeError("serialized record specification inventory is incomplete")

    schema_root = ROOT / "schemas" / VERSION
    record_root = schema_root / "records"
    expected_record_files = {f"{slug(name)}.schema.json" for name in SERIALIZED_RECORDS}
    if record_root.is_dir():
        for path in record_root.glob("*.schema.json"):
            if path.name not in expected_record_files:
                path.unlink()
    fixture_root = ROOT / "fixtures" / "schema" / VERSION
    conformance_root = ROOT / "conformance" / VERSION
    write_json(schema_root / "common.schema.json", common_schema())
    write_json(schema_root / "operation-result.schema.json", operation_result_schema())
    write_json(schema_root / "typed-payload.schema.json", typed_payload_schema())
    write_json(schema_root / "bundle-manifest.schema.json", bundle_schema())

    fixture_manifest: list[Json] = []
    for name in SERIALIZED_RECORDS:
        record_path = record_root / f"{slug(name)}.schema.json"
        write_json(record_path, record_schema(name, definitions[name]))
        withheld = base_fixture(name, definitions[name]) | {"availability": "withheld"}
        if name == "AcquisitionEvent":
            withheld["temporal_state"] = "atemporal"
            withheld.pop("start_at")
            withheld.pop("end_at")
        elif name == "SourceRecord":
            withheld["source_availability"] = "withheld"
            withheld.pop("locator")
        elif name == "ArtifactRecord":
            withheld["artifact_availability"] = "withheld"
            withheld["byte_state"] = "withheld_non_byte_state"
            withheld.pop("content_digest")
        elif name == "ObservationRecord":
            withheld["observation_state"] = "absent"
            withheld.pop("value")
        cases = {
            "minimal.valid.json": (base_fixture(name, definitions[name]), True, "valid_minimal"),
            "maximal.valid.json": (maximal_fixture(name, definitions[name]), True, "valid_maximal"),
            "withheld.valid.json": (withheld, True, "explicit_withheld"),
            "forward-extension.valid.json": (base_fixture(name, definitions[name]) | {"ext:futureField": {"opaque": [1, 2, 3]}}, True, "namespaced_extension"),
        }
        wrong = base_fixture(name, definitions[name])
        wrong[next(iter(definitions[name]))] = 7
        cases["invalid-type.invalid.json"] = (wrong, False, "type")
        missing = base_fixture(name, definitions[name])
        missing.pop(next(iter(definitions[name])))
        cases["missing-required.invalid.json"] = (missing, False, "required")
        for filename, (payload, valid, reason) in cases.items():
            path = fixture_root / slug(name) / filename
            write_json(path, payload)
            fixture_manifest.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "schema_id": schema_id(name),
                    "expected_valid": valid,
                    "expected_reason": reason,
                    "record_type": name,
                }
            )

    bundle = bundle_fixture()
    bundle_cases = {
        "minimal.valid.json": (bundle, True, "valid_minimal"),
        "maximal.valid.json": (bundle | {"allowlist": ["records/*"], "omission_manifest": [{"path": "private/*", "reason": "withheld"}]}, True, "valid_maximal"),
        "withheld.valid.json": (bundle | {"disclosure_status": "restricted", "omission_manifest": [{"path": "records/private.json", "availability": "withheld"}]}, True, "explicit_withheld"),
        "forward-extension.valid.json": (bundle | {"ext:futureField": True}, True, "namespaced_extension"),
        "missing-required.invalid.json": ({key: value for key, value in bundle.items() if key != "record_manifest"}, False, "required"),
        "invalid-type.invalid.json": (bundle | {"record_manifest": "not-an-array"}, False, "type"),
    }
    bundle_schema_id = f"{BASE_URI}/bundle-manifest.schema.json"
    for filename, (payload, valid, reason) in bundle_cases.items():
        path = fixture_root / "bundle" / filename
        write_json(path, payload)
        fixture_manifest.append({"path": path.relative_to(ROOT).as_posix(), "schema_id": bundle_schema_id, "expected_valid": valid, "expected_reason": reason, "record_type": "Bundle"})

    payload_cases = {
        "minimal.valid.json": ({"payload_type": "CandidateSet", "payload_schema_id": "qste-payload/0.3.0", "items": []}, True, "valid_typed_payload"),
        "unknown-type.invalid.json": ({"payload_type": "DSQ", "payload_schema_id": "qste-payload/0.3.0", "items": []}, False, "enum"),
    }
    payload_schema_id = f"{BASE_URI}/typed-payload.schema.json"
    for filename, (payload, valid, reason) in payload_cases.items():
        path = fixture_root / "typed-payload" / filename
        write_json(path, payload)
        fixture_manifest.append({"path": path.relative_to(ROOT).as_posix(), "schema_id": payload_schema_id, "expected_valid": valid, "expected_reason": reason, "record_type": "typed_payload"})

    operation_cases = {
        "completed.valid.json": ({"contract_id": CONTRACT_ID, "operation": "qste:validate/0.3.0", "value_type": "qste-payload/0.3.0/CandidateSet", "operation_status": "completed", "value": {"payload_type": "CandidateSet", "payload_schema_id": "qste-payload/0.3.0", "items": []}, "reason_code": "completed", "authorization_status": "permitted", "capability_status": "available", "receipt_id": fixture_id("OperationReceipt"), "diagnostics": {}, "cli_exit_class": 0}, True, "completed"),
        "failed-invalid-spec.valid.json": ({"contract_id": CONTRACT_ID, "operation": "qste:assess/0.3.0", "value_type": schema_id("DSQAssessment"), "operation_status": "failed", "value": None, "reason_code": "invalid_assessment_spec", "authorization_status": "permitted", "capability_status": "available", "receipt_id": fixture_id("OperationReceipt"), "diagnostics": {"field": "meaningful_bound"}, "cli_exit_class": 2}, True, "failed_without_domain_status"),
        "partial-without-targets.invalid.json": ({"contract_id": CONTRACT_ID, "operation": "qste:repair/0.3.0", "value_type": "qste-payload/0.3.0/RepairPropagation", "operation_status": "partial", "value": {}, "reason_code": "partial_completion", "authorization_status": "permitted", "capability_status": "degraded", "receipt_id": fixture_id("OperationReceipt"), "diagnostics": {}, "cli_exit_class": 6}, False, "required"),
        "domain-token-as-operation.invalid.json": ({"contract_id": CONTRACT_ID, "operation": "qste:assess/0.3.0", "value_type": schema_id("DSQAssessment"), "operation_status": "indeterminate", "value": None, "reason_code": "required_evidence_unavailable", "authorization_status": "permitted", "capability_status": "available", "receipt_id": fixture_id("OperationReceipt"), "diagnostics": {}, "cli_exit_class": 5}, False, "enum"),
    }
    operation_schema_id = f"{BASE_URI}/operation-result.schema.json"
    for filename, (payload, valid, reason) in operation_cases.items():
        path = fixture_root / "operation-result" / filename
        write_json(path, payload)
        fixture_manifest.append({"path": path.relative_to(ROOT).as_posix(), "schema_id": operation_schema_id, "expected_valid": valid, "expected_reason": reason, "record_type": "OperationResult"})

    # Cross-record fixtures deliberately use a corpus envelope, not a new QSTE record.
    source = base_fixture("SourceRecord", definitions["SourceRecord"])
    successor = base_fixture("SourceRecord", definitions["SourceRecord"])
    successor["record_id"] = fixture_id("SourceRecord", 2)
    successor["references"] = [{"record_id": source["record_id"], "record_type": "SourceRecord", "relation": "succeeds"}]
    closed = {"objects": [source, successor]}
    missing_ref = deepcopy(closed)
    missing_ref["objects"][1]["references"][0]["record_id"] = fixture_id("SourceRecord", 99)
    wrong_type = deepcopy(closed)
    wrong_type["objects"][1]["references"][0]["record_type"] = "ArtifactRecord"
    for filename, payload in {"closed.valid.json": closed, "missing-reference.invalid.json": missing_ref, "wrong-type.invalid.json": wrong_type}.items():
        write_json(fixture_root / "reference-closure" / filename, payload)

    refinement_types = [
        "RefinementGraph",
        "RepresentationFamilySpec",
        "InterventionSpec",
        "CandidateUnit",
        "RepresentationSpec",
        "RepresentationInstance",
        "MappingSpec",
        "ArtifactRecord",
        "OperationReceipt",
        "ClaimRecord",
        "ObservationRecord",
        "AcquisitionEvent",
        "ApparatusSpec",
        "SourceRecord",
    ]
    refinement_records = [base_fixture(name, definitions[name]) for name in refinement_types]
    ids_by_type = {record["record_type"]: record["record_id"] for record in refinement_records}

    def close_fixture_references(value: Any) -> None:
        if isinstance(value, dict):
            if set(("record_id", "record_type", "relation")).issubset(value):
                value["record_id"] = ids_by_type[value["record_type"]]
                return
            for child in value.values():
                close_fixture_references(child)
        elif isinstance(value, list):
            for child in value:
                close_fixture_references(child)

    close_fixture_references(refinement_records)
    refinement_closed = {"objects": refinement_records}
    refinement_missing_mapping = deepcopy(refinement_closed)
    next(record for record in refinement_missing_mapping["objects"] if record["record_type"] == "RepresentationFamilySpec")["mapping_refs"] = []
    write_json(fixture_root / "reference-closure" / "refinement.valid.json", refinement_closed)
    write_json(fixture_root / "reference-closure" / "refinement-mapping-missing.invalid.json", refinement_missing_mapping)

    write_json(fixture_root / "fixture-manifest.json", {"schema_set_id": SCHEMA_SET_ID, "fixtures": sorted(fixture_manifest, key=lambda item: item["path"])})

    schemas = [
        {"kind": "shared", "name": "common", "id": COMMON_ID, "path": "common.schema.json"},
        {"kind": "envelope", "name": "OperationResult", "id": operation_schema_id, "path": "operation-result.schema.json"},
        {"kind": "typed_payload", "name": "typed payload", "id": payload_schema_id, "path": "typed-payload.schema.json"},
        {"kind": "sealed_container", "name": "Bundle", "id": bundle_schema_id, "path": "bundle-manifest.schema.json"},
    ] + [{"kind": "serialized_record", "name": name, "id": schema_id(name), "path": f"records/{slug(name)}.schema.json"} for name in SERIALIZED_RECORDS]
    for entry in schemas:
        entry["sha256"] = file_sha256(schema_root / entry["path"])
    write_json(schema_root / "schema-index.json", {"schema_set_id": SCHEMA_SET_ID, "contract_id": CONTRACT_ID, "json_schema_dialect": "https://json-schema.org/draft/2020-12/schema", "compatibility": "exact_only_no_legacy_reader", "schemas": schemas})

    behavior_phases = {
        "AcquisitionEvent": "P4", "SourceRecord": "P4", "ArtifactRecord": "P3", "ObservationRecord": "P4", "ApparatusSpec": "P4", "ApertureSpec": "P4",
        "RepresentationFamilySpec": "P5", "RepresentationSpec": "P5", "RepresentationInstance": "P5", "CandidateUnit": "P5", "InterventionSpec": "P5",
        "TaskSpec": "P6", "RefinementGraph": "P6", "DSQAssessment": "P6", "ProjectionSpec": "P7", "ComparisonSpec": "P7", "RelationAssertion": "P7",
        "MappingSpec": "P8", "ListeningHarnessSpec": "P10", "GovernanceBoundary": "P8", "RevisionOpportunity": "P10", "SuccessorSpec": "P10", "DecisionEvent": "P10",
        "AppealCase": "P8", "RepairAction": "P8", "RepairReceipt": "P8", "OperationReceipt": "P3", "ListeningAccount": "P12h", "ClaimRecord": "P3", "AuthorityManifest": "P2", "RunManifest": "P3",
    }
    coverage = [
        {"entity": "Phenomenon", "contract_form": "abstract_concept", "owner": "ontology/0.3.0/QSTE_ontology.md", "schema": None, "container": None, "first_schema_phase": "not_applicable", "first_behavior_phase": "not_applicable", "schema_availability": "not_applicable", "behavior_availability": "not_applicable"},
        *[{"entity": name, "contract_form": "serialized_record", "owner": f"schemas/{VERSION}/records/{slug(name)}.schema.json", "schema": f"schemas/{VERSION}/records/{slug(name)}.schema.json", "container": "Bundle", "first_schema_phase": "P2", "first_behavior_phase": behavior_phases[name], "schema_availability": "available", "behavior_availability": "available" if behavior_phases[name] == "P2" else "unavailable"} for name in SERIALIZED_RECORDS],
        *[{"entity": name, "contract_form": "typed_payload", "owner": f"schemas/{VERSION}/typed-payload.schema.json", "schema": f"schemas/{VERSION}/typed-payload.schema.json", "container": "OperationResult.value; persist via core record", "first_schema_phase": "P2", "first_behavior_phase": "operation_specific", "schema_availability": "available", "behavior_availability": "unavailable"} for name in TYPED_PAYLOADS],
        {"entity": "Bundle", "contract_form": "sealed_container", "owner": f"schemas/{VERSION}/bundle-manifest.schema.json", "schema": f"schemas/{VERSION}/bundle-manifest.schema.json", "container": None, "first_schema_phase": "P2", "first_behavior_phase": "P3", "schema_availability": "available", "behavior_availability": "unavailable"},
        {"entity": "OperationResult<T>", "contract_form": "operation_envelope", "owner": f"schemas/{VERSION}/operation-result.schema.json", "schema": f"schemas/{VERSION}/operation-result.schema.json", "container": "operation boundary", "first_schema_phase": "P2", "first_behavior_phase": "P2", "schema_availability": "available", "behavior_availability": "available"},
    ]
    write_json(conformance_root / "entity-coverage.json", {"contract_id": CONTRACT_ID, "schema_set_id": SCHEMA_SET_ID, "entities": coverage})
    write_json(conformance_root / "controlled-vocabularies.json", {"contract_id": CONTRACT_ID, "schema_set_id": SCHEMA_SET_ID, "registries": VOCABULARIES, "legacy_aliases": {}, "writer_policy": "reject_noncanonical"})
    write_json(conformance_root / "state-transitions.json", {
        "contract_id": CONTRACT_ID,
        "axes_are_independent": ["assessment_status", "dependency_validity", "authorization_status", "appeal_status", "pause_status", "adjudication_outcome", "repair_status"],
        "operation_status": {"completed": {"exit_classes": [0, 5], "domain_status_allowed": True}, "refused": {"reason": "policy_refused", "exit_classes": [3]}, "unavailable": {"reason": "capability_unavailable", "exit_classes": [4]}, "failed": {"reasons": ["invalid_input", "invalid_assessment_spec", "invalid_comparison_spec", "execution_failed", "conformance_failed", "internal_error"], "exit_classes": [2, 7, 8, 9]}, "partial": {"reason": "partial_completion", "exit_classes": [6], "requires": ["unresolved_targets"]}},
        "appeal_status": {"opened": ["under_review", "closed"], "under_review": ["adjudicated", "closed"], "adjudicated": ["closed"], "closed": []},
        "pause_status": {"not_requested": ["requested"], "requested": ["active", "denied"], "active": ["released"], "denied": [], "released": []},
        "repair_status": {"not_requested": ["pending", "impossible"], "pending": ["applied", "partially_applied", "impossible"], "applied": ["superseded"], "partially_applied": ["superseded"], "impossible": ["superseded"], "superseded": []},
    })
    write_json(conformance_root / "reader-writer-profile.json", {
        "id": CONFORMANCE_ID,
        "contract_id": CONTRACT_ID,
        "schema_set_id": SCHEMA_SET_ID,
        "reader": {"json": "strict_finite", "unknown_unqualified_fields": "reject", "namespaced_extensions": "preserve_verbatim", "legacy_aliases": "reject", "reference_closure": "required_for_bundle"},
        "writer": {"json": "canonical_sorted_utf8", "nonfinite_numbers": "reject", "unknown_unqualified_fields": "reject", "namespaced_extensions": "preserve_verbatim", "canonical_tokens_only": True, "legacy_output": "prohibited"},
        "identity": {"record_id": "random_uuid4", "semantic_key": "typed_rfc8785_compatible_sha256", "content_digest": "serialized_bytes_sha256", "substitution": "prohibited"},
    })
    write_json(conformance_root / "conformance-profile.json", {
        "id": CONFORMANCE_ID,
        "contract_id": CONTRACT_ID,
        "schema_set_id": SCHEMA_SET_ID,
        "phase": "P2",
        "fixtures": "fixtures/schema/0.3.0/fixture-manifest.json",
        "required_checks": ["schema_self_validation", "fixture_expectations", "namespaced_extension_roundtrip", "entity_coverage", "identity_non_substitution", "candidate_assessment_distinction", "state_axis_independence", "nullable_relation_type", "canonical_token_rejection", "refinement_dependency_shape", "reference_closure"],
        "legacy_reader": None,
        "migration_map": None,
    })
    future_phase = {1: "P2", 2: "P2", 3: "P2", 4: "P2", 5: "P2", 6: "P2", 7: "P2", 8: "P2", 9: "P6", 10: "P6", 11: "P6", 12: "P2", 13: "P2", 14: "P7", 15: "P2", 16: "P7", 17: "P7", 18: "P7", 19: "P10", 20: "P10", 21: "P10", 22: "P10", 23: "P8", 24: "P8", 25: "P3", 26: "P2", 27: "P2", 28: "P2"}
    schema_enforced = {1, 2, 3, 4, 5, 6, 7, 8, 12, 13, 15, 26, 27, 28}
    write_json(conformance_root / "obligation-coverage.json", {
        "contract_id": CONTRACT_ID,
        "scope": "ontology_section_17",
        "truth_boundary": "P2 validates representational contracts; later behavioral phases remain unavailable",
        "obligations": [
            {"number": number, "p2_status": "schema_and_semantic_enforced" if number in schema_enforced else "schema_surface_only", "behavior_first_phase": future_phase[number], "behavior_available": future_phase[number] == "P2"}
            for number in range(1, 29)
        ],
    })
    conformance_paths = [
        conformance_root / "conformance-profile.json",
        conformance_root / "controlled-vocabularies.json",
        conformance_root / "entity-coverage.json",
        conformance_root / "obligation-coverage.json",
        conformance_root / "reader-writer-profile.json",
        conformance_root / "state-transitions.json",
        fixture_root / "fixture-manifest.json",
    ]
    write_json(conformance_root / "conformance-index.json", {
        "id": CONFORMANCE_ID,
        "contract_id": CONTRACT_ID,
        "schema_set_id": SCHEMA_SET_ID,
        "files": [
            {"path": path.relative_to(ROOT).as_posix(), "sha256": file_sha256(path)}
            for path in conformance_paths
        ],
    })


if __name__ == "__main__":
    generate()
