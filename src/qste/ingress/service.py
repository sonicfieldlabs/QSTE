"""Bounded P4 ingress plus apparatus and aperture derivation services."""

from __future__ import annotations

import csv
import io
import math
import mimetypes
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

import numpy as np

from qste.core import canonical_json_bytes, content_digest, loads_json, utc_timestamp
from qste.core.contracts import ContractError
from qste.core.p4_contracts import (
    APERTURE_PROFILE,
    APPARATUS_PROFILE,
    INGRESS_PROFILE,
    RUN_PROFILE,
    validate_apparatus_declaration,
)
from qste.ingress.models import (
    ApertureOutcome,
    ApparatusOutcome,
    AudioTransform,
    IngressLimits,
    IngressOutcome,
)
from qste.ingress.records import bind_semantic_key, operation_receipt, record_base, record_ref
from qste.storage import ArtifactStore, RecordStore, WorkspacePaths


class IngressService:
    """Import one explicitly typed local source under hard resource and path bounds."""

    def __init__(self, workspace: Path, limits: IngressLimits) -> None:
        self.store = RecordStore.initialize(workspace)
        self.artifacts = ArtifactStore(self.store.paths)
        self.limits = limits

    def ingest(
        self,
        path: Path,
        *,
        kind: str,
        apparatus_record_id: str,
        attributed_origin: str,
        rights: Mapping[str, Any],
        retention: Mapping[str, Any],
        authorization_status: str,
        audio_transform: AudioTransform | None = None,
    ) -> IngressOutcome:
        """Import without mutating or executing the source; persist failure receipts."""

        apparatus = self._apparatus(apparatus_record_id)
        timestamp = utc_timestamp()
        try:
            if authorization_status != "permitted":
                raise ContractError("policy_refused", "ingress requires explicit permission")
            data, portable_locator = self._bounded_read(path, kind)
            self._validate_rights(rights, retention)
            outcome = self._prepare(
                data,
                portable_locator=portable_locator,
                source_name=path.name,
                kind=kind,
                apparatus=apparatus,
                attributed_origin=attributed_origin,
                rights=rights,
                retention=retention,
                authorization_status=authorization_status,
                timestamp=timestamp,
                audio_transform=audio_transform,
            )
            return outcome
        except ContractError as error:
            receipt_id = self._record_failed_attempt(
                apparatus,
                timestamp=timestamp,
                kind=kind,
                path=path,
                authorization_status=authorization_status,
                error=error,
            )
            error.receipt_id = receipt_id  # type: ignore[attr-defined]
            raise

    def _prepare(
        self,
        data: bytes,
        *,
        portable_locator: str,
        source_name: str,
        kind: str,
        apparatus: dict[str, Any],
        attributed_origin: str,
        rights: Mapping[str, Any],
        retention: Mapping[str, Any],
        authorization_status: str,
        timestamp: str,
        audio_transform: AudioTransform | None,
    ) -> IngressOutcome:
        media_kinds = cast(list[str], apparatus["acquisition_surface"]["media_kinds"])
        if kind not in media_kinds:
            raise ContractError(
                "capability_unavailable", "apparatus does not admit this ingress kind"
            )

        source = self._source_record(
            data,
            kind=kind,
            locator=portable_locator,
            attributed_origin=attributed_origin,
            rights=rights,
            retention=retention,
            timestamp=timestamp,
        )
        parsed, derivative_bytes, derivative_type, derivative_role, acquisition_meta = self._decode(
            data, kind=kind, apparatus=apparatus, transform=audio_transform
        )
        original_object = self.artifacts.put_bytes(data)
        original_media_type = _media_type(kind, source_name)
        self.store.register_artifact(
            original_object.content_digest,
            original_object.size,
            original_object.relative_path,
            media_type=original_media_type,
            registered_at=timestamp,
        )
        original = self._artifact_record(
            original_object.content_digest,
            original_object.size,
            original_media_type,
            kind=kind,
            role="imported_original",
            timestamp=timestamp,
            references=[record_ref(source["record_id"], "SourceRecord", "acquired_from")],
        )

        derivative_records: list[dict[str, Any]] = []
        if derivative_bytes is None:
            result = original
        else:
            derivative_object = self.artifacts.put_bytes(derivative_bytes)
            self.store.register_artifact(
                derivative_object.content_digest,
                derivative_object.size,
                derivative_object.relative_path,
                media_type=derivative_type,
                registered_at=timestamp,
            )
            result = self._artifact_record(
                derivative_object.content_digest,
                derivative_object.size,
                derivative_type,
                kind=kind,
                role=derivative_role,
                timestamp=timestamp,
                references=[record_ref(original["record_id"], "ArtifactRecord", "derived_from")],
                extra=acquisition_meta,
            )
            derivative_records.append(result)

        receipt_id = cast(str, record_base("OperationReceipt", created_at=timestamp)["record_id"])
        acquisition = self._acquisition_record(
            apparatus,
            source,
            result,
            receipt_id=receipt_id,
            original_artifact_id=original["record_id"],
            kind=kind,
            timestamp=timestamp,
            authorization_status=authorization_status,
            acquisition_meta=acquisition_meta,
        )
        result["qste:acquisitionRef"] = record_ref(
            acquisition["record_id"], "AcquisitionEvent", "produced_by"
        )
        bind_semantic_key(
            result,
            "qste-semantic-key/artifact-occurrence-p4-v1",
            {
                "content_digest": result["content_digest"],
                "role": result["qste:artifactRole"],
                "acquisition": acquisition["record_id"],
            },
        )
        observations = self._observations(
            parsed,
            kind=kind,
            acquisition=acquisition,
            external_authority={
                "locator": portable_locator,
                "content_digest": source["content_digest"],
            },
            timestamp=timestamp,
            acquisition_meta=acquisition_meta,
        )
        output_refs = [
            record_ref(acquisition["record_id"], "AcquisitionEvent", "produced_by"),
            record_ref(result["record_id"], "ArtifactRecord", "produced_by"),
            *[
                record_ref(record["record_id"], "ObservationRecord", "produced_by")
                for record in observations
            ],
        ]
        receipt = operation_receipt(
            created_at=timestamp,
            record_id=receipt_id,
            request_ref=record_ref(source["record_id"], "SourceRecord"),
            authorization_status=authorization_status,
            operation="ingest",
            inputs=[
                record_ref(source["record_id"], "SourceRecord"),
                record_ref(apparatus["record_id"], "ApparatusSpec"),
            ],
            parameters={
                "ingress_kind": kind,
                "limit_bytes": self.limits.byte_limit(kind),
                "audio_transform": _transform_value(audio_transform),
            },
            outputs=output_refs,
        )
        records = [source, original, *derivative_records, acquisition, *observations, receipt]
        _, event = self.store.insert_records_with_event(
            records,
            domain_event_record_id=acquisition["record_id"],
            event_type="qste:ingress-completed/0.1",
            subject_record_id=acquisition["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={
                "ingress_kind": kind,
                "source_digest": source["content_digest"],
                "result_digest": result["content_digest"],
                "original_preserved": True,
            },
            created_at=timestamp,
        )
        stored_acquisition = self.store.get_record(acquisition["record_id"]).record
        return IngressOutcome(
            source_record=source,
            acquisition_record=stored_acquisition,
            original_artifact_record=original,
            result_artifact_record=result,
            derivative_artifact_records=tuple(derivative_records),
            observation_records=tuple(observations),
            receipt_record=receipt,
            event_sequence=event.event_sequence,
        )

    def _bounded_read(self, path: Path, kind: str) -> tuple[bytes, str]:
        limit = self.limits.byte_limit(kind)
        candidate = path.expanduser()
        if candidate.is_symlink() or not candidate.is_file():
            raise ContractError("invalid_input", "ingress path is absent, non-file, or a symlink")
        resolved = candidate.resolve(strict=True)
        allowed_entry = next(
            (
                root
                for root in self.limits.allowed_roots
                if _is_relative_to(resolved, root.resolve(strict=True))
            ),
            None,
        )
        if allowed_entry is None:
            raise ContractError("policy_refused", "ingress path is outside the allowed roots")
        _reject_symlink_components(candidate, allowed_entry)
        before = resolved.stat()
        if before.st_size > limit:
            raise ContractError("invalid_input", f"ingress source exceeds {limit} bytes")
        with resolved.open("rb") as handle:
            data = handle.read(limit + 1)
        after = resolved.stat()
        if len(data) > limit:
            raise ContractError("invalid_input", f"ingress source exceeds {limit} bytes")
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if identity_before != identity_after or len(data) != before.st_size:
            raise ContractError("execution_failed", "ingress source changed during bounded read")
        return data, f"qste://local-ingress/{content_digest(data).removeprefix('sha256:')}"

    def _decode(
        self,
        data: bytes,
        *,
        kind: str,
        apparatus: dict[str, Any],
        transform: AudioTransform | None,
    ) -> tuple[Any, bytes | None, str, str, dict[str, Any]]:
        available = cast(list[str], apparatus["computation_surface"]["preprocessing_operations"])
        if kind == "audio":
            chosen = transform or AudioTransform()
            required = {"decode"}
            if chosen.target_sample_rate_hz is not None:
                required.add("resample")
            if chosen.normalization != "none":
                required.add("normalize")
            numeric_dtypes = cast(list[str], apparatus["computation_surface"]["numeric_dtypes"])
            if chosen.output_dtype not in numeric_dtypes:
                raise ContractError(
                    "capability_unavailable", "output dtype exceeds apparatus computation surface"
                )
            if not required.issubset(available):
                raise ContractError(
                    "capability_unavailable",
                    "audio transform exceeds apparatus computation surface",
                )
            return _decode_audio(data, apparatus, chosen)
        if transform is not None:
            raise ContractError("invalid_input", "audio transforms apply only to audio ingress")
        if kind in {"json_observations", "model_observations"}:
            if "parse_observations" not in available:
                raise ContractError(
                    "capability_unavailable",
                    "apparatus cannot parse numerical observations",
                )
            value = loads_json(data)
            parsed = _parse_json_observations(value, kind, self.limits.maximum_observations)
            canonical = canonical_json_bytes(value)
            return (
                parsed,
                canonical,
                "application/json",
                "decoded_derivative",
                {
                    "qste:timebaseKind": "atemporal",
                    "qste:channelCount": 1,
                },
            )
        if kind == "csv_observations":
            if "parse_observations" not in available:
                raise ContractError(
                    "capability_unavailable",
                    "apparatus cannot parse numerical observations",
                )
            parsed = _parse_csv_observations(data, self.limits)
            canonical = canonical_json_bytes({"observations": parsed})
            return (
                parsed,
                canonical,
                "application/json",
                "decoded_derivative",
                {
                    "qste:timebaseKind": "atemporal",
                    "qste:channelCount": 1,
                },
            )
        if kind == "text":
            try:
                data.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise ContractError("invalid_input", "text ingress must be strict UTF-8") from error
            return (
                None,
                None,
                "text/plain; charset=utf-8",
                "imported_original",
                {
                    "qste:timebaseKind": "atemporal",
                    "qste:channelCount": 1,
                    "qste:dataOnly": True,
                },
            )
        raise ContractError("invalid_input", f"unknown P4 ingress kind: {kind}")

    def _source_record(
        self,
        data: bytes,
        *,
        kind: str,
        locator: str,
        attributed_origin: str,
        rights: Mapping[str, Any],
        retention: Mapping[str, Any],
        timestamp: str,
    ) -> dict[str, Any]:
        if not attributed_origin:
            raise ContractError("invalid_input", "attributed origin is required")
        record = record_base("SourceRecord", created_at=timestamp) | {
            "attributed_origin": attributed_origin,
            "source_availability": "known",
            "rights": dict(rights),
            "locator": locator,
            "content_digest": content_digest(data),
            "qste:ingressProfile": INGRESS_PROFILE,
            "qste:ingressKind": kind,
            "qste:retention": dict(retention),
            "qste:dataOnly": True,
            "qste:sourceBytes": len(data),
        }
        bind_semantic_key(
            record,
            "qste-semantic-key/source-content-p4-v1",
            {"content_digest": record["content_digest"], "origin": attributed_origin},
        )
        return record

    def _artifact_record(
        self,
        digest: str,
        size: int,
        media_type: str,
        *,
        kind: str,
        role: str,
        timestamp: str,
        references: Sequence[Mapping[str, Any]],
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = record_base("ArtifactRecord", created_at=timestamp, references=references) | {
            "media_type": media_type,
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": digest,
            "qste:ingressProfile": INGRESS_PROFILE,
            "qste:ingressKind": kind,
            "qste:artifactRole": role,
            "qste:sizeBytes": size,
            **dict(extra or {}),
        }
        bind_semantic_key(
            record,
            "qste-semantic-key/artifact-content-role-p4-v1",
            {"content_digest": digest, "role": role},
        )
        return record

    def _acquisition_record(
        self,
        apparatus: dict[str, Any],
        source: dict[str, Any],
        result: dict[str, Any],
        *,
        receipt_id: str,
        original_artifact_id: str,
        kind: str,
        timestamp: str,
        authorization_status: str,
        acquisition_meta: Mapping[str, Any],
    ) -> dict[str, Any]:
        acquisition_surface = cast(dict[str, Any], apparatus["acquisition_surface"])
        timebase_kind = cast(str, acquisition_meta.get("qste:timebaseKind", "atemporal"))
        channels = cast(int, acquisition_meta.get("qste:channelCount", 1))
        declared_channels = cast(list[dict[str, Any]], acquisition_surface["channel_map"])
        if channels > len(declared_channels):
            raise ContractError("capability_unavailable", "input exceeds apparatus channel surface")
        channel_map = [dict(item) for item in declared_channels[:channels]]
        record = record_base("AcquisitionEvent", created_at=timestamp) | {
            "apparatus_ref": record_ref(apparatus["record_id"], "ApparatusSpec"),
            "provider_or_channel": "bounded_local_file",
            "temporal_state": "atemporal",
            "timebase": timebase_kind,
            "source_ref": record_ref(source["record_id"], "SourceRecord", "acquired_from"),
            "result_ref": record_ref(result["record_id"], "ArtifactRecord", "produced_by"),
            "calibration": acquisition_surface["calibration"],
            "route": {"kind": "local_typed_ingress", "network_access": False},
            "environment": {"execution": "local", "source_execution": False},
            "limits": {
                "maximum_bytes": self.limits.byte_limit(kind),
                "maximum_observations": self.limits.maximum_observations,
            },
            "authorization_status": authorization_status,
            "receipt_ref": record_ref(receipt_id, "OperationReceipt"),
            "lineage_relation": "acquired_from",
            "event_sequence": 1,
            "qste:ingressProfile": INGRESS_PROFILE,
            "qste:ingressKind": kind,
            "qste:timebase": {
                "kind": timebase_kind,
                "sample_rate_hz": acquisition_meta.get("qste:sourceSampleRateHz", "not_applicable"),
            },
            "qste:channelMap": channel_map,
            "qste:originalArtifactRef": record_ref(
                original_artifact_id,
                "ArtifactRecord",
            ),
        }
        bind_semantic_key(
            record,
            "qste-semantic-key/acquisition-event-p4-v1",
            {
                "source": source["content_digest"],
                "apparatus": apparatus["record_id"],
                "result": result["content_digest"],
            },
        )
        return record

    def _observations(
        self,
        parsed: Any,
        *,
        kind: str,
        acquisition: dict[str, Any],
        external_authority: Mapping[str, Any],
        timestamp: str,
        acquisition_meta: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]]
        model_identity: Mapping[str, Any] | None = None
        if kind == "model_observations":
            model_identity = cast(Mapping[str, Any], parsed["model"])
            items = cast(list[dict[str, Any]], parsed["observations"])
        elif kind in {"json_observations", "csv_observations"}:
            items = cast(list[dict[str, Any]], parsed)
        elif kind == "audio":
            items = [
                _observation_value(
                    "source_sample_rate",
                    acquisition_meta["qste:sourceSampleRateHz"],
                    "Hz",
                ),
                _observation_value(
                    "derivative_sample_rate",
                    acquisition_meta["qste:sampleRateHz"],
                    "Hz",
                ),
                _observation_value("frame_count", acquisition_meta["qste:frameCount"], "frames"),
                _observation_value(
                    "channel_count", acquisition_meta["qste:channelCount"], "channels"
                ),
                _observation_value("duration", acquisition_meta["qste:durationSeconds"], "s"),
            ]
        else:
            return []
        records: list[dict[str, Any]] = []
        for item in items:
            evidence = "model_inferred" if model_identity is not None else item["evidence_basis"]
            record = record_base("ObservationRecord", created_at=timestamp) | {
                "variable": item["variable"],
                "observation_state": item["observation_state"],
                "units": item["units"],
                "method": item["method"],
                "evidence_basis": evidence,
                "acquisition_ref": record_ref(
                    acquisition["record_id"], "AcquisitionEvent", "produced_by"
                ),
                "qste:ingressProfile": INGRESS_PROFILE,
                "qste:ingressKind": kind,
                "qste:externalAuthority": dict(external_authority),
            }
            if item["observation_state"] == "value":
                record["value"] = item["value"]
            if "coordinate" in item:
                record["qste:coordinate"] = item["coordinate"]
            if model_identity is not None:
                record["qste:modelIdentity"] = dict(model_identity)
            bind_semantic_key(
                record,
                "qste-semantic-key/observation-occurrence-p4-v1",
                {
                    "acquisition": acquisition["record_id"],
                    "variable": item["variable"],
                    "coordinate": item.get("coordinate", "none"),
                },
            )
            records.append(record)
        return records

    def _apparatus(self, record_id: str) -> dict[str, Any]:
        record = self.store.get_record(record_id).record
        if (
            record.get("record_type") != "ApparatusSpec"
            or record.get("qste:apparatusProfile") != APPARATUS_PROFILE
        ):
            raise ContractError("invalid_input", "P4 ingress requires a P4 ApparatusSpec")
        return record

    @staticmethod
    def _validate_rights(rights: Mapping[str, Any], retention: Mapping[str, Any]) -> None:
        if not isinstance(rights.get("use"), str) or not rights["use"]:
            raise ContractError("invalid_input", "rights.use must be explicit")
        if rights.get("redistribution") not in {"prohibited", "restricted", "permitted"}:
            raise ContractError("invalid_input", "rights.redistribution must be explicit")
        if retention.get("mode") not in {"retain", "delete_after", "reference_only"}:
            raise ContractError("invalid_input", "retention.mode is invalid")
        if retention.get("redistribution") != rights.get("redistribution"):
            raise ContractError("invalid_input", "retention and rights redistribution disagree")

    def _record_failed_attempt(
        self,
        apparatus: dict[str, Any],
        *,
        timestamp: str,
        kind: str,
        path: Path,
        authorization_status: str,
        error: ContractError,
    ) -> str:
        status = (
            authorization_status if authorization_status in {"permitted", "refused"} else "unknown"
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(apparatus["record_id"], "ApparatusSpec"),
            authorization_status=status,
            operation="ingest",
            inputs=[{"input_kind": kind, "path_disclosed": False}],
            parameters={"ingress_kind": kind, "source_name": path.name},
            outputs=[{"availability": "unavailable", "reason_code": error.reason_code}],
            operation_status="refused" if error.reason_code == "policy_refused" else "failed",
        )
        self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:ingress-failed/0.1",
            subject_record_id=receipt["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={
                "ingress_kind": kind,
                "reason_code": error.reason_code,
                "source_name": path.name,
                "source_deleted": False,
            },
            created_at=timestamp,
        )
        return cast(str, receipt["record_id"])


