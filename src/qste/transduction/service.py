"""Bounded, local-only P8 mapping and transduction reference service."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, cast

from qste.core import canonical_json_bytes
from qste.core.contracts import BASE_URI, ContractError
from qste.core.identity import utc_timestamp
from qste.ingress.records import bind_semantic_key, operation_receipt, record_base, record_ref
from qste.storage import ArtifactStore, RecordStore, WorkspacePaths
from qste.transduction.models import TransductionOutcome

MAPPING_PROFILE = "qste-transduction-mapping/v0.1"
TRANSDUCTION_PROFILE = "qste-bounded-transduction/v0.1"
TRANSDUCTION_MODES = (
    "sonification",
    "desonification",
    "resonification",
    "sonic_transformation",
    "cross_domain_contrast",
)
REVERSIBILITY_CLAIMS = (
    "reversible",
    "partially_reversible",
    "irreversible",
    "untested",
)
MAX_VALUES = 4096
MAX_OUTPUT_BYTES = 1_048_576


class TransductionService:
    """Declare exact mappings and execute non-playing, bounded P8 fixtures."""

    def __init__(self, workspace: Any) -> None:
        self.paths = WorkspacePaths.open(workspace)
        self.store = RecordStore(self.paths)
        self.artifacts = ArtifactStore(self.paths)

    def declare_mapping(
        self,
        *,
        context_record_id: str,
        specification: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> TransductionOutcome:
        context = self.store.get_record(context_record_id).record
        self._authorize_or_refuse(
            authorization_status,
            "declare_mapping",
            context,
            inputs=[record_ref(context_record_id, cast(str, context["record_type"]))],
            parameters=specification,
        )
        try:
            normalized = _validate_mapping_input(specification)
        except ContractError as error:
            error.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                "declare_mapping", context, specification, error, authorization_status
            )
            raise
        timestamp = utc_timestamp()
        mapping = (
            record_base(
                "MappingSpec",
                created_at=timestamp,
                references=[record_ref(context_record_id, cast(str, context["record_type"]))],
            )
            | normalized
            | {
                "qste:mappingProfile": MAPPING_PROFILE,
                "qste:allowedTransductionModes": list(normalized["qste:allowedTransductionModes"]),
                "qste:boundedOutput": {
                    "maximum_values": MAX_VALUES,
                    "maximum_bytes": MAX_OUTPUT_BYTES,
                    "playback": "prohibited",
                    "network": "prohibited",
                },
            }
        )
        bind_semantic_key(
            mapping,
            "qste-semantic-key/transduction-mapping-v1",
            {
                "context_semantic_key": context.get("semantic_key"),
                "context_record_digest": self.store.get_record(context_record_id).record_digest,
                "mapping_contract": {
                    key: mapping[key]
                    for key in (
                        "source_domain",
                        "target_domain",
                        "variables",
                        "units",
                        "normalization",
                        "uncertainty",
                        "missing_data_behavior",
                        "interpolation",
                        "range",
                        "loss",
                        "reversibility_claim",
                        "qste:allowedTransductionModes",
                    )
                },
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(context_record_id, cast(str, context["record_type"])),
            authorization_status=authorization_status,
            operation="declare_mapping",
            inputs=[record_ref(context_record_id, cast(str, context["record_type"]))],
            parameters={"profile": MAPPING_PROFILE},
            outputs=[record_ref(mapping["record_id"], "MappingSpec", "produced_by")],
            tool_id="qste-p8-transducer",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [mapping, receipt],
            domain_event_record_id=None,
            event_type="qste:mapping-declared/0.1",
            subject_record_id=mapping["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"profile": MAPPING_PROFILE},
            created_at=timestamp,
        )
        return TransductionOutcome(
            mapping,
            f"{BASE_URI}/records/mapping-spec.schema.json",
            receipt,
            event.event_sequence,
        )

    def transduce(
        self,
        *,
        mode: str,
        source_record_ids: Sequence[str],
        mapping_record_id: str,
        parameters: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> TransductionOutcome:
        if mode not in TRANSDUCTION_MODES:
            raise ContractError("invalid_input", "transduction mode is not canonical")
        if not source_record_ids or len(source_record_ids) > 32:
            raise ContractError("invalid_input", "transduction requires between 1 and 32 sources")
        if len(set(source_record_ids)) != len(source_record_ids):
            raise ContractError("invalid_input", "transduction source IDs must be unique")
        mapping = self._record(mapping_record_id, "MappingSpec")
        sources = [self.store.get_record(value).record for value in source_record_ids]
        request = sources[0]
        inputs = [
            record_ref(cast(str, value["record_id"]), cast(str, value["record_type"]))
            for value in sources
        ]
        self._authorize_or_refuse(
            authorization_status,
            f"transduce_{mode}",
            request,
            inputs=inputs,
            parameters=parameters,
        )
        if mode not in cast(Sequence[str], mapping["qste:allowedTransductionModes"]):
            error = ContractError("policy_refused", "mapping does not authorize this mode")
            error.authorization_status = "refused"  # type: ignore[attr-defined]
            error.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                f"transduce_{mode}", request, parameters, error, "refused"
            )
            raise error
        for source in sources:
            if self._is_blocked(cast(str, source["record_id"])):
                error = ContractError("policy_refused", "source authorization is revoked or paused")
                error.authorization_status = "revoked"  # type: ignore[attr-defined]
                error.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                    f"transduce_{mode}", request, parameters, error, "revoked"
                )
                raise error
        try:
            if mode == "sonification":
                return self._artifact_transduction(mode, sources, mapping, parameters)
            if mode == "desonification":
                return self._desonify(sources, mapping, parameters)
            if mode in {"resonification", "sonic_transformation"}:
                return self._artifact_transduction(mode, sources, mapping, parameters)
            return self._contrast(sources, mapping, parameters)
        except ContractError as error:
            if not hasattr(error, "receipt_id"):
                error.receipt_id = self._failure_receipt(  # type: ignore[attr-defined]
                    f"transduce_{mode}", request, parameters, error, authorization_status
                )
            raise

    def _artifact_transduction(
        self,
        mode: str,
        sources: Sequence[dict[str, Any]],
        mapping: Mapping[str, Any],
        parameters: Mapping[str, Any],
    ) -> TransductionOutcome:
        expected = "ObservationRecord" if mode == "sonification" else "ArtifactRecord"
        if any(value["record_type"] != expected for value in sources):
            raise ContractError("invalid_input", f"{mode} requires {expected} sources")
        if mode == "sonification":
            target_id = _required_string(parameters, "target_apparatus_record_id")
            target = self._record(target_id, "ApparatusSpec")
        else:
            context_id = _required_string(parameters, "context_record_id")
            target = self.store.get_record(context_id).record
        control_id = _required_string(parameters, "control_record_id")
        control = self.store.get_record(control_id).record
        if control_id in {value["record_id"] for value in sources}:
            raise ContractError("invalid_input", "control and analytical source must be distinct")
        raw_values = parameters.get("values")
        if raw_values is None and mode == "sonification":
            raw_values = [value.get("value") for value in sources]
        values = _finite_values(raw_values)
        mapped = _map_values(values, mapping)
        safety = parameters.get("safety_controls")
        if not isinstance(safety, Mapping) or not safety:
            raise ContractError("invalid_input", "bounded output safety controls are required")
        peak = safety.get("maximum_normalized_peak")
        if not _finite(peak) or not 0 < cast(float, peak) <= 1:
            raise ContractError("invalid_input", "maximum normalized peak must be in (0,1]")
        payload = {
            "profile": TRANSDUCTION_PROFILE,
            "mode": mode,
            "mapping_record_id": mapping["record_id"],
            "source_record_ids": [value["record_id"] for value in sources],
            "control_record_id": control["record_id"],
            "target_or_context_record_id": target["record_id"],
            "analytical_values": mapped,
            "uncertainty": mapping["uncertainty"],
            "loss": mapping["loss"],
            "render_status": "analytical_fixture",
            "heard_output": "not_produced",
            "playback": "prohibited",
        }
        analytical_bytes = canonical_json_bytes(payload)
        if len(analytical_bytes) > MAX_OUTPUT_BYTES:
            raise ContractError("invalid_input", "analytical output exceeds P8 byte bound")
        analytical_object = self.artifacts.put_bytes(analytical_bytes)
        timestamp = utc_timestamp()
        references = [
            record_ref(
                cast(str, value["record_id"]), cast(str, value["record_type"]), "derived_from"
            )
            for value in sources
        ] + [
            record_ref(cast(str, mapping["record_id"]), "MappingSpec"),
            record_ref(cast(str, control["record_id"]), cast(str, control["record_type"])),
            record_ref(cast(str, target["record_id"]), cast(str, target["record_type"])),
        ]
        analytical = record_base(
            "ArtifactRecord",
            created_at=timestamp,
            references=references,
        ) | {
            "media_type": "application/vnd.qste.transduction+json",
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": analytical_object.content_digest,
            "qste:transductionProfile": TRANSDUCTION_PROFILE,
            "qste:transductionMode": mode,
            "qste:mappingRef": record_ref(cast(str, mapping["record_id"]), "MappingSpec"),
            "qste:controlRef": record_ref(
                cast(str, control["record_id"]), cast(str, control["record_type"])
            ),
            "qste:analyticalOutput": True,
            "qste:heardOutput": "not_produced",
            "qste:uncertainty": mapping["uncertainty"],
            "qste:loss": mapping["loss"],
        }
        bind_semantic_key(
            analytical,
            "qste-semantic-key/transduction-artifact-v1",
            {
                "mode": mode,
                "mapping_semantic_key": mapping.get("semantic_key"),
                "source_record_digests": [
                    self.store.get_record(cast(str, value["record_id"])).record_digest
                    for value in sources
                ],
                "control_record_digest": self.store.get_record(control_id).record_digest,
                "payload_digest": analytical_object.content_digest,
            },
        )
        safety_values = [max(-cast(float, peak), min(cast(float, peak), value)) for value in mapped]
        safety_payload = {
            "profile": "qste-safety-descendant/v0.1",
            "analytical_record_id": analytical["record_id"],
            "bounded_values": safety_values,
            "controls": dict(safety),
            "heard_output": "not_produced",
        }
        safety_bytes = canonical_json_bytes(safety_payload)
        safety_object = self.artifacts.put_bytes(safety_bytes)
        safety_record = record_base(
            "ArtifactRecord",
            created_at=timestamp,
            references=[record_ref(analytical["record_id"], "ArtifactRecord", "descendant_of")],
        ) | {
            "media_type": "application/vnd.qste.safety-render+json",
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": safety_object.content_digest,
            "qste:safetyProfile": "qste-safety-descendant/v0.1",
            "qste:analyticalParentRef": record_ref(analytical["record_id"], "ArtifactRecord"),
            "qste:heardOutput": "not_produced",
            "qste:controls": dict(safety),
        }
        bind_semantic_key(
            safety_record,
            "qste-semantic-key/safety-descendant-v1",
            {
                "analytical_semantic_key": analytical["semantic_key"],
                "controls": dict(safety),
                "payload_digest": safety_object.content_digest,
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(
                cast(str, sources[0]["record_id"]), cast(str, sources[0]["record_type"])
            ),
            authorization_status="permitted",
            operation=f"transduce_{mode}",
            inputs=references,
            parameters={
                "mapping_profile": MAPPING_PROFILE,
                "transduction_mode": mode,
                "safety_controls": dict(safety),
            },
            outputs=[
                record_ref(analytical["record_id"], "ArtifactRecord", "produced_by"),
                record_ref(safety_record["record_id"], "ArtifactRecord", "produced_by"),
            ],
            tool_id="qste-p8-transducer",
            tool_version="v0.1",
        )
        self.store.register_artifact(
            analytical_object.content_digest,
            analytical_object.size,
            analytical_object.relative_path,
            media_type=analytical["media_type"],
        )
        self.store.register_artifact(
            safety_object.content_digest,
            safety_object.size,
            safety_object.relative_path,
            media_type=safety_record["media_type"],
        )
        _, event = self.store.insert_records_with_event(
            [analytical, safety_record, receipt],
            domain_event_record_id=None,
            event_type="qste:transduction-completed/0.1",
            subject_record_id=analytical["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={
                "profile": TRANSDUCTION_PROFILE,
                "mode": mode,
                "safety_descendant_record_id": safety_record["record_id"],
                "heard_output": "not_produced",
            },
            created_at=timestamp,
        )
        return TransductionOutcome(
            analytical,
            f"{BASE_URI}/records/artifact-record.schema.json",
            receipt,
            event.event_sequence,
            safety_record_ids=(cast(str, safety_record["record_id"]),),
        )

    def _desonify(
        self,
        sources: Sequence[dict[str, Any]],
        mapping: Mapping[str, Any],
        parameters: Mapping[str, Any],
    ) -> TransductionOutcome:
        if len(sources) != 1 or sources[0]["record_type"] != "ArtifactRecord":
            raise ContractError("invalid_input", "desonification requires one ArtifactRecord")
        declarations = parameters.get("observations")
        if not isinstance(declarations, list) or not declarations or len(declarations) > 128:
            raise ContractError(
                "invalid_input", "desonification observations are missing or unbounded"
            )
        if mapping["reversibility_claim"] in {"irreversible", "untested"} and not parameters.get(
            "bounded_inference"
        ):
            raise ContractError(
                "invalid_input",
                "nonreversible desonification requires a bounded inference declaration",
            )
        timestamp = utc_timestamp()
        records: list[dict[str, Any]] = []
        for declaration in declarations:
            if not isinstance(declaration, Mapping):
                raise ContractError("invalid_input", "observation declaration must be an object")
            variable = _required_string(declaration, "variable")
            units = _required_string(declaration, "units")
            value = declaration.get("value")
            if not _finite(value):
                raise ContractError("invalid_input", "desonified observation must be finite")
            observation = record_base(
                "ObservationRecord",
                created_at=timestamp,
                references=[
                    record_ref(sources[0]["record_id"], "ArtifactRecord", "derived_from"),
                    record_ref(cast(str, mapping["record_id"]), "MappingSpec"),
                ],
            ) | {
                "variable": variable,
                "observation_state": "value",
                "value": float(cast(float, value)),
                "units": units,
                "method": "qste-bounded-desonification/v0.1",
                "evidence_basis": "instrumentally_derived",
                "acquisition_ref": record_ref(sources[0]["record_id"], "ArtifactRecord"),
                "qste:transductionMode": "desonification",
                "qste:mappingRef": record_ref(cast(str, mapping["record_id"]), "MappingSpec"),
                "qste:uncertainty": mapping["uncertainty"],
                "qste:loss": mapping["loss"],
                "qste:claimLimit": "bounded_observation_not_complete_cause_or_meaning",
            }
            bind_semantic_key(
                observation,
                "qste-semantic-key/desonified-observation-v1",
                {
                    "source_record_digest": self.store.get_record(
                        cast(str, sources[0]["record_id"])
                    ).record_digest,
                    "mapping_semantic_key": mapping.get("semantic_key"),
                    "variable": variable,
                    "units": units,
                    "value": value,
                },
            )
            records.append(observation)
        payload = {
            "payload_schema_id": "qste-payload/0.3.0",
            "payload_type": "ObservationSet",
            "items": records,
            "data": {
                "transduction_mode": "desonification",
                "mapping_record_id": mapping["record_id"],
                "complete_cause_or_meaning_claim": False,
            },
        }
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(sources[0]["record_id"], "ArtifactRecord"),
            authorization_status="permitted",
            operation="transduce_desonification",
            inputs=[
                record_ref(sources[0]["record_id"], "ArtifactRecord"),
                record_ref(cast(str, mapping["record_id"]), "MappingSpec"),
            ],
            parameters={"bounded_inference": bool(parameters.get("bounded_inference"))},
            outputs=[record_ref(value["record_id"], "ObservationRecord") for value in records],
            tool_id="qste-p8-transducer",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [*records, receipt],
            domain_event_record_id=None,
            event_type="qste:desonification-completed/0.1",
            subject_record_id=records[0]["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"profile": TRANSDUCTION_PROFILE, "observation_count": len(records)},
            created_at=timestamp,
        )
        return TransductionOutcome(
            payload,
            "qste-payload/0.3.0/ObservationSet",
            receipt,
            event.event_sequence,
        )

    def _contrast(
        self,
        sources: Sequence[dict[str, Any]],
        mapping: Mapping[str, Any],
        parameters: Mapping[str, Any],
    ) -> TransductionOutcome:
        kinds = {value["record_type"] for value in sources}
        if "ArtifactRecord" not in kinds or "ObservationRecord" not in kinds:
            raise ContractError(
                "invalid_input", "cross-domain contrast requires sonic and nonsonic records"
            )
        distinction = _required_string(parameters, "distinction")
        if distinction not in {"correlation", "co_occurrence", "mapping"}:
            raise ContractError(
                "invalid_input", "P8 contrast cannot infer causation from a mapping fixture"
            )
        variables = parameters.get("variables")
        if not isinstance(variables, list) or not variables or len(variables) > 64:
            raise ContractError("invalid_input", "contrast variables are missing or unbounded")
        timestamp = utc_timestamp()
        payload = {
            "payload_schema_id": "qste-payload/0.3.0",
            "payload_type": "RelationSet",
            "items": [],
            "data": {
                "transduction_mode": "cross_domain_contrast",
                "mapping_record_id": mapping["record_id"],
                "source_record_ids": [value["record_id"] for value in sources],
                "variables": list(variables),
                "method": _required_string(parameters, "method"),
                "distinction": distinction,
                "causation_claim": False,
                "relation_assertions": "none_emitted_by_bounded_mapping_fixture",
            },
        }
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(sources[0]["record_id"], sources[0]["record_type"]),
            authorization_status="permitted",
            operation="transduce_cross_domain_contrast",
            inputs=[
                *[record_ref(value["record_id"], value["record_type"]) for value in sources],
                record_ref(cast(str, mapping["record_id"]), "MappingSpec"),
            ],
            parameters={
                "variables": list(variables),
                "method": parameters["method"],
                "distinction": distinction,
            },
            outputs=[{"availability": "not_applicable", "reason": "no_relation_asserted"}],
            tool_id="qste-p8-transducer",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:cross-domain-contrast-completed/0.1",
            subject_record_id=sources[0]["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"distinction": distinction, "causation_claim": False},
            created_at=timestamp,
        )
        return TransductionOutcome(
            payload,
            "qste-payload/0.3.0/RelationSet",
            receipt,
            event.event_sequence,
        )

    def _record(self, record_id: str, expected_type: str) -> dict[str, Any]:
        record = self.store.get_record(record_id).record
        if record["record_type"] != expected_type:
            raise ContractError("invalid_input", f"record is not {expected_type}: {record_id}")
        return record

    def _is_blocked(self, record_id: str) -> bool:
        for event in self.store.iter_events():
            if event.subject_record_id != record_id:
                continue
            if event.event_type in {
                "qste:authorization-revoked/0.1",
                "qste:use-paused/0.1",
                "qste:dependency-invalidated/0.1",
            }:
                return True
            if event.event_type in {
                "qste:authorization-restored/0.1",
                "qste:pause-released/0.1",
            }:
                return False
        return False

    def _authorize_or_refuse(
        self,
        authorization_status: str,
        operation: str,
        request: Mapping[str, Any],
        *,
        inputs: Sequence[Any],
        parameters: Mapping[str, Any],
    ) -> None:
        if authorization_status == "permitted":
            return
        if authorization_status not in {"unknown", "refused", "deferred", "revoked"}:
            raise ContractError("invalid_input", "authorization status is not executable in P8")
        error = ContractError("policy_refused", f"{operation} blocked by authorization")
        error.authorization_status = authorization_status  # type: ignore[attr-defined]
        error.receipt_id = self._refusal_receipt(  # type: ignore[attr-defined]
            operation,
            request,
            inputs=inputs,
            parameters=parameters,
            authorization_status=authorization_status,
        )
        raise error

    def _refusal_receipt(
        self,
        operation: str,
        request: Mapping[str, Any],
        *,
        inputs: Sequence[Any],
        parameters: Mapping[str, Any],
        authorization_status: str,
    ) -> str:
        timestamp = utc_timestamp()
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(
                cast(str, request["record_id"]), cast(str, request["record_type"])
            ),
            authorization_status=authorization_status,
            operation=operation,
            inputs=inputs,
            parameters=dict(parameters) or {"mode": "none"},
            outputs=[{"availability": "not_applicable", "reason": "policy_refused"}],
            operation_status="refused",
            tool_id="qste-p8-transducer",
            tool_version="v0.1",
        )
        self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:operation-refused/0.1",
            subject_record_id=cast(str, request["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={
                "operation": operation,
                "authorization_status": authorization_status,
                "executable_consequence": "no_authoritative_derivative",
            },
            created_at=timestamp,
        )
        return cast(str, receipt["record_id"])

    def _failure_receipt(
        self,
        operation: str,
        request: Mapping[str, Any],
        parameters: Mapping[str, Any],
        error: ContractError,
        authorization_status: str,
    ) -> str:
        timestamp = utc_timestamp()
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(
                cast(str, request["record_id"]), cast(str, request["record_type"])
            ),
            authorization_status=(
                authorization_status
                if authorization_status
                in {"unknown", "permitted", "refused", "deferred", "revoked", "not_applicable"}
                else "not_applicable"
            ),
            operation=operation,
            inputs=[record_ref(cast(str, request["record_id"]), cast(str, request["record_type"]))],
            parameters={"reason_code": error.reason_code, "request": dict(parameters)},
            outputs=[{"availability": "not_applicable", "reason": error.reason_code}],
            operation_status="failed",
            tool_id="qste-p8-transducer",
            tool_version="v0.1",
        )
        self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:transduction-failed/0.1",
            subject_record_id=cast(str, request["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"operation": operation, "reason_code": error.reason_code},
            created_at=timestamp,
        )
        return cast(str, receipt["record_id"])


def _validate_mapping_input(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "source_domain",
        "target_domain",
        "variables",
        "units",
        "normalization",
        "uncertainty",
        "missing_data_behavior",
        "interpolation",
        "range",
        "loss",
        "reversibility_claim",
        "allowed_transduction_modes",
    }
    if set(value) != required:
        missing = sorted(required - set(value))
        extra = sorted(set(value) - required)
        raise ContractError(
            "invalid_input", f"mapping fields conflict; missing={missing}, extra={extra}"
        )
    for key in (
        "source_domain",
        "target_domain",
        "normalization",
        "uncertainty",
        "interpolation",
        "loss",
    ):
        if not isinstance(value[key], Mapping) or not value[key]:
            raise ContractError("invalid_input", f"mapping {key} must be a nonempty object")
    variables = value["variables"]
    if not isinstance(variables, list) or not variables or len(variables) > 64:
        raise ContractError("invalid_input", "mapping variables are missing or unbounded")
    for variable in variables:
        if not isinstance(variable, Mapping):
            raise ContractError("invalid_input", "mapping variable must be an object")
        _required_string(variable, "source")
        _required_string(variable, "target")
    units = value["units"]
    if not isinstance(units, Mapping) or set(units) != {"source", "target"}:
        raise ContractError("invalid_input", "mapping units require exact source and target units")
    _required_string(units, "source")
    _required_string(units, "target")
    ranges = value["range"]
    if not isinstance(ranges, Mapping) or set(ranges) != {"source", "target"}:
        raise ContractError("invalid_input", "mapping ranges require source and target")
    _range_pair(ranges["source"], "source")
    _range_pair(ranges["target"], "target")
    if value["missing_data_behavior"] not in {"fail", "drop", "zero_fill", "hold_last"}:
        raise ContractError("invalid_input", "mapping missing-data behavior is invalid")
    if value["interpolation"].get("method") not in {"none", "linear", "nearest"}:
        raise ContractError("invalid_input", "mapping interpolation method is invalid")
    if value["normalization"].get("method") not in {"none", "linear_range"}:
        raise ContractError("invalid_input", "mapping normalization method is invalid")
    if value["reversibility_claim"] not in REVERSIBILITY_CLAIMS:
        raise ContractError("invalid_input", "mapping reversibility claim is invalid")
    uncertainty_bound = value["uncertainty"].get("absolute_bound")
    if not _finite(uncertainty_bound) or cast(float, uncertainty_bound) < 0:
        raise ContractError(
            "invalid_input", "mapping uncertainty bound must be finite and nonnegative"
        )
    if not isinstance(value["loss"].get("known"), bool) or not value["loss"].get("description"):
        raise ContractError(
            "invalid_input", "mapping loss must declare known state and description"
        )
    modes = value["allowed_transduction_modes"]
    if (
        not isinstance(modes, list)
        or not modes
        or len(set(modes)) != len(modes)
        or any(mode not in TRANSDUCTION_MODES for mode in modes)
    ):
        raise ContractError("invalid_input", "allowed transduction modes are invalid")
    return {
        "source_domain": dict(cast(Mapping[str, Any], value["source_domain"])),
        "target_domain": dict(cast(Mapping[str, Any], value["target_domain"])),
        "variables": [dict(cast(Mapping[str, Any], item)) for item in variables],
        "units": dict(cast(Mapping[str, Any], units)),
        "normalization": dict(cast(Mapping[str, Any], value["normalization"])),
        "uncertainty": dict(cast(Mapping[str, Any], value["uncertainty"])),
        "missing_data_behavior": value["missing_data_behavior"],
        "interpolation": dict(cast(Mapping[str, Any], value["interpolation"])),
        "range": {
            "source": list(cast(Sequence[float], ranges["source"])),
            "target": list(cast(Sequence[float], ranges["target"])),
        },
        "loss": dict(cast(Mapping[str, Any], value["loss"])),
        "reversibility_claim": value["reversibility_claim"],
        "qste:allowedTransductionModes": list(cast(Sequence[str], modes)),
    }


def _map_values(values: Sequence[float], mapping: Mapping[str, Any]) -> list[float]:
    ranges = cast(Mapping[str, Sequence[float]], mapping["range"])
    source_low, source_high = ranges["source"]
    target_low, target_high = ranges["target"]
    behavior = cast(str, mapping["missing_data_behavior"])
    result: list[float] = []
    for raw in values:
        value = raw
        if not math.isfinite(value):
            if behavior == "fail":
                raise ContractError(
                    "invalid_input", "mapping source contains missing/nonfinite data"
                )
            if behavior == "drop":
                continue
            value = 0.0 if behavior == "zero_fill" else (result[-1] if result else 0.0)
        if value < source_low or value > source_high:
            raise ContractError("invalid_input", "mapping source value is outside declared range")
        if mapping["normalization"].get("method") == "linear_range":
            ratio = (value - source_low) / (source_high - source_low)
            value = target_low + ratio * (target_high - target_low)
        if value < target_low or value > target_high:
            raise ContractError("invalid_input", "mapped value is outside declared target range")
        result.append(float(value))
    if not result:
        raise ContractError("invalid_input", "mapping produced no target values")
    return result


def _finite_values(value: Any) -> list[float]:
    if not isinstance(value, list) or not value or len(value) > MAX_VALUES:
        raise ContractError("invalid_input", "transduction values are missing or unbounded")
    result: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise ContractError("invalid_input", "transduction values must be numeric")
        result.append(float(item))
    return result


def _range_pair(value: Any, name: str) -> tuple[float, float]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(_finite(item) for item in value)
        or cast(float, value[0]) >= cast(float, value[1])
    ):
        raise ContractError("invalid_input", f"mapping {name} range is invalid")
    return float(value[0]), float(value[1])


def _required_string(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ContractError("invalid_input", f"{key} must be a nonempty string")
    return result


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
