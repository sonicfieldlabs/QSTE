"""Bounded supervised/captured P9 representation adapter service."""

from __future__ import annotations

import io
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn, cast

import numpy as np

from qste.adapters.contracts import (
    ADAPTER_PROFILE,
    CAPTURE_PROFILE,
    IMPLEMENTED_CAPTURE_OPERATIONS,
    OPERATIONS,
    AdapterTarget,
    capability_map,
    target_for,
)
from qste.adapters.models import AdapterOutcome
from qste.core import canonical_json_bytes, content_digest, loads_json, utc_timestamp
from qste.core.contracts import BASE_URI, ContractError
from qste.ingress.records import bind_semantic_key, operation_receipt, record_base, record_ref
from qste.storage import ArtifactStore, DenseStore, RecordStore, WorkspacePaths

MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_NATIVE_ELEMENTS = 65_536
MAX_CANDIDATES = 256
MAX_DECODED_ELEMENTS = 480_000
MAX_PROBE_FILE_BYTES = 512 * 1024 * 1024


class ExternalRepresentationService:
    """Expose P9 adapters without hiding execution, license, or model boundaries."""

    def __init__(self, workspace: Path) -> None:
        self.paths = WorkspacePaths.open(workspace)
        self.store = RecordStore(self.paths)
        self.artifacts = ArtifactStore(self.paths)
        self.dense = DenseStore(self.paths, self.store)

    def probe(
        self,
        *,
        adapter_id: str,
        context_record_id: str,
        specification: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> AdapterOutcome:
        """Inspect only explicitly supplied local paths; never launch an external tool."""

        target = target_for(adapter_id)
        context = self.store.get_record(context_record_id).record
        self._authorize(authorization_status, "adapter_probe", context)
        try:
            probe = _probe_paths(target, specification)
        except ContractError as error:
            self._fail("adapter_probe", context, error.reason_code, str(error))
        account = _payload(
            "CapabilityAccount",
            data={
                "adapter_profile": ADAPTER_PROFILE,
                "adapter_id": adapter_id,
                "target_id": target.target_id,
                "execution_mode": target.execution_mode,
                "operation_capabilities": capability_map(),
                "external_execution": probe["external_execution"],
                "probe": probe,
                "network_access": False,
                "subprocess_invoked": False,
                "model_loaded": False,
                "playback": False,
                "scientific_evidence": "not_produced",
            },
        )
        return self._receipt_outcome(
            target,
            operation="adapter_probe",
            request=context,
            parameters={"adapter_id": adapter_id, "probe": probe},
            value=account,
            value_type="qste-payload/0.3.0/CapabilityAccount",
            event_type="qste:adapter-probed/0.1",
            event_payload={
                "adapter_id": adapter_id,
                "external_execution": probe["external_execution"],
            },
        )

    def encode_capture(
        self,
        *,
        adapter_id: str,
        artifact_record_id: str,
        aperture_record_id: str,
        capture: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> AdapterOutcome:
        """Import one bounded supervised or synthetic capture as a native instance."""

        target = target_for(adapter_id)
        artifact = self._record(artifact_record_id, "ArtifactRecord")
        aperture = self._record(aperture_record_id, "ApertureSpec")
        self._authorize(authorization_status, "encode", artifact)
        try:
            self._require_aperture(aperture, artifact_record_id)
            normalized = _validate_capture(target, capture, artifact)
        except ContractError as error:
            self._fail("encode", artifact, error.reason_code, str(error))
        timestamp = utc_timestamp()
        capture_bytes = canonical_json_bytes(normalized)
        capture_object = self.artifacts.put_bytes(capture_bytes)
        native_values = np.asarray(normalized["native_values"], dtype=np.float64)
        dense_id = f"p9-{adapter_id}-{uuid.uuid4().hex}"
        dense_object = self.dense.write_array(
            dense_id,
            native_values,
            chunks=(min(64, native_values.shape[0]), native_values.shape[1]),
            dimension_names=("native_item", "native_component"),
            coordinates={
                "native_item": np.arange(native_values.shape[0], dtype=np.int64),
                "native_component": np.arange(native_values.shape[1], dtype=np.int64),
            },
            created_at=timestamp,
        )
        dense_manifest_object = self.artifacts.put_bytes(
            canonical_json_bytes(dense_object.manifest)
        )
        for object_, media_type in (
            (capture_object, "application/vnd.qste.external-representation-capture+json"),
            (dense_manifest_object, "application/vnd.qste.dense-manifest+json"),
        ):
            self.store.register_artifact(
                object_.content_digest,
                object_.size,
                object_.relative_path,
                media_type=media_type,
                registered_at=timestamp,
            )

        receipt_id = cast(str, record_base("OperationReceipt", created_at=timestamp)["record_id"])
        instance_id = cast(
            str, record_base("RepresentationInstance", created_at=timestamp)["record_id"]
        )
        family_id = cast(
            str, record_base("RepresentationFamilySpec", created_at=timestamp)["record_id"]
        )
        spec = self._representation_spec(target, normalized, timestamp)
        mapping = self._instance_mapping(target, spec, normalized, timestamp)
        intervention = self._intervention_spec(target, normalized, timestamp)
        capture_record = record_base(
            "ArtifactRecord",
            created_at=timestamp,
            references=[record_ref(artifact_record_id, "ArtifactRecord", "derived_from")],
        ) | {
            "media_type": "application/vnd.qste.external-representation-capture+json",
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": capture_object.content_digest,
            "qste:adapterProfile": ADAPTER_PROFILE,
            "qste:captureProfile": CAPTURE_PROFILE,
            "qste:adapterId": target.adapter_id,
            "qste:executionMode": normalized["execution_mode"],
            "qste:evidenceClass": normalized["evidence_class"],
            "qste:opaqueBoundary": normalized["opaque_boundary"],
            "qste:networkAccess": False,
            "qste:modelExecutedByQste": False,
        }
        bind_semantic_key(
            capture_record,
            "qste-semantic-key/external-representation-capture-v1",
            {
                "adapter_id": target.adapter_id,
                "source_content_digest": artifact["content_digest"],
                "capture_digest": capture_object.content_digest,
                "execution_mode": normalized["execution_mode"],
            },
        )
        dense_record = record_base(
            "ArtifactRecord",
            created_at=timestamp,
            references=[record_ref(capture_record["record_id"], "ArtifactRecord")],
        ) | {
            "media_type": "application/vnd.qste.dense-manifest+json",
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": dense_manifest_object.content_digest,
            "qste:adapterProfile": ADAPTER_PROFILE,
            "qste:adapterId": target.adapter_id,
            "qste:representationArtifactRole": "captured_native_values",
            "qste:denseId": dense_id,
            "qste:denseManifestDigest": dense_object.manifest_digest,
            "qste:denseShape": list(native_values.shape),
        }
        bind_semantic_key(
            dense_record,
            "qste-semantic-key/external-native-dense-artifact-v1",
            {
                "adapter_id": target.adapter_id,
                "dense_manifest_digest": dense_object.manifest_digest,
                "capture_digest": capture_object.content_digest,
            },
        )
        instance = record_base(
            "RepresentationInstance", created_at=timestamp, record_id=instance_id
        ) | {
            "source_artifact_ref": record_ref(artifact_record_id, "ArtifactRecord"),
            "representation_spec_ref": record_ref(spec["record_id"], "RepresentationSpec"),
            "execution_receipt_ref": record_ref(receipt_id, "OperationReceipt"),
            "dense_data_ref": record_ref(dense_record["record_id"], "ArtifactRecord"),
            "instance_context": {
                "aperture_ref": record_ref(aperture_record_id, "ApertureSpec"),
                "capture_ref": record_ref(capture_record["record_id"], "ArtifactRecord"),
                "source_sample_rate_hz": normalized["source"]["sample_rate_hz"],
                "representation_sample_rate_hz": normalized["resampling"]["target_hz"],
                "resampling": normalized["resampling"],
                "channel_count": normalized["source"]["channel_count"],
            },
            "qste:adapterProfile": ADAPTER_PROFILE,
            "qste:captureProfile": CAPTURE_PROFILE,
            "qste:adapterId": target.adapter_id,
            "qste:targetId": target.target_id,
            "qste:captureRef": record_ref(capture_record["record_id"], "ArtifactRecord"),
            "qste:familyRef": record_ref(family_id, "RepresentationFamilySpec"),
            "qste:defaultInterventionRef": record_ref(
                intervention["record_id"], "InterventionSpec"
            ),
            "qste:candidateCatalog": normalized["candidates"],
            "qste:refinementCapability": normalized["refinement"],
            "qste:opaqueBoundary": normalized["opaque_boundary"],
            "qste:dsqCapability": "candidate_only_without_closed_refinement_graph",
            "qste:externalExecutionStatus": normalized["execution_status"],
            "qste:modelExecutedByQste": False,
            "qste:heardOutput": "not_produced",
        }
        bind_semantic_key(
            instance,
            "qste-semantic-key/external-representation-instance-v1",
            {
                "adapter_id": target.adapter_id,
                "target_id": target.target_id,
                "source_content_digest": artifact["content_digest"],
                "representation_spec_semantic_key": spec["semantic_key"],
                "configuration": normalized["configuration"],
                "resampling": normalized["resampling"],
                "native_values": normalized["native_values"],
            },
        )
        family = record_base(
            "RepresentationFamilySpec", created_at=timestamp, record_id=family_id
        ) | {
            "family_id": f"qste-representation-family/{target.adapter_id}",
            "family_version": "v0.1",
            "spec_refs": [record_ref(spec["record_id"], "RepresentationSpec")],
            "instance_refs": [record_ref(instance_id, "RepresentationInstance")],
            "mapping_refs": [record_ref(mapping["record_id"], "MappingSpec")],
            "permitted_refinements": [normalized["refinement"]],
            "qste:adapterProfile": ADAPTER_PROFILE,
            "qste:adapterId": target.adapter_id,
            "qste:knownIncomparabilities": [
                "native units and metrics do not become a cross-arm common scale",
                "block size, frame size, token position, or codebook depth alone is not refinement",
            ],
        }
        bind_semantic_key(
            family,
            "qste-semantic-key/external-representation-family-v1",
            {
                "adapter_id": target.adapter_id,
                "spec": spec["semantic_key"],
                "instance": instance["semantic_key"],
                "refinement": normalized["refinement"],
            },
        )
        boundary = record_base(
            "ClaimRecord",
            created_at=timestamp,
            references=[
                record_ref(instance_id, "RepresentationInstance"),
                record_ref(capture_record["record_id"], "ArtifactRecord"),
            ],
        ) | {
            "proposition": (
                "The adapter exposes only the declared captured fields; "
                "hidden external state remains opaque."
            ),
            "evidence_basis": "instrumentally_derived",
            "epistemic_status": "derived",
            "scope": {
                "adapter_id": target.adapter_id,
                "execution_mode": normalized["execution_mode"],
                "scientific_result": False,
            },
            "subject_ref": record_ref(instance_id, "RepresentationInstance"),
            "evidence_refs": [record_ref(capture_record["record_id"], "ArtifactRecord")],
            "qste:adapterProfile": ADAPTER_PROFILE,
            "qste:adapterId": target.adapter_id,
            "qste:opaqueBoundary": normalized["opaque_boundary"],
        }
        bind_semantic_key(
            boundary,
            "qste-semantic-key/opaque-boundary-claim-v1",
            {
                "instance_semantic_key": instance["semantic_key"],
                "opaque_boundary": normalized["opaque_boundary"],
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            record_id=receipt_id,
            request_ref=record_ref(aperture_record_id, "ApertureSpec"),
            authorization_status="permitted",
            operation="encode",
            inputs=[
                record_ref(artifact_record_id, "ArtifactRecord"),
                record_ref(aperture_record_id, "ApertureSpec"),
            ],
            parameters={
                "adapter_id": target.adapter_id,
                "target_id": target.target_id,
                "execution_mode": normalized["execution_mode"],
                "capture_digest": capture_object.content_digest,
                "subprocess_invoked": False,
            },
            outputs=[
                record_ref(instance_id, "RepresentationInstance"),
                record_ref(capture_record["record_id"], "ArtifactRecord"),
                record_ref(dense_record["record_id"], "ArtifactRecord"),
                record_ref(boundary["record_id"], "ClaimRecord"),
            ],
            tool_id=f"qste-{target.adapter_id}-capture-adapter",
            tool_version="v0.1",
        )
        records = [
            spec,
            mapping,
            intervention,
            capture_record,
            dense_record,
            instance,
            family,
            boundary,
            receipt,
        ]
        _, event = self.store.insert_records_with_event(
            records,
            domain_event_record_id=None,
            event_type="qste:external-representation-captured/0.1",
            subject_record_id=instance_id,
            receipt_record_id=receipt_id,
            payload={
                "adapter_id": target.adapter_id,
                "execution_mode": normalized["execution_mode"],
                "candidate_only": True,
                "scientific_evidence": "not_produced",
            },
            created_at=timestamp,
        )
        return AdapterOutcome(
            self.store.get_record(instance_id).record,
            f"{BASE_URI}/records/representation-instance.schema.json",
            receipt,
            event.event_sequence,
            target.adapter_id,
        )

    def enumerate(
        self,
        *,
        instance_record_id: str,
        candidate_rule: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> AdapterOutcome:
        """Materialize only candidates explicitly present in the capture catalog."""

        instance, target = self._instance(instance_record_id)
        self._authorize(authorization_status, "enumerate", instance)
        try:
            if set(candidate_rule) != {"selection", "maximum_candidates"}:
                raise ContractError("invalid_input", "external candidate rule fields are not exact")
            if candidate_rule["selection"] != "all_captured":
                raise ContractError(
                    "capability_unavailable", "only captured candidate enumeration exists"
                )
            maximum = candidate_rule["maximum_candidates"]
            if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
                raise ContractError("invalid_input", "candidate maximum must be a positive integer")
        except ContractError as error:
            self._fail("enumerate", instance, error.reason_code, str(error))
        catalog = cast(list[Mapping[str, Any]], instance["qste:candidateCatalog"])
        if len(catalog) > min(maximum, MAX_CANDIDATES):
            self._fail(
                "enumerate",
                instance,
                "capability_unavailable",
                "captured candidate catalog exceeds the requested bound",
            )
        timestamp = utc_timestamp()
        rule = f"qste-candidate-rule/{target.adapter_id}-captured-v0.1"
        candidates: list[dict[str, Any]] = []
        for index, item in enumerate(catalog):
            candidate = record_base(
                "CandidateUnit",
                created_at=timestamp,
                references=[record_ref(instance_record_id, "RepresentationInstance")],
            ) | {
                "representation_instance_ref": record_ref(
                    instance_record_id, "RepresentationInstance"
                ),
                "native_address": dict(cast(Mapping[str, Any], item["native_address"])),
                "candidate_rule_version": rule,
                "native_support": dict(cast(Mapping[str, Any], item["native_support"])),
                "qste:adapterProfile": ADAPTER_PROFILE,
                "qste:adapterId": target.adapter_id,
                "qste:captureCandidateIndex": index,
                "qste:addressable": item["addressable"],
                "qste:refinementEligibility": (
                    "unavailable_without_verified_mapping_and_intervention"
                ),
                "qste:candidateOnly": True,
            }
            bind_semantic_key(
                candidate,
                "qste-semantic-key/external-candidate-v1",
                {
                    "representation_instance_semantic_key": instance["semantic_key"],
                    "native_address": candidate["native_address"],
                    "candidate_rule_version": rule,
                },
            )
            candidates.append(candidate)
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(instance_record_id, "RepresentationInstance"),
            authorization_status="permitted",
            operation="enumerate",
            inputs=[record_ref(instance_record_id, "RepresentationInstance")],
            parameters=dict(candidate_rule),
            outputs=[record_ref(value["record_id"], "CandidateUnit") for value in candidates],
            tool_id=f"qste-{target.adapter_id}-capture-adapter",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [*candidates, receipt],
            domain_event_record_id=None,
            event_type="qste:external-candidates-enumerated/0.1",
            subject_record_id=instance_record_id,
            receipt_record_id=receipt["record_id"],
            payload={"adapter_id": target.adapter_id, "candidate_count": len(candidates)},
            created_at=timestamp,
        )
        return AdapterOutcome(
            _payload(
                "CandidateSet",
                items=candidates,
                data={
                    "adapter_id": target.adapter_id,
                    "candidate_only": True,
                    "refinement_status": "unavailable",
                },
            ),
            "qste-payload/0.3.0/CandidateSet",
            receipt,
            event.event_sequence,
            target.adapter_id,
        )

    def operate(
        self,
        *,
        operation: str,
        target_record_ids: Sequence[str],
        specification: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> AdapterOutcome:
        """Execute or explicitly decline one remaining REP-01 operation."""

        if operation not in OPERATIONS:
            raise ContractError("invalid_input", "adapter operation is not canonical")
        if operation in {"encode", "enumerate"}:
            raise ContractError("invalid_input", "use the typed encode or enumerate route")
        if not target_record_ids:
            raise ContractError("invalid_input", "adapter operation requires a target")
        request = self.store.get_record(target_record_ids[0]).record
        target = self._target_from_record(request)
        self._authorize(authorization_status, operation, request)
        try:
            if operation not in IMPLEMENTED_CAPTURE_OPERATIONS:
                reason = {
                    "refine": "closed_refinement_mapping_and_intervention_evidence_unavailable",
                    "project": "calibrated_external_projection_unavailable",
                    "measure": "validated_native_metric_execution_unavailable",
                    "perturb": "external_instance_perturbation_unavailable",
                }[operation]
                self._fail(operation, request, "capability_unavailable", reason)
            if operation == "support":
                return self._support(target, request, specification)
            if operation == "address":
                return self._address(target, request, specification)
            if operation == "intervene":
                return self._intervene(target, request, specification)
            if operation == "decode":
                return self._decode(target, request, specification)
            if operation == "account":
                return self._account(target, request, specification)
            raise ContractError("internal_error", "adapter dispatch reached an impossible branch")
        except ContractError as error:
            if hasattr(error, "receipt_id"):
                raise
            self._fail(operation, request, error.reason_code, str(error))

    def _support(
        self, target: AdapterTarget, candidate: Mapping[str, Any], specification: Mapping[str, Any]
    ) -> AdapterOutcome:
        self._require_type(candidate, "CandidateUnit")
        if set(specification) != {"method"} or specification["method"] != "captured_native_support":
            raise ContractError("invalid_input", "support method is not the captured native method")
        value = _payload(
            "SupportEstimate",
            data={
                "adapter_id": target.adapter_id,
                "native_address": candidate["native_address"],
                "native_support": candidate["native_support"],
                "method": "captured_native_support",
                "cross_arm_identity": False,
            },
        )
        return self._receipt_outcome(
            target,
            operation="support",
            request=candidate,
            parameters=specification,
            value=value,
            value_type="qste-payload/0.3.0/SupportEstimate",
            event_type="qste:external-support-estimated/0.1",
        )

    def _address(
        self, target: AdapterTarget, candidate: Mapping[str, Any], specification: Mapping[str, Any]
    ) -> AdapterOutcome:
        self._require_type(candidate, "CandidateUnit")
        if set(specification) != {"intervention_mode"} or specification[
            "intervention_mode"
        ] not in {"mask", "replace"}:
            raise ContractError("invalid_input", "address intervention mode is invalid")
        value = _payload(
            "AddressabilityResult",
            data={
                "adapter_id": target.adapter_id,
                "native_address": candidate["native_address"],
                "addressable": candidate["qste:addressable"],
                "intervention_mode": specification["intervention_mode"],
                "renderer_or_decoder_required": True,
            },
        )
        return self._receipt_outcome(
            target,
            operation="address",
            request=candidate,
            parameters=specification,
            value=value,
            value_type="qste-payload/0.3.0/AddressabilityResult",
            event_type="qste:external-address-checked/0.1",
        )

    def _intervene(
        self, target: AdapterTarget, candidate: Mapping[str, Any], specification: Mapping[str, Any]
    ) -> AdapterOutcome:
        self._require_type(candidate, "CandidateUnit")
        if set(specification) != {"mode", "control"}:
            raise ContractError("invalid_input", "external intervention fields are not exact")
        if specification["mode"] not in {"mask", "replace"} or specification["control"] not in {
            "zero_native_value",
            "captured_reference_value",
        }:
            raise ContractError("invalid_input", "external intervention is not supported")
        if candidate["qste:addressable"] is not True:
            self._fail(
                "intervene",
                candidate,
                "capability_unavailable",
                "candidate capture is not independently addressable",
            )
        payload_data = {
            "profile": "qste-captured-native-intervention/0.1",
            "adapter_id": target.adapter_id,
            "candidate_record_id": candidate["record_id"],
            "native_address": candidate["native_address"],
            "mode": specification["mode"],
            "control": specification["control"],
            "external_renderer_invoked": False,
            "playback": False,
            "scientific_effect": "not_measured",
        }
        data = canonical_json_bytes(payload_data)
        object_ = self.artifacts.put_bytes(data)
        timestamp = utc_timestamp()
        self.store.register_artifact(
            object_.content_digest,
            object_.size,
            object_.relative_path,
            media_type="application/vnd.qste.captured-native-intervention+json",
            registered_at=timestamp,
        )
        artifact = record_base(
            "ArtifactRecord",
            created_at=timestamp,
            references=[record_ref(candidate["record_id"], "CandidateUnit", "derived_from")],
        ) | {
            "media_type": "application/vnd.qste.captured-native-intervention+json",
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": object_.content_digest,
            "qste:adapterProfile": ADAPTER_PROFILE,
            "qste:adapterId": target.adapter_id,
            "qste:interventionMode": specification["mode"],
            "qste:externalRendererInvoked": False,
            "qste:heardOutput": "not_produced",
        }
        bind_semantic_key(
            artifact,
            "qste-semantic-key/captured-native-intervention-v1",
            {"payload_digest": object_.content_digest, "candidate": candidate["semantic_key"]},
        )
        value = _payload(
            "IntervenedState",
            data={
                **payload_data,
                "artifact_ref": record_ref(artifact["record_id"], "ArtifactRecord"),
            },
        )
        return self._receipt_outcome(
            target,
            operation="intervene",
            request=candidate,
            parameters=specification,
            value=value,
            value_type="qste-payload/0.3.0/IntervenedState",
            event_type="qste:external-intervention-captured/0.1",
            records=[artifact],
            output_refs=[record_ref(artifact["record_id"], "ArtifactRecord")],
            created_at=timestamp,
        )

    def _decode(
        self, target: AdapterTarget, instance: Mapping[str, Any], specification: Mapping[str, Any]
    ) -> AdapterOutcome:
        self._require_type(instance, "RepresentationInstance")
        if set(specification) != {"source"} or specification["source"] != "captured_decoder_output":
            raise ContractError("invalid_input", "decode requires the captured decoder output")
        capture = self._capture(instance)
        waveform = np.asarray(capture["decoded_waveform"], dtype=np.float32)
        buffer = io.BytesIO()
        np.save(buffer, waveform, allow_pickle=False)
        object_ = self.artifacts.put_bytes(buffer.getvalue())
        timestamp = utc_timestamp()
        self.store.register_artifact(
            object_.content_digest,
            object_.size,
            object_.relative_path,
            media_type="application/x-npy",
            registered_at=timestamp,
        )
        artifact = record_base(
            "ArtifactRecord",
            created_at=timestamp,
            references=[
                record_ref(instance["record_id"], "RepresentationInstance", "derived_from")
            ],
        ) | {
            "media_type": "application/x-npy",
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": object_.content_digest,
            "qste:adapterProfile": ADAPTER_PROFILE,
            "qste:adapterId": target.adapter_id,
            "qste:decodedCapture": True,
            "qste:sampleRateHz": capture["resampling"]["target_hz"],
            "qste:frameCount": int(waveform.shape[0]),
            "qste:channelCount": int(waveform.shape[1]),
            "qste:externalDecoderInvoked": False,
            "qste:heardOutput": "not_produced",
            "qste:evidenceClass": capture["evidence_class"],
        }
        bind_semantic_key(
            artifact,
            "qste-semantic-key/external-decoded-capture-v1",
            {
                "instance_semantic_key": instance["semantic_key"],
                "content_digest": object_.content_digest,
                "capture_record_id": instance["qste:captureRef"]["record_id"],
            },
        )
        return self._receipt_outcome(
            target,
            operation="decode",
            request=instance,
            parameters=specification,
            value=artifact,
            value_type=f"{BASE_URI}/records/artifact-record.schema.json",
            event_type="qste:external-decode-captured/0.1",
            records=[artifact],
            output_refs=[record_ref(artifact["record_id"], "ArtifactRecord")],
            created_at=timestamp,
        )

    def _account(
        self, target: AdapterTarget, request: Mapping[str, Any], specification: Mapping[str, Any]
    ) -> AdapterOutcome:
        if specification:
            raise ContractError("invalid_input", "adapter account takes no specification fields")
        value = _payload(
            "CapabilityAccount",
            data={
                "adapter_profile": ADAPTER_PROFILE,
                "adapter_id": target.adapter_id,
                "target_id": target.target_id,
                "operation_capabilities": capability_map(),
                "refinement": "unavailable_without_closed_mapping_and_intervention_evidence",
                "candidate_status": "candidate_only",
                "native_unit": target.native_unit,
                "native_metric": target.native_metric,
                "network_access": False,
                "model_loaded": False,
            },
        )
        return self._receipt_outcome(
            target,
            operation="account",
            request=request,
            parameters={},
            value=value,
            value_type="qste-payload/0.3.0/CapabilityAccount",
            event_type="qste:adapter-capability-accounted/0.1",
        )

    def _representation_spec(
        self, target: AdapterTarget, capture: Mapping[str, Any], timestamp: str
    ) -> dict[str, Any]:
        spec = record_base("RepresentationSpec", created_at=timestamp) | {
            "representation_id": f"qste-representation/{target.adapter_id}-captured-v0.1",
            "algorithm_or_model_digest": target.package_digest,
            "parameters": dict(cast(Mapping[str, Any], capture["configuration"])),
            "native_unit": target.native_unit,
            "metric": {
                "id": target.native_metric,
                "execution_status": "captured_or_unavailable",
                "cross_arm_metric": False,
            },
            "capacity": {
                "maximum_native_elements": MAX_NATIVE_ELEMENTS,
                "maximum_candidates": MAX_CANDIDATES,
                "maximum_decoded_elements": MAX_DECODED_ELEMENTS,
            },
            "renderer_or_decoder": {
                "mode": "captured_output_only",
                "external_invocation": False,
                "playback": False,
            },
            "qste:adapterProfile": ADAPTER_PROFILE,
            "qste:adapterId": target.adapter_id,
            "qste:targetId": target.target_id,
            "qste:implementationRevision": target.implementation_revision,
            "qste:compatibilityManifest": target.compatibility_manifest,
            "qste:operationCapabilities": capability_map(),
            "qste:licenseStatus": target.license_status,
            "qste:checkpointIdentity": (
                {
                    "id": target.checkpoint_id,
                    "revision": target.checkpoint_revision,
                    "content_digest": target.checkpoint_digest,
                    "local_availability": "unavailable",
                }
                if target.checkpoint_id
                else {"availability": "not_applicable"}
            ),
            "qste:opaqueBoundary": capture["opaque_boundary"],
        }
        bind_semantic_key(
            spec,
            "qste-semantic-key/external-representation-spec-v1",
            {
                "adapter_id": target.adapter_id,
                "target_id": target.target_id,
                "algorithm_or_model_digest": target.package_digest,
                "configuration": capture["configuration"],
                "native_unit": target.native_unit,
                "metric": target.native_metric,
            },
        )
        return spec

    def _instance_mapping(
        self,
        target: AdapterTarget,
        spec: Mapping[str, Any],
        capture: Mapping[str, Any],
        timestamp: str,
    ) -> dict[str, Any]:
        mapping = record_base(
            "MappingSpec",
            created_at=timestamp,
            references=[record_ref(spec["record_id"], "RepresentationSpec")],
        ) | {
            "source_domain": {"id": target.target_id, "scope": "captured_configuration"},
            "target_domain": {"id": target.target_id, "scope": "same_instance_native_address"},
            "variables": [{"source": "native_address", "target": "native_address"}],
            "units": {"source": target.native_unit, "target": target.native_unit},
            "normalization": {"method": "none"},
            "uncertainty": {"method": "captured_not_inferred"},
            "missing_data_behavior": "fail",
            "interpolation": {"method": "none"},
            "range": {"source": "captured_catalog", "target": "captured_catalog"},
            "loss": {
                "known": True,
                "description": "mapping does not establish cross-instance identity or refinement",
            },
            "reversibility_claim": "identity_only_within_exact_capture",
            "qste:adapterProfile": ADAPTER_PROFILE,
            "qste:adapterId": target.adapter_id,
            "qste:mappingScope": "same_instance_only",
            "qste:configurationDigest": content_digest(
                canonical_json_bytes(capture["configuration"])
            ),
        }
        bind_semantic_key(
            mapping,
            "qste-semantic-key/external-instance-mapping-v1",
            {
                "adapter_id": target.adapter_id,
                "spec": spec["semantic_key"],
                "configuration": capture["configuration"],
                "scope": "same_instance_only",
            },
        )
        return mapping

    def _intervention_spec(
        self, target: AdapterTarget, capture: Mapping[str, Any], timestamp: str
    ) -> dict[str, Any]:
        intervention = record_base("InterventionSpec", created_at=timestamp) | {
            "operator_family": f"qste-{target.adapter_id}-captured-native-intervention/v0.1",
            "native_operation": {"modes": ["mask", "replace"], "execution": "captured"},
            "reference_distribution": {"mode": "captured_or_zero", "sampling": False},
            "renderer_or_decoder": {
                "mode": "captured_output_only",
                "external_invocation": False,
            },
            "controls": ["zero_native_value", "captured_reference_value"],
            "random_source": {"mode": "not_applicable", "deterministic": True},
            "qste:adapterProfile": ADAPTER_PROFILE,
            "qste:adapterId": target.adapter_id,
            "qste:artifactControls": capture["artifact_controls"],
        }
        bind_semantic_key(
            intervention,
            "qste-semantic-key/external-intervention-spec-v1",
            {
                "adapter_id": target.adapter_id,
                "configuration": capture["configuration"],
                "artifact_controls": capture["artifact_controls"],
            },
        )
        return intervention

    def _capture(self, instance: Mapping[str, Any]) -> dict[str, Any]:
        capture_record = self._record(
            cast(str, instance["qste:captureRef"]["record_id"]), "ArtifactRecord"
        )
        data = self.artifacts.read_bytes(
            cast(str, capture_record["content_digest"]), maximum_bytes=MAX_CAPTURE_BYTES
        )
        value = loads_json(data)
        if not isinstance(value, dict):
            raise ContractError("conformance_failed", "external capture artifact is not an object")
        return cast(dict[str, Any], value)

    def _instance(self, record_id: str) -> tuple[dict[str, Any], AdapterTarget]:
        instance = self._record(record_id, "RepresentationInstance")
        return instance, self._target_from_record(instance)

    def _target_from_record(self, record: Mapping[str, Any]) -> AdapterTarget:
        adapter_id = record.get("qste:adapterId")
        if not isinstance(adapter_id, str):
            if record.get("record_type") == "CandidateUnit":
                instance = self._record(
                    cast(str, record["representation_instance_ref"]["record_id"]),
                    "RepresentationInstance",
                )
                adapter_id = cast(str, instance["qste:adapterId"])
            else:
                raise ContractError("invalid_input", "record is not owned by a P9 adapter")
        return target_for(adapter_id)

    def _receipt_outcome(
        self,
        target: AdapterTarget,
        *,
        operation: str,
        request: Mapping[str, Any],
        parameters: Mapping[str, Any],
        value: dict[str, Any],
        value_type: str,
        event_type: str,
        event_payload: Mapping[str, Any] | None = None,
        records: Sequence[Mapping[str, Any]] = (),
        output_refs: Sequence[Mapping[str, Any]] = (),
        created_at: str | None = None,
    ) -> AdapterOutcome:
        timestamp = created_at or utc_timestamp()
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(request["record_id"], request["record_type"]),
            authorization_status="permitted",
            operation=operation,
            inputs=[record_ref(request["record_id"], request["record_type"])],
            parameters=dict(parameters) or {"mode": "none"},
            outputs=list(output_refs) or [{"payload_type": value.get("payload_type", value_type)}],
            tool_id=f"qste-{target.adapter_id}-capture-adapter",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [*[dict(value) for value in records], receipt],
            domain_event_record_id=None,
            event_type=event_type,
            subject_record_id=cast(str, request["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"adapter_id": target.adapter_id, **dict(event_payload or {})},
            created_at=timestamp,
        )
        return AdapterOutcome(
            value,
            value_type,
            receipt,
            event.event_sequence,
            target.adapter_id,
        )

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
            f"adapter operation authorization is {authorization_status}",
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
        operation_status = "refused" if reason == "policy_refused" else "failed"
        effective_authorization_status = (
            "refused" if reason == "policy_refused" else authorization_status
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(request["record_id"], request["record_type"]),
            authorization_status=effective_authorization_status,
            operation=operation,
            inputs=[record_ref(request["record_id"], request["record_type"])],
            parameters={"reason_code": reason},
            outputs=[{"availability": "not_applicable", "reason": reason}],
            operation_status=operation_status,
            tool_id="qste-p9-external-representation-adapter",
            tool_version="v0.1",
        )
        self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type=(
                "qste:adapter-operation-refused/0.1"
                if reason == "policy_refused"
                else "qste:adapter-operation-failed/0.1"
            ),
            subject_record_id=cast(str, request["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"operation": operation, "reason_code": reason, "derivative_created": False},
            created_at=timestamp,
        )
        error = ContractError(reason, message)
        error.receipt_id = receipt["record_id"]
        error.authorization_status = effective_authorization_status
        raise error

    def _require_aperture(self, aperture: Mapping[str, Any], artifact_record_id: str) -> None:
        if aperture["input_ref"]["record_id"] != artifact_record_id:
            raise ContractError("invalid_input", "aperture input does not match capture source")
        operations = aperture.get("permitted_operations", [])
        if "encode" not in operations:
            raise ContractError("policy_refused", "aperture does not permit representation encode")

    def _record(self, record_id: str, expected_type: str) -> dict[str, Any]:
        record = self.store.get_record(record_id).record
        self._require_type(record, expected_type)
        return record

    @staticmethod
    def _require_type(record: Mapping[str, Any], expected_type: str) -> None:
        if record.get("record_type") != expected_type:
            raise ContractError("invalid_input", f"record is not {expected_type}")


def _validate_capture(
    target: AdapterTarget, capture: Mapping[str, Any], artifact: Mapping[str, Any]
) -> dict[str, Any]:
    required = {
        "profile_id",
        "adapter_id",
        "execution_mode",
        "execution_status",
        "evidence_class",
        "target_id",
        "source",
        "resampling",
        "configuration",
        "native_values",
        "candidates",
        "decoded_waveform",
        "artifact_controls",
        "opaque_boundary",
        "refinement",
    }
    if set(capture) != required:
        raise ContractError("invalid_input", "external capture fields are not exact")
    if capture["profile_id"] != CAPTURE_PROFILE or capture["adapter_id"] != target.adapter_id:
        raise ContractError("invalid_input", "capture profile or adapter identity conflicts")
    if capture["target_id"] != target.target_id:
        raise ContractError("invalid_input", "capture compatibility target conflicts")
    permitted_modes = (
        {"supervised_capture", "synthetic_contract_fixture"}
        if target.adapter_id == "samplebrain"
        else {"external_capture", "synthetic_contract_fixture"}
    )
    if capture["execution_mode"] not in permitted_modes:
        raise ContractError("invalid_input", "capture execution mode is not permitted")
    if capture["execution_status"] != "completed":
        raise ContractError("execution_failed", "external capture did not complete")
    expected_evidence = (
        "synthetic_non_model_fixture"
        if capture["execution_mode"] == "synthetic_contract_fixture"
        else "externally_recorded_capture"
    )
    if capture["evidence_class"] != expected_evidence:
        raise ContractError("invalid_input", "capture evidence class conflicts with execution mode")
    source = _exact_object(
        capture["source"], {"content_digest", "sample_rate_hz", "channel_count"}, "capture source"
    )
    if source["content_digest"] != artifact.get("content_digest"):
        raise ContractError("conformance_failed", "capture source digest does not match artifact")
    sample_rate = _positive_int(source["sample_rate_hz"], "source sample rate")
    channel_count = _positive_int(source["channel_count"], "source channel count")
    resampling = _exact_object(
        capture["resampling"], {"applied", "source_hz", "target_hz", "method"}, "resampling"
    )
    if not isinstance(resampling["applied"], bool):
        raise ContractError("invalid_input", "resampling applied must be boolean")
    source_hz = _positive_int(resampling["source_hz"], "resampling source rate")
    target_hz = _positive_int(resampling["target_hz"], "resampling target rate")
    if source_hz != sample_rate:
        raise ContractError("conformance_failed", "resampling source rate conflicts with source")
    if not isinstance(resampling["method"], str) or not resampling["method"]:
        raise ContractError("invalid_input", "resampling method is required")
    if not resampling["applied"] and (source_hz != target_hz or resampling["method"] != "none"):
        raise ContractError("conformance_failed", "silent resampling declaration conflicts")
    configuration = capture["configuration"]
    if not isinstance(configuration, Mapping) or not configuration:
        raise ContractError("invalid_input", "adapter configuration is required")
    native = _finite_matrix(capture["native_values"], "native values", MAX_NATIVE_ELEMENTS)
    decoded = _finite_matrix(capture["decoded_waveform"], "decoded waveform", MAX_DECODED_ELEMENTS)
    if len(decoded[0]) != channel_count:
        raise ContractError("conformance_failed", "decoded channel count conflicts with source")
    candidates = capture["candidates"]
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_CANDIDATES:
        raise ContractError("invalid_input", "captured candidate catalog is empty or oversized")
    normalized_candidates: list[dict[str, Any]] = []
    for value in candidates:
        candidate = _exact_object(
            value, {"native_address", "native_support", "addressable"}, "capture candidate"
        )
        if not isinstance(candidate["native_address"], Mapping) or not candidate["native_address"]:
            raise ContractError("invalid_input", "candidate native address is required")
        support = _exact_object(
            candidate["native_support"],
            {"time_seconds", "source_frame_range", "method"},
            "candidate native support",
        )
        interval = support["time_seconds"]
        frame_range = support["source_frame_range"]
        if not _ordered_pair(interval, numeric=True) or not _ordered_pair(
            frame_range, numeric=False
        ):
            raise ContractError("invalid_input", "candidate support intervals are invalid")
        if not isinstance(support["method"], str) or not support["method"]:
            raise ContractError("invalid_input", "candidate support method is required")
        if not isinstance(candidate["addressable"], bool):
            raise ContractError("invalid_input", "candidate addressability must be boolean")
        normalized_candidates.append(
            {
                "native_address": dict(candidate["native_address"]),
                "native_support": dict(support),
                "addressable": candidate["addressable"],
            }
        )
    controls = capture["artifact_controls"]
    if not isinstance(controls, Mapping) or not controls:
        raise ContractError("invalid_input", "artifact controls are required")
    opaque = _exact_object(
        capture["opaque_boundary"],
        {"visible_fields", "opaque_fields", "observability"},
        "opaque boundary",
    )
    if not _string_list(opaque["visible_fields"]) or not _string_list(opaque["opaque_fields"]):
        raise ContractError("invalid_input", "opaque boundary field lists are required")
    if opaque["observability"] != "captured_outputs_only":
        raise ContractError("invalid_input", "opaque boundary observability is invalid")
    refinement = _exact_object(
        capture["refinement"], {"status", "reason", "graph_created"}, "refinement"
    )
    if (
        refinement["status"] != "unavailable"
        or refinement["graph_created"] is not False
        or not isinstance(refinement["reason"], str)
        or not refinement["reason"]
    ):
        raise ContractError(
            "conformance_failed", "P9 capture must not invent a closed refinement graph"
        )
    normalized = dict(capture)
    normalized["source"] = {
        "content_digest": source["content_digest"],
        "sample_rate_hz": sample_rate,
        "channel_count": channel_count,
    }
    normalized["resampling"] = {
        "applied": resampling["applied"],
        "source_hz": source_hz,
        "target_hz": target_hz,
        "method": resampling["method"],
    }
    normalized["configuration"] = dict(configuration)
    normalized["native_values"] = native
    normalized["candidates"] = normalized_candidates
    normalized["decoded_waveform"] = decoded
    normalized["artifact_controls"] = dict(controls)
    normalized["opaque_boundary"] = {
        "visible_fields": list(opaque["visible_fields"]),
        "opaque_fields": list(opaque["opaque_fields"]),
        "observability": opaque["observability"],
    }
    normalized["refinement"] = dict(refinement)
    if len(canonical_json_bytes(normalized)) > MAX_CAPTURE_BYTES:
        raise ContractError("invalid_input", "external capture exceeds the byte bound")
    return normalized


def _probe_paths(target: AdapterTarget, specification: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "allowed_roots",
        "executable_path",
        "executable_digest",
        "environment_lock_path",
        "environment_lock_digest",
        "checkpoint_path",
        "checkpoint_digest",
    }
    if not set(specification).issubset(allowed):
        raise ContractError("invalid_input", "adapter probe contains unknown fields")
    roots_value = specification.get("allowed_roots", [])
    if not isinstance(roots_value, list) or not all(
        isinstance(value, str) for value in roots_value
    ):
        raise ContractError("invalid_input", "adapter probe roots must be paths")
    roots = tuple(Path(value).resolve() for value in roots_value)
    checks: dict[str, Any] = {}
    for label, expected_default in (
        ("executable", None),
        ("environment_lock", None),
        ("checkpoint", target.checkpoint_digest),
    ):
        raw_path = specification.get(f"{label}_path")
        expected = specification.get(f"{label}_digest", expected_default)
        if raw_path is None:
            checks[label] = {"status": "unavailable", "reason": f"{label}_not_supplied"}
            continue
        if not isinstance(raw_path, str) or not isinstance(expected, str):
            raise ContractError("invalid_input", f"{label} path and digest must be explicit")
        path = Path(raw_path).resolve()
        if not roots or not any(path == root or root in path.parents for root in roots):
            raise ContractError("policy_refused", f"{label} path is outside allowed roots")
        if not path.is_file() or path.is_symlink():
            checks[label] = {"status": "unavailable", "reason": f"{label}_absent"}
            continue
        if path.stat().st_size > MAX_PROBE_FILE_BYTES:
            raise ContractError("resource_limit", f"{label} exceeds the probe byte bound")
        actual = content_digest(path.read_bytes())
        checks[label] = {
            "status": "available" if actual == expected else "failed",
            "content_digest": actual,
            "expected_digest": expected,
        }
    executable_ok = checks["executable"]["status"] == "available"
    checkpoint_ok = checks["checkpoint"]["status"] == "available"
    environment_ok = checks["environment_lock"]["status"] == "available"
    if target.adapter_id == "samplebrain":
        external = "available" if executable_ok else "unavailable"
    else:
        external = (
            "available"
            if environment_ok and checkpoint_ok and target.license_status.startswith("verified_")
            else "unavailable"
        )
    return {
        "external_execution": external,
        "checks": checks,
        "license_status": target.license_status,
        "checkpoint_downloaded": False,
    }


def _exact_object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ContractError("invalid_input", f"{label} fields are not exact")
    return dict(value)


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ContractError("invalid_input", f"{label} must be a positive integer")
    return value


def _finite_matrix(value: Any, label: str, maximum_elements: int) -> list[list[float]]:
    if not isinstance(value, list) or not value or not all(isinstance(row, list) for row in value):
        raise ContractError("invalid_input", f"{label} must be a nonempty matrix")
    widths = {len(row) for row in value}
    if len(widths) != 1 or not widths or next(iter(widths)) < 1:
        raise ContractError("invalid_input", f"{label} must be rectangular and nonempty")
    if len(value) * next(iter(widths)) > maximum_elements:
        raise ContractError("invalid_input", f"{label} exceeds its element bound")
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or not np.isfinite(array).all():
        raise ContractError("invalid_input", f"{label} must contain finite numbers")
    return cast(list[list[float]], array.tolist())


def _ordered_pair(value: Any, *, numeric: bool) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    if numeric:
        return all(
            isinstance(item, (int, float)) and not isinstance(item, bool) for item in value
        ) and (float(value[0]) <= float(value[1]))
    return all(isinstance(item, int) and not isinstance(item, bool) for item in value) and (
        int(value[0]) <= int(value[1])
    )


def _string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item) for item in value)
    )


def _payload(
    payload_type: str,
    *,
    items: Sequence[Mapping[str, Any]] = (),
    data: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "payload_type": payload_type,
        "items": [dict(item) for item in items],
        "data": dict(data),
    }