def declare_apparatus(workspace: Path, declaration: Mapping[str, Any]) -> ApparatusOutcome:
    """Persist a bounded apparatus declaration and its receipt."""

    validate_apparatus_declaration(declaration)
    timestamp = utc_timestamp()
    store = RecordStore.initialize(workspace)
    record = record_base("ApparatusSpec", created_at=timestamp) | {
        key: value for key, value in declaration.items() if key != "authorization_status"
    }
    record["qste:apparatusProfile"] = APPARATUS_PROFILE
    record["qste:authorizationStatus"] = declaration["authorization_status"]
    bind_semantic_key(
        record,
        "qste-semantic-key/apparatus-declaration-p4-v1",
        {key: value for key, value in declaration.items() if key != "authorization_status"},
    )
    receipt = operation_receipt(
        created_at=timestamp,
        request_ref=record_ref(record["record_id"], "ApparatusSpec"),
        authorization_status=cast(str, declaration["authorization_status"]),
        operation="declare_apparatus",
        inputs=[{"declaration_profile": APPARATUS_PROFILE}],
        parameters={"validation": "strict_exact_fields"},
        outputs=[record_ref(record["record_id"], "ApparatusSpec", "produced_by")],
    )
    _, event = store.insert_records_with_event(
        [record, receipt],
        domain_event_record_id=None,
        event_type="qste:apparatus-declared/0.1",
        subject_record_id=record["record_id"],
        receipt_record_id=receipt["record_id"],
        payload={"apparatus_profile": APPARATUS_PROFILE},
        created_at=timestamp,
    )
    return ApparatusOutcome(record, receipt, event.event_sequence)


