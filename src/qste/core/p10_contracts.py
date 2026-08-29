"""Semantic invariants for P10 agent-host and comparative-control records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qste.core.contracts import ContractError

AGENT_PROFILE = "qste-evidence-dependent-revision/v0.1"
PAYLOAD_PROFILE = "qste-dsq-information-payload/v0.1"
TREATMENT_PROFILE = "qste-revision-treatment/v0.1"
STUDY_PROFILE = "qste-revision-comparative-baseline/v0.1"
UTILITY_PROFILE = "qste-held-out-utility-cost/v0.1"
TREATMENTS = {"authentic", "absent", "placebo", "permuted"}
VOLATILE = {"record_id", "created_at", "semantic_key", "content_digest", "serialization"}


def validate_p10_semantics(record: Mapping[str, Any]) -> None:
    """Reject P10 records that turn plans into authority or traces into research claims."""

    if record.get("qste:agentProfile") != AGENT_PROFILE:
        return
    record_type = record.get("record_type")
    if record_type == "ListeningHarnessSpec":
        _harness(record)
    elif record_type == "RevisionOpportunity":
        _opportunity(record)
    elif record_type == "SuccessorSpec":
        _successor(record)
    elif record_type == "DecisionEvent":
        _decision(record)
    elif record_type == "ArtifactRecord":
        _artifact(record)
    elif record_type == "RunManifest":
        _next_run(record)
    elif record_type == "ClaimRecord":
        _claim(record)


def _harness(record: Mapping[str, Any]) -> None:
    surface = _object(record.get("action_surface"), "harness action surface")
    if (
        surface.get("network") is not False
        or surface.get("model_execution") is not False
        or surface.get("external_write") is not False
        or surface.get("prompt_authority") is not False
    ):
        raise ContractError("conformance_failed", "P10 harness enlarged its action surface")
    if record.get("qste:experiencingSubjectClaim") is not False:
        raise ContractError("conformance_failed", "P10 harness claims an experiencing subject")
    limits = _object(record.get("qste:limits"), "harness limits")
    if len(limits) != 5 or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 1
        for value in limits.values()
    ):
        raise ContractError("conformance_failed", "P10 harness limits are incomplete")


def _opportunity(record: Mapping[str, Any]) -> None:
    if record.get("qste:opportunityStatus") != "executable":
        raise ContractError("conformance_failed", "P10 opportunity is not executable")
    _object(record.get("budget"), "opportunity budget")
    _object(record.get("qste:outsideInformation"), "matched outside information")
    if not isinstance(record.get("matched_state_key"), str):
        raise ContractError("conformance_failed", "P10 matched state key is absent")


def _successor(record: Mapping[str, Any]) -> None:
    diff = _object(record.get("semantic_diff"), "successor diff")
    if diff.get("semantic_or_behavioral_difference") is not True:
        raise ContractError("conformance_failed", "P10 successor is hash-only or no-change")
    changes = diff.get("changed_fields")
    if not isinstance(changes, list) or not changes:
        raise ContractError("conformance_failed", "P10 successor has no changed field")
    for change in changes:
        if not isinstance(change, Mapping) or change.get("field") in VOLATILE:
            raise ContractError("conformance_failed", "P10 successor changes volatile identity")
        if change.get("before") == change.get("after"):
            raise ContractError("conformance_failed", "P10 successor change is semantically empty")
    if not isinstance(record.get("qste:nextOpportunityRef"), Mapping):
        raise ContractError("conformance_failed", "P10 successor is not persisted forward")
    _object(record.get("qste:state"), "successor executable state")


def _decision(record: Mapping[str, Any]) -> None:
    if record.get("revision_treatment") not in TREATMENTS:
        raise ContractError("conformance_failed", "P10 decision treatment is noncanonical")
    if record.get("qste:executorOriginatedAuthority") is not False:
        raise ContractError("conformance_failed", "P10 executor originated authority")
    if record.get("qste:creativeConsequence") != "not_assessed":
        raise ContractError("conformance_failed", "P10 decision collapsed creativity")
    if not isinstance(record.get("cited_evidence"), list) or not record["cited_evidence"]:
        raise ContractError("conformance_failed", "P10 decision cites no exact evidence")
    diff = _object(record.get("predecessor_successor_diff"), "decision diff")
    action = record.get("decision_action")
    if (
        action in {"refuse", "escalate", "no_change"}
        and diff.get("semantic_or_behavioral_difference") is not False
    ):
        raise ContractError("conformance_failed", "P10 nonsuccessor decision claims revision")
    consequence = _object(record.get("executable_consequence"), "decision consequence")
    if consequence.get("external_execution") is True:
        raise ContractError("conformance_failed", "P10 decision implies external execution")
    leakage = _object(record.get("leakage_checks"), "decision leakage checks")
    if leakage.get("prompt_authority") is not False:
        raise ContractError("conformance_failed", "P10 prompt became authority")


def _artifact(record: Mapping[str, Any]) -> None:
    if record.get("qste:payloadProfile") == PAYLOAD_PROFILE:
        if record.get("qste:recordLevel") not in {
            "ordinary",
            "formation_only",
            "full_assessment",
        }:
            raise ContractError("conformance_failed", "P10 payload level is invalid")
        if record.get("qste:dsqLabel") != "not_inferred_from_payload_level":
            raise ContractError("conformance_failed", "P10 payload level inferred a DSQ")
        if not isinstance(record.get("qste:invariantOutcomeCoreDigest"), str):
            raise ContractError("conformance_failed", "P10 payload lacks invariant core")
    if record.get("qste:treatmentProfile") == TREATMENT_PROFILE:
        treatment = record.get("qste:revisionTreatment")
        if treatment not in TREATMENTS:
            raise ContractError("conformance_failed", "P10 treatment is invalid")
        if record.get("qste:sourceAuthorizationOverride") is not False:
            raise ContractError("conformance_failed", "P10 treatment overrides permission")
        if treatment == "absent":
            if (
                record.get("artifact_availability") != "unavailable"
                or record.get("qste:executorPayloadSupplied") is not False
            ):
                raise ContractError("conformance_failed", "P10 absent condition supplies content")
        elif record.get("qste:executorPayloadSupplied") is not True:
            raise ContractError("conformance_failed", "P10 content treatment is missing")
        if (treatment == "authentic") != (record.get("qste:evidenceRelationIntact") is True):
            raise ContractError("conformance_failed", "P10 treatment relation state conflicts")
    if record.get("qste:plan") is True and (
        record.get("qste:promptAuthority") is not False
        or record.get("qste:externalExecution") is not False
    ):
        raise ContractError("conformance_failed", "P10 plan was treated as a command")


def _next_run(record: Mapping[str, Any]) -> None:
    if record.get("qste:runStatus") != "scheduled_not_executed":
        raise ContractError("conformance_failed", "P10 next run falsely claims execution")
    if not isinstance(record.get("qste:predecessorRunRef"), Mapping):
        raise ContractError("conformance_failed", "P10 next run loses its predecessor")


def _claim(record: Mapping[str, Any]) -> None:
    scope = _object(record.get("scope"), "P10 claim scope")
    if record.get("qste:studyProfile") == STUDY_PROFILE and (
        scope.get("synthetic_conformance_only") is not True
        or scope.get("empirical_or_causal_research_claim") is not False
        or record.get("qste:implementerClassDecisive") is not False
        or record.get("qste:utilityStatus") != "not_assessed_separate_axis"
    ):
        raise ContractError("conformance_failed", "P10 study overclaims its fixture")
    if record.get("qste:utilityProfile") == UTILITY_PROFILE and (
        record.get("qste:heldOut") is not True
        or record.get("qste:evidenceDependenceStatus") != "not_inferred_from_utility"
        or record.get("qste:creativeConsequence") != "not_assessed"
    ):
        raise ContractError("conformance_failed", "P10 utility collapsed independent axes")


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ContractError("conformance_failed", f"P10 {label} is absent")
    return value
