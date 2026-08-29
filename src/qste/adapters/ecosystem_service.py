"""Fixture-first P11 ecosystem adapters and bounded synthetic engine routes."""

from __future__ import annotations

import socket
import struct

# B404: only the fixed packaged fixture is executable.
import subprocess  # nosec B404
import sys
from collections.abc import Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any, NoReturn, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]
from referencing import Registry, Resource

from qste.adapters.ecosystem_contracts import (
    ECOSYSTEM_PROFILE,
    ENGINE_PROFILE,
    EcosystemTarget,
    ecosystem_target,
    engine_capability,
)
from qste.adapters.ecosystem_models import P11AdapterOutcome
from qste.core import canonical_json_bytes, content_digest, loads_json, utc_timestamp
from qste.core.contracts import BASE_URI, ContractError
from qste.ingress.records import bind_semantic_key, operation_receipt, record_base, record_ref
from qste.storage import ArtifactStore, RecordStore, WorkspacePaths

MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_FIELDS = 256
PROCESS_LIMIT_KEYS = {
    "maximum_input_bytes",
    "maximum_output_bytes",
    "maximum_log_bytes",
    "maximum_memory_bytes",
    "maximum_disk_bytes",
    "maximum_channels",
    "maximum_sample_rate_hz",
    "maximum_duration_seconds",
    "maximum_output_count",
}