def derive_aperture(
    workspace: Path,
    *,
    apparatus_record_id: str,
    input_artifact_record_id: str,
    policy: Mapping[str, Any],
) -> ApertureOutcome:
    """Derive, never declare, the evidenced aperture for one apparatus/input/run."""

    store = RecordStore(WorkspacePaths.open(workspace))
    apparatus = store.get_record(apparatus_record_id).record
    artifact = store.get_record(input_artifact_record_id).record
    if apparatus.get("qste:apparatusProfile") != APPARATUS_PROFILE:
        raise ContractError("invalid_input", "aperture requires a P4 apparatus")
    if artifact.get("qste:ingressProfile") != INGRESS_PROFILE:
        raise ContractError("invalid_input", "aperture requires a P4 ingress artifact")
    if policy.get("authorization_status") != "permitted":
        raise ContractError("policy_refused", "aperture derivation requires permission")
    requested = policy.get("allowed_operations")
    if (
        not isinstance(requested, list)
        or not requested
        or not all(isinstance(item, str) for item in requested)
    ):
        raise ContractError("invalid_input", "policy.allowed_operations must be a nonempty list")
    apparatus_ops = cast(list[str], apparatus["action_surface"]["permitted_operations"])
    permitted = [operation for operation in apparatus_ops if operation in requested]
    if not permitted:
        raise ContractError("policy_refused", "policy/apparatus operation intersection is empty")

    timestamp = utc_timestamp()
    aperture_id = cast(str, record_base("ApertureSpec", created_at=timestamp)["record_id"])
    run_id = cast(str, record_base("RunManifest", created_at=timestamp)["record_id"])
    receipt_id = cast(str, record_base("OperationReceipt", created_at=timestamp)["record_id"])
    acquisition_ref = artifact.get("qste:acquisitionRef")
    if not isinstance(acquisition_ref, Mapping):
        raise ContractError("conformance_failed", "ingress result has no acquisition evidence")

    ranges, exclusions = _derive_ranges(artifact, policy)
    capabilities = _calibration_capabilities(apparatus, ranges)
    aperture = record_base("ApertureSpec", created_at=timestamp, record_id=aperture_id) | {
        "apparatus_ref": record_ref(apparatus_record_id, "ApparatusSpec"),
        "run_ref": record_ref(run_id, "RunManifest"),
        "input_ref": record_ref(input_artifact_record_id, "ArtifactRecord"),
        "policy_state": dict(policy),
        "accessible_ranges": ranges,
        "permitted_operations": permitted,
        "known_exclusions": exclusions,
        "derivation": {
            "method": "bounded_intersection/0.1",
            "evidence_refs": [
                record_ref(apparatus_record_id, "ApparatusSpec"),
                record_ref(input_artifact_record_id, "ArtifactRecord"),
                dict(acquisition_ref),
            ],
            "no_historical_expansion": True,
        },
        "qste:apertureProfile": APERTURE_PROFILE,
        "qste:calibrationCapabilities": capabilities,
    }
    bind_semantic_key(
        aperture,
        "qste-semantic-key/aperture-run-input-p4-v1",
        {"apparatus": apparatus_record_id, "input": input_artifact_record_id, "policy": policy},
    )
    run = record_base("RunManifest", created_at=timestamp, record_id=run_id) | {
        "apparatus_ref": record_ref(apparatus_record_id, "ApparatusSpec"),
        "aperture_ref": record_ref(aperture_id, "ApertureSpec"),
        "corpus_refs": [record_ref(input_artifact_record_id, "ArtifactRecord")],
        "spec_refs": [record_ref(apparatus_record_id, "ApparatusSpec")],
        "budgets": {"operation_count": len(permitted), "network_access": False},
        "seeds": [0],
        "event_refs": [dict(acquisition_ref)],
        "artifact_refs": [record_ref(input_artifact_record_id, "ArtifactRecord")],
        "output_refs": [record_ref(aperture_id, "ApertureSpec", "produced_by")],
        "frozen_versions": {
            "contract": "qste-contract/0.3.0",
            "aperture_profile": APERTURE_PROFILE,
        },
        "qste:runProfile": RUN_PROFILE,
    }
    bind_semantic_key(
        run,
        "qste-semantic-key/aperture-run-p4-v1",
        {"aperture": aperture_id, "input": input_artifact_record_id},
    )
    receipt = operation_receipt(
        created_at=timestamp,
        record_id=receipt_id,
        request_ref=record_ref(run_id, "RunManifest"),
        authorization_status="permitted",
        operation="derive_aperture",
        inputs=[
            record_ref(apparatus_record_id, "ApparatusSpec"),
            record_ref(input_artifact_record_id, "ArtifactRecord"),
        ],
        parameters=dict(policy),
        outputs=[record_ref(aperture_id, "ApertureSpec", "produced_by")],
    )
    _, event = store.insert_records_with_event(
        [aperture, run, receipt],
        domain_event_record_id=None,
        event_type="qste:aperture-derived/0.1",
        subject_record_id=aperture_id,
        receipt_record_id=receipt_id,
        payload={"aperture_profile": APERTURE_PROFILE, "no_historical_expansion": True},
        created_at=timestamp,
    )
    return ApertureOutcome(aperture, run, receipt, event.event_sequence)


