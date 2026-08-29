"""Event-sourced P8 authorization, appeal, adjudication, and repair service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, NoReturn, cast

from qste.core import canonical_json_bytes
from qste.core.contracts import BASE_URI, ContractError
from qste.core.identity import utc_timestamp
from qste.ingress.records import bind_semantic_key, operation_receipt, record_base, record_ref
from qste.policy.models import PolicyOutcome
from qste.storage import ArtifactStore, RecordStore, WorkspacePaths

GOVERNANCE_PROFILE = "qste-governance-boundary/v0.1"
APPEAL_PROFILE = "qste-appeal-case/v0.1"
REPAIR_PROFILE = "qste-repair-chain/v0.1"
REPAIR_ACTIONS = (
    "pause",
    "correct",
    "revoke",
    "delete",
    "restrict",
    "restore",
    "release_pause",
)
PERMITTED_ACTIONS = frozenset(
    (
        *REPAIR_ACTIONS,
        "transduce",
        "export",
        "appeal",
        "adjudicate",
        "revise_aperture",
        "revise_task",
        "revise_bound",
        "revise_representation",
        "revise_plan",
        "revise_action_set",
        "refuse",
        "escalate",
        "resume",
        "no_change",
    )
)
OUTCOME_REASONS = {
    "upheld": "requested_remedy_upheld",
    "denied": "requested_remedy_denied",
    "partial": "requested_remedy_partial",
    "escalated": "jurisdiction_declined",
    "withdrawn": "appeal_withdrawn",
}
MAX_CLOSURE = 4096


class PolicyService:
    """Apply policy as executable state while preserving every historical record."""

    def __init__(self, workspace: Any) -> None:
        self.paths = WorkspacePaths.open(workspace)
        self.store = RecordStore(self.paths)
        self.artifacts = ArtifactStore(self.paths)

    def declare_boundary(
        self,
        *,
        context_record_id: str,
        specification: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> PolicyOutcome:
        context = self.store.get_record(context_record_id).record
        self._require_permitted(authorization_status, "declare_governance_boundary", context)
        try:
            normalized = self._validate_boundary(specification)
        except ContractError as error:
            if error.reason_code == "policy_refused":
                self._policy_refusal("declare_governance_boundary", context, str(error))
            raise
        timestamp = utc_timestamp()
        authority_refs = [
            record_ref(value, cast(str, self.store.get_record(value).record["record_type"]))
            for value in normalized.pop("authority_ids")
        ]
        boundary = record_base(
            "GovernanceBoundary",
            created_at=timestamp,
            references=[
                record_ref(context_record_id, cast(str, context["record_type"])),
                *authority_refs,
            ],
        ) | {
            "immutable_fields": normalized["immutable_fields"],
            "mutable_successor_fields": normalized["mutable_successor_fields"],
            "authority_refs": authority_refs,
            "permitted_actions": normalized["permitted_actions"],
            "budgets": normalized["budgets"],
            "stop_rules": normalized["stop_rules"],
            "resume_rules": normalized["resume_rules"],
            "qste:governanceProfile": GOVERNANCE_PROFILE,
            "qste:roots": normalized["roots"],
            "qste:humanAuthorizationActions": normalized["human_authorization_actions"],
            "qste:approvingAuthorityIds": normalized["approving_authority_ids"],
            "qste:revokingAuthorityIds": normalized["revoking_authority_ids"],
            "qste:appealConditions": normalized["appeal_conditions"],
            "qste:escalationConditions": normalized["escalation_conditions"],
        }
        bind_semantic_key(
            boundary,
            "qste-semantic-key/governance-boundary-v1",
            {
                "context_record_digest": self.store.get_record(context_record_id).record_digest,
                "immutable_fields": boundary["immutable_fields"],
                "mutable_successor_fields": boundary["mutable_successor_fields"],
                "authority_ids": [value["record_id"] for value in authority_refs],
                "permitted_actions": boundary["permitted_actions"],
                "budgets": boundary["budgets"],
                "stop_rules": boundary["stop_rules"],
                "resume_rules": boundary["resume_rules"],
                "roots": boundary["qste:roots"],
                "human_authorization_actions": boundary["qste:humanAuthorizationActions"],
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(context_record_id, cast(str, context["record_type"])),
            authorization_status="permitted",
            operation="declare_governance_boundary",
            inputs=[record_ref(context_record_id, cast(str, context["record_type"]))],
            parameters={"profile": GOVERNANCE_PROFILE},
            outputs=[record_ref(boundary["record_id"], "GovernanceBoundary")],
            tool_id="qste-p8-policy",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [boundary, receipt],
            domain_event_record_id=None,
            event_type="qste:governance-boundary-declared/0.1",
            subject_record_id=boundary["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"profile": GOVERNANCE_PROFILE},
            created_at=timestamp,
        )
        return PolicyOutcome(
            boundary,
            f"{BASE_URI}/records/governance-boundary.schema.json",
            receipt,
            event.event_sequence,
        )

    def open_appeal(
        self,
        *,
        governance_boundary_record_id: str,
        appellant_record_id: str,
        responding_authority_record_id: str,
        target_record_id: str,
        specification: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> PolicyOutcome:
        boundary = self._record(governance_boundary_record_id, "GovernanceBoundary")
        appellant = self.store.get_record(appellant_record_id).record
        authority = self.store.get_record(responding_authority_record_id).record
        target = self.store.get_record(target_record_id).record
        self._require_permitted(authorization_status, "open_appeal", target)
        self._require_action(boundary, "appeal", "open_appeal", target)
        self._require_authority(
            boundary,
            responding_authority_record_id,
            "open_appeal",
            target,
        )
        standing = specification.get("standing_basis")
        if not isinstance(standing, str) or not standing.strip():
            self._governance_failure("standing_unverified", "standing basis is required", target)
        if specification.get("standing_verified") is not True:
            self._governance_failure("standing_denied", "standing was not verified", target)
        standing_evidence_id = _required_string(specification, "standing_evidence_record_id")
        standing_evidence = self.store.get_record(standing_evidence_id).record
        if specification.get("duty_to_respond") is not True:
            self._governance_failure(
                "authority_unresolved", "named authority has no duty to respond", target
            )
        requested_action = _required_string(specification, "requested_action")
        if requested_action not in REPAIR_ACTIONS:
            raise ContractError("invalid_input", "requested repair action is not canonical")
        deadlines = specification.get("deadlines")
        if not isinstance(deadlines, Mapping) or not deadlines:
            raise ContractError("invalid_input", "appeal deadlines are required")
        jurisdiction = _required_string(specification, "jurisdiction")
        pause_requested = specification.get("pause_requested")
        risk_met = specification.get("pause_risk_threshold_met")
        if not isinstance(pause_requested, bool) or not isinstance(risk_met, bool):
            raise ContractError("invalid_input", "appeal pause decision booleans are required")
        pause_status = "active" if pause_requested and risk_met else "denied"
        pause_reason = (
            "pause_risk_threshold_met"
            if pause_status == "active"
            else "pause_risk_threshold_not_met"
        )
        closure = self.resolve_target_closure(target_record_id)
        timestamp = utc_timestamp()
        case = record_base(
            "AppealCase",
            created_at=timestamp,
            references=[],
        )
        decision = record_base("DecisionEvent", created_at=timestamp, references=[])
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(target_record_id, cast(str, target["record_type"])),
            authorization_status="permitted",
            operation="open_appeal",
            inputs=[
                record_ref(appellant_record_id, cast(str, appellant["record_type"])),
                record_ref(responding_authority_record_id, cast(str, authority["record_type"])),
                record_ref(target_record_id, cast(str, target["record_type"])),
                record_ref(standing_evidence_id, cast(str, standing_evidence["record_type"])),
                record_ref(governance_boundary_record_id, "GovernanceBoundary"),
            ],
            parameters={
                "requested_action": requested_action,
                "pause_requested": pause_requested,
                "pause_risk_threshold_met": risk_met,
            },
            outputs=[record_ref(case["record_id"], "AppealCase")],
            tool_id="qste-p8-policy",
            tool_version="v0.1",
        )
        case.update(
            {
                "references": [
                    record_ref(appellant_record_id, cast(str, appellant["record_type"])),
                    record_ref(responding_authority_record_id, cast(str, authority["record_type"])),
                    record_ref(target_record_id, cast(str, target["record_type"])),
                    record_ref(standing_evidence_id, cast(str, standing_evidence["record_type"])),
                    record_ref(governance_boundary_record_id, "GovernanceBoundary"),
                    record_ref(decision["record_id"], "DecisionEvent"),
                    record_ref(receipt["record_id"], "OperationReceipt"),
                ],
                "appellant_ref": record_ref(
                    appellant_record_id, cast(str, appellant["record_type"])
                ),
                "standing_basis": standing,
                "responding_authority_ref": record_ref(
                    responding_authority_record_id, cast(str, authority["record_type"])
                ),
                "target_closure": closure,
                "reason_code": pause_reason,
                "requested_action": requested_action,
                "deadlines": dict(deadlines),
                "jurisdiction": jurisdiction,
                "appeal_status": "under_review",
                "pause_status": pause_status,
                "adjudication_outcome": "not_decided",
                "repair_status": "not_requested",
                "adjudication_evidence_refs": [
                    record_ref(standing_evidence_id, cast(str, standing_evidence["record_type"]))
                ],
                "decision_event_refs": [record_ref(decision["record_id"], "DecisionEvent")],
                "successor_case_ref": None,
                "qste:appealProfile": APPEAL_PROFILE,
                "qste:governanceBoundaryRef": record_ref(
                    governance_boundary_record_id, "GovernanceBoundary"
                ),
                "qste:standingValidation": "verified",
                "qste:dutyToRespond": True,
                "qste:eventTransitions": [
                    "appeal:opened->under_review",
                    f"pause:not_requested->requested->{pause_status}",
                ],
            }
        )
        bind_semantic_key(
            case,
            "qste-semantic-key/appeal-case-v1",
            {
                "target_record_id": target_record_id,
                "appellant_record_id": appellant_record_id,
                "authority_record_id": responding_authority_record_id,
                "standing_basis": standing,
                "requested_action": requested_action,
                "jurisdiction": jurisdiction,
                "predecessor_case_semantic_key": None,
                "statuses": _case_axes(case),
            },
        )
        decision.update(
            _decision_fields(
                case=case,
                target=target,
                authority=authority,
                boundary=boundary,
                receipt=receipt,
                action="pause" if pause_status == "active" else "no_change",
                reason=pause_reason,
                evidence_refs=[standing_evidence],
                consequence={
                    "target_closure_paused": pause_status == "active",
                    "next_eligible_actions": ["adjudicate", "appeal"],
                },
                event_sequence=1,
            )
        )
        bind_semantic_key(
            decision,
            "qste-semantic-key/governance-decision-v1",
            {
                "case_semantic_key": case["semantic_key"],
                "action": decision["decision_action"],
                "reason": pause_reason,
                "consequence": decision["executable_consequence"],
            },
        )
        _, event = self.store.insert_records_with_event(
            [case, decision, receipt],
            domain_event_record_id=None,
            event_type="qste:appeal-opened/0.1",
            subject_record_id=case["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={
                "appeal_status": case["appeal_status"],
                "pause_status": pause_status,
                "reason_code": pause_reason,
            },
            created_at=timestamp,
        )
        if pause_status == "active":
            self._propagate_event(
                closure,
                "qste:use-paused/0.1",
                receipt["record_id"],
                {"appeal_case_record_id": case["record_id"], "reason_code": pause_reason},
            )
        return PolicyOutcome(
            case,
            f"{BASE_URI}/records/appeal-case.schema.json",
            receipt,
            event.event_sequence,
        )

    def adjudicate(
        self,
        *,
        appeal_case_record_id: str,
        authority_record_id: str,
        outcome: str,
        evidence_record_ids: Sequence[str],
        authorization_status: str = "permitted",
    ) -> PolicyOutcome:
        prior = self._record(appeal_case_record_id, "AppealCase")
        boundary = self._record(
            cast(str, prior["qste:governanceBoundaryRef"]["record_id"]), "GovernanceBoundary"
        )
        authority = self.store.get_record(authority_record_id).record
        self._require_permitted(authorization_status, "adjudicate", prior)
        self._require_action(boundary, "adjudicate", "adjudicate", prior)
        self._require_authority(boundary, authority_record_id, "adjudicate", prior)
        if prior["appeal_status"] not in {"opened", "under_review"}:
            raise ContractError("invalid_input", "appeal is not eligible for adjudication")
        if prior["adjudication_outcome"] != "not_decided":
            raise ContractError("invalid_input", "adjudication outcome is already frozen")
        if outcome not in OUTCOME_REASONS:
            raise ContractError("invalid_input", "adjudication outcome is not canonical")
        if not evidence_record_ids:
            raise ContractError("invalid_input", "adjudication evidence is required")
        evidence = [self.store.get_record(value).record for value in evidence_record_ids]
        reason = OUTCOME_REASONS[outcome]
        timestamp = utc_timestamp()
        successor = record_base("AppealCase", created_at=timestamp, references=[])
        decision = record_base("DecisionEvent", created_at=timestamp, references=[])
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(appeal_case_record_id, "AppealCase"),
            authorization_status="permitted",
            operation="adjudicate",
            inputs=[
                record_ref(appeal_case_record_id, "AppealCase"),
                record_ref(authority_record_id, cast(str, authority["record_type"])),
                *[record_ref(value["record_id"], value["record_type"]) for value in evidence],
            ],
            parameters={"adjudication_outcome": outcome},
            outputs=[record_ref(successor["record_id"], "AppealCase")],
            tool_id="qste-p8-policy",
            tool_version="v0.1",
        )
        successor.update(
            _successor_case_fields(
                prior,
                successor,
                decision,
                receipt,
                appeal_status="adjudicated",
                pause_status=cast(str, prior["pause_status"]),
                adjudication_outcome=outcome,
                repair_status="not_requested",
                reason_code=reason,
                evidence=evidence,
                transition=f"adjudication:not_decided->{outcome}",
            )
        )
        bind_semantic_key(
            successor,
            "qste-semantic-key/appeal-case-v1",
            {
                "predecessor_case_semantic_key": prior["semantic_key"],
                "target_record_id": prior["target_closure"]["root_record_id"],
                "statuses": _case_axes(successor),
                "reason_code": reason,
            },
        )
        target = self.store.get_record(cast(str, prior["target_closure"]["root_record_id"])).record
        decision.update(
            _decision_fields(
                case=successor,
                target=target,
                authority=authority,
                boundary=boundary,
                receipt=receipt,
                action="no_change" if outcome in {"denied", "withdrawn"} else "revise",
                reason=reason,
                evidence_refs=evidence,
                consequence={
                    "repair_eligible": outcome in {"upheld", "partial"},
                    "repair_action": prior["requested_action"],
                },
                event_sequence=len(cast(list[Any], prior["decision_event_refs"])) + 1,
            )
        )
        bind_semantic_key(
            decision,
            "qste-semantic-key/governance-decision-v1",
            {
                "case_semantic_key": successor["semantic_key"],
                "outcome": outcome,
                "reason": reason,
                "evidence_record_ids": list(evidence_record_ids),
            },
        )
        _, event = self.store.insert_records_with_event(
            [successor, decision, receipt],
            domain_event_record_id=None,
            event_type="qste:appeal-adjudicated/0.1",
            subject_record_id=successor["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"adjudication_outcome": outcome, "reason_code": reason},
            created_at=timestamp,
        )
        return PolicyOutcome(
            successor,
            f"{BASE_URI}/records/appeal-case.schema.json",
            receipt,
            event.event_sequence,
        )

    def apply_repair(
        self,
        *,
        appeal_case_record_id: str,
        authority_record_id: str,
        repair_action: str,
        specification: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> PolicyOutcome:
        case = self._record(appeal_case_record_id, "AppealCase")
        boundary = self._record(
            cast(str, case["qste:governanceBoundaryRef"]["record_id"]), "GovernanceBoundary"
        )
        authority = self.store.get_record(authority_record_id).record
        self._require_permitted(authorization_status, "apply_repair", case)
        self._require_authority(boundary, authority_record_id, "apply_repair", case)
        if repair_action not in REPAIR_ACTIONS:
            raise ContractError("invalid_input", "repair action is not canonical")
        self._require_action(boundary, repair_action, "apply_repair", case)
        if case["appeal_status"] != "adjudicated" or case["adjudication_outcome"] not in {
            "upheld",
            "partial",
        }:
            self._policy_refusal(
                "apply_repair",
                case,
                "repair requires authorized favorable adjudication",
            )
        if repair_action != case["requested_action"]:
            self._policy_refusal(
                "apply_repair", case, "repair action differs from adjudicated request"
            )
        feasible = specification.get("feasible_change_or_stop")
        if not isinstance(feasible, bool):
            raise ContractError("invalid_input", "repair feasibility decision is required")
        retention = specification.get("retention")
        if not isinstance(retention, Mapping) or retention.get("mode") not in {
            "retain",
            "tombstone",
            "delete",
        }:
            raise ContractError("invalid_input", "repair retention semantics are invalid")
        external_copies = specification.get("external_copies")
        if not isinstance(external_copies, list):
            raise ContractError("invalid_input", "external copy report is required")
        propagation_failures = specification.get("propagation_failures", [])
        if not isinstance(propagation_failures, list):
            raise ContractError("invalid_input", "propagation failures must be an array")
        closure = self.resolve_target_closure(
            cast(str, case["target_closure"]["root_record_id"]),
            maximum_depth=int(specification.get("maximum_depth", 64)),
        )
        unresolved: list[str] = [
            str(value.get("locator", value)) if isinstance(value, Mapping) else str(value)
            for value in external_copies
        ] + [
            str(value.get("record_id", value)) if isinstance(value, Mapping) else str(value)
            for value in propagation_failures
        ]
        if repair_action == "delete" and retention["mode"] != "delete":
            unresolved.append("retention_duty_blocks_deletion")
        if repair_action == "delete":
            unresolved.append("immutable_qste_record_history")
        if not feasible:
            unresolved.append("repair_not_feasible")
            repair_status = "impossible"
            reason = "repair_not_feasible"
        elif unresolved:
            repair_status = "partially_applied"
            reason = "repair_partially_completed"
        else:
            repair_status = "applied"
            reason = "repair_completed"
        operation_status = "completed" if repair_status == "applied" else "partial"
        timestamp = utc_timestamp()
        successor_case = record_base("AppealCase", created_at=timestamp, references=[])
        operation = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(appeal_case_record_id, "AppealCase"),
            authorization_status="permitted",
            operation="apply_repair",
            inputs=[
                record_ref(appeal_case_record_id, "AppealCase"),
                record_ref(authority_record_id, cast(str, authority["record_type"])),
            ],
            parameters={
                "repair_action": repair_action,
                "retention": dict(retention),
                "feasible_change_or_stop": feasible,
            },
            outputs=[{"pending": "repair_action_and_receipt"}],
            operation_status=operation_status,
            tool_id="qste-p8-policy",
            tool_version="v0.1",
        )
        decision_ref = cast(list[Mapping[str, Any]], case["decision_event_refs"])[-1]
        successor_spec: dict[str, Any] | None = None
        if feasible and repair_action != "delete":
            target_id = cast(str, closure["root_record_id"])
            target = self.store.get_record(target_id).record
            before_state = _current_policy_state(target_id, self.store)
            after_state = _policy_state_after(repair_action, before_state)
            after_action_set = cast(list[str], after_state["action_set"])
            successor_spec = record_base(
                "SuccessorSpec",
                created_at=timestamp,
                references=[
                    record_ref(target_id, cast(str, target["record_type"]), "succeeds"),
                    dict(decision_ref),
                    record_ref(authority_record_id, cast(str, authority["record_type"])),
                ],
            ) | {
                "predecessor_ref": record_ref(target_id, cast(str, target["record_type"])),
                "completed_run_ref": record_ref(target_id, cast(str, target["record_type"])),
                "semantic_diff": {
                    "changed_fields": [
                        {
                            "field": _action_field(repair_action),
                            "before": before_state,
                            "after": after_state,
                        }
                    ],
                    "comparator": "qste-semantic-or-behavioral-difference/v0.1",
                    "semantic_or_behavioral_difference": before_state != after_state,
                },
                "executable_action_set": after_action_set or ["no_eligible_action"],
                "capability_requirements": ["qste-foundation/0.1"],
                "decision_event_ref": dict(decision_ref),
                "evidence_fields": [
                    "adjudication_outcome",
                    "requested_action",
                    "target_closure",
                ],
                "revision_treatment": "authentic",
                "authority_ref": record_ref(
                    authority_record_id, cast(str, authority["record_type"])
                ),
                "persistence_target": "qste_append_only_event_store",
                "qste:repairProfile": REPAIR_PROFILE,
                "qste:governanceBoundaryRef": record_ref(
                    boundary["record_id"], "GovernanceBoundary"
                ),
            }
            bind_semantic_key(
                successor_spec,
                "qste-semantic-key/successor-spec-v1",
                {
                    "predecessor_record_digest": self.store.get_record(target_id).record_digest,
                    "semantic_diff": successor_spec["semantic_diff"],
                    "executable_action_set": successor_spec["executable_action_set"],
                    "decision_event_record_id": decision_ref["record_id"],
                    "authority_record_id": authority_record_id,
                },
            )
            if successor_spec["semantic_diff"]["semantic_or_behavioral_difference"] is not True:
                raise ContractError("conformance_failed", "repair successor is hash-only/no-change")
        action = record_base("RepairAction", created_at=timestamp, references=[])
        receipt_record = record_base("RepairReceipt", created_at=timestamp, references=[])
        action.update(
            {
                "references": [
                    record_ref(appeal_case_record_id, "AppealCase"),
                    record_ref(authority_record_id, cast(str, authority["record_type"])),
                    record_ref(operation["record_id"], "OperationReceipt"),
                    *(
                        [record_ref(successor_spec["record_id"], "SuccessorSpec")]
                        if successor_spec
                        else []
                    ),
                ],
                "appeal_case_ref": record_ref(appeal_case_record_id, "AppealCase"),
                "adjudication_outcome": case["adjudication_outcome"],
                "authority_ref": record_ref(
                    authority_record_id, cast(str, authority["record_type"])
                ),
                "repair_action": repair_action,
                "target_closure": closure,
                "operation_scope": {
                    "inside_qste_authority": True,
                    "external_copy_count": len(external_copies),
                },
                "predecessor_state": {
                    "case_record_id": appeal_case_record_id,
                    "axes": _case_axes(case),
                },
                "successor_state": {
                    "repair_status": repair_status,
                    "successor_spec_record_id": (
                        successor_spec["record_id"] if successor_spec else None
                    ),
                },
                "authorization_status": "permitted",
                "execution_status": operation_status,
                "reason_code": reason,
                "failures": (
                    [{"availability": "not_applicable"}]
                    if not unresolved
                    else [{"unresolved_target": value} for value in unresolved]
                ),
                "receipt_ref": record_ref(operation["record_id"], "OperationReceipt"),
                "propagation_requirement": {
                    "required": True,
                    "closure_member_count": len(cast(list[Any], closure["member_record_ids"])),
                },
                "retention_semantics": dict(retention),
                "qste:repairProfile": REPAIR_PROFILE,
            }
        )
        bind_semantic_key(
            action,
            "qste-semantic-key/repair-action-v1",
            {
                "case_semantic_key": case["semantic_key"],
                "repair_action": repair_action,
                "target_closure": closure,
                "successor_semantic_key": successor_spec.get("semantic_key")
                if successor_spec
                else None,
                "repair_status": repair_status,
            },
        )
        pause_status = _pause_after(repair_action, cast(str, case["pause_status"]), feasible)
        successor_case.update(
            _successor_case_fields(
                case,
                successor_case,
                None,
                operation,
                appeal_status="closed",
                pause_status=pause_status,
                adjudication_outcome=cast(str, case["adjudication_outcome"]),
                repair_status=repair_status,
                reason_code=reason,
                evidence=[action],
                transition=f"repair:not_requested->pending->{repair_status}",
                decision_ref=decision_ref,
            )
        )
        successor_case["references"].extend(
            [
                record_ref(action["record_id"], "RepairAction"),
                record_ref(receipt_record["record_id"], "RepairReceipt"),
            ]
        )
        bind_semantic_key(
            successor_case,
            "qste-semantic-key/appeal-case-v1",
            {
                "predecessor_case_semantic_key": case["semantic_key"],
                "target_record_id": closure["root_record_id"],
                "statuses": _case_axes(successor_case),
                "reason_code": reason,
            },
        )
        successor_refs = (
            [record_ref(successor_spec["record_id"], "SuccessorSpec")]
            if successor_spec
            else [record_ref(successor_case["record_id"], "AppealCase")]
        )
        external_payload = external_copies or [{"availability": "not_applicable"}]
        unresolved_payload = (
            [{"target": value, "reason": _limit_reason(value)} for value in unresolved]
            if unresolved
            else [{"availability": "not_applicable"}]
        )
        receipt_record.update(
            {
                "references": [
                    record_ref(appeal_case_record_id, "AppealCase"),
                    record_ref(action["record_id"], "RepairAction"),
                    record_ref(authority_record_id, cast(str, authority["record_type"])),
                    *successor_refs,
                ],
                "appeal_case_ref": record_ref(appeal_case_record_id, "AppealCase"),
                "action_refs": [record_ref(action["record_id"], "RepairAction")],
                "affected_closure": closure,
                "actions_applied": [
                    {
                        "repair_action": repair_action,
                        "inside_qste_authority": feasible,
                    }
                ],
                "propagation_failures": propagation_failures
                or [{"availability": "not_applicable"}],
                "external_copies": external_payload,
                "unresolved_limits": unresolved_payload,
                "repair_status": repair_status,
                "pause_status": pause_status,
                "successor_refs": successor_refs,
                "final_authority_ref": record_ref(
                    authority_record_id, cast(str, authority["record_type"])
                ),
                "completed_at": timestamp,
                "event_sequence": len(self.store.iter_events()) + 1,
                "qste:repairProfile": REPAIR_PROFILE,
                "qste:operationReceiptRef": record_ref(operation["record_id"], "OperationReceipt"),
            }
        )
        bind_semantic_key(
            receipt_record,
            "qste-semantic-key/repair-receipt-v1",
            {
                "case_semantic_key": case["semantic_key"],
                "action_semantic_key": action["semantic_key"],
                "repair_status": repair_status,
                "pause_status": pause_status,
                "external_copies": external_payload,
                "unresolved_limits": unresolved_payload,
            },
        )
        operation["outputs"] = [
            record_ref(action["record_id"], "RepairAction"),
            record_ref(receipt_record["record_id"], "RepairReceipt"),
            record_ref(successor_case["record_id"], "AppealCase"),
            *successor_refs,
        ]
        bind_semantic_key(
            operation,
            "qste-semantic-key/operation-receipt-p4-v1",
            {
                "operation": "apply_repair",
                "request_ref": operation["request_ref"],
                "authorization_status": "permitted",
                "inputs": operation["inputs"],
                "parameters": operation["parameters"],
                "outputs": operation["outputs"],
                "operation_status": operation_status,
            },
        )
        records = [
            *([successor_spec] if successor_spec else []),
            action,
            receipt_record,
            successor_case,
            operation,
        ]
        _, event = self.store.insert_records_with_event(
            records,
            domain_event_record_id=None,
            event_type="qste:repair-issued/0.1",
            subject_record_id=receipt_record["record_id"],
            receipt_record_id=operation["record_id"],
            payload={
                "repair_action": repair_action,
                "repair_status": repair_status,
                "reason_code": reason,
                "unresolved_targets": unresolved,
            },
            created_at=timestamp,
        )
        if feasible:
            event_type = _propagation_event_type(repair_action)
            self._propagate_event(
                closure,
                event_type,
                operation["record_id"],
                {
                    "repair_action_record_id": action["record_id"],
                    "successor_spec_record_id": successor_spec.get("record_id")
                    if successor_spec
                    else None,
                },
            )
        return PolicyOutcome(
            receipt_record,
            f"{BASE_URI}/records/repair-receipt.schema.json",
            operation,
            event.event_sequence,
            operation_status=operation_status,
            reason_code=reason,
            repair_status=repair_status,
            unresolved_targets=tuple(
                unresolved or (["repair_not_feasible"] if not feasible else [])
            ),
        )

    def export_projection(
        self,
        *,
        target_record_id: str,
        governance_boundary_record_id: str,
        disclosure_status: str,
        human_authorized: bool,
        authorization_status: str = "permitted",
    ) -> PolicyOutcome:
        target = self.store.get_record(target_record_id).record
        boundary = self._record(governance_boundary_record_id, "GovernanceBoundary")
        self._require_permitted(authorization_status, "export", target)
        self._require_action(boundary, "export", "export", target)
        if self.current_authorization(target_record_id) in {"revoked", "refused"}:
            self._policy_refusal("export", target, "withdrawal blocks dependent export")
        if disclosure_status not in {"private", "restricted", "project_internal", "public"}:
            raise ContractError("invalid_input", "export disclosure status is invalid")
        if disclosure_status == "public" and not human_authorized:
            self._policy_refusal("export", target, "public projection requires human authorization")
        payload = {
            "profile": "qste-allowlisted-export-projection/v0.1",
            "source_record_id": target_record_id,
            "source_record_type": target["record_type"],
            "source_semantic_key": target.get("semantic_key"),
            "disclosure_status": disclosure_status,
            "omitted_fields": sorted(
                key
                for key in target
                if key
                not in {
                    "record_type",
                    "contract_id",
                    "semantic_key",
                    "integrity_status",
                }
            ),
            "external_write": False,
        }
        data = canonical_json_bytes(payload)
        if len(data) > 262_144:
            raise ContractError("invalid_input", "export projection exceeds P8 safety bound")
        staged = self.artifacts.put_bytes(data)
        timestamp = utc_timestamp()
        projection = record_base(
            "ArtifactRecord",
            created_at=timestamp,
            disclosure_status=disclosure_status,
            references=[
                record_ref(target_record_id, cast(str, target["record_type"]), "derived_from"),
                record_ref(governance_boundary_record_id, "GovernanceBoundary"),
            ],
        ) | {
            "media_type": "application/vnd.qste.export-projection+json",
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": staged.content_digest,
            "qste:exportProjectionProfile": "qste-allowlisted-export-projection/v0.1",
            "qste:externalWrite": False,
            "qste:omissionManifest": payload["omitted_fields"],
        }
        bind_semantic_key(
            projection,
            "qste-semantic-key/export-projection-v1",
            {
                "target_record_digest": self.store.get_record(target_record_id).record_digest,
                "boundary_semantic_key": boundary["semantic_key"],
                "disclosure_status": disclosure_status,
                "payload_digest": staged.content_digest,
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(target_record_id, cast(str, target["record_type"])),
            authorization_status="permitted",
            operation="export",
            inputs=[
                record_ref(target_record_id, cast(str, target["record_type"])),
                record_ref(governance_boundary_record_id, "GovernanceBoundary"),
            ],
            parameters={
                "disclosure_status": disclosure_status,
                "human_authorized": human_authorized,
                "external_write": False,
            },
            outputs=[record_ref(projection["record_id"], "ArtifactRecord")],
            tool_id="qste-p8-policy",
            tool_version="v0.1",
        )
        self.store.register_artifact(
            staged.content_digest,
            staged.size,
            staged.relative_path,
            media_type=projection["media_type"],
        )
        _, event = self.store.insert_records_with_event(
            [projection, receipt],
            domain_event_record_id=None,
            event_type="qste:export-projection-created/0.1",
            subject_record_id=projection["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"disclosure_status": disclosure_status, "external_write": False},
            created_at=timestamp,
        )
        return PolicyOutcome(
            projection,
            f"{BASE_URI}/records/artifact-record.schema.json",
            receipt,
            event.event_sequence,
        )

    def resolve_target_closure(
        self, target_record_id: str, *, maximum_depth: int = 64
    ) -> dict[str, Any]:
        self.store.get_record(target_record_id)
        if maximum_depth < 1 or maximum_depth > 128:
            raise ContractError("invalid_input", "repair closure depth must be between 1 and 128")
        edges = self.store.trace_lineage(
            target_record_id, direction="descendants", maximum_depth=maximum_depth
        )
        members = {target_record_id}
        for edge in edges:
            members.add(edge.source_record_id)
            members.add(edge.target_record_id)
        if len(members) > MAX_CLOSURE:
            raise ContractError("capability_unavailable", "repair target closure exceeds P8 bound")
        records = [self.store.get_record(value).record for value in sorted(members)]
        categories: dict[str, list[str]] = {
            "descendants": [],
            "claims": [],
            "renders": [],
            "bundles": [],
            "projections": [],
        }
        for record in records:
            record_id = cast(str, record["record_id"])
            if record_id != target_record_id:
                categories["descendants"].append(record_id)
            if record["record_type"] == "ClaimRecord":
                categories["claims"].append(record_id)
            if record.get("qste:safetyProfile") or record.get("qste:analyticalOutput"):
                categories["renders"].append(record_id)
            if record["record_type"] == "Bundle":
                categories["bundles"].append(record_id)
            if (
                record.get("qste:exportProjectionProfile")
                or record["record_type"] == "ProjectionSpec"
            ):
                categories["projections"].append(record_id)
        return {
            "payload_type": "TargetClosure",
            "root_record_id": target_record_id,
            "member_record_ids": sorted(members),
            "edge_sequences": [value.edge_sequence for value in edges],
            "maximum_depth": maximum_depth,
            "complete_within_bound": True,
            "categories": categories,
        }

    def current_authorization(self, target_record_id: str) -> str:
        self.store.get_record(target_record_id)
        status = "permitted"
        for event in self.store.iter_events():
            if event.subject_record_id != target_record_id:
                continue
            if event.event_type == "qste:authorization-revoked/0.1":
                status = "revoked"
            elif event.event_type == "qste:authorization-restored/0.1":
                status = "permitted"
            elif event.event_type == "qste:use-paused/0.1":
                status = "refused"
            elif event.event_type == "qste:pause-released/0.1":
                status = "permitted"
        return status

    def _validate_boundary(self, value: Mapping[str, Any]) -> dict[str, Any]:
        required = {
            "immutable_fields",
            "mutable_successor_fields",
            "authority_ids",
            "approving_authority_ids",
            "revoking_authority_ids",
            "permitted_actions",
            "budgets",
            "roots",
            "stop_rules",
            "resume_rules",
            "appeal_conditions",
            "escalation_conditions",
            "human_authorization_actions",
        }
        if set(value) != required:
            raise ContractError("invalid_input", "governance boundary fields are not exact")
        immutable = _string_list(value["immutable_fields"], "immutable fields")
        mutable = _string_list(value["mutable_successor_fields"], "mutable successor fields")
        if set(immutable) & set(mutable):
            raise ContractError("invalid_input", "immutable and successor fields overlap")
        authorities = _string_list(value["authority_ids"], "authority IDs")
        approving = _string_list(value["approving_authority_ids"], "approving authorities")
        revoking = _string_list(value["revoking_authority_ids"], "revoking authorities")
        if not set(approving).issubset(authorities) or not set(revoking).issubset(authorities):
            raise ContractError("invalid_input", "authority roles exceed named authorities")
        for authority_id in authorities:
            self.store.get_record(authority_id)
        actions = _string_list(value["permitted_actions"], "permitted actions")
        if any(action not in PERMITTED_ACTIONS for action in actions):
            raise ContractError("invalid_input", "governance action is not supported in P8")
        human = _string_list(value["human_authorization_actions"], "human authorization actions")
        if any(action not in actions for action in human):
            raise ContractError("invalid_input", "human-authorized action is not permitted")
        budgets = _object(value["budgets"], "budgets")
        if (
            not isinstance(budgets.get("maximum_operations"), int)
            or not 1 <= cast(int, budgets["maximum_operations"]) <= 100_000
        ):
            raise ContractError("invalid_input", "governance operation budget is invalid")
        roots = _object(value["roots"], "roots")
        for name in ("filesystem", "network", "model", "output", "disclosure"):
            if name not in roots:
                raise ContractError("invalid_input", f"governance root is missing: {name}")
        if roots["network"] != "disabled" or roots["model"] != "disabled":
            raise ContractError("policy_refused", "P8 network and model roots must be disabled")
        return {
            "immutable_fields": immutable,
            "mutable_successor_fields": mutable,
            "authority_ids": authorities,
            "approving_authority_ids": approving,
            "revoking_authority_ids": revoking,
            "permitted_actions": actions,
            "budgets": dict(budgets),
            "roots": dict(roots),
            "stop_rules": dict(_object(value["stop_rules"], "stop rules")),
            "resume_rules": dict(_object(value["resume_rules"], "resume rules")),
            "appeal_conditions": dict(_object(value["appeal_conditions"], "appeal conditions")),
            "escalation_conditions": dict(
                _object(value["escalation_conditions"], "escalation conditions")
            ),
            "human_authorization_actions": human,
        }

    def _require_permitted(
        self, authorization_status: str, operation: str, request: Mapping[str, Any]
    ) -> None:
        if authorization_status == "permitted":
            return
        if authorization_status not in {"unknown", "refused", "deferred", "revoked"}:
            raise ContractError("invalid_input", "authorization status is invalid")
        self._policy_refusal(operation, request, f"authorization is {authorization_status}")

    def _policy_refusal(self, operation: str, request: Mapping[str, Any], message: str) -> NoReturn:
        timestamp = utc_timestamp()
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(
                cast(str, request["record_id"]), cast(str, request["record_type"])
            ),
            authorization_status="refused",
            operation=operation,
            inputs=[record_ref(cast(str, request["record_id"]), cast(str, request["record_type"]))],
            parameters={"reason_code": "policy_refused"},
            outputs=[{"availability": "not_applicable", "reason": "policy_refused"}],
            operation_status="refused",
            tool_id="qste-p8-policy",
            tool_version="v0.1",
        )
        self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:operation-refused/0.1",
            subject_record_id=cast(str, request["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"operation": operation, "executable_consequence": "no_state_change"},
            created_at=timestamp,
        )
        error = ContractError("policy_refused", message)
        error.authorization_status = "refused"  # type: ignore[attr-defined]
        error.receipt_id = receipt["record_id"]  # type: ignore[attr-defined]
        raise error

    def _governance_failure(
        self,
        reason: str,
        message: str,
        request: Mapping[str, Any],
        *,
        operation: str = "open_appeal",
    ) -> NoReturn:
        timestamp = utc_timestamp()
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(
                cast(str, request["record_id"]), cast(str, request["record_type"])
            ),
            authorization_status="permitted",
            operation=operation,
            inputs=[record_ref(cast(str, request["record_id"]), cast(str, request["record_type"]))],
            parameters={"reason_code": reason},
            outputs=[{"availability": "not_applicable", "reason": reason}],
            operation_status="failed",
            tool_id="qste-p8-policy",
            tool_version="v0.1",
        )
        self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type=(
                "qste:appeal-intake-failed/0.1"
                if operation == "open_appeal"
                else "qste:governance-operation-failed/0.1"
            ),
            subject_record_id=cast(str, request["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"operation": operation, "reason_code": reason},
            created_at=timestamp,
        )
        error = ContractError(reason, message)
        error.receipt_id = receipt["record_id"]  # type: ignore[attr-defined]
        raise error

    def _require_authority(
        self,
        boundary: Mapping[str, Any],
        authority_id: str,
        operation: str,
        request: Mapping[str, Any],
    ) -> None:
        ids = {value["record_id"] for value in boundary["authority_refs"]}
        if authority_id not in ids:
            self._governance_failure(
                "authority_unresolved",
                "authority is outside governance boundary",
                request,
                operation=operation,
            )

    def _require_action(
        self,
        boundary: Mapping[str, Any],
        action: str,
        operation: str,
        request: Mapping[str, Any],
    ) -> None:
        if action not in boundary["permitted_actions"]:
            self._policy_refusal(operation, request, "action is outside governance boundary")

    def _record(self, record_id: str, expected_type: str) -> dict[str, Any]:
        record = self.store.get_record(record_id).record
        if record["record_type"] != expected_type:
            raise ContractError("invalid_input", f"record is not {expected_type}: {record_id}")
        return record

    def _propagate_event(
        self,
        closure: Mapping[str, Any],
        event_type: str,
        receipt_record_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        for record_id in cast(Sequence[str], closure["member_record_ids"]):
            self.store.append_event(
                event_type,
                record_id,
                {**dict(payload), "root_record_id": closure["root_record_id"]},
                receipt_record_id=receipt_record_id,
            )


def _decision_fields(
    *,
    case: Mapping[str, Any],
    target: Mapping[str, Any],
    authority: Mapping[str, Any],
    boundary: Mapping[str, Any],
    receipt: Mapping[str, Any],
    action: str,
    reason: str,
    evidence_refs: Sequence[Mapping[str, Any]],
    consequence: Mapping[str, Any],
    event_sequence: int,
) -> dict[str, Any]:
    return {
        "references": [
            record_ref(cast(str, case["record_id"]), "AppealCase"),
            record_ref(cast(str, target["record_id"]), cast(str, target["record_type"])),
            record_ref(cast(str, authority["record_id"]), cast(str, authority["record_type"])),
            record_ref(cast(str, boundary["record_id"]), "GovernanceBoundary"),
            record_ref(cast(str, receipt["record_id"]), "OperationReceipt"),
        ],
        "opportunity_ref": record_ref(cast(str, case["record_id"]), "AppealCase"),
        "revision_treatment": "authentic",
        "alternatives": ["execute_requested_remedy", "refuse", "escalate", "no_change"],
        "cited_evidence": [
            {
                "record_id": value["record_id"],
                "record_type": value["record_type"],
                "fields": ["record_id", "semantic_key", "integrity_status"],
            }
            for value in evidence_refs
        ],
        "reason_code": reason,
        "authority_ref": record_ref(
            cast(str, authority["record_id"]), cast(str, authority["record_type"])
        ),
        "governance_boundary_ref": record_ref(
            cast(str, boundary["record_id"]), "GovernanceBoundary"
        ),
        "decision_action": action,
        "predecessor_successor_diff": {
            "changed_fields": ["appeal_status", "pause_status", "adjudication_outcome"],
            "hash_only": False,
        },
        "executable_consequence": dict(consequence),
        "next_run_ref": record_ref(cast(str, case["record_id"]), "AppealCase"),
        "budget": dict(cast(Mapping[str, Any], boundary["budgets"])),
        "leakage_checks": {"record_content_treated_as_data": True, "outside_information": "none"},
        "receipt_ref": record_ref(cast(str, receipt["record_id"]), "OperationReceipt"),
        "event_sequence": event_sequence,
        "qste:governanceTransition": True,
    }


def _successor_case_fields(
    prior: Mapping[str, Any],
    successor: Mapping[str, Any],
    decision: Mapping[str, Any] | None,
    receipt: Mapping[str, Any],
    *,
    appeal_status: str,
    pause_status: str,
    adjudication_outcome: str,
    repair_status: str,
    reason_code: str,
    evidence: Sequence[Mapping[str, Any]],
    transition: str,
    decision_ref: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    active_decision_ref = (
        record_ref(cast(str, decision["record_id"]), "DecisionEvent")
        if decision is not None
        else dict(cast(Mapping[str, Any], decision_ref))
    )
    references = [
        record_ref(cast(str, prior["record_id"]), "AppealCase", "succeeds"),
        record_ref(cast(str, receipt["record_id"]), "OperationReceipt"),
        active_decision_ref,
        *[
            record_ref(cast(str, value["record_id"]), cast(str, value["record_type"]))
            for value in evidence
        ],
    ]
    return {
        "references": references,
        "appellant_ref": dict(cast(Mapping[str, Any], prior["appellant_ref"])),
        "standing_basis": prior["standing_basis"],
        "responding_authority_ref": dict(
            cast(Mapping[str, Any], prior["responding_authority_ref"])
        ),
        "target_closure": dict(cast(Mapping[str, Any], prior["target_closure"])),
        "reason_code": reason_code,
        "requested_action": prior["requested_action"],
        "deadlines": dict(cast(Mapping[str, Any], prior["deadlines"])),
        "jurisdiction": prior["jurisdiction"],
        "appeal_status": appeal_status,
        "pause_status": pause_status,
        "adjudication_outcome": adjudication_outcome,
        "repair_status": repair_status,
        "adjudication_evidence_refs": [
            record_ref(cast(str, value["record_id"]), cast(str, value["record_type"]))
            for value in evidence
        ]
        or list(cast(list[Mapping[str, Any]], prior["adjudication_evidence_refs"])),
        "decision_event_refs": [
            *list(cast(list[Mapping[str, Any]], prior["decision_event_refs"])),
            active_decision_ref,
        ],
        "successor_case_ref": None,
        "qste:appealProfile": APPEAL_PROFILE,
        "qste:governanceBoundaryRef": dict(
            cast(Mapping[str, Any], prior["qste:governanceBoundaryRef"])
        ),
        "qste:standingValidation": prior["qste:standingValidation"],
        "qste:dutyToRespond": prior["qste:dutyToRespond"],
        "qste:predecessorCaseRef": record_ref(cast(str, prior["record_id"]), "AppealCase"),
        "qste:eventTransitions": [
            *list(cast(list[str], prior.get("qste:eventTransitions", []))),
            transition,
        ],
    }


def _case_axes(case: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "appeal_status": case["appeal_status"],
        "pause_status": case["pause_status"],
        "adjudication_outcome": case["adjudication_outcome"],
        "repair_status": case["repair_status"],
    }


def _current_policy_state(target_id: str, store: RecordStore) -> dict[str, Any]:
    authorization_status = "permitted"
    pause_status = "not_requested"
    for event in store.iter_events():
        if event.subject_record_id != target_id:
            continue
        if event.event_type == "qste:authorization-revoked/0.1":
            authorization_status = "revoked"
        elif event.event_type == "qste:authorization-restored/0.1":
            authorization_status = "permitted"
        elif event.event_type == "qste:use-paused/0.1":
            pause_status = "active"
        elif event.event_type == "qste:pause-released/0.1":
            pause_status = "released"
    executable = authorization_status == "permitted" and pause_status != "active"
    return {
        "authorization_status": authorization_status,
        "pause_status": pause_status,
        "action_set": ["reuse", "project", "transduce"] if executable else ["appeal"],
    }


def _action_set_after(action: str, before: Sequence[str]) -> list[str]:
    if action in {"pause", "revoke", "restrict", "delete"}:
        return ["appeal"]
    if action in {"restore", "release_pause"}:
        return ["reuse", "project", "transduce"]
    if action == "correct":
        return sorted({*before, "use_corrected_successor"})
    return list(before)


def _policy_state_after(action: str, before: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "authorization_status": before["authorization_status"],
        "pause_status": before["pause_status"],
        "action_set": list(cast(Sequence[str], before["action_set"])),
    }
    if action == "revoke":
        result["authorization_status"] = "revoked"
    elif action == "restore":
        result["authorization_status"] = "permitted"
    elif action in {"pause", "restrict"}:
        result["pause_status"] = "active"
    elif action == "release_pause":
        result["pause_status"] = "released"
    elif action == "correct":
        result["corrected_successor"] = True
    result["action_set"] = _action_set_after(action, cast(Sequence[str], before["action_set"]))
    if result["authorization_status"] != "permitted" or result["pause_status"] == "active":
        result["action_set"] = ["appeal"]
    return result


def _action_field(action: str) -> str:
    return {
        "pause": "pause_status",
        "revoke": "authorization_status",
        "delete": "availability",
        "restrict": "permitted_actions",
        "restore": "authorization_status",
        "release_pause": "pause_status",
        "correct": "successor_spec",
    }[action]


def _pause_after(action: str, prior: str, feasible: bool) -> str:
    if not feasible:
        return prior
    if action == "pause":
        return "active"
    if action == "release_pause":
        return "released"
    return prior


def _propagation_event_type(action: str) -> str:
    return {
        "pause": "qste:use-paused/0.1",
        "correct": "qste:dependency-invalidated/0.1",
        "revoke": "qste:authorization-revoked/0.1",
        "delete": "qste:dependency-invalidated/0.1",
        "restrict": "qste:use-paused/0.1",
        "restore": "qste:authorization-restored/0.1",
        "release_pause": "qste:pause-released/0.1",
    }[action]


def _limit_reason(value: str) -> str:
    if value == "retention_duty_blocks_deletion":
        return "retention_duty_blocks_deletion"
    if value == "immutable_qste_record_history":
        return "repair_not_feasible"
    return "external_copy_out_of_scope"


def _required_string(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ContractError("invalid_input", f"{key} must be a nonempty string")
    return result


def _string_list(value: Any, name: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise ContractError("invalid_input", f"{name} must be a unique nonempty string array")
    return list(value)


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ContractError("invalid_input", f"{name} must be a nonempty object")
    return value
