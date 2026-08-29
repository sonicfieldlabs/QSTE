"""P14 program and dataset-manifest governance without model execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn, cast

from qste.core import canonical_json_bytes, utc_timestamp
from qste.core.contracts import ContractError
from qste.ingress.records import bind_semantic_key, operation_receipt, record_base, record_ref
from qste.model_research.contracts import (
    DATASET_FIELDS,
    DATASET_PROFILE,
    MODEL_CARD_SECTIONS,
    PROGRAM_FIELDS,
    PROGRAM_PROFILE,
    PROGRAM_SAFETY_FLAGS,
)
from qste.model_research.models import ModelResearchOutcome
from qste.storage import ArtifactStore, RecordStore, WorkspacePaths

MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_DATASET_ITEMS = 4096


class ModelResearchService:
    """Freeze model research declarations while training remains unavailable."""

    def __init__(self, workspace: Path) -> None:
        self.paths = WorkspacePaths.open(workspace)
        self.store = RecordStore(self.paths)
        self.artifacts = ArtifactStore(self.paths)

    def freeze_program(
        self,
        *,
        context_record_id: str,
        specification: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> ModelResearchOutcome:
        context = self.store.get_record(context_record_id).record
        self._authorize(authorization_status, "model_program_freeze", context)
        try:
            normalized = _validate_program(specification)
        except ContractError as error:
            self._fail("model_program_freeze", context, error.reason_code, str(error))
        timestamp = utc_timestamp()
        record = self._artifact(
            normalized,
            timestamp=timestamp,
            media_type="application/vnd.qste.model-research-program+json",
            references=[record_ref(context_record_id, cast(str, context["record_type"]))],
        )
        record.update(
            {
                "qste:modelResearchProfile": PROGRAM_PROFILE,
                "qste:modelResearchStatus": "contract_frozen",
                "qste:datasetStatus": "unavailable",
                "qste:trainingStatus": "not_started",
                "qste:checkpointStatus": "unavailable",
                "qste:learnedGainStatus": "unavailable",
                "qste:customModelStatus": "unavailable",
                "qste:publicProjection": False,
            }
        )
        bind_semantic_key(
            record,
            "qste-semantic-key/model-research-program-v1",
            {
                "program_digest": record["content_digest"],
                "context": context.get("semantic_key", context_record_id),
            },
        )
        return self._persist("model_program_freeze", context, record, timestamp)

    def register_dataset_manifest(
        self,
        *,
        program_record_id: str,
        manifest: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> ModelResearchOutcome:
        program = self.store.get_record(program_record_id).record
        self._authorize(authorization_status, "model_dataset_register", program)
        if program.get("qste:modelResearchProfile") != PROGRAM_PROFILE:
            self._fail(
                "model_dataset_register",
                program,
                "invalid_input",
                "dataset input is not a frozen P14 research program",
            )
        try:
            normalized = _validate_dataset(manifest)
            if normalized["program_digest"] != program.get("content_digest"):
                raise ContractError(
                    "conformance_failed", "dataset manifest does not bind the frozen program"
                )
            source_records = {
                item["source_record_id"]: self.store.get_record(item["source_record_id"]).record
                for item in normalized["items"]
            }
        except ContractError as error:
            self._fail("model_dataset_register", program, error.reason_code, str(error))
        timestamp = utc_timestamp()
        record = self._artifact(
            normalized,
            timestamp=timestamp,
            media_type="application/vnd.qste.model-dataset-manifest+json",
            references=[
                record_ref(program_record_id, "ArtifactRecord"),
                *[
                    record_ref(source_id, cast(str, source["record_type"]))
                    for source_id, source in sorted(source_records.items())
                ],
            ],
        )
        record.update(
            {
                "qste:modelResearchProfile": PROGRAM_PROFILE,
                "qste:datasetProfile": DATASET_PROFILE,
                "qste:datasetStatus": "metadata_only_unverified_bytes",
                "qste:trainingEligibility": "unavailable",
                "qste:trainingStatus": "not_started",
                "qste:publicProjection": False,
            }
        )
        bind_semantic_key(
            record,
            "qste-semantic-key/model-dataset-manifest-v1",
            {
                "program": program["semantic_key"],
                "manifest_digest": record["content_digest"],
            },
        )
        return self._persist("model_dataset_register", program, record, timestamp)

    def account(
        self,
        *,
        context_record_id: str,
        authorization_status: str = "permitted",
    ) -> ModelResearchOutcome:
        context = self.store.get_record(context_record_id).record
        self._authorize(authorization_status, "model_research_account", context)
        timestamp = utc_timestamp()
        value = {
            "payload_type": "CapabilityAccount",
            "payload_schema_id": "qste-payload/0.3.0",
            "items": [],
            "data": {
                "program_freeze": "available",
                "dataset_manifest_registry": "available",
                "synthetic_conformance": "available",
                "dataset_bytes": "unavailable",
                "checkpoint_download": "unavailable",
                "fine_tuning_execution": "authorization_required",
                "trained_model": "unavailable",
                "learned_gain_evidence": "unavailable",
                "analysis_evaluation": "unavailable",
                "generation_evaluation": "unavailable",
                "custom_model": "unavailable",
                "public_projection": "prohibited",
            },
        }
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(context_record_id, cast(str, context["record_type"])),
            authorization_status="permitted",
            operation="model_research_account",
            inputs=[record_ref(context_record_id, cast(str, context["record_type"]))],
            parameters={"profile": PROGRAM_PROFILE},
            outputs=[],
            tool_id="qste-p14-model-research",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:model-research-capability-accounted/0.1",
            subject_record_id=context_record_id,
            receipt_record_id=receipt["record_id"],
            payload={"training": False, "model": False, "human_data": False},
            created_at=timestamp,
        )
        return ModelResearchOutcome(
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
        if len(data) > MAX_MANIFEST_BYTES:
            raise ContractError("invalid_input", "P14 manifest exceeds its byte bound")
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

    def _persist(
        self,
        operation: str,
        request: Mapping[str, Any],
        record: dict[str, Any],
        timestamp: str,
    ) -> ModelResearchOutcome:
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(
                cast(str, request["record_id"]), cast(str, request["record_type"])
            ),
            authorization_status="permitted",
            operation=operation,
            inputs=[record_ref(cast(str, request["record_id"]), cast(str, request["record_type"]))],
            parameters={"profile": PROGRAM_PROFILE},
            outputs=[record_ref(cast(str, record["record_id"]), "ArtifactRecord")],
            tool_id="qste-p14-model-research",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [record, receipt],
            domain_event_record_id=None,
            event_type=f"qste:{operation.replace('_', '-')}/0.1",
            subject_record_id=cast(str, record["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"training": False, "model": False, "human_data": False},
            created_at=timestamp,
        )
        return ModelResearchOutcome(
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
                f"P14 preparation authorization is {authorization_status}",
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
            tool_id="qste-p14-model-research",
            tool_version="v0.1",
        )
        self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type="qste:model-research-operation-refused/0.1"
            if reason == "policy_refused"
            else "qste:model-research-operation-failed/0.1",
            subject_record_id=cast(str, request["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"operation": operation, "reason_code": reason},
            created_at=timestamp,
        )
        error = ContractError(reason, message)
        error.receipt_id = receipt["record_id"]  # type: ignore[attr-defined]
        error.authorization_status = effective  # type: ignore[attr-defined]
        raise error


def _validate_program(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != PROGRAM_FIELDS:
        raise ContractError("invalid_input", "P14 program fields are not exact")
    if value["profile_id"] != PROGRAM_PROFILE or value["stage"] != "development_contract":
        raise ContractError("invalid_input", "P14 program profile or stage is invalid")
    question = _mapping(value["research_question"], "research_question")
    if (
        set(question)
        != {"question", "justification_evidence_status", "falsifier", "simpler_baseline_required"}
        or not _text(question["question"])
        or not _text(question["falsifier"])
        or question["justification_evidence_status"] != "unavailable"
        or question["simpler_baseline_required"] is not True
    ):
        raise ContractError("invalid_input", "P14 research question is not bounded")
    governance = _mapping(value["dataset_governance"], "dataset_governance")
    required_governance = {
        "rights_required": True,
        "consent_required_for_human_data": True,
        "self_generated_identification_required": True,
        "retention_required": True,
        "disclosure_default": "private",
    }
    if dict(governance) != required_governance:
        raise ContractError("policy_refused", "P14 dataset governance is incomplete")
    representations = _mapping(value["training_representations"], "training_representations")
    if set(representations) != {"dsq_derived", "ordinary_segment_baseline"}:
        raise ContractError("invalid_input", "P14 representation comparison is incomplete")
    dsq = _mapping(representations["dsq_derived"], "dsq_derived")
    ordinary = _mapping(representations["ordinary_segment_baseline"], "ordinary baseline")
    if (
        set(dsq) != {"status", "qualification_required", "universal_particle_claim"}
        or set(ordinary) != {"status", "baseline_required", "universal_particle_claim"}
        or dsq.get("status") != "contract_only"
        or dsq.get("qualification_required") is not True
        or dsq.get("universal_particle_claim") is not False
        or ordinary.get("status") != "contract_only"
        or ordinary.get("baseline_required") is not True
        or ordinary.get("universal_particle_claim") is not False
    ):
        raise ContractError("conformance_failed", "P14 representation boundary is invalid")
    fine_tuning = _mapping(value["fine_tuning"], "fine_tuning")
    if (
        set(fine_tuning)
        != {
            "base_model_status",
            "training_status",
            "separate_authorization_required",
            "custom_model_status",
            "method",
        }
        or fine_tuning.get("base_model_status") != "unselected"
        or fine_tuning.get("training_status") != "not_started"
        or fine_tuning.get("separate_authorization_required") is not True
        or fine_tuning.get("custom_model_status") != "unavailable"
        or not _text(fine_tuning.get("method"))
    ):
        raise ContractError("policy_refused", "P14 fine-tuning boundary is invalid")
    evaluation = _mapping(value["evaluation_suite"], "evaluation_suite")
    if set(evaluation) != {
        "analysis_tasks",
        "generation_tasks",
        "held_out_baselines",
        "recursive_ontology_revision",
        "recursive_benchmark_revision",
        "learned_gains_status",
    }:
        raise ContractError("invalid_input", "P14 evaluation fields are not exact")
    for key in ("analysis_tasks", "generation_tasks", "held_out_baselines"):
        _sequence(evaluation.get(key), key)
    if (
        evaluation.get("recursive_ontology_revision") is not False
        or evaluation.get("recursive_benchmark_revision") is not False
        or evaluation.get("learned_gains_status") != "unavailable"
    ):
        raise ContractError("policy_refused", "P14 recursive evaluation boundary is invalid")
    budget = _mapping(value["compute_environment_budget"], "compute_environment_budget")
    if set(budget) != {
        "maximum_cpu_seconds",
        "maximum_gpu_seconds",
        "maximum_memory_bytes",
        "maximum_storage_bytes",
        "energy_accounting",
        "network_access",
    }:
        raise ContractError("invalid_input", "P14 compute-budget fields are not exact")
    for key in (
        "maximum_cpu_seconds",
        "maximum_gpu_seconds",
        "maximum_memory_bytes",
        "maximum_storage_bytes",
    ):
        _positive_integer(budget.get(key), key)
    if budget.get("network_access") is not False or not _text(budget.get("energy_accounting")):
        raise ContractError("policy_refused", "P14 compute budget is invalid")
    card = _mapping(value["model_card_template"], "model_card_template")
    if (
        set(card) != {"required_sections"}
        or set(_sequence(card.get("required_sections"), "model card sections"))
        != MODEL_CARD_SECTIONS
    ):
        raise ContractError("invalid_input", "P14 model card sections are incomplete")
    failure = _mapping(value["failure_analysis"], "failure_analysis")
    _sequence(failure.get("categories"), "failure categories")
    if (
        set(failure) != {"categories", "revoke_model_capability", "earlier_bundles_remain_readable"}
        or failure.get("revoke_model_capability") is not True
        or failure.get("earlier_bundles_remain_readable") is not True
    ):
        raise ContractError("policy_refused", "P14 recovery contract is invalid")
    route = _mapping(value["custom_model_route"], "custom_model_route")
    if (
        set(route) != {"status", "stages"}
        or route.get("status") != "not_started"
        or _sequence(route.get("stages"), "route stages")[-1]
        != "separate_custom_model_authorization"
    ):
        raise ContractError("invalid_input", "P14 custom-model route is invalid")
    flags = _mapping(value["safety_flags"], "safety_flags")
    if set(flags) != PROGRAM_SAFETY_FLAGS or any(flags[key] is not False for key in flags):
        raise ContractError("policy_refused", "P14 program records execution or data use")
    return dict(value)


def _validate_dataset(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != DATASET_FIELDS:
        raise ContractError("invalid_input", "P14 dataset fields are not exact")
    if value["profile_id"] != DATASET_PROFILE or value["manifest_stage"] != "metadata_only":
        raise ContractError("invalid_input", "P14 dataset profile or stage is invalid")
    if (
        not _digest(value["program_digest"])
        or not _text(value["dataset_id"])
        or not _text(value["version"])
    ):
        raise ContractError("invalid_input", "P14 dataset identity is invalid")
    items = _sequence(value["items"], "dataset items", maximum=MAX_DATASET_ITEMS)
    item_ids: set[str] = set()
    for raw_item in items:
        item = _mapping(raw_item, "dataset item")
        required = {
            "item_id",
            "content_digest",
            "source_kind",
            "source_record_id",
            "rights_status",
            "consent_status",
            "attribution",
            "retention",
            "disclosure_status",
            "self_generated",
            "generator_provenance",
        }
        if set(item) != required or not _text(item["item_id"]) or item["item_id"] in item_ids:
            raise ContractError("invalid_input", "P14 dataset item identity is invalid")
        item_ids.add(cast(str, item["item_id"]))
        if (
            not _digest(item["content_digest"])
            or not _text(item["source_record_id"])
            or not _text(item["source_kind"])
            or not _text(item["attribution"])
        ):
            raise ContractError("invalid_input", "P14 dataset item provenance is invalid")
        if item["rights_status"] != "permitted" or item["consent_status"] not in {
            "permitted",
            "not_applicable",
        }:
            raise ContractError("policy_refused", "P14 dataset item lacks rights or consent")
        retention = _mapping(item["retention"], "retention")
        if (
            item["disclosure_status"] != "private"
            or set(retention) != {"mode", "scope"}
            or not _text(retention["mode"])
            or not _text(retention["scope"])
        ):
            raise ContractError("policy_refused", "P14 dataset retention or disclosure is invalid")
        if item["self_generated"] is True:
            provenance = _mapping(item["generator_provenance"], "generator provenance")
            if (
                set(provenance) != {"generator", "version", "seed"}
                or not _text(provenance["generator"])
                or not _text(provenance["version"])
                or not isinstance(provenance["seed"], int)
                or isinstance(provenance["seed"], bool)
            ):
                raise ContractError(
                    "conformance_failed", "self-generated data lacks generator provenance"
                )
        if item["self_generated"] is False and item["generator_provenance"] is not None:
            raise ContractError("invalid_input", "external data has false generator provenance")
    splits = _mapping(value["splits"], "splits")
    if set(splits) != {"train", "validation", "test"}:
        raise ContractError("invalid_input", "P14 dataset splits are not exact")
    split_values = {
        key: _sequence(splits[key], f"{key} split", maximum=MAX_DATASET_ITEMS) for key in splits
    }
    split_sets = {key: set(values) for key, values in split_values.items()}
    if (
        set.union(*split_sets.values()) != item_ids
        or any(
            split_sets[left].intersection(split_sets[right])
            for left, right in (("train", "validation"), ("train", "test"), ("validation", "test"))
        )
        or any(len(split_sets[key]) != len(split_values[key]) for key in splits)
    ):
        raise ContractError("conformance_failed", "P14 dataset splits overlap or omit items")
    governance = _mapping(value["governance"], "governance")
    required_governance = {
        "all_items_rights_permitted": True,
        "consent_statuses_complete": True,
        "self_generated_items_identifiable": True,
        "held_out_test_sealed": True,
        "bytes_verified": False,
    }
    if dict(governance) != required_governance:
        raise ContractError("policy_refused", "P14 dataset governance account is invalid")
    flags = _mapping(value["safety_flags"], "safety_flags")
    if flags != {
        "training_executed": False,
        "evaluation_executed": False,
        "generation_performed": False,
    }:
        raise ContractError("policy_refused", "P14 dataset manifest records execution")
    return dict(value)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError("invalid_input", f"{label} must be an object")
    return value


def _sequence(value: Any, label: str, *, maximum: int = 256) -> Sequence[Any]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or not value
        or len(value) > maximum
    ):
        raise ContractError("invalid_input", f"{label} must be a bounded nonempty array")
    return value


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 4096


def _positive_integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ContractError("invalid_input", f"{label} must be a positive integer")
    return value


def _digest(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        return False
    return all(character in "0123456789abcdef" for character in value[7:])