class EcosystemAdapterService:
    """Validate frozen external fixtures without importing adjacent projects."""

    def __init__(self, workspace: Path) -> None:
        self.paths = WorkspacePaths.open(workspace)
        self.store = RecordStore(self.paths)
        self.artifacts = ArtifactStore(self.paths)

    def import_payload(
        self,
        *,
        target_id: str,
        context_record_id: str,
        payload: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> P11AdapterOutcome:
        return self._store_payload(
            target_id=target_id,
            operation="import",
            context_record_id=context_record_id,
            payload=payload,
            authorization_status=authorization_status,
            human_authorized=False,
        )

    def project_payload(
        self,
        *,
        target_id: str,
        context_record_id: str,
        payload: Mapping[str, Any],
        human_authorized: bool = False,
        authorization_status: str = "permitted",
    ) -> P11AdapterOutcome:
        return self._store_payload(
            target_id=target_id,
            operation="project",
            context_record_id=context_record_id,
            payload=payload,
            authorization_status=authorization_status,
            human_authorized=human_authorized,
        )

    def inspect_payload(
        self,
        *,
        target_id: str,
        context_record_id: str,
        payload: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> P11AdapterOutcome:
        return self._store_payload(
            target_id=target_id,
            operation="inspect",
            context_record_id=context_record_id,
            payload=payload,
            authorization_status=authorization_status,
            human_authorized=False,
        )

    def live_loopback(
        self,
        *,
        target_id: str,
        context_record_id: str,
        authorization_status: str = "permitted",
    ) -> P11AdapterOutcome:
        target = ecosystem_target(target_id)
        context = self.store.get_record(context_record_id).record
        self._authorize(authorization_status, "ecosystem_live_loopback", context)
        self._require_capability(target, "live_loopback", context)
        raise AssertionError("live target capability unexpectedly available")

    def account(
        self,
        *,
        target_id: str,
        context_record_id: str,
        authorization_status: str = "permitted",
    ) -> P11AdapterOutcome:
        target = ecosystem_target(target_id)
        context = self.store.get_record(context_record_id).record
        self._authorize(authorization_status, "ecosystem_account", context)
        value = _payload(
            "CapabilityAccount",
            {
                "adapter_profile": ECOSYSTEM_PROFILE,
                "target_id": target.target_id,
                "target_version": target.version,
                "target_revision": target.revision,
                "contracts": list(target.contracts),
                "capabilities": target.capabilities,
                "validation_mode": target.validation_mode,
                "live_external_execution": False,
                "adjacent_checkout_write": False,
            },
        )
        return self._outcome(
            target_id=target_id,
            operation="ecosystem_account",
            request=context,
            parameters={"target_id": target_id},
            value=value,
            value_type="qste-payload/0.3.0/CapabilityAccount",
            records=(),
            output_refs=(),
            event_type="qste:ecosystem-capability-accounted/0.1",
        )

    def _store_payload(
        self,
        *,
        target_id: str,
        operation: str,
        context_record_id: str,
        payload: Mapping[str, Any],
        authorization_status: str,
        human_authorized: bool,
    ) -> P11AdapterOutcome:
        target = ecosystem_target(target_id)
        context = self.store.get_record(context_record_id).record
        self._authorize(authorization_status, f"ecosystem_{operation}", context)
        self._require_capability(target, operation, context)
        if not isinstance(human_authorized, bool):
            raise ContractError("invalid_input", "human authorization must be an exact boolean")
        normalized = _bounded_object(payload)
        if (
            operation == "project"
            and _is_public_projection(target, normalized)
            and not human_authorized
        ):
            self._fail(
                f"ecosystem_{operation}",
                context,
                "policy_refused",
                "public ecosystem projection requires explicit human authorization",
                capability_status="prohibited",
                authorization_status="refused",
            )
        try:
            validation = _validate_target_payload(target, normalized, operation)
        except ContractError as error:
            self._fail(
                f"ecosystem_{operation}",
                context,
                error.reason_code,
                str(error),
                capability_status="degraded",
            )
        timestamp = utc_timestamp()
        data = canonical_json_bytes(normalized)
        object_ = self.artifacts.put_bytes(data)
        self.store.register_artifact(
            object_.content_digest,
            object_.size,
            object_.relative_path,
            media_type=f"application/vnd.qste.p11.{target.target_id}+json",
            registered_at=timestamp,
        )
        transported = _transported_evidence(target.target_id, normalized)
        artifact = record_base(
            "ArtifactRecord",
            created_at=timestamp,
            references=[record_ref(context["record_id"], context["record_type"])],
        ) | {
            "media_type": f"application/vnd.qste.p11.{target.target_id}+json",
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": object_.content_digest,
            "qste:adapterProfile": ECOSYSTEM_PROFILE,
            "qste:adapterTarget": target.target_id,
            "qste:targetName": target.name,
            "qste:targetVersion": target.version,
            "qste:targetRevision": target.revision,
            "qste:nativeContracts": list(target.contracts),
            "qste:adapterOperation": operation,
            "qste:validation": validation,
            "qste:transportedEvidence": transported,
            "qste:externalWrite": False,
            "qste:externalExecution": False,
            "qste:networkAccess": False,
            "qste:playback": False,
            "qste:modelExecution": False,
        }
        bind_semantic_key(
            artifact,
            "qste-semantic-key/ecosystem-adapter-artifact-v1",
            {
                "target_id": target.target_id,
                "target_revision": target.revision,
                "operation": operation,
                "content_digest": object_.content_digest,
                "native_identity": _native_identity(target.target_id, normalized),
            },
        )
        return self._outcome(
            target_id=target_id,
            operation=f"ecosystem_{operation}",
            request=context,
            parameters={
                "target_id": target_id,
                "target_version": target.version,
                "validation_mode": target.validation_mode,
                "human_authorized": human_authorized,
            },
            value=artifact,
            value_type=f"{BASE_URI}/records/artifact-record.schema.json",
            records=[artifact],
            output_refs=[record_ref(artifact["record_id"], "ArtifactRecord")],
            event_type=f"qste:ecosystem-{operation}-recorded/0.1",
        )

    def _require_capability(
        self, target: EcosystemTarget, operation: str, request: Mapping[str, Any]
    ) -> None:
        capability = target.capabilities[operation]
        if capability == "available":
            return
        if capability == "prohibited":
            self._fail(
                f"ecosystem_{operation}",
                request,
                "policy_refused",
                f"{target.target_id} {operation} is prohibited",
                capability_status="prohibited",
                authorization_status="refused",
            )
        self._fail(
            f"ecosystem_{operation}",
            request,
            "capability_unavailable",
            f"{target.target_id} {operation} is {capability}",
            capability_status=capability,
        )

    def _outcome(
        self,
        *,
        target_id: str,
        operation: str,
        request: Mapping[str, Any],
        parameters: Mapping[str, Any],
        value: dict[str, Any],
        value_type: str,
        records: Sequence[Mapping[str, Any]],
        output_refs: Sequence[Mapping[str, Any]],
        event_type: str,
    ) -> P11AdapterOutcome:
        timestamp = utc_timestamp()
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(request["record_id"], request["record_type"]),
            authorization_status="permitted",
            operation=operation,
            inputs=[record_ref(request["record_id"], request["record_type"])],
            parameters=parameters,
            outputs=list(output_refs) or [{"payload_type": value.get("payload_type", value_type)}],
            tool_id=f"qste-p11-{target_id}-adapter",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [*[dict(item) for item in records], receipt],
            domain_event_record_id=None,
            event_type=event_type,
            subject_record_id=cast(str, request["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"target_id": target_id, "operation": operation},
            created_at=timestamp,
        )
        return P11AdapterOutcome(value, value_type, receipt, event.event_sequence, target_id)

    def _authorize(
        self, authorization_status: str, operation: str, request: Mapping[str, Any]
    ) -> None:
        if authorization_status == "permitted":
            return
        if authorization_status not in {"unknown", "refused", "deferred", "revoked"}:
            raise ContractError("invalid_input", "authorization status is invalid")
        self._fail(
            operation,
            request,
            "policy_refused",
            f"P11 adapter authorization is {authorization_status}",
            capability_status="prohibited",
            authorization_status="refused",
        )

    def _fail(
        self,
        operation: str,
        request: Mapping[str, Any],
        reason: str,
        message: str,
        *,
        capability_status: str,
        authorization_status: str = "permitted",
        diagnostics: Mapping[str, Any] | None = None,
    ) -> NoReturn:
        _persist_failure(
            self.store,
            operation=operation,
            request=request,
            reason=reason,
            message=message,
            capability_status=capability_status,
            authorization_status=authorization_status,
            diagnostics=diagnostics,
        )


class BoundedEngineService:
    """Run only fixed QSTE synthetic process and OSC loopback demonstrations."""

    def __init__(self, workspace: Path) -> None:
        self.paths = WorkspacePaths.open(workspace)
        self.store = RecordStore(self.paths)
        self.artifacts = ArtifactStore(self.paths)

    def execute(
        self,
        *,
        target_id: str,
        context_record_id: str,
        request: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> P11AdapterOutcome:
        context = self.store.get_record(context_record_id).record
        self._authorize(authorization_status, "engine_execute", context)
        self._require_capability(target_id, context)
        if target_id != "qste_fixture_process":
            raise AssertionError("available non-process target reached process execution")
        normalized = _validate_process_request(request)
        input_bytes = canonical_json_bytes(normalized)
        limits = cast(Mapping[str, int], normalized["limits"])
        if len(input_bytes) > limits["maximum_input_bytes"]:
            self._fail(
                "engine_execute",
                context,
                "invalid_input",
                "engine input exceeds declared byte limit",
                capability_status="available",
            )
        timeout = float(normalized["timeout_seconds"])
        fixture_program = Path(__file__).with_name("engine_fixture.py")
        command = [sys.executable, str(fixture_program)]
        try:
            # B603: both the interpreter and fixture path are fixed by QSTE.
            completed = subprocess.run(  # nosec B603
                command,
                input=input_bytes,
                capture_output=True,
                check=False,
                timeout=timeout,
                cwd=self.paths.root,
                env={"PATH": "", "PYTHONHASHSEED": "0"},
            )
        except subprocess.TimeoutExpired as error:
            stdout = bytes(error.stdout or b"")[: limits["maximum_output_bytes"]]
            stderr = bytes(error.stderr or b"")[: limits["maximum_log_bytes"]]
            self._fail(
                "engine_execute",
                context,
                "execution_failed",
                "bounded fixture process timed out",
                capability_status="degraded",
                diagnostics={
                    "timeout_state": True,
                    "stdout_digest": content_digest(stdout),
                    "stderr_digest": content_digest(stderr),
                    "timeout_seconds": timeout,
                },
            )
        stdout = completed.stdout[: limits["maximum_output_bytes"]]
        stderr = completed.stderr[: limits["maximum_log_bytes"]]
        if completed.returncode != 0:
            self._fail(
                "engine_execute",
                context,
                "execution_failed",
                f"bounded fixture process exited {completed.returncode}",
                capability_status="degraded",
                diagnostics={
                    "timeout_state": False,
                    "return_code": completed.returncode,
                    "stdout_digest": content_digest(stdout),
                    "stderr_digest": content_digest(stderr),
                },
            )
        try:
            output = loads_json(stdout)
        except Exception as error:
            self._fail(
                "engine_execute",
                context,
                "conformance_failed",
                f"fixture process output is not JSON: {type(error).__name__}",
                capability_status="degraded",
            )
        if not isinstance(output, dict):
            self._fail(
                "engine_execute",
                context,
                "conformance_failed",
                "fixture process output is not an object",
                capability_status="degraded",
            )
        execution = {
            "target_id": target_id,
            "execution_mode": "bounded_synthetic_process",
            "parameters": normalized["parameters"],
            "limits": normalized["limits"],
            "command_identity": "packaged-file:qste.adapters/engine_fixture.py",
            "return_code": completed.returncode,
            "logs": {
                "stdout_digest": content_digest(stdout),
                "stderr_digest": content_digest(stderr),
                "stdout_bytes": len(stdout),
                "stderr_bytes": len(stderr),
            },
            "output_digest": content_digest(stdout),
            "timeout_state": False,
            "timeout_seconds": timeout,
            "output": output,
            "external_engine_executed": False,
            "playback": False,
            "network_access": False,
            "disk_write": False,
        }
        return self._store_execution(context, target_id, execution, "engine_execute")

    def osc_loopback(
        self,
        *,
        target_id: str,
        context_record_id: str,
        request: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> P11AdapterOutcome:
        context = self.store.get_record(context_record_id).record
        self._authorize(authorization_status, "engine_osc_loopback", context)
        self._require_capability(target_id, context)
        if target_id != "qste_fixture_osc_loopback":
            raise AssertionError("available non-loopback target reached OSC loopback")
        normalized = _validate_loopback_request(request)
        packet = _osc_string_packet(normalized["address"], normalized["message"])
        if len(packet) > normalized["maximum_packet_bytes"]:
            self._fail(
                "engine_osc_loopback",
                context,
                "invalid_input",
                "OSC packet exceeds declared byte limit",
                capability_status="available",
            )
        timeout = float(normalized["timeout_seconds"])
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(timeout)
            endpoint = cast(tuple[str, int], receiver.getsockname())
            sender.sendto(packet, endpoint)
            received, peer = receiver.recvfrom(normalized["maximum_packet_bytes"])
        except TimeoutError:
            self._fail(
                "engine_osc_loopback",
                context,
                "execution_failed",
                "OSC fixture loopback timed out",
                capability_status="degraded",
                diagnostics={"timeout_state": True, "timeout_seconds": timeout},
            )
        finally:
            sender.close()
            receiver.close()
        if received != packet or peer[0] != "127.0.0.1":
            self._fail(
                "engine_osc_loopback",
                context,
                "conformance_failed",
                "OSC loopback payload or peer changed",
                capability_status="degraded",
            )
        execution = {
            "target_id": target_id,
            "execution_mode": "authorized_synthetic_osc_loopback",
            "parameters": {
                "protocol": normalized["protocol"],
                "address": normalized["address"],
                "message": normalized["message"],
            },
            "logs": {
                "sent_digest": content_digest(packet),
                "received_digest": content_digest(received),
                "packet_bytes": len(packet),
            },
            "output_digest": content_digest(received),
            "timeout_state": False,
            "timeout_seconds": timeout,
            "loopback_host": "127.0.0.1",
            "external_engine_executed": False,
            "playback": False,
            "adjacent_checkout_write": False,
        }
        return self._store_execution(context, target_id, execution, "engine_osc_loopback")

    def account(
        self,
        *,
        target_id: str,
        context_record_id: str,
        authorization_status: str = "permitted",
    ) -> P11AdapterOutcome:
        context = self.store.get_record(context_record_id).record
        self._authorize(authorization_status, "engine_account", context)
        capability = engine_capability(target_id)
        value = _payload(
            "CapabilityAccount",
            {
                "engine_profile": ENGINE_PROFILE,
                "target_id": target_id,
                "capability_status": capability,
                "external_engine_execution": False,
                "fixture_process_available": target_id == "qste_fixture_process",
                "fixture_loopback_available": target_id == "qste_fixture_osc_loopback",
                "playback": False,
            },
        )
        return self._outcome(
            target_id,
            "engine_account",
            context,
            {"target_id": target_id},
            value,
            "qste-payload/0.3.0/CapabilityAccount",
            (),
            (),
            "qste:engine-capability-accounted/0.1",
        )

    def _store_execution(
        self,
        context: Mapping[str, Any],
        target_id: str,
        execution: Mapping[str, Any],
        operation: str,
    ) -> P11AdapterOutcome:
        timestamp = utc_timestamp()
        data = canonical_json_bytes(execution)
        object_ = self.artifacts.put_bytes(data)
        self.store.register_artifact(
            object_.content_digest,
            object_.size,
            object_.relative_path,
            media_type="application/vnd.qste.p11-engine-execution+json",
            registered_at=timestamp,
        )
        artifact = record_base(
            "ArtifactRecord",
            created_at=timestamp,
            references=[record_ref(context["record_id"], context["record_type"])],
        ) | {
            "media_type": "application/vnd.qste.p11-engine-execution+json",
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": object_.content_digest,
            "qste:engineProfile": ENGINE_PROFILE,
            "qste:engineTarget": target_id,
            "qste:engineExecution": dict(execution),
            "qste:adjacentCheckoutWrite": False,
        }
        bind_semantic_key(
            artifact,
            "qste-semantic-key/bounded-engine-execution-v1",
            {
                "target_id": target_id,
                "operation": operation,
                "parameters": execution["parameters"],
                "output_digest": execution["output_digest"],
                "timeout_state": execution["timeout_state"],
            },
        )
        return self._outcome(
            target_id,
            operation,
            context,
            cast(Mapping[str, Any], execution["parameters"]),
            artifact,
            f"{BASE_URI}/records/artifact-record.schema.json",
            [artifact],
            [record_ref(artifact["record_id"], "ArtifactRecord")],
            f"qste:{operation.replace('_', '-')}-recorded/0.1",
        )

    def _outcome(
        self,
        target_id: str,
        operation: str,
        request: Mapping[str, Any],
        parameters: Mapping[str, Any],
        value: dict[str, Any],
        value_type: str,
        records: Sequence[Mapping[str, Any]],
        output_refs: Sequence[Mapping[str, Any]],
        event_type: str,
    ) -> P11AdapterOutcome:
        timestamp = utc_timestamp()
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(request["record_id"], request["record_type"]),
            authorization_status="permitted",
            operation=operation,
            inputs=[record_ref(request["record_id"], request["record_type"])],
            parameters=parameters,
            outputs=list(output_refs) or [{"payload_type": value.get("payload_type", value_type)}],
            tool_id=f"qste-p11-{target_id}-engine-adapter",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [*[dict(item) for item in records], receipt],
            domain_event_record_id=None,
            event_type=event_type,
            subject_record_id=cast(str, request["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"target_id": target_id, "operation": operation},
            created_at=timestamp,
        )
        return P11AdapterOutcome(value, value_type, receipt, event.event_sequence, target_id)

    def _authorize(
        self, authorization_status: str, operation: str, request: Mapping[str, Any]
    ) -> None:
        if authorization_status == "permitted":
            return
        if authorization_status not in {"unknown", "refused", "deferred", "revoked"}:
            raise ContractError("invalid_input", "authorization status is invalid")
        self._fail(
            operation,
            request,
            "policy_refused",
            f"P11 engine authorization is {authorization_status}",
            capability_status="prohibited",
            authorization_status="refused",
        )

    def _require_capability(self, target_id: str, request: Mapping[str, Any]) -> None:
        capability = engine_capability(target_id)
        if capability == "available":
            return
        if capability == "prohibited":
            self._fail(
                "engine_execute",
                request,
                "policy_refused",
                f"engine target {target_id} is prohibited",
                capability_status="prohibited",
                authorization_status="refused",
            )
        self._fail(
            "engine_execute",
            request,
            "capability_unavailable",
            f"engine target {target_id} is {capability}",
            capability_status=capability,
        )

    def _fail(
        self,
        operation: str,
        request: Mapping[str, Any],
        reason: str,
        message: str,
        *,
        capability_status: str,
        authorization_status: str = "permitted",
        diagnostics: Mapping[str, Any] | None = None,
    ) -> NoReturn:
        _persist_failure(
            self.store,
            operation=operation,
            request=request,
            reason=reason,
            message=message,
            capability_status=capability_status,
            authorization_status=authorization_status,
            diagnostics=diagnostics,
        )


def _persist_failure(
    store: RecordStore,
    *,
    operation: str,
    request: Mapping[str, Any],
    reason: str,
    message: str,
    capability_status: str,
    authorization_status: str,
    diagnostics: Mapping[str, Any] | None,
) -> NoReturn:
    timestamp = utc_timestamp()
    operation_status = (
        "refused"
        if reason == "policy_refused"
        else "unavailable"
        if reason == "capability_unavailable"
        else "failed"
    )
    effective_authorization = "refused" if reason == "policy_refused" else authorization_status
    detail = dict(diagnostics or {})
    receipt = operation_receipt(
        created_at=timestamp,
        request_ref=record_ref(request["record_id"], request["record_type"]),
        authorization_status=effective_authorization,
        operation=operation,
        inputs=[record_ref(request["record_id"], request["record_type"])],
        parameters={
            "reason_code": reason,
            "capability_status": capability_status,
            **detail,
        },
        outputs=[{"availability": "not_applicable", "reason": reason}],
        operation_status=operation_status,
        tool_id="qste-p11-adapter-boundary",
        tool_version="v0.1",
    )
    store.insert_records_with_event(
        [receipt],
        domain_event_record_id=None,
        event_type=(
            "qste:p11-operation-refused/0.1"
            if reason == "policy_refused"
            else "qste:p11-operation-unavailable/0.1"
            if reason == "capability_unavailable"
            else "qste:p11-operation-failed/0.1"
        ),
        subject_record_id=cast(str, request["record_id"]),
        receipt_record_id=receipt["record_id"],
        payload={
            "operation": operation,
            "reason_code": reason,
            "capability_status": capability_status,
            "derivative_created": False,
        },
        created_at=timestamp,
    )
    error = ContractError(reason, message)
    error.receipt_id = receipt["record_id"]
    error.authorization_status = effective_authorization
    error.capability_status = capability_status
    error.diagnostics_extra = detail
    raise error


def _bounded_object(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    data = canonical_json_bytes(normalized)
    if len(data) > MAX_PAYLOAD_BYTES:
        raise ContractError("invalid_input", "P11 payload exceeds the 2 MiB bound")
    return normalized


def _validate_target_payload(
    target: EcosystemTarget, payload: Mapping[str, Any], operation: str
) -> dict[str, Any]:
    validation = {
        "structural_status": "passed",
        "schema_status": "passed",
        "interoperability_status": "passed_frozen_fixture",
        "operation": operation,
    }
    try:
        if target.target_id == "masa":
            _validate_masa(payload)
        elif target.target_id == "cosmoaudition":
            _validate_cosmo(payload)
            validation["schema_status"] = "unavailable_external_schema_not_published"
            validation["interoperability_status"] = "fixture_structural_only"
        elif target.target_id == "akouo":
            _validate_schema("akouo-route-decision.schema.json", payload)
        elif target.target_id == "oida":
            _validate_schema("oida-perception-report.schema.json", payload)
        elif target.target_id in {"earworm", "akousmata"}:
            _validate_schema("earworm-akousma.schema.json", payload)
            if target.target_id == "akousmata":
                validation["interoperability_status"] = "read_only_inspection_fixture"
        elif target.target_id == "listening_stack":
            _validate_listening_stack(payload)
            validation["schema_status"] = "not_applicable_metadata_snapshot"
            validation["interoperability_status"] = "not_claimed_by_association"
    except ValidationError as error:
        path = ".".join(str(item) for item in error.absolute_path)
        suffix = f" at {path}" if path else ""
        raise ContractError(
            "conformance_failed", f"frozen external schema rejected payload{suffix}"
        ) from error
    return validation


def _validate_masa(payload: Mapping[str, Any]) -> None:
    root = _frozen_schema_root()
    names = (
        "masa-definitions.schema.json",
        "masa-capability.schema.json",
        "masa-matter-record.schema.json",
    )
    schemas = [cast(dict[str, Any], loads_json((root / name).read_bytes())) for name in names]
    registry = Registry()
    for schema in schemas:
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    Draft202012Validator(schemas[-1], registry=registry).validate(payload)


def _validate_schema(name: str, payload: Mapping[str, Any]) -> None:
    schema = loads_json((_frozen_schema_root() / name).read_bytes())
    if not isinstance(schema, dict):
        raise ContractError("conformance_failed", f"frozen schema {name} is not an object")
    Draft202012Validator(schema).validate(payload)


def _validate_cosmo(payload: Mapping[str, Any]) -> None:
    descriptor = loads_json((_frozen_schema_root() / "cosmo-modulation-contract.json").read_bytes())
    if not isinstance(descriptor, dict):
        raise ContractError("conformance_failed", "Cosmo contract descriptor is invalid")
    required = descriptor["required_frame_fields"]
    if not isinstance(required, list) or not set(required).issubset(payload):
        raise ContractError("conformance_failed", "Cosmo frame is incomplete")
    if payload.get("contract") != "cosmo/modulation/v0.2":
        raise ContractError("conformance_failed", "Cosmo modulation contract differs")
    catalog = payload.get("signalCatalog")
    if not isinstance(catalog, Mapping) or (
        catalog.get("contract") != "cosmo/signal-catalog/v0.2" or catalog.get("version") != "0.2.0"
    ):
        raise ContractError("conformance_failed", "Cosmo signal catalog identity differs")
    signals = _list_of_objects(payload.get("signals"), "Cosmo signals")
    controls = _list_of_objects(payload.get("controls"), "Cosmo controls")
    absences = _list_of_objects(payload.get("absences"), "Cosmo absences")
    attributions = _list_of_objects(payload.get("attribution"), "Cosmo attribution")
    sources = _list_of_objects(payload.get("sources"), "Cosmo sources")
    values = payload.get("values")
    if not isinstance(values, Mapping):
        raise ContractError("conformance_failed", "Cosmo values are not an object")
    for signal in signals:
        for key in (
            "id",
            "unit",
            "value",
            "normalized",
            "timestamp",
            "sourceId",
            "confidence",
            "epistemicStatus",
            "temporalCharacter",
            "signalKind",
            "normalization",
        ):
            if key not in signal:
                raise ContractError("conformance_failed", f"Cosmo signal lacks {key}")
    controls_by_target = {item.get("target"): item for item in controls}
    for target, value in values.items():
        control = controls_by_target.get(target)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or control is None:
            raise ContractError("conformance_failed", "Cosmo value lacks a control decision")
        if control.get("status") is None or control.get("outputValue") != value:
            raise ContractError("conformance_failed", "Cosmo value and control status differ")
    for absence in absences:
        reason = absence.get("reason")
        if absence.get("target") in values or not isinstance(reason, str) or not reason.strip():
            raise ContractError("conformance_failed", "Cosmo absence is not explicit")
    if not attributions or not sources:
        raise ContractError("conformance_failed", "Cosmo attribution or source health is absent")


def _validate_listening_stack(payload: Mapping[str, Any]) -> None:
    if set(payload) != {
        "profile_id",
        "installer_version",
        "source_commit",
        "role",
        "interoperability_claim",
        "installation_performed",
        "components",
        "contracts",
    }:
        raise ContractError("conformance_failed", "Listening Stack metadata fields differ")
    if (
        payload["profile_id"] != "qste-listening-stack-read-only-snapshot/0.1"
        or payload["installer_version"] != "0.4.1"
        or payload["role"] != "compatibility_metadata_only"
        or payload["interoperability_claim"] is not False
        or payload["installation_performed"] is not False
    ):
        raise ContractError("conformance_failed", "Listening Stack metadata overclaims capability")


def _transported_evidence(target_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    categories: dict[str, list[dict[str, Any]]] = {
        "native_identifiers": [],
        "statuses": [],
        "attribution": [],
        "uncertainty": [],
        "units": [],
        "times": [],
    }
    key_categories = {
        "id": "native_identifiers",
        "akousma_id": "native_identifiers",
        "frameId": "native_identifiers",
        "status": "statuses",
        "state": "statuses",
        "outcome": "statuses",
        "availability": "statuses",
        "createdBy": "attribution",
        "sourceId": "attribution",
        "actor": "attribution",
        "attributed_to": "attribution",
        "confidence": "uncertainty",
        "uncertainty": "uncertainty",
        "unit": "units",
        "created_at": "times",
        "createdAt": "times",
        "generatedAt": "times",
        "timestamp": "times",
        "decided_at": "times",
    }

    def visit(value: Any, path: str) -> None:
        if sum(len(items) for items in categories.values()) >= MAX_EVIDENCE_FIELDS:
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                next_path = f"{path}.{key}" if path else str(key)
                category = key_categories.get(str(key))
                if category is not None and isinstance(item, (str, int, float, bool)):
                    categories[category].append({"path": next_path, "value": item})
                visit(item, next_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(payload, "")
    return {"target_id": target_id, **categories}


def _native_identity(target_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if target_id == "masa":
        return {"id": payload.get("id"), "version": payload.get("masaVersion")}
    if target_id == "cosmoaudition":
        return {"id": payload.get("frameId"), "contract": payload.get("contract")}
    if target_id == "akouo":
        return {"id": payload.get("id"), "gate": payload.get("gate")}
    if target_id == "oida":
        return {"version": payload.get("version"), "engine": payload.get("engine")}
    if target_id in {"earworm", "akousmata"}:
        return {"id": payload.get("akousma_id"), "version": payload.get("schema_version")}
    return {"profile_id": payload.get("profile_id"), "version": payload.get("installer_version")}


def _is_public_projection(target: EcosystemTarget, payload: Mapping[str, Any]) -> bool:
    if target.target_id == "masa":
        return payload.get("disclosure") == "public"
    extensions = payload.get("extensions")
    return isinstance(extensions, Mapping) and extensions.get("qste:disclosure_status") == "public"


def _validate_process_request(request: Mapping[str, Any]) -> dict[str, Any]:
    required = {"parameters", "payload", "delay_ms", "timeout_seconds", "limits"}
    if set(request) != required:
        raise ContractError("invalid_input", "engine process request fields are not exact")
    parameters = request["parameters"]
    payload = request["payload"]
    limits = request["limits"]
    if not isinstance(parameters, Mapping) or set(parameters) != {"gain", "mode"}:
        raise ContractError("invalid_input", "engine parameters are invalid")
    if (
        parameters["mode"] != "scale"
        or not isinstance(parameters["gain"], (int, float))
        or isinstance(parameters["gain"], bool)
    ):
        raise ContractError("invalid_input", "engine fixture permits only numeric scale mode")
    if (
        not isinstance(payload, list)
        or len(payload) > 4096
        or not all(
            isinstance(item, (int, float)) and not isinstance(item, bool) for item in payload
        )
    ):
        raise ContractError("invalid_input", "engine payload is invalid")
    if not isinstance(limits, Mapping) or set(limits) != PROCESS_LIMIT_KEYS:
        raise ContractError("invalid_input", "engine limit fields are not exact")
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in limits.values()
    ):
        raise ContractError("invalid_input", "engine limits must be nonnegative integers")
    exact_upper = {
        "maximum_input_bytes": 65_536,
        "maximum_output_bytes": 65_536,
        "maximum_log_bytes": 16_384,
        "maximum_memory_bytes": 67_108_864,
        "maximum_disk_bytes": 0,
        "maximum_channels": 2,
        "maximum_sample_rate_hz": 48_000,
        "maximum_duration_seconds": 10,
        "maximum_output_count": 1,
    }
    if any(cast(int, limits[key]) > maximum for key, maximum in exact_upper.items()):
        raise ContractError("invalid_input", "engine limit exceeds P11 fixture maximum")
    timeout = request["timeout_seconds"]
    delay = request["delay_ms"]
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 5:
        raise ContractError("invalid_input", "engine timeout is outside (0, 5] seconds")
    if not isinstance(delay, int) or isinstance(delay, bool) or not 0 <= delay <= 2_000:
        raise ContractError("invalid_input", "engine delay is outside fixture bounds")
    return {
        "parameters": dict(parameters),
        "payload": list(payload),
        "delay_ms": delay,
        "timeout_seconds": float(timeout),
        "limits": dict(limits),
    }


def _validate_loopback_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if set(request) != {
        "protocol",
        "address",
        "message",
        "timeout_seconds",
        "maximum_packet_bytes",
    }:
        raise ContractError("invalid_input", "OSC loopback fields are not exact")
    if request["protocol"] != "osc_fixture_v0.1" or request["address"] != "/qste/fixture":
        raise ContractError("invalid_input", "OSC fixture protocol or address differs")
    message = request["message"]
    if not isinstance(message, str) or not message or len(message.encode()) > 512:
        raise ContractError("invalid_input", "OSC fixture message is invalid")
    timeout = request["timeout_seconds"]
    maximum = request["maximum_packet_bytes"]
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 2:
        raise ContractError("invalid_input", "OSC timeout is outside (0, 2] seconds")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 64 <= maximum <= 1024:
        raise ContractError("invalid_input", "OSC packet bound is outside [64, 1024]")
    return {
        "protocol": request["protocol"],
        "address": request["address"],
        "message": message,
        "timeout_seconds": float(timeout),
        "maximum_packet_bytes": maximum,
    }


def _osc_string_packet(address: str, message: str) -> bytes:
    def padded(value: str) -> bytes:
        data = value.encode("utf-8") + b"\0"
        return data + (b"\0" * ((4 - len(data) % 4) % 4))

    packet = padded(address) + padded(",s") + padded(message)
    if len(packet) % struct.calcsize("!I") != 0:
        raise ContractError("conformance_failed", "OSC fixture packet is not word-aligned")
    return packet


def _list_of_objects(value: Any, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ContractError("conformance_failed", f"{label} is not a list of objects")
    return cast(list[Mapping[str, Any]], value)


def _frozen_schema_root() -> Any:
    packaged = files("qste") / "contracts/profiles/adapters/ecosystem/0.1/frozen-schemas"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[3] / "profiles/adapters/ecosystem/0.1/frozen-schemas"


def _payload(payload_type: str, data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "payload_type": payload_type,
        "schema_id": f"qste-payload/0.3.0/{payload_type}",
        "data": dict(data),
    }
