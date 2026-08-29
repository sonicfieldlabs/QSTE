"""Bounded P12a preparation and method-pilot service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn, cast

from qste.core import canonical_json_bytes, content_digest, loads_json, utc_timestamp
from qste.core.contracts import ContractError
from qste.experiments.contracts import (
    PARAMETER_FIELDS,
    PILOT_PROFILE,
    PREPARATION_PROFILE,
    SAFETY_FLAGS,
)
from qste.experiments.models import ExperimentOutcome
from qste.ingress.records import bind_semantic_key, operation_receipt, record_base, record_ref
from qste.storage import ArtifactStore, RecordStore, WorkspacePaths

MAX_PACKET_BYTES = 2 * 1024 * 1024
MAX_SEQUENCE_ITEMS = 256
FORBIDDEN_PILOT_KEYS = frozenset(
    {"outcomes", "effects", "p_values", "participants", "listener_responses"}
)


class ExperimentPreparationService:
    """Freeze preparation inputs and nonconfirmatory pilot feasibility evidence."""

    def __init__(self, workspace: Path) -> None:
        self.paths = WorkspacePaths.open(workspace)
        self.store = RecordStore(self.paths)
        self.artifacts = ArtifactStore(self.paths)

    def freeze(
        self,
        *,
        context_record_id: str,
        packet: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> ExperimentOutcome:
        context = self.store.get_record(context_record_id).record
        self._authorize(authorization_status, "experiment_freeze", context)
        try:
            normalized = _validate_packet(packet)
        except ContractError as error:
            self._fail("experiment_freeze", context, error.reason_code, str(error))
        timestamp = utc_timestamp()
        record = self._artifact(
            normalized,
            timestamp=timestamp,
            media_type="application/vnd.qste.experiment-preparation+json",
            references=[record_ref(context_record_id, cast(str, context["record_type"]))],
        )
        record.update(
            {
                "qste:experimentProfile": PREPARATION_PROFILE,
                "qste:studyStage": "method_pilot",
                "qste:preparationStatus": "frozen",
                "qste:confirmatoryStatus": "not_started",
                "qste:humanDataStatus": "not_collected",
                "qste:physicalCalibrationStatus": normalized["acquisition"][
                    "physical_calibration_status"
                ],
                "qste:publicProjection": False,
            }
        )
        bind_semantic_key(
            record,
            "qste-semantic-key/experiment-preparation-v1",
            {
                "packet_digest": record["content_digest"],
                "context": context.get("semantic_key", context_record_id),
            },
        )
        return self._persist("experiment_freeze", context, record, timestamp)

    def pilot(
        self,
        *,
        preparation_record_id: str,
        evidence: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> ExperimentOutcome:
        preparation = self.store.get_record(preparation_record_id).record
        self._authorize(authorization_status, "experiment_pilot", preparation)
        if preparation.get("qste:experimentProfile") != PREPARATION_PROFILE:
            self._fail(
                "experiment_pilot",
                preparation,
                "invalid_input",
                "pilot input is not a frozen P12a preparation",
            )
        try:
            normalized = _validate_pilot(evidence)
            packet = self._artifact_json(preparation)
            if normalized["frozen_parameter_digest"] != content_digest(
                canonical_json_bytes(packet["parameters"])
            ):
                raise ContractError(
                    "conformance_failed", "pilot evidence does not bind frozen parameters"
                )
        except ContractError as error:
            self._fail("experiment_pilot", preparation, error.reason_code, str(error))
        timestamp = utc_timestamp()
        record = self._artifact(
            normalized,
            timestamp=timestamp,
            media_type="application/vnd.qste.method-pilot+json",
            references=[record_ref(preparation_record_id, "ArtifactRecord")],
        )
        record.update(
            {
                "qste:experimentProfile": PREPARATION_PROFILE,
                "qste:pilotProfile": PILOT_PROFILE,
                "qste:pilotStatus": "feasible_parameters_frozen",
                "qste:confirmatoryStatus": "not_started",
                "qste:humanDataStatus": "not_collected",
                "qste:heldOutOutcomeStatus": "not_accessed",
                "qste:p12mStatus": "unavailable",
                "qste:p12hStatus": "authorization_required",
                "qste:publicProjection": False,
            }
        )
        bind_semantic_key(
            record,
            "qste-semantic-key/method-pilot-v1",
            {
                "preparation": preparation["semantic_key"],
                "evidence_digest": record["content_digest"],
            },
        )
        return self._persist("experiment_pilot", preparation, record, timestamp)

    def account(
        self,
        *,
        context_record_id: str,
        authorization_status: str = "permitted",
    ) -> ExperimentOutcome:
        context = self.store.get_record(context_record_id).record
        self._authorize(authorization_status, "experiment_account", context)
        timestamp = utc_timestamp()
        value = {
            "payload_type": "CapabilityAccount",
            "payload_schema_id": "qste-payload/0.3.0",
            "items": [],
            "data": {
                "preparation": "available",
                "method_pilot": "available",
                "confirmatory_machine_study": "unavailable",
                "human_protocol_submission": "authorization_required",
                "human_data_collection": "prohibited",
                "integrated_analysis": "unavailable",
                "public_research_projection": "prohibited",
            },
        }
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(context_record_id, cast(str, context["record_type"])),
            authorization_status="permitted",
            operation="experiment_account",
            inputs=[record_ref(context_record_id, cast(str, context["record_type"]))],
            parameters={"profile": PREPARATION_PROFILE},
            outputs=[],
            tool_id="qste-p12a-experiment-preparation",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:experiment-capability-accounted/0.1",
            subject_record_id=context_record_id,
            receipt_record_id=receipt["record_id"],
            payload={"confirmatory": False, "human_data": False},
            created_at=timestamp,
        )
        return ExperimentOutcome(
            value, "qste-payload/0.3.0/CapabilityAccount", receipt, event.event_sequence
        )

    def _artifact(
        self,
        value: Mapping[str, Any],
        *,
        timestamp: str,
        media_type: str,
        references: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        data = canonical_json_bytes(dict(value))
        if len(data) > MAX_PACKET_BYTES:
            raise ContractError("resource_limit", "P12a packet exceeds byte bound")
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
            raise ContractError("capability_unavailable", "preparation bytes are unavailable")
        value = loads_json(self.artifacts.read_bytes(digest, maximum_bytes=MAX_PACKET_BYTES))
        if not isinstance(value, dict):
            raise ContractError("conformance_failed", "preparation is not a JSON object")
        return cast(dict[str, Any], value)

    def _persist(
        self,
        operation: str,
        request: Mapping[str, Any],
        record: dict[str, Any],
        timestamp: str,
    ) -> ExperimentOutcome:
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(
                cast(str, request["record_id"]), cast(str, request["record_type"])
            ),
            authorization_status="permitted",
            operation=operation,
            inputs=[record_ref(cast(str, request["record_id"]), cast(str, request["record_type"]))],
            parameters={"profile": PREPARATION_PROFILE},
            outputs=[record_ref(cast(str, record["record_id"]), "ArtifactRecord")],
            tool_id="qste-p12a-experiment-preparation",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [record, receipt],
            domain_event_record_id=None,
            event_type=f"qste:{operation.replace('_', '-')}/0.1",
            subject_record_id=cast(str, record["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"confirmatory": False, "human_data": False},
            created_at=timestamp,
        )
        return ExperimentOutcome(
            record,
            "https://schemas.qste.invalid/0.3.0/records/artifact-record.schema.json",
            receipt,
            event.event_sequence,
        )

    def _authorize(
        self, authorization_status: str, operation: str, request: Mapping[str, Any]
    ) -> None:
        if authorization_status != "permitted":
            self._fail(
                operation,
                request,
                "policy_refused",
                f"P12a authorization is {authorization_status}",
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
            request_ref=record_ref(
                cast(str, request["record_id"]), cast(str, request["record_type"])
            ),
            authorization_status=effective,
            operation=operation,
            inputs=[record_ref(cast(str, request["record_id"]), cast(str, request["record_type"]))],
            parameters={"reason_code": reason},
            outputs=[{"availability": "not_applicable", "reason": reason}],
            operation_status="refused" if reason == "policy_refused" else "failed",
            tool_id="qste-p12a-experiment-preparation",
            tool_version="v0.1",
        )
        self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:experiment-operation-refused/0.1"
            if reason == "policy_refused"
            else "qste:experiment-operation-failed/0.1",
            subject_record_id=cast(str, request["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"operation": operation, "reason_code": reason},
            created_at=timestamp,
        )
        error = ContractError(reason, message)
        error.receipt_id = receipt["record_id"]  # type: ignore[attr-defined]
        error.authorization_status = effective  # type: ignore[attr-defined]
        raise error


def _validate_packet(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "profile_id",
        "study_stage",
        "corpus",
        "acquisition",
        "checkpoints",
        "code",
        "models",
        "licenses",
        "task_profiles",
        "exclusions",
        "failure_rules",
        "parameters",
        "estimands",
        "execution_packet",
        "treatment_materials",
        "composition_grammar",
        "protocol_inputs",
        "safety_flags",
    }
    if set(value) != required:
        raise ContractError("invalid_input", "P12a preparation fields are not exact")
    if value["profile_id"] != PREPARATION_PROFILE or value["study_stage"] != "method_pilot":
        raise ContractError("invalid_input", "P12a packet has the wrong profile or stage")
    corpus = _mapping(value["corpus"], "corpus")
    if corpus.get("rights_status") != "cleared" or not _digest(corpus.get("content_digest")):
        raise ContractError("policy_refused", "corpus rights and digest must be frozen")
    acquisition = _mapping(value["acquisition"], "acquisition")
    if acquisition.get("calibration_status") != "digital_reference_calibrated":
        raise ContractError("conformance_failed", "digital calibration subset is not frozen")
    if acquisition.get("physical_calibration_status") not in {"available", "unavailable"}:
        raise ContractError("invalid_input", "physical calibration status is invalid")
    parameters = _mapping(value["parameters"], "parameters")
    if set(parameters) != PARAMETER_FIELDS:
        raise ContractError("invalid_input", "P12a parameter fields are not exact")
    meaningful = _number(parameters["meaningful_bound"], "meaningful_bound", positive=True)
    region = parameters["equivalence_region"]
    if (
        not isinstance(region, list)
        or len(region) != 2
        or not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in region)
        or float(region[0]) > 0
        or float(region[1]) < 0
        or float(region[1]) >= meaningful
    ):
        raise ContractError("invalid_input", "equivalence region and meaningful bound overlap")
    for key in ("coverage_tolerance", "effect_tolerance", "unmatched_penalty_lambda"):
        _number(parameters[key], key, positive=False)
    flags = _mapping(value["safety_flags"], "safety_flags")
    if set(flags) != SAFETY_FLAGS or any(flags[key] is not False for key in SAFETY_FLAGS):
        raise ContractError("policy_refused", "P12a cannot contain confirmatory or human outcomes")
    for key in (
        "checkpoints",
        "code",
        "models",
        "licenses",
        "task_profiles",
        "exclusions",
        "failure_rules",
        "estimands",
    ):
        _sequence(value[key], key)
    for key in (
        "execution_packet",
        "treatment_materials",
        "composition_grammar",
        "protocol_inputs",
    ):
        if not _mapping(value[key], key):
            raise ContractError("invalid_input", f"{key} is empty")
    return dict(value)


def _validate_pilot(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "profile_id",
        "frozen_parameter_digest",
        "feasibility_checks",
        "calibration_summary",
        "leakage_check_status",
        "power_assumption_status",
        "safety_flags",
    }
    if set(value) != required or value.get("profile_id") != PILOT_PROFILE:
        raise ContractError("invalid_input", "method-pilot evidence fields are not exact")
    if FORBIDDEN_PILOT_KEYS.intersection(value):
        raise ContractError("policy_refused", "confirmatory or human outcome fields are prohibited")
    if not _digest(value["frozen_parameter_digest"]):
        raise ContractError("invalid_input", "frozen parameter digest is invalid")
    checks = _mapping(value["feasibility_checks"], "feasibility_checks")
    if not checks or any(item is not True for item in checks.values()):
        raise ContractError("conformance_failed", "method-pilot feasibility is incomplete")
    if value["leakage_check_status"] != "passed":
        raise ContractError("conformance_failed", "leakage checks did not pass")
    if value["power_assumption_status"] != "frozen_not_tested":
        raise ContractError("conformance_failed", "power assumptions are not frozen")
    flags = _mapping(value["safety_flags"], "safety_flags")
    if set(flags) != SAFETY_FLAGS or any(flags[key] is not False for key in SAFETY_FLAGS):
        raise ContractError("policy_refused", "pilot contains confirmatory or human outcomes")
    if not _mapping(value["calibration_summary"], "calibration_summary"):
        raise ContractError("invalid_input", "calibration summary is empty")
    return dict(value)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError("invalid_input", f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or len(value) > MAX_SEQUENCE_ITEMS
    ):
        raise ContractError("invalid_input", f"{label} must be a bounded nonempty array")
    return value


def _number(value: Any, label: str, *, positive: bool) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ContractError("invalid_input", f"{label} must be numeric")
    result = float(value)
    if result < 0 or (positive and result <= 0):
        raise ContractError("invalid_input", f"{label} is outside its allowed range")
    return result


def _digest(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and len(value) == 71