def require_calibration_claim(aperture: Mapping[str, Any], claim: str) -> None:
    """Gate physical-domain claims on the aperture's recorded calibration evidence."""

    capabilities = cast(Mapping[str, Any], aperture.get("qste:calibrationCapabilities", {}))
    capability = capabilities.get(claim)
    if not isinstance(capability, Mapping):
        raise ContractError("invalid_input", f"unknown calibration claim: {claim}")
    if capability.get("status") != "available":
        raise ContractError("capability_unavailable", f"{claim} requires calibration evidence")


def _decode_audio(
    data: bytes, apparatus: Mapping[str, Any], transform: AudioTransform
) -> tuple[np.ndarray[Any, Any], bytes, str, str, dict[str, Any]]:
    import soundfile as sf  # type: ignore[import-untyped]
    from scipy.signal import resample_poly  # type: ignore[import-untyped]

    try:
        samples, sample_rate = sf.read(io.BytesIO(data), dtype="float64", always_2d=True)
    except (RuntimeError, ValueError) as error:
        raise ContractError("invalid_input", f"audio decode failed: {error}") from error
    if samples.size == 0 or sample_rate <= 0 or not np.isfinite(samples).all():
        raise ContractError("invalid_input", "audio decode produced empty or non-finite samples")
    source_sample_rate = sample_rate
    allowed_rates = cast(
        list[float], apparatus["acquisition_surface"]["timebase"]["sample_rates_hz"]
    )
    if sample_rate not in allowed_rates:
        raise ContractError("capability_unavailable", "input sample rate is outside apparatus")
    output = samples
    operations = ["decode"]
    if transform.target_sample_rate_hz is not None:
        if transform.target_sample_rate_hz <= 0:
            raise ContractError("invalid_input", "target sample rate must be positive")
        ratio = Fraction(transform.target_sample_rate_hz, sample_rate)
        output = resample_poly(output, ratio.numerator, ratio.denominator, axis=0)
        sample_rate = transform.target_sample_rate_hz
        operations.append("resample")
    if transform.normalization == "peak":
        if not 0 < transform.target_peak <= 1:
            raise ContractError("invalid_input", "target peak must be in (0, 1]")
        peak = float(np.max(np.abs(output)))
        if peak > 0:
            output = output * (transform.target_peak / peak)
        operations.append("normalize")
    dtype = np.float32 if transform.output_dtype == "float32" else np.float64
    output = np.asarray(output, dtype=dtype)
    stream = io.BytesIO()
    np.save(stream, output, allow_pickle=False)
    metadata = {
        "qste:sampleRateHz": sample_rate,
        "qste:sourceSampleRateHz": source_sample_rate,
        "qste:frameCount": int(output.shape[0]),
        "qste:channelCount": int(output.shape[1]),
        "qste:durationSeconds": float(output.shape[0] / sample_rate),
        "qste:timebaseKind": "sample_clock",
        "qste:numericDtype": transform.output_dtype,
        "qste:derivationOperations": operations,
    }
    role = "processed_derivative" if len(operations) > 1 else "decoded_derivative"
    return output, stream.getvalue(), "application/x-npy", role, metadata


