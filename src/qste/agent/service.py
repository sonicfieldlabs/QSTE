"""Bounded, deterministic P10 agent host and comparative controls."""

from __future__ import annotations

import base64
import random
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn, cast

from qste.agent.contracts import (
    ACTION_REGISTRY,
    EXECUTOR_CLASSES,
    HARNESS_PROFILE,
    LIMIT_FIELDS,
    PAYLOAD_LEVELS,
    PAYLOAD_PROFILE,
    REVISION_PROFILE,
    STUDY_PROFILE,
    TREATMENT_PROFILE,
    TREATMENTS,
    UTILITY_PROFILE,
    VOLATILE_FIELDS,
)
from qste.agent.models import AgentOutcome
from qste.core import canonical_json_bytes, content_digest, loads_json, utc_timestamp
from qste.core.contracts import BASE_URI, ContractError
from qste.ingress.records import bind_semantic_key, operation_receipt, record_base, record_ref
from qste.storage import ArtifactStore, RecordStore, WorkspacePaths

MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_TREATMENT_FIELDS = 64
MAX_ACTIONS = 64


class AgentHostService:
    """Host proposals as data and execute only independently validated actions."""

    def __init__(self, workspace: Path) -> None:
        self.paths = WorkspacePaths.open(workspace)
        self.store = RecordStore(self.paths)
        self.artifacts = ArtifactStore(self.paths)

    def create_payloads(
        self,
        *,
        assessment_record_id: str,
        outcome_core: Mapping[str, Any],
        formation: Mapping[str, Any],
        assessment: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> AgentOutcome:
        """Create three redactions with one byte-identical invariant outcome core."""

        source = self.store.get_record(assessment_record_id).record
        self._authorize(authorization_status, "create_information_payloads", source)
        try:
            core = _exact_nonempty(
                outcome_core,
                {
                    "candidate_support",
                    "task_response",
                    "uncertainty",
                    "operation_refs",
                    "provenance",
                },
                "outcome core",
            )
            formation_value = _exact_nonempty(
                formation,
                {
                    "apparatus",
                    "aperture",
                    "representation",
                    "candidate_construction",
                    "intervention_formation",
                },
                "formation payload",
            )
            assessment_value = _exact_nonempty(
                assessment,
                {
                    "meaningful_bound",
                    "equivalence_region",
                    "refinement_procedure",
                    "proper_node_intervals",
                    "controls",
                    "multiplicity",
                    "verdict",
                },
                "assessment payload",
            )
        except ContractError as error:
            self._fail("create_information_payloads", source, error.reason_code, str(error))
        core_digest = content_digest(canonical_json_bytes(core))
        timestamp = utc_timestamp()
        records: list[dict[str, Any]] = []
        for level in PAYLOAD_LEVELS:
            payload: dict[str, Any] = {
                "profile_id": PAYLOAD_PROFILE,
                "record_level": level,
                "outcome_core": core,
            }
            if level in {"formation_only", "full_assessment"}:
                payload["formation"] = formation_value
            if level == "full_assessment":
                payload["assessment"] = assessment_value
            record = self._known_artifact(
                payload,
                media_type="application/vnd.qste.dsq-information-payload+json",
                timestamp=timestamp,
                references=[record_ref(assessment_record_id, cast(str, source["record_type"]))],
            )
            record.update(
                {
                    "qste:agentProfile": REVISION_PROFILE,
                    "qste:payloadProfile": PAYLOAD_PROFILE,
                    "qste:recordLevel": level,
                    "qste:invariantOutcomeCoreDigest": core_digest,
                    "qste:dsqLabel": "not_inferred_from_payload_level",
                    "qste:assessmentStatus": (
                        assessment_value["verdict"] if level == "full_assessment" else "not_exposed"
                    ),
                }
            )
            bind_semantic_key(
                record,
                "qste-semantic-key/information-payload-v1",
                {
                    "source_semantic_key": source.get("semantic_key", source["record_id"]),
                    "record_level": level,
                    "outcome_core_digest": core_digest,
                    "payload_digest": record["content_digest"],
                },
            )
            records.append(record)
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(assessment_record_id, cast(str, source["record_type"])),
            authorization_status="permitted",
            operation="create_information_payloads",
            inputs=[record_ref(assessment_record_id, cast(str, source["record_type"]))],
            parameters={"profile": PAYLOAD_PROFILE, "levels": list(PAYLOAD_LEVELS)},
            outputs=[record_ref(value["record_id"], "ArtifactRecord") for value in records],
            tool_id="qste-p10-agent-host",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [*records, receipt],
            domain_event_record_id=None,
            event_type="qste:information-payloads-created/0.1",
            subject_record_id=records[-1]["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"levels": list(PAYLOAD_LEVELS), "core_digest": core_digest},
            created_at=timestamp,
        )
        return AgentOutcome(
            _payload("InformationPayloadSet", items=records, data={"core_digest": core_digest}),
            "qste-payload/0.3.0/InformationPayloadSet",
            receipt,
            event.event_sequence,
        )

    def initialize_harness(
        self,
        *,
        governance_boundary_record_id: str,
        authority_record_id: str,
        source_record_id: str,
        completed_run_record_id: str,
        predecessor_record_id: str,
        record_ids: Sequence[str],
        executor: Mapping[str, Any],
        initial_state: Mapping[str, Any],
        executable_action_set: Sequence[str],
        limits: Mapping[str, Any],
        evaluation: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> AgentOutcome:
        """Freeze H, its baseline successor, and its first executable opportunity."""

        boundary = self._record(governance_boundary_record_id, "GovernanceBoundary")
        authority = self.store.get_record(authority_record_id).record
        source = self.store.get_record(source_record_id).record
        run = self._record(completed_run_record_id, "RunManifest")
        predecessor = self.store.get_record(predecessor_record_id).record
        self._authorize(authorization_status, "initialize_harness", source)
        try:
            normalized_executor = _executor(executor)
            normalized_limits = self._limits(limits, boundary)
            actions = self._action_set(executable_action_set, boundary)
            if not isinstance(initial_state, Mapping) or not initial_state:
                raise ContractError("invalid_input", "initial listening state is required")
            if not isinstance(evaluation, Mapping) or not evaluation:
                raise ContractError("invalid_input", "evaluation and controls are required")
            self._authority(boundary, authority_record_id)
            resolved = [self.store.get_record(value).record for value in record_ids]
            if not resolved:
                raise ContractError("invalid_input", "harness record set is empty")
        except ContractError as error:
            self._fail("initialize_harness", source, error.reason_code, str(error))

        timestamp = utc_timestamp()
        next_sequence = len(self.store.iter_events()) + 1
        receipt_id = cast(str, record_base("OperationReceipt", created_at=timestamp)["record_id"])
        decision_id = cast(str, record_base("DecisionEvent", created_at=timestamp)["record_id"])
        successor_id = cast(str, record_base("SuccessorSpec", created_at=timestamp)["record_id"])
        opportunity_id = cast(
            str, record_base("RevisionOpportunity", created_at=timestamp)["record_id"]
        )
        harness_id = cast(
            str, record_base("ListeningHarnessSpec", created_at=timestamp)["record_id"]
        )
        opportunity = record_base(
            "RevisionOpportunity", created_at=timestamp, record_id=opportunity_id
        ) | {
            "references": [
                record_ref(source_record_id, cast(str, source["record_type"])),
                record_ref(completed_run_record_id, "RunManifest"),
                record_ref(successor_id, "SuccessorSpec"),
                record_ref(governance_boundary_record_id, "GovernanceBoundary"),
                record_ref(harness_id, "ListeningHarnessSpec"),
            ],
            "source_item_ref": record_ref(source_record_id, cast(str, source["record_type"])),
            "completed_run_ref": record_ref(completed_run_record_id, "RunManifest"),
            "initial_successor_spec_ref": record_ref(successor_id, "SuccessorSpec"),
            "governance_boundary_ref": record_ref(
                governance_boundary_record_id, "GovernanceBoundary"
            ),
            "matched_state_key": content_digest(
                canonical_json_bytes(
                    {
                        "source": source.get("semantic_key", source_record_id),
                        "run": run.get("semantic_key", completed_run_record_id),
                        "state": dict(initial_state),
                        "limits": normalized_limits,
                    }
                )
            ),
            "budget": normalized_limits,
            "qste:agentProfile": REVISION_PROFILE,
            "qste:harnessRef": record_ref(harness_id, "ListeningHarnessSpec"),
            "qste:opportunityStatus": "executable",
            "qste:outsideInformation": dict(evaluation.get("outside_information", {})),
        }
        bind_semantic_key(
            opportunity,
            "qste-semantic-key/revision-opportunity-v1",
            {
                "source": source.get("semantic_key", source_record_id),
                "completed_run": run.get("semantic_key", completed_run_record_id),
                "initial_state": dict(initial_state),
                "boundary": boundary["semantic_key"],
                "matched_state_key": opportunity["matched_state_key"],
                "budget": normalized_limits,
            },
        )
        decision = record_base("DecisionEvent", created_at=timestamp, record_id=decision_id) | {
            "references": [
                record_ref(opportunity_id, "RevisionOpportunity"),
                record_ref(source_record_id, cast(str, source["record_type"])),
                record_ref(authority_record_id, cast(str, authority["record_type"])),
                record_ref(governance_boundary_record_id, "GovernanceBoundary"),
                record_ref(completed_run_record_id, "RunManifest"),
                record_ref(receipt_id, "OperationReceipt"),
            ],
            "opportunity_ref": record_ref(opportunity_id, "RevisionOpportunity"),
            "revision_treatment": "authentic",
            "alternatives": ["initialize", "refuse", "escalate"],
            "cited_evidence": [
                {"record_id": source_record_id, "fields": ["record_type", "semantic_key"]}
            ],
            "reason_code": "initial_harness_state_authorized",
            "authority_ref": record_ref(authority_record_id, cast(str, authority["record_type"])),
            "governance_boundary_ref": record_ref(
                governance_boundary_record_id, "GovernanceBoundary"
            ),
            "decision_action": "execute",
            "predecessor_successor_diff": {
                "comparator": "qste-semantic-or-behavioral-difference/v0.1",
                "changed_fields": [
                    {"field": "initial_state", "before": None, "after": dict(initial_state)}
                ],
                "semantic_or_behavioral_difference": True,
            },
            "executable_consequence": {
                "next_action_set": actions,
                "external_execution": False,
            },
            "next_run_ref": record_ref(completed_run_record_id, "RunManifest"),
            "budget": normalized_limits,
            "leakage_checks": {
                "status": "not_applicable_initialization",
                "prompt_authority": False,
            },
            "receipt_ref": record_ref(receipt_id, "OperationReceipt"),
            "event_sequence": next_sequence,
            "qste:agentProfile": REVISION_PROFILE,
            "qste:executorClass": normalized_executor["executor_class"],
            "qste:executorOriginatedAuthority": False,
            "qste:creativeConsequence": "not_assessed",
        }
        bind_semantic_key(
            decision,
            "qste-semantic-key/agent-decision-event-v1",
            {
                "opportunity_record_id": opportunity_id,
                "treatment": "authentic",
                "cited_evidence": decision["cited_evidence"],
                "decision_action": "execute",
                "diff": decision["predecessor_successor_diff"],
                "authority_record_id": authority_record_id,
            },
        )
        successor = record_base("SuccessorSpec", created_at=timestamp, record_id=successor_id) | {
            "references": [
                record_ref(
                    predecessor_record_id, cast(str, predecessor["record_type"]), "succeeds"
                ),
                record_ref(completed_run_record_id, "RunManifest"),
                record_ref(decision_id, "DecisionEvent"),
                record_ref(authority_record_id, cast(str, authority["record_type"])),
                record_ref(opportunity_id, "RevisionOpportunity"),
            ],
            "predecessor_ref": record_ref(
                predecessor_record_id, cast(str, predecessor["record_type"]), "succeeds"
            ),
            "completed_run_ref": record_ref(completed_run_record_id, "RunManifest"),
            "semantic_diff": decision["predecessor_successor_diff"],
            "executable_action_set": actions,
            "capability_requirements": ["qste-foundation/0.1", HARNESS_PROFILE],
            "decision_event_ref": record_ref(decision_id, "DecisionEvent"),
            "evidence_fields": ["initial_state", "governance_boundary"],
            "revision_treatment": "authentic",
            "authority_ref": record_ref(authority_record_id, cast(str, authority["record_type"])),
            "persistence_target": "first_revision_opportunity",
            "qste:agentProfile": REVISION_PROFILE,
            "qste:governanceBoundaryRef": record_ref(
                governance_boundary_record_id, "GovernanceBoundary"
            ),
            "qste:state": dict(initial_state),
            "qste:nextOpportunityRef": record_ref(opportunity_id, "RevisionOpportunity"),
        }
        bind_semantic_key(
            successor,
            "qste-semantic-key/agent-successor-spec-v1",
            {
                "predecessor": predecessor.get("semantic_key", predecessor_record_id),
                "completed_run": run.get("semantic_key", completed_run_record_id),
                "state": dict(initial_state),
                "action_set": actions,
                "authority": authority_record_id,
            },
        )
        harness = record_base(
            "ListeningHarnessSpec", created_at=timestamp, record_id=harness_id
        ) | {
            "references": [
                *[
                    record_ref(value["record_id"], cast(str, value["record_type"]))
                    for value in resolved
                ],
                record_ref(authority_record_id, cast(str, authority["record_type"])),
                record_ref(governance_boundary_record_id, "GovernanceBoundary"),
                record_ref(successor_id, "SuccessorSpec"),
                record_ref(opportunity_id, "RevisionOpportunity"),
            ],
            "record_refs": [
                record_ref(value["record_id"], cast(str, value["record_type"]))
                for value in resolved
            ],
            "routes": ["plan", "revise", "refuse", "escalate", "resume", "account"],
            "permissions": [
                {"action_id": value, "source": "governance_boundary"} for value in actions
            ],
            "refusals": [
                "source_authorization_not_permitted",
                "action_outside_boundary",
                "budget_exhausted",
                "human_authorization_required",
            ],
            "authority_ref": record_ref(authority_record_id, cast(str, authority["record_type"])),
            "executor": normalized_executor["executor_id"],
            "action_surface": {
                "registry": "qste-agent-action-registry/v0.1",
                "permitted_actions": actions,
                "network": False,
                "model_execution": False,
                "external_write": False,
                "prompt_authority": False,
            },
            "qste:agentProfile": REVISION_PROFILE,
            "qste:harnessProfile": HARNESS_PROFILE,
            "qste:executorClass": normalized_executor["executor_class"],
            "qste:executorImplementationStatus": normalized_executor["implementation_status"],
            "qste:governanceBoundaryRef": record_ref(
                governance_boundary_record_id, "GovernanceBoundary"
            ),
            "qste:limits": normalized_limits,
            "qste:evaluation": dict(evaluation),
            "qste:initialSuccessorRef": record_ref(successor_id, "SuccessorSpec"),
            "qste:firstOpportunityRef": record_ref(opportunity_id, "RevisionOpportunity"),
            "qste:experiencingSubjectClaim": False,
        }
        bind_semantic_key(
            harness,
            "qste-semantic-key/listening-harness-v1",
            {
                "records": [value.get("semantic_key", value["record_id"]) for value in resolved],
                "boundary": boundary["semantic_key"],
                "executor": normalized_executor,
                "actions": actions,
                "limits": normalized_limits,
                "evaluation": dict(evaluation),
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            record_id=receipt_id,
            request_ref=record_ref(source_record_id, cast(str, source["record_type"])),
            authorization_status="permitted",
            operation="initialize_harness",
            inputs=[
                record_ref(source_record_id, cast(str, source["record_type"])),
                record_ref(governance_boundary_record_id, "GovernanceBoundary"),
                record_ref(completed_run_record_id, "RunManifest"),
            ],
            parameters={"executor": normalized_executor, "limits": normalized_limits},
            outputs=[
                record_ref(harness_id, "ListeningHarnessSpec"),
                record_ref(successor_id, "SuccessorSpec"),
                record_ref(opportunity_id, "RevisionOpportunity"),
            ],
            tool_id="qste-p10-agent-host",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [opportunity, decision, successor, harness, receipt],
            domain_event_record_id=None,
            event_type="qste:listening-harness-initialized/0.1",
            subject_record_id=harness_id,
            receipt_record_id=receipt_id,
            payload={"executor_class": normalized_executor["executor_class"]},
            created_at=timestamp,
        )
        return AgentOutcome(
            _payload(
                "HarnessInitialization",
                items=[harness, successor, opportunity, decision],
                data={"executor_originated_authority": False},
            ),
            "qste-payload/0.3.0/HarnessInitialization",
            receipt,
            event.event_sequence,
        )

    def prepare_treatments(
        self,
        *,
        opportunity_record_id: str,
        authentic_payload_record_id: str,
        allocation: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> AgentOutcome:
        """Create authentic, absent, byte-matched placebo, and permuted materials."""

        opportunity = self._record(opportunity_record_id, "RevisionOpportunity")
        payload_record = self._record(authentic_payload_record_id, "ArtifactRecord")
        self._authorize(authorization_status, "prepare_revision_treatments", opportunity)
        try:
            allocation_value = _exact_nonempty(
                allocation,
                {
                    "method",
                    "seed",
                    "presentation_slot",
                    "access_profile",
                    "timing_profile",
                    "matching_assumptions",
                    "residual_confounding",
                },
                "treatment allocation",
            )
            if allocation_value["method"] not in {"randomized", "matched"}:
                raise ContractError("invalid_input", "allocation method is not canonical")
            seed = _nonnegative_int(allocation_value["seed"], "allocation seed")
            payload = self._artifact_json(payload_record)
            exposure = _exposure(payload_record, payload)
            if not 2 <= len(exposure["slots"]) <= MAX_TREATMENT_FIELDS:
                raise ContractError("invalid_input", "treatment requires 2-64 exposed fields")
        except ContractError as error:
            self._fail("prepare_revision_treatments", opportunity, error.reason_code, str(error))
        authentic_bytes = canonical_json_bytes(exposure)
        placebo = {
            **exposure,
            "source_content_digest": "sha256:" + "0" * 64,
            "slots": [
                {"field": value["field"], "payload_b64": "A" * len(value["payload_b64"])}
                for value in exposure["slots"]
            ],
        }
        rotated = [value["payload_b64"] for value in exposure["slots"]]
        rotated = rotated[1:] + rotated[:1]
        permuted = {
            **exposure,
            "slots": [
                {"field": value["field"], "payload_b64": rotated[index]}
                for index, value in enumerate(exposure["slots"])
            ],
        }
        placebo_bytes = canonical_json_bytes(placebo)
        permuted_bytes = canonical_json_bytes(permuted)
        if len(placebo_bytes) != len(authentic_bytes):
            self._fail(
                "prepare_revision_treatments",
                opportunity,
                "conformance_failed",
                "placebo is not byte-length matched",
            )
        if len(permuted_bytes) != len(authentic_bytes):
            self._fail(
                "prepare_revision_treatments",
                opportunity,
                "conformance_failed",
                "permuted treatment is not byte-length matched",
            )
        if sorted(rotated) != sorted(value["payload_b64"] for value in exposure["slots"]):
            self._fail(
                "prepare_revision_treatments",
                opportunity,
                "conformance_failed",
                "permutation does not preserve payload values",
            )
        timestamp = utc_timestamp()
        values: list[dict[str, Any]] = []
        known_bytes = {
            "authentic": authentic_bytes,
            "placebo": placebo_bytes,
            "permuted": permuted_bytes,
        }
        order = list(TREATMENTS)
        # B311: this is deterministic study allocation, not cryptographic randomness.
        random.Random(seed).shuffle(order)  # nosec B311
        for treatment in TREATMENTS:
            if treatment == "absent":
                record = record_base(
                    "ArtifactRecord",
                    created_at=timestamp,
                    references=[record_ref(opportunity_record_id, "RevisionOpportunity")],
                ) | {
                    "media_type": "application/vnd.qste.revision-treatment+json",
                    "artifact_availability": "unavailable",
                    "byte_state": "intentionally_absent_from_executor",
                }
            else:
                record = self._known_artifact_bytes(
                    known_bytes[treatment],
                    media_type="application/vnd.qste.revision-treatment+json",
                    timestamp=timestamp,
                    references=[
                        record_ref(opportunity_record_id, "RevisionOpportunity"),
                        record_ref(authentic_payload_record_id, "ArtifactRecord"),
                    ],
                )
            record.update(
                {
                    "qste:agentProfile": REVISION_PROFILE,
                    "qste:treatmentProfile": TREATMENT_PROFILE,
                    "qste:revisionTreatment": treatment,
                    "qste:opportunityRef": record_ref(opportunity_record_id, "RevisionOpportunity"),
                    "qste:authenticPayloadRef": record_ref(
                        authentic_payload_record_id, "ArtifactRecord"
                    ),
                    "qste:allocation": {
                        **allocation_value,
                        "order": order,
                        "position": order.index(treatment),
                    },
                    "qste:executorPayloadSupplied": treatment != "absent",
                    "qste:evidenceRelationIntact": treatment == "authentic",
                    "qste:matchedExposureBytes": len(authentic_bytes),
                    "qste:payloadMultisetDigest": content_digest(
                        canonical_json_bytes(
                            sorted(value["payload_b64"] for value in exposure["slots"])
                        )
                    ),
                    "qste:sourceAuthorizationOverride": False,
                }
            )
            bind_semantic_key(
                record,
                "qste-semantic-key/revision-treatment-v1",
                {
                    "opportunity": opportunity["semantic_key"],
                    "treatment": treatment,
                    "payload_digest": record.get("content_digest"),
                    "allocation": record["qste:allocation"],
                },
            )
            values.append(record)
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(opportunity_record_id, "RevisionOpportunity"),
            authorization_status="permitted",
            operation="prepare_revision_treatments",
            inputs=[
                record_ref(opportunity_record_id, "RevisionOpportunity"),
                record_ref(authentic_payload_record_id, "ArtifactRecord"),
            ],
            parameters={"allocation": allocation_value},
            outputs=[record_ref(value["record_id"], "ArtifactRecord") for value in values],
            tool_id="qste-p10-agent-host",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [*values, receipt],
            domain_event_record_id=None,
            event_type="qste:revision-treatments-prepared/0.1",
            subject_record_id=opportunity_record_id,
            receipt_record_id=receipt["record_id"],
            payload={"treatments": list(TREATMENTS), "allocation_order": order},
            created_at=timestamp,
        )
        return AgentOutcome(
            _payload("TreatmentSet", items=values, data={"allocation_order": order}),
            "qste-payload/0.3.0/TreatmentSet",
            receipt,
            event.event_sequence,
        )

    def plan(
        self,
        *,
        opportunity_record_id: str,
        treatment_record_id: str,
        proposal: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> AgentOutcome:
        """Persist an executor proposal as inert data after structural validation."""

        opportunity = self._record(opportunity_record_id, "RevisionOpportunity")
        treatment = self._record(treatment_record_id, "ArtifactRecord")
        self._authorize(authorization_status, "plan_revision", opportunity)
        try:
            normalized = _proposal(proposal)
            if treatment.get("qste:opportunityRef", {}).get("record_id") != opportunity_record_id:
                raise ContractError(
                    "conformance_failed", "treatment belongs to another opportunity"
                )
            self._resource_use(normalized["resource_use"], opportunity["budget"])
        except ContractError as error:
            self._fail("plan_revision", opportunity, error.reason_code, str(error))
        timestamp = utc_timestamp()
        plan_value = {
            "profile_id": REVISION_PROFILE,
            "opportunity_record_id": opportunity_record_id,
            "treatment_record_id": treatment_record_id,
            "revision_treatment": treatment["qste:revisionTreatment"],
            "proposal": normalized,
            "prompt_role": "untrusted_data_not_authority",
        }
        plan = self._known_artifact(
            plan_value,
            media_type="application/vnd.qste.revision-plan+json",
            timestamp=timestamp,
            references=[
                record_ref(opportunity_record_id, "RevisionOpportunity"),
                record_ref(treatment_record_id, "ArtifactRecord"),
            ],
        )
        plan.update(
            {
                "qste:agentProfile": REVISION_PROFILE,
                "qste:plan": True,
                "qste:actionId": normalized["action_id"],
                "qste:promptAuthority": False,
                "qste:externalExecution": False,
            }
        )
        bind_semantic_key(
            plan,
            "qste-semantic-key/revision-plan-v1",
            {
                "opportunity": opportunity["semantic_key"],
                "treatment": treatment["semantic_key"],
                "proposal": normalized,
            },
        )
        return self._simple_outcome(
            operation="plan_revision",
            request=opportunity,
            value=plan,
            value_type=f"{BASE_URI}/records/artifact-record.schema.json",
            records=[plan],
            parameters={"action_id": normalized["action_id"]},
            outputs=[record_ref(plan["record_id"], "ArtifactRecord")],
            event_type="qste:revision-plan-recorded/0.1",
            timestamp=timestamp,
        )

    def revise(
        self,
        *,
        plan_record_id: str,
        authority_record_id: str,
        source_authorization_status: str,
        enforcement_mode: str,
        fixture_authorization: str,
        human_authorized: bool = False,
        authorization_status: str = "permitted",
    ) -> AgentOutcome:
        """Evaluate an inert plan and persist a decision plus any permitted successor."""

        plan_record = self._record(plan_record_id, "ArtifactRecord")
        self._authorize(authorization_status, "revise", plan_record)
        plan = self._artifact_json(plan_record)
        try:
            if source_authorization_status not in {
                "unknown",
                "permitted",
                "refused",
                "deferred",
                "revoked",
            }:
                raise ContractError("invalid_input", "source authorization status is invalid")
            if not isinstance(human_authorized, bool):
                raise ContractError("invalid_input", "human authorization must be an exact boolean")
            if plan.get("profile_id") != REVISION_PROFILE or plan.get("prompt_role") != (
                "untrusted_data_not_authority"
            ):
                raise ContractError("conformance_failed", "revision plan boundary is invalid")
            opportunity = self._record(
                cast(str, plan["opportunity_record_id"]), "RevisionOpportunity"
            )
            treatment = self._record(cast(str, plan["treatment_record_id"]), "ArtifactRecord")
            boundary = self._record(
                cast(str, opportunity["governance_boundary_ref"]["record_id"]),
                "GovernanceBoundary",
            )
            initial = self._record(
                cast(str, opportunity["initial_successor_spec_ref"]["record_id"]),
                "SuccessorSpec",
            )
            completed_run = self._record(
                cast(str, opportunity["completed_run_ref"]["record_id"]), "RunManifest"
            )
            authority = self.store.get_record(authority_record_id).record
            self._authority(boundary, authority_record_id)
            proposal = _proposal(cast(Mapping[str, Any], plan["proposal"]))
            action = ACTION_REGISTRY[proposal["action_id"]]
            self._resource_use(proposal["resource_use"], opportunity["budget"])
            if proposal["action_id"] not in boundary["permitted_actions"]:
                raise ContractError("policy_refused", "planned action is outside the boundary")
            if source_authorization_status != "permitted":
                return self._refusal(
                    plan_record,
                    opportunity,
                    treatment,
                    boundary,
                    authority,
                    proposal,
                    "source_authorization_not_permitted",
                    source_authorization_status,
                )
            human_actions = boundary.get("qste:humanAuthorizationActions", [])
            if proposal["action_id"] in human_actions and not human_authorized:
                return self._refusal(
                    plan_record,
                    opportunity,
                    treatment,
                    boundary,
                    authority,
                    proposal,
                    "human_authorization_required",
                    "permitted",
                )
            if enforcement_mode not in {"active", "shadow"}:
                raise ContractError("invalid_input", "enforcement mode is invalid")
            if fixture_authorization not in {"synthetic", "fully_authorized"}:
                raise ContractError("policy_refused", "P10 revision fixture is not authorized")
            study_allowed = proposal["study_policy_permitted"]
            if not study_allowed and enforcement_mode == "active":
                return self._refusal(
                    plan_record,
                    opportunity,
                    treatment,
                    boundary,
                    authority,
                    proposal,
                    "study_policy_blocked",
                    "permitted",
                )
            if action.decision_action == "refuse":
                return self._refusal(
                    plan_record,
                    opportunity,
                    treatment,
                    boundary,
                    authority,
                    proposal,
                    proposal["reason_code"],
                    "permitted",
                )
            return self._decision(
                plan_record,
                opportunity,
                treatment,
                boundary,
                initial,
                completed_run,
                authority,
                proposal,
                action.decision_action,
                enforcement_mode,
                would_have_blocked=not study_allowed,
            )
        except ContractError as error:
            if hasattr(error, "receipt_id"):
                raise
            self._fail("revise", plan_record, error.reason_code, str(error))

    def assess_study(
        self,
        *,
        decision_record_ids: Mapping[str, Sequence[str]],
        preregistration: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> AgentOutcome:
        """Assess synthetic treatment divergence without making an empirical claim."""

        if set(decision_record_ids) != set(TREATMENTS):
            raise ContractError("invalid_input", "study requires all four treatment conditions")
        decisions = {
            treatment: [self._record(value, "DecisionEvent") for value in values]
            for treatment, values in decision_record_ids.items()
        }
        request = decisions["authentic"][0]
        self._authorize(authorization_status, "assess_revision_study", request)
        try:
            spec = _exact_nonempty(
                preregistration,
                {
                    "minimum_opportunities_per_condition",
                    "randomization_or_matching",
                    "matching_complete",
                    "leakage_detected",
                    "outside_information_matched",
                    "budgets_matched",
                    "action_surface_matched",
                    "initial_state_matched",
                    "executor_resources_matched",
                },
                "study preregistration",
            )
            minimum = _positive_int(
                spec["minimum_opportunities_per_condition"], "minimum opportunities"
            )
            if spec["randomization_or_matching"] not in {"randomized", "matched"}:
                raise ContractError("invalid_input", "study allocation method is invalid")
            for treatment, values in decisions.items():
                if len(values) < minimum or any(
                    value["revision_treatment"] != treatment for value in values
                ):
                    raise ContractError(
                        "conformance_failed", "study treatment cells are incomplete"
                    )
        except ContractError as error:
            self._fail("assess_revision_study", request, error.reason_code, str(error))
        matched = all(
            spec[key] is True
            for key in (
                "matching_complete",
                "outside_information_matched",
                "budgets_matched",
                "action_surface_matched",
                "initial_state_matched",
                "executor_resources_matched",
            )
        )
        authentic_changed = all(
            value["predecessor_successor_diff"].get("semantic_or_behavioral_difference") is True
            for value in decisions["authentic"]
        )
        controls_changed = any(
            value["predecessor_successor_diff"].get("semantic_or_behavioral_difference") is True
            for treatment in ("absent", "placebo", "permuted")
            for value in decisions[treatment]
        )
        supported = (
            matched
            and spec["leakage_detected"] is False
            and authentic_changed
            and not controls_changed
        )
        timestamp = utc_timestamp()
        claim = record_base(
            "ClaimRecord",
            created_at=timestamp,
            references=[
                record_ref(value["record_id"], "DecisionEvent")
                for values in decisions.values()
                for value in values
            ],
        ) | {
            "proposition": (
                "Synthetic P10 fixture satisfies the preregistered divergence comparator."
                if supported
                else (
                    "Synthetic P10 fixture does not satisfy the preregistered "
                    "divergence comparator."
                )
            ),
            "evidence_basis": "instrumentally_derived",
            "epistemic_status": "derived",
            "scope": {
                "profile": STUDY_PROFILE,
                "synthetic_conformance_only": True,
                "empirical_or_causal_research_claim": False,
            },
            "subject_ref": record_ref(request["record_id"], "DecisionEvent"),
            "evidence_refs": [
                record_ref(value["record_id"], "DecisionEvent")
                for values in decisions.values()
                for value in values
            ],
            "qste:agentProfile": REVISION_PROFILE,
            "qste:studyProfile": STUDY_PROFILE,
            "qste:evidenceDependenceStatus": (
                "supported_synthetic_conformance" if supported else "not_supported"
            ),
            "qste:implementerClassDecisive": False,
            "qste:utilityStatus": "not_assessed_separate_axis",
            "qste:creativeConsequence": "not_assessed",
            "qste:preregistration": spec,
            "qste:cellCounts": {key: len(value) for key, value in decisions.items()},
        }
        bind_semantic_key(
            claim,
            "qste-semantic-key/revision-study-claim-v1",
            {
                "decision_semantic_keys": {
                    key: [value["semantic_key"] for value in values]
                    for key, values in decisions.items()
                },
                "preregistration": spec,
                "status": claim["qste:evidenceDependenceStatus"],
            },
        )
        return self._simple_outcome(
            operation="assess_revision_study",
            request=request,
            value=claim,
            value_type=f"{BASE_URI}/records/claim-record.schema.json",
            records=[claim],
            parameters={"profile": STUDY_PROFILE},
            outputs=[record_ref(claim["record_id"], "ClaimRecord")],
            event_type="qste:revision-study-assessed/0.1",
            timestamp=timestamp,
        )

    def evaluate_utility(
        self,
        *,
        decision_record_id: str,
        evaluation: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> AgentOutcome:
        """Record held-out utility and cost without inferring creativity."""

        decision = self._record(decision_record_id, "DecisionEvent")
        self._authorize(authorization_status, "evaluate_agent_utility", decision)
        try:
            value = _exact_nonempty(
                evaluation,
                {
                    "held_out",
                    "task_metric",
                    "task_score",
                    "false_positive_rate",
                    "compute_units",
                    "latency_ms",
                    "intervention_count",
                    "refusal_cost",
                },
                "utility evaluation",
            )
            if value["held_out"] is not True:
                raise ContractError("conformance_failed", "utility evaluation is not held out")
            for key in (
                "task_score",
                "false_positive_rate",
                "compute_units",
                "latency_ms",
                "intervention_count",
                "refusal_cost",
            ):
                _nonnegative_number(value[key], key)
        except ContractError as error:
            self._fail("evaluate_agent_utility", decision, error.reason_code, str(error))
        timestamp = utc_timestamp()
        claim = record_base(
            "ClaimRecord",
            created_at=timestamp,
            references=[record_ref(decision_record_id, "DecisionEvent")],
        ) | {
            "proposition": "Held-out utility and cost were recorded as a separate axis.",
            "evidence_basis": "instrumentally_derived",
            "epistemic_status": "measured",
            "scope": {"profile": UTILITY_PROFILE, "creative_consequence": False},
            "subject_ref": record_ref(decision_record_id, "DecisionEvent"),
            "evidence_refs": [record_ref(decision_record_id, "DecisionEvent")],
            "qste:agentProfile": REVISION_PROFILE,
            "qste:utilityProfile": UTILITY_PROFILE,
            "qste:heldOut": True,
            "qste:utilityAndCost": value,
            "qste:evidenceDependenceStatus": "not_inferred_from_utility",
            "qste:creativeConsequence": "not_assessed",
        }
        bind_semantic_key(
            claim,
            "qste-semantic-key/held-out-utility-v1",
            {"decision": decision["semantic_key"], "evaluation": value},
        )
        return self._simple_outcome(
            operation="evaluate_agent_utility",
            request=decision,
            value=claim,
            value_type=f"{BASE_URI}/records/claim-record.schema.json",
            records=[claim],
            parameters={"profile": UTILITY_PROFILE},
            outputs=[record_ref(claim["record_id"], "ClaimRecord")],
            event_type="qste:agent-utility-evaluated/0.1",
            timestamp=timestamp,
        )

    def _decision(
        self,
        plan_record: Mapping[str, Any],
        opportunity: Mapping[str, Any],
        treatment: Mapping[str, Any],
        boundary: Mapping[str, Any],
        initial: Mapping[str, Any],
        completed_run: Mapping[str, Any],
        authority: Mapping[str, Any],
        proposal: Mapping[str, Any],
        decision_action: str,
        enforcement_mode: str,
        *,
        would_have_blocked: bool,
    ) -> AgentOutcome:
        action = ACTION_REGISTRY[cast(str, proposal["action_id"])]
        timestamp = utc_timestamp()
        sequence = len(self.store.iter_events()) + 1
        receipt_id = cast(str, record_base("OperationReceipt", created_at=timestamp)["record_id"])
        decision_id = cast(str, record_base("DecisionEvent", created_at=timestamp)["record_id"])
        treatment_name = cast(str, treatment["qste:revisionTreatment"])
        current_state = dict(cast(Mapping[str, Any], initial.get("qste:state", {})))
        changes = cast(list[Mapping[str, Any]], proposal["changes"])
        successor: dict[str, Any] | None = None
        next_run: dict[str, Any] | None = None
        next_opportunity: dict[str, Any] | None = None
        diff = {
            "comparator": "qste-semantic-or-behavioral-difference/v0.1",
            "changed_fields": [dict(value) for value in changes],
            "semantic_or_behavioral_difference": False,
        }
        if action.creates_successor:
            if not changes:
                self._fail("revise", plan_record, "conformance_failed", "successor has no change")
            allowed_fields = set(cast(list[str], boundary["mutable_successor_fields"]))
            next_state = dict(current_state)
            for change in changes:
                field = change.get("field")
                if (
                    not isinstance(field, str)
                    or field in VOLATILE_FIELDS
                    or field not in allowed_fields
                    or field != action.mutable_field
                ):
                    self._fail(
                        "revise",
                        plan_record,
                        "policy_refused",
                        "planned successor field is not permitted",
                    )
                if change.get("before") != current_state.get(field) or change.get("after") == (
                    change.get("before")
                ):
                    self._fail(
                        "revise",
                        plan_record,
                        "conformance_failed",
                        "successor comparator found no exact behavioral change",
                    )
                next_state[field] = change.get("after")
            next_actions = self._action_set(
                cast(Sequence[str], proposal["next_action_set"]), boundary
            )
            diff["semantic_or_behavioral_difference"] = (
                next_state != current_state or next_actions != initial["executable_action_set"]
            )
            if diff["semantic_or_behavioral_difference"] is not True:
                self._fail("revise", plan_record, "conformance_failed", "successor is hash-only")
            successor_id = cast(
                str, record_base("SuccessorSpec", created_at=timestamp)["record_id"]
            )
            next_run_id = cast(str, record_base("RunManifest", created_at=timestamp)["record_id"])
            next_opportunity_id = cast(
                str, record_base("RevisionOpportunity", created_at=timestamp)["record_id"]
            )
            successor = record_base(
                "SuccessorSpec", created_at=timestamp, record_id=successor_id
            ) | {
                "references": [
                    record_ref(cast(str, initial["record_id"]), "SuccessorSpec", "succeeds"),
                    dict(opportunity["completed_run_ref"]),
                    record_ref(decision_id, "DecisionEvent"),
                    record_ref(
                        cast(str, authority["record_id"]), cast(str, authority["record_type"])
                    ),
                    record_ref(next_opportunity_id, "RevisionOpportunity"),
                ],
                "predecessor_ref": record_ref(
                    cast(str, initial["record_id"]), "SuccessorSpec", "succeeds"
                ),
                "completed_run_ref": dict(opportunity["completed_run_ref"]),
                "semantic_diff": diff,
                "executable_action_set": next_actions,
                "capability_requirements": ["qste-foundation/0.1", HARNESS_PROFILE],
                "decision_event_ref": record_ref(decision_id, "DecisionEvent"),
                "evidence_fields": list(proposal["evidence_fields"]),
                "revision_treatment": treatment_name,
                "authority_ref": record_ref(
                    cast(str, authority["record_id"]), cast(str, authority["record_type"])
                ),
                "persistence_target": f"revision-opportunity:{next_opportunity_id}",
                "qste:agentProfile": REVISION_PROFILE,
                "qste:governanceBoundaryRef": dict(opportunity["governance_boundary_ref"]),
                "qste:state": next_state,
                "qste:nextOpportunityRef": record_ref(next_opportunity_id, "RevisionOpportunity"),
            }
            bind_semantic_key(
                successor,
                "qste-semantic-key/agent-successor-spec-v1",
                {
                    "predecessor": initial["semantic_key"],
                    "completed_run": completed_run["semantic_key"],
                    "diff": diff,
                    "state": next_state,
                    "action_set": next_actions,
                    "treatment": treatment_name,
                    "authority": authority["record_id"],
                },
            )
            next_run = record_base("RunManifest", created_at=timestamp, record_id=next_run_id) | {
                "references": [
                    record_ref(cast(str, completed_run["record_id"]), "RunManifest", "succeeds"),
                    record_ref(decision_id, "DecisionEvent"),
                    record_ref(successor_id, "SuccessorSpec"),
                    record_ref(next_opportunity_id, "RevisionOpportunity"),
                ],
                "apparatus_ref": dict(completed_run["apparatus_ref"]),
                "aperture_ref": dict(completed_run["aperture_ref"]),
                "corpus_refs": [dict(value) for value in completed_run["corpus_refs"]],
                "spec_refs": [
                    record_ref(successor_id, "SuccessorSpec"),
                    record_ref(next_opportunity_id, "RevisionOpportunity"),
                ],
                "budgets": dict(opportunity["budget"]),
                "seeds": [0],
                "event_refs": [record_ref(decision_id, "DecisionEvent")],
                "artifact_refs": [dict(value) for value in completed_run["artifact_refs"]],
                "output_refs": [record_ref(successor_id, "SuccessorSpec")],
                "frozen_versions": {
                    **dict(completed_run["frozen_versions"]),
                    "agent_profile": REVISION_PROFILE,
                },
                "qste:agentProfile": REVISION_PROFILE,
                "qste:runStatus": "scheduled_not_executed",
                "qste:predecessorRunRef": record_ref(
                    cast(str, completed_run["record_id"]), "RunManifest"
                ),
            }
            bind_semantic_key(
                next_run,
                "qste-semantic-key/agent-next-run-v1",
                {
                    "predecessor_run": completed_run["semantic_key"],
                    "successor": successor["semantic_key"],
                    "budget": opportunity["budget"],
                },
            )
            next_opportunity = record_base(
                "RevisionOpportunity", created_at=timestamp, record_id=next_opportunity_id
            ) | {
                "references": [
                    dict(opportunity["source_item_ref"]),
                    record_ref(next_run_id, "RunManifest"),
                    record_ref(successor_id, "SuccessorSpec"),
                    dict(opportunity["governance_boundary_ref"]),
                    dict(opportunity["qste:harnessRef"]),
                    record_ref(
                        cast(str, opportunity["record_id"]),
                        "RevisionOpportunity",
                        "succeeds",
                    ),
                ],
                "source_item_ref": dict(opportunity["source_item_ref"]),
                "completed_run_ref": record_ref(next_run_id, "RunManifest"),
                "initial_successor_spec_ref": record_ref(successor_id, "SuccessorSpec"),
                "governance_boundary_ref": dict(opportunity["governance_boundary_ref"]),
                "matched_state_key": f"{opportunity['matched_state_key']}:next",
                "budget": dict(opportunity["budget"]),
                "qste:agentProfile": REVISION_PROFILE,
                "qste:harnessRef": dict(opportunity["qste:harnessRef"]),
                "qste:opportunityStatus": "executable",
                "qste:outsideInformation": dict(opportunity["qste:outsideInformation"]),
                "qste:predecessorOpportunityRef": record_ref(
                    cast(str, opportunity["record_id"]), "RevisionOpportunity"
                ),
            }
            bind_semantic_key(
                next_opportunity,
                "qste-semantic-key/revision-opportunity-v1",
                {
                    "source": opportunity["source_item_ref"]["record_id"],
                    "completed_run": next_run["semantic_key"],
                    "initial_successor": successor["semantic_key"],
                    "boundary": boundary["semantic_key"],
                    "matched_state_key": next_opportunity["matched_state_key"],
                    "budget": opportunity["budget"],
                },
            )
        elif changes:
            self._fail(
                "revise", plan_record, "conformance_failed", "non-successor action carries changes"
            )
        if decision_action == "no_change" and list(proposal["next_action_set"]) != list(
            initial["executable_action_set"]
        ):
            self._fail(
                "revise",
                plan_record,
                "conformance_failed",
                "no-change decision changed the executable action set",
            )

        decision = record_base("DecisionEvent", created_at=timestamp, record_id=decision_id) | {
            "references": [
                record_ref(cast(str, opportunity["record_id"]), "RevisionOpportunity"),
                record_ref(cast(str, treatment["record_id"]), "ArtifactRecord"),
                record_ref(cast(str, authority["record_id"]), cast(str, authority["record_type"])),
                dict(opportunity["governance_boundary_ref"]),
                record_ref(cast(str, plan_record["record_id"]), "ArtifactRecord"),
                *(
                    [
                        record_ref(cast(str, successor["record_id"]), "SuccessorSpec"),
                        record_ref(cast(str, next_run["record_id"]), "RunManifest"),
                    ]
                    if successor is not None and next_run is not None
                    else []
                ),
                record_ref(receipt_id, "OperationReceipt"),
            ],
            "opportunity_ref": record_ref(
                cast(str, opportunity["record_id"]), "RevisionOpportunity"
            ),
            "revision_treatment": treatment_name,
            "alternatives": list(ACTION_REGISTRY),
            "cited_evidence": [
                {
                    "record_id": treatment["record_id"],
                    "fields": list(proposal["evidence_fields"]),
                }
            ],
            "reason_code": proposal["reason_code"],
            "authority_ref": record_ref(
                cast(str, authority["record_id"]), cast(str, authority["record_type"])
            ),
            "governance_boundary_ref": dict(opportunity["governance_boundary_ref"]),
            "decision_action": decision_action,
            "predecessor_successor_diff": diff,
            "executable_consequence": {
                "action_id": proposal["action_id"],
                "next_action_set": list(proposal["next_action_set"]),
                "successor_created": successor is not None,
                "external_execution": False,
                "shadow_mode": enforcement_mode == "shadow",
                "would_have_blocked": would_have_blocked,
            },
            "next_run_ref": (
                record_ref(cast(str, next_run["record_id"]), "RunManifest")
                if next_run
                else dict(opportunity["completed_run_ref"])
            ),
            "budget": {"limits": dict(opportunity["budget"]), "used": proposal["resource_use"]},
            "leakage_checks": {
                "treatment_relation_intact": treatment["qste:evidenceRelationIntact"],
                "outside_information_matched": True,
                "prompt_authority": False,
            },
            "receipt_ref": record_ref(receipt_id, "OperationReceipt"),
            "event_sequence": sequence,
            "qste:agentProfile": REVISION_PROFILE,
            "qste:planRef": record_ref(plan_record["record_id"], "ArtifactRecord"),
            "qste:executorOriginatedAuthority": False,
            "qste:creativeConsequence": "not_assessed",
        }
        bind_semantic_key(
            decision,
            "qste-semantic-key/agent-decision-event-v1",
            {
                "opportunity_semantic_key": opportunity["semantic_key"],
                "treatment_semantic_key": treatment["semantic_key"],
                "cited_evidence": decision["cited_evidence"],
                "decision_action": decision_action,
                "diff": diff,
                "action_id": proposal["action_id"],
                "authority_record_id": authority["record_id"],
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            record_id=receipt_id,
            request_ref=record_ref(plan_record["record_id"], "ArtifactRecord"),
            authorization_status="permitted",
            operation="revise",
            inputs=[
                record_ref(plan_record["record_id"], "ArtifactRecord"),
                record_ref(treatment["record_id"], "ArtifactRecord"),
                record_ref(authority["record_id"], cast(str, authority["record_type"])),
            ],
            parameters={
                "action_id": proposal["action_id"],
                "enforcement_mode": enforcement_mode,
                "would_have_blocked": would_have_blocked,
            },
            outputs=(
                [
                    record_ref(decision_id, "DecisionEvent"),
                    record_ref(cast(str, successor["record_id"]), "SuccessorSpec"),
                    record_ref(cast(str, next_opportunity["record_id"]), "RevisionOpportunity"),
                ]
                if successor and next_opportunity
                else [record_ref(decision_id, "DecisionEvent")]
            ),
            tool_id="qste-p10-agent-host",
            tool_version="v0.1",
        )
        successor_records: list[Mapping[str, Any]] = []
        if successor is not None and next_run is not None and next_opportunity is not None:
            successor_records = [successor, next_run, next_opportunity]
        records = [decision, *successor_records, receipt]
        _, event = self.store.insert_records_with_event(
            records,
            domain_event_record_id=None,
            event_type="qste:agent-revision-decided/0.1",
            subject_record_id=decision_id,
            receipt_record_id=receipt_id,
            payload={
                "decision_action": decision_action,
                "successor_created": successor is not None,
                "treatment": treatment_name,
            },
            created_at=timestamp,
        )
        return AgentOutcome(
            _payload(
                "RevisionOutcome",
                items=[decision, *successor_records],
                data={
                    "decision_action": decision_action,
                    "successor_created": successor is not None,
                    "creative_consequence": "not_assessed",
                },
            ),
            "qste-payload/0.3.0/RevisionOutcome",
            receipt,
            event.event_sequence,
        )

    def _refusal(
        self,
        plan_record: Mapping[str, Any],
        opportunity: Mapping[str, Any],
        treatment: Mapping[str, Any],
        boundary: Mapping[str, Any],
        authority: Mapping[str, Any],
        proposal: Mapping[str, Any],
        reason: str,
        source_authorization_status: str,
    ) -> AgentOutcome:
        next_actions = list(proposal["next_action_set"])
        current = self._record(
            cast(str, opportunity["initial_successor_spec_ref"]["record_id"]),
            "SuccessorSpec",
        )
        if next_actions == current["executable_action_set"]:
            self._fail(
                "revise",
                plan_record,
                "conformance_failed",
                "refusal did not change next action set",
            )
        if not proposal["resume_conditions"] and not proposal["escalation_conditions"]:
            self._fail(
                "revise",
                plan_record,
                "conformance_failed",
                "refusal lacks resumption or escalation conditions",
            )
        timestamp = utc_timestamp()
        sequence = len(self.store.iter_events()) + 1
        receipt_id = cast(str, record_base("OperationReceipt", created_at=timestamp)["record_id"])
        decision = record_base("DecisionEvent", created_at=timestamp) | {
            "references": [
                record_ref(opportunity["record_id"], "RevisionOpportunity"),
                record_ref(treatment["record_id"], "ArtifactRecord"),
                record_ref(authority["record_id"], authority["record_type"]),
                record_ref(boundary["record_id"], "GovernanceBoundary"),
                record_ref(plan_record["record_id"], "ArtifactRecord"),
                record_ref(receipt_id, "OperationReceipt"),
            ],
            "opportunity_ref": record_ref(opportunity["record_id"], "RevisionOpportunity"),
            "revision_treatment": treatment["qste:revisionTreatment"],
            "alternatives": list(ACTION_REGISTRY),
            "cited_evidence": [
                {"record_id": treatment["record_id"], "fields": list(proposal["evidence_fields"])}
            ],
            "reason_code": reason,
            "authority_ref": record_ref(authority["record_id"], authority["record_type"]),
            "governance_boundary_ref": record_ref(boundary["record_id"], "GovernanceBoundary"),
            "decision_action": "refuse",
            "predecessor_successor_diff": {
                "comparator": "qste-semantic-or-behavioral-difference/v0.1",
                "changed_fields": [],
                "semantic_or_behavioral_difference": False,
            },
            "executable_consequence": {
                "next_action_set": next_actions,
                "successor_created": False,
                "resume_conditions": proposal["resume_conditions"],
                "escalation_conditions": proposal["escalation_conditions"],
            },
            "next_run_ref": dict(opportunity["completed_run_ref"]),
            "budget": {"limits": opportunity["budget"], "used": proposal["resource_use"]},
            "leakage_checks": {"prompt_authority": False},
            "receipt_ref": record_ref(receipt_id, "OperationReceipt"),
            "event_sequence": sequence,
            "qste:agentProfile": REVISION_PROFILE,
            "qste:planRef": record_ref(plan_record["record_id"], "ArtifactRecord"),
            "qste:executorOriginatedAuthority": False,
            "qste:creativeConsequence": "not_assessed",
        }
        bind_semantic_key(
            decision,
            "qste-semantic-key/agent-decision-event-v1",
            {
                "opportunity_semantic_key": opportunity["semantic_key"],
                "treatment_semantic_key": treatment["semantic_key"],
                "cited_evidence": decision["cited_evidence"],
                "decision_action": "refuse",
                "reason_code": reason,
                "next_action_set": next_actions,
                "authority_record_id": authority["record_id"],
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            record_id=receipt_id,
            request_ref=record_ref(plan_record["record_id"], "ArtifactRecord"),
            authorization_status=(
                "refused"
                if source_authorization_status == "permitted"
                else source_authorization_status
            ),
            operation="revise",
            inputs=[record_ref(plan_record["record_id"], "ArtifactRecord")],
            parameters={"reason_code": reason},
            outputs=[record_ref(decision["record_id"], "DecisionEvent")],
            operation_status="refused",
            tool_id="qste-p10-agent-host",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [decision, receipt],
            domain_event_record_id=None,
            event_type="qste:agent-revision-refused/0.1",
            subject_record_id=decision["record_id"],
            receipt_record_id=receipt_id,
            payload={"reason_code": reason, "successor_created": False},
            created_at=timestamp,
        )
        return AgentOutcome(
            _payload(
                "RevisionOutcome",
                items=[decision],
                data={"decision_action": "refuse", "successor_created": False},
            ),
            "qste-payload/0.3.0/RevisionOutcome",
            receipt,
            event.event_sequence,
            operation_status="refused",
            reason_code="policy_refused",
        )

    def _simple_outcome(
        self,
        *,
        operation: str,
        request: Mapping[str, Any],
        value: dict[str, Any],
        value_type: str,
        records: Sequence[Mapping[str, Any]],
        parameters: Mapping[str, Any],
        outputs: Sequence[Mapping[str, Any]],
        event_type: str,
        timestamp: str,
    ) -> AgentOutcome:
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(request["record_id"], request["record_type"]),
            authorization_status="permitted",
            operation=operation,
            inputs=[record_ref(request["record_id"], request["record_type"])],
            parameters=dict(parameters),
            outputs=list(outputs),
            tool_id="qste-p10-agent-host",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [*[dict(value) for value in records], receipt],
            domain_event_record_id=None,
            event_type=event_type,
            subject_record_id=cast(str, value["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"operation": operation},
            created_at=timestamp,
        )
        return AgentOutcome(value, value_type, receipt, event.event_sequence)

    def _known_artifact(
        self,
        value: Mapping[str, Any],
        *,
        media_type: str,
        timestamp: str,
        references: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        data = canonical_json_bytes(dict(value))
        if len(data) > MAX_PAYLOAD_BYTES:
            raise ContractError("resource_limit", "P10 payload exceeds its byte bound")
        return self._known_artifact_bytes(
            data, media_type=media_type, timestamp=timestamp, references=references
        )

    def _known_artifact_bytes(
        self,
        data: bytes,
        *,
        media_type: str,
        timestamp: str,
        references: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        object_ = self.artifacts.put_bytes(data)
        self.store.register_artifact(
            object_.content_digest,
            object_.size,
            object_.relative_path,
            media_type=media_type,
            registered_at=timestamp,
        )
        return record_base("ArtifactRecord", created_at=timestamp, references=list(references)) | {
            "media_type": media_type,
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": object_.content_digest,
        }

    def _artifact_json(self, record: Mapping[str, Any]) -> dict[str, Any]:
        digest = record.get("content_digest")
        if not isinstance(digest, str):
            raise ContractError("capability_unavailable", "artifact content is unavailable")
        value = loads_json(self.artifacts.read_bytes(digest, maximum_bytes=MAX_PAYLOAD_BYTES))
        if not isinstance(value, dict):
            raise ContractError("conformance_failed", "P10 artifact is not a JSON object")
        return cast(dict[str, Any], value)

    def _limits(self, value: Mapping[str, Any], boundary: Mapping[str, Any]) -> dict[str, int]:
        if set(value) != set(LIMIT_FIELDS):
            raise ContractError("invalid_input", "agent limits are not exact")
        normalized = {key: _positive_int(value[key], key) for key in LIMIT_FIELDS}
        boundary_budgets = boundary.get("budgets")
        if not isinstance(boundary_budgets, Mapping):
            raise ContractError("conformance_failed", "boundary budgets are absent")
        aliases = {
            "maximum_operations": "maximum_operations",
            "maximum_seconds": "maximum_seconds",
            "maximum_information_records": "maximum_information_records",
            "maximum_memory_items": "maximum_memory_items",
            "maximum_resource_units": "maximum_resource_units",
        }
        for key, boundary_key in aliases.items():
            maximum = boundary_budgets.get(boundary_key)
            if not isinstance(maximum, int) or normalized[key] > maximum:
                raise ContractError("policy_refused", f"{key} exceeds governance boundary")
        return normalized

    def _resource_use(self, value: Mapping[str, Any], limits: Mapping[str, Any]) -> None:
        if set(value) != set(LIMIT_FIELDS):
            raise ContractError("invalid_input", "resource-use fields are not exact")
        for key in LIMIT_FIELDS:
            used = _nonnegative_int(value[key], key)
            if used > cast(int, limits[key]):
                raise ContractError("capability_unavailable", f"{key} budget exhausted")

    def _action_set(self, values: Sequence[str], boundary: Mapping[str, Any]) -> list[str]:
        if (
            not isinstance(values, Sequence)
            or isinstance(values, (str, bytes))
            or not values
            or len(values) > MAX_ACTIONS
            or not all(isinstance(value, str) for value in values)
        ):
            raise ContractError("invalid_input", "agent action set is invalid")
        result = list(values)
        if len(set(result)) != len(result) or not set(result).issubset(ACTION_REGISTRY):
            raise ContractError("invalid_input", "agent action set is noncanonical")
        if not set(result).issubset(set(cast(list[str], boundary["permitted_actions"]))):
            raise ContractError("policy_refused", "agent action set exceeds the boundary")
        return result

    def _authority(self, boundary: Mapping[str, Any], authority_record_id: str) -> None:
        ids = {
            value.get("record_id")
            for value in cast(Sequence[Mapping[str, Any]], boundary["authority_refs"])
        }
        if authority_record_id not in ids:
            raise ContractError("policy_refused", "executor cannot originate authority")

    def _authorize(
        self, authorization_status: str, operation: str, request: Mapping[str, Any]
    ) -> None:
        if authorization_status != "permitted":
            self._fail(
                operation,
                request,
                "policy_refused",
                f"agent-host authorization is {authorization_status}",
                authorization_status="refused",
            )

    def _fail(
        self,
        operation: str,
        request: Mapping[str, Any],
        reason: str,
        message: str,
        *,
        authorization_status: str = "permitted",
    ) -> NoReturn:
        timestamp = utc_timestamp()
        effective = "refused" if reason == "policy_refused" else authorization_status
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(request["record_id"], request["record_type"]),
            authorization_status=effective,
            operation=operation,
            inputs=[record_ref(request["record_id"], request["record_type"])],
            parameters={"reason_code": reason},
            outputs=[{"availability": "not_applicable", "reason": reason}],
            operation_status="refused" if reason == "policy_refused" else "failed",
            tool_id="qste-p10-agent-host",
            tool_version="v0.1",
        )
        self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type=(
                "qste:agent-operation-refused/0.1"
                if reason == "policy_refused"
                else "qste:agent-operation-failed/0.1"
            ),
            subject_record_id=cast(str, request["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"operation": operation, "reason_code": reason, "derivative_created": False},
            created_at=timestamp,
        )
        error = ContractError(reason, message)
        error.receipt_id = receipt["record_id"]
        error.authorization_status = effective
        raise error

    def _record(self, record_id: str, record_type: str) -> dict[str, Any]:
        value = self.store.get_record(record_id).record
        if value.get("record_type") != record_type:
            raise ContractError("invalid_input", f"record is not {record_type}")
        return value


def _executor(value: Mapping[str, Any]) -> dict[str, str]:
    normalized = _exact_nonempty(
        value, {"executor_id", "executor_class", "implementation_status"}, "executor"
    )
    if normalized["executor_class"] not in EXECUTOR_CLASSES:
        raise ContractError("invalid_input", "executor class is noncanonical")
    if normalized["implementation_status"] not in {
        "human_fixture",
        "deterministic_fixture",
        "interface_fixture_no_model",
    }:
        raise ContractError("invalid_input", "executor fixture status is invalid")
    if not isinstance(normalized["executor_id"], str) or not normalized["executor_id"]:
        raise ContractError("invalid_input", "executor id is required")
    return cast(dict[str, str], normalized)


def _proposal(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _exact_nonempty(
        value,
        {
            "action_id",
            "changes",
            "next_action_set",
            "evidence_fields",
            "reason_code",
            "resume_conditions",
            "escalation_conditions",
            "resource_use",
            "prompt_text",
            "study_policy_permitted",
        },
        "revision proposal",
    )
    if normalized["action_id"] not in ACTION_REGISTRY:
        raise ContractError("invalid_input", "proposal action is noncanonical")
    for key in ("changes", "next_action_set", "evidence_fields"):
        if not isinstance(normalized[key], list):
            raise ContractError("invalid_input", f"proposal {key} must be a list")
    if not normalized["next_action_set"] or not normalized["evidence_fields"]:
        raise ContractError("invalid_input", "proposal action set and evidence fields are required")
    for key in ("resume_conditions", "escalation_conditions", "resource_use"):
        if not isinstance(normalized[key], Mapping):
            raise ContractError("invalid_input", f"proposal {key} must be an object")
    if not isinstance(normalized["reason_code"], str) or not normalized["reason_code"]:
        raise ContractError("invalid_input", "proposal reason code is required")
    if not isinstance(normalized["prompt_text"], str):
        raise ContractError("invalid_input", "prompt text must be data")
    if not isinstance(normalized["study_policy_permitted"], bool):
        raise ContractError("invalid_input", "study policy result must be boolean")
    return normalized


def _exposure(record: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    slots = [
        {
            "field": key,
            "payload_b64": base64.b64encode(canonical_json_bytes(payload[key])).decode("ascii"),
        }
        for key in sorted(payload)
        if key not in {"profile_id", "record_level"}
    ]
    return {
        "profile_id": TREATMENT_PROFILE,
        "record_level": payload.get("record_level"),
        "source_content_digest": record["content_digest"],
        "slots": slots,
    }


def _exact_nonempty(value: Mapping[str, Any], keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ContractError("invalid_input", f"{label} fields are not exact")
    if not value:
        raise ContractError("invalid_input", f"{label} is empty")
    return dict(value)


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ContractError("invalid_input", f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractError("invalid_input", f"{label} must be a nonnegative integer")
    return value


def _nonnegative_number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ContractError("invalid_input", f"{label} must be a nonnegative number")
    return float(value)


def _payload(
    payload_type: str,
    *,
    items: Sequence[Mapping[str, Any]] = (),
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "payload_type": payload_type,
        "payload_schema_id": "qste-payload/0.3.0",
        "items": [dict(value) for value in items],
        "data": dict(data or {}),
    }