def _parse_json_observations(value: Any, kind: str, maximum: int) -> Any:
    if not isinstance(value, Mapping):
        raise ContractError("invalid_input", "observation JSON must be an object")
    expected_profile = (
        "qste-model-observations/0.1"
        if kind == "model_observations"
        else "qste-numerical-observations/0.1"
    )
    if value.get("profile_id") != expected_profile:
        raise ContractError("invalid_input", f"JSON profile_id must be {expected_profile}")
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations or len(observations) > maximum:
        raise ContractError("invalid_input", "observation count is empty or out of bounds")
    parsed = [_validate_observation(item) for item in observations]
    if kind == "model_observations":
        model = value.get("model")
        if not isinstance(model, Mapping) or set(model) != {"id", "version", "checkpoint_digest"}:
            raise ContractError("invalid_input", "model identity must be exact and complete")
        if not all(isinstance(model[key], str) and model[key] for key in model):
            raise ContractError("invalid_input", "model identity values must be nonempty strings")
        return {"model": dict(model), "observations": parsed}
    return parsed


def _parse_csv_observations(data: bytes, limits: IngressLimits) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ContractError("invalid_input", "CSV ingress must be strict UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    required = {"variable", "observation_state", "value", "units", "method", "evidence_basis"}
    if reader.fieldnames is None:
        raise ContractError("invalid_input", "CSV has no header")
    columns = set(reader.fieldnames)
    if columns != required and columns != required | {"coordinate"}:
        raise ContractError("invalid_input", "CSV columns do not match the P4 observation profile")
    if len(reader.fieldnames) > limits.maximum_columns:
        raise ContractError("invalid_input", "CSV column count exceeds its bound")
    result: list[dict[str, Any]] = []
    for row in reader:
        if len(result) >= limits.maximum_observations:
            raise ContractError("invalid_input", "CSV observation count exceeds its bound")
        if any(len(value or "") > limits.maximum_cell_characters for value in row.values()):
            raise ContractError("invalid_input", "CSV cell exceeds its character bound")
        item: dict[str, Any] = dict(row)
        if item.get("observation_state") == "value":
            try:
                item["value"] = float(item["value"])
            except (TypeError, ValueError) as error:
                raise ContractError("invalid_input", "CSV value must be finite numeric") from error
        elif item.get("value") not in {"", None}:
            raise ContractError("invalid_input", "absent CSV observations cannot contain value")
        else:
            item.pop("value", None)
        if not item.get("coordinate"):
            item.pop("coordinate", None)
        result.append(_validate_observation(item))
    if not result:
        raise ContractError("invalid_input", "CSV requires at least one observation")
    return result


def _validate_observation(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError("invalid_input", "observation must be an object")
    required = {"variable", "observation_state", "units", "method", "evidence_basis"}
    allowed = required | {"value", "coordinate"}
    if not required.issubset(value) or not set(value).issubset(allowed):
        raise ContractError("invalid_input", "observation fields are incomplete or unknown")
    for field in ("variable", "units", "method"):
        if not isinstance(value[field], str) or not value[field]:
            raise ContractError("invalid_input", f"observation {field} is required")
    if value["evidence_basis"] not in {
        "directly_recorded",
        "calibrated_measurement",
        "instrumentally_derived",
        "model_inferred",
        "human_reported",
        "theoretically_reconstructed",
    }:
        raise ContractError("invalid_input", "observation evidence_basis is invalid")
    state = value["observation_state"]
    if state == "value":
        numeric = value.get("value")
        if (
            not isinstance(numeric, (int, float))
            or isinstance(numeric, bool)
            or not math.isfinite(numeric)
        ):
            raise ContractError("invalid_input", "observation value must be finite numeric")
    elif state == "absent":
        if "value" in value:
            raise ContractError("invalid_input", "absent observation cannot contain a value")
    else:
        raise ContractError("invalid_input", "observation state must be value or absent")
    return dict(value)


def _derive_ranges(
    artifact: Mapping[str, Any], policy: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ranges: dict[str, Any] = {"media_kind": artifact["qste:ingressKind"]}
    exclusions: list[dict[str, Any]] = []
    sample_rate = artifact.get("qste:sourceSampleRateHz", artifact.get("qste:sampleRateHz"))
    duration = artifact.get("qste:durationSeconds")
    if isinstance(sample_rate, (int, float)) and not isinstance(sample_rate, bool):
        nyquist = float(sample_rate) / 2
        policy_frequency = policy.get("maximum_frequency_hz")
        upper = (
            min(nyquist, float(cast(float, policy_frequency)))
            if _positive(policy_frequency)
            else nyquist
        )
        ranges["digital_frequency_hz"] = [0.0, upper]
        if upper < nyquist:
            exclusions.append({"kind": "policy_frequency_limit", "range_hz": [upper, nyquist]})
        exclusions.append({"kind": "sampled_alias_domain", "range_hz": [nyquist, "unbounded"]})
    else:
        ranges["digital_frequency_hz"] = "not_applicable"
        exclusions.append({"kind": "no_sampled_frequency_axis"})
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        available = float(duration)
        policy_duration = policy.get("maximum_duration_seconds")
        upper_duration = (
            min(available, float(cast(float, policy_duration)))
            if _positive(policy_duration)
            else available
        )
        ranges["time_seconds"] = [0.0, upper_duration]
        if upper_duration < available:
            exclusions.append(
                {"kind": "policy_duration_limit", "range_seconds": [upper_duration, available]}
            )
    else:
        ranges["time_seconds"] = "atemporal"
    ranges["channels"] = int(artifact.get("qste:channelCount", 1))
    if not exclusions:
        exclusions.append({"kind": "none_evidenced"})
    return ranges, exclusions


def _calibration_capabilities(
    apparatus: Mapping[str, Any], ranges: Mapping[str, Any]
) -> dict[str, Any]:
    calibration = cast(
        Mapping[str, Mapping[str, Any]],
        apparatus["acquisition_surface"]["calibration"],
    )
    level = calibration["level"]
    frequency = calibration["frequency"]
    frequency_range = ranges.get("digital_frequency_hz")
    spl_available = level.get("status") == "calibrated"
    extra_human = (
        frequency.get("status") == "calibrated"
        and isinstance(frequency_range, list)
        and frequency_range[1] > 20_000
        and cast(list[float], frequency.get("range_hz", [0, 0]))[1] > 20_000
    )
    return {
        "digital_sample_domain": {
            "status": "available",
            "evidence": "content-addressed decoded artifact",
        },
        "spl": (
            {"status": "available", "evidence": level["evidence"], "units": "dB_SPL"}
            if spl_available
            else {"status": "unavailable", "reason": "calibration_unavailable"}
        ),
        "extra_human_frequency": (
            {
                "status": "available",
                "evidence": frequency["evidence"],
                "range_hz": frequency["range_hz"],
            }
            if extra_human
            else {"status": "unavailable", "reason": "calibration_unavailable"}
        ),
    }


def _observation_value(variable: str, value: int | float, units: str) -> dict[str, Any]:
    return {
        "variable": variable,
        "observation_state": "value",
        "value": value,
        "units": units,
        "method": "bounded_decode_metadata/0.1",
        "evidence_basis": "instrumentally_derived",
    }


def _media_type(kind: str, locator: str) -> str:
    if kind == "text":
        return "text/plain; charset=utf-8"
    if kind == "json_observations" or kind == "model_observations":
        return "application/json"
    if kind == "csv_observations":
        return "text/csv; charset=utf-8"
    return mimetypes.guess_type(locator)[0] or "application/octet-stream"


def _transform_value(transform: AudioTransform | None) -> dict[str, Any]:
    value = transform or AudioTransform()
    return {
        "target_sample_rate_hz": value.target_sample_rate_hz or "unchanged",
        "normalization": value.normalization,
        "target_peak": value.target_peak,
        "output_dtype": value.output_dtype,
    }


def _positive(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _reject_symlink_components(path: Path, allowed_root: Path) -> None:
    absolute = path.absolute()
    root_absolute = allowed_root.expanduser().absolute()
    try:
        relative = absolute.relative_to(root_absolute)
    except ValueError as error:
        raise ContractError("policy_refused", "ingress path is outside its allowed root") from error
    cursor = root_absolute
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ContractError("policy_refused", "ingress path contains a symlink component")
