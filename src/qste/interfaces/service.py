"""Read-first P13 workbench and bounded operation broker."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any

from qste.core import SchemaRegistry, canonical_json_bytes, new_record_id
from qste.core.contracts import ContractError
from qste.interfaces.contracts import INTERFACE_PROFILE, InterfacePolicy
from qste.operations import (
    OperationResult,
    failure_result,
    inspect,
    relation_compare,
    trace_lineage,
    transduce,
    verify,
)
from qste.storage import RecordStore, WorkspacePaths

RELATION_TYPES = frozenset({"ProjectionSpec", "ComparisonSpec", "RelationAssertion"})
MAPPING_TYPES = frozenset({"MappingSpec", "TransductionEvent"})
CLAIM_TYPES = frozenset(
    {
        "DSQAssessment",
        "RevisionOutcome",
        "ListeningAccount",
        "AdjudicationDecision",
        "RelationAssertion",
    }
)
EVIDENCE_TYPES = frozenset(
    {
        "Observation",
        "RunManifest",
        "TaskSpec",
        "OperationReceipt",
        "ArtifactRecord",
        "AcquisitionEvent",
    }
)
TRANSDUCTION_MODES = {
    "sonify": "sonification",
    "desonify": "desonification",
    "resonify": "resonification",
    "transform": "sonic_transformation",
    "contrast": "cross_domain_contrast",
}


class InspectionWorkbench:
    """Produce bounded, read-only views without merging record identities."""

    def __init__(self, policy: InterfacePolicy) -> None:
        self.policy = policy
        self.store = RecordStore(WorkspacePaths.open(policy.workspace))

    def snapshot(
        self, *, record_id: str | None = None, maximum_items: int | None = None
    ) -> OperationResult:
        limit = self.policy.bounded_items(maximum_items)
        stored = self.store.iter_records()
        selected = stored[-limit:]
        groups: dict[str, list[dict[str, Any]]] = {
            "relations_and_disagreements": [],
            "mappings": [],
            "claims": [],
            "evidence": [],
        }
        for item in selected:
            summary = _summary(item.record, item.record_digest, item.storage_sequence)
            if item.record_type in RELATION_TYPES:
                groups["relations_and_disagreements"].append(summary)
            if item.record_type in MAPPING_TYPES:
                groups["mappings"].append(summary)
            if item.record_type in CLAIM_TYPES:
                groups["claims"].append(summary)
            if item.record_type in EVIDENCE_TYPES:
                groups["evidence"].append(summary)

        focus: dict[str, Any] | None = None
        if record_id is not None:
            occurrence = self.store.get_record(record_id)
            ancestors = self.store.trace_lineage(
                record_id,
                direction="ancestors",
                maximum_depth=self.policy.maximum_lineage_depth,
            )
            descendants = self.store.trace_lineage(
                record_id,
                direction="descendants",
                maximum_depth=self.policy.maximum_lineage_depth,
            )
            focus = {
                "record": occurrence.record,
                "record_digest": occurrence.record_digest,
                "storage_sequence": occurrence.storage_sequence,
                "ancestor_edges": [_edge(value) for value in ancestors[:limit]],
                "descendant_edges": [_edge(value) for value in descendants[:limit]],
            }

        counts = Counter(item.record_type for item in stored)
        value = {
            "payload_schema_id": "qste-payload/0.3.0",
            "payload_type": "CapabilityAccount",
            "items": [],
            "data": {
                "profile": INTERFACE_PROFILE,
                "workspace": "caller_owned_explicit_root",
                "record_count": len(stored),
                "record_type_counts": dict(sorted(counts.items())),
                "groups": groups,
                "focus": focus,
                "inference_is_measurement": False,
                "render_is_source": False,
                "mutations_enabled": self.policy.mutations_enabled,
                "truncated": len(stored) > limit,
            },
        }
        result: OperationResult = {
            "contract_id": "qste-contract/0.3.0",
            "operation": "qste:workbench-snapshot/0.1.0",
            "value_type": "qste-payload/0.3.0/CapabilityAccount",
            "operation_status": "completed",
            "value": value,
            "reason_code": "completed",
            "authorization_status": "not_applicable",
            "capability_status": "available",
            "receipt_id": new_record_id("OperationReceipt"),
            "diagnostics": {
                "maximum_items": limit,
                "maximum_lineage_depth": self.policy.maximum_lineage_depth,
            },
            "cli_exit_class": 0,
        }
        SchemaRegistry().validate_operation_result(result)
        return result


class InterfaceBroker:
    """Map each interface method to one bounded versioned Python operation."""

    def __init__(self, policy: InterfacePolicy) -> None:
        self.policy = policy
        self.workbench = InspectionWorkbench(policy)

    def inspect(self, record_id: str) -> OperationResult:
        return self._read("qste:inspect/0.3.0", lambda: inspect(self.policy.workspace, record_id))

    def lineage(
        self, record_id: str, *, direction: str = "ancestors", maximum_depth: int = 16
    ) -> OperationResult:
        depth = self.policy.bounded_depth(maximum_depth)
        return self._read(
            "qste:lineage/0.3.0",
            lambda: trace_lineage(
                self.policy.workspace, record_id, direction=direction, maximum_depth=depth
            ),
        )

    def verify(self) -> OperationResult:
        return self._read("qste:verify/0.3.0", lambda: verify(workspace=self.policy.workspace))

    def snapshot(
        self, *, record_id: str | None = None, maximum_items: int | None = None
    ) -> OperationResult:
        return self._read(
            "qste:workbench-snapshot/0.1.0",
            lambda: self.workbench.snapshot(record_id=record_id, maximum_items=maximum_items),
        )

    def compare(
        self,
        *,
        comparison_spec_record_id: str,
        source_candidate_record_ids: list[str],
        target_candidate_record_ids: list[str],
        evidence: Mapping[str, Any],
        approved: bool,
    ) -> OperationResult:
        return self._mutation(
            "qste:compare_relations/0.1.0",
            approved,
            evidence,
            lambda: relation_compare(
                self.policy.workspace,
                comparison_spec_record_id=comparison_spec_record_id,
                source_candidate_record_ids=source_candidate_record_ids,
                target_candidate_record_ids=target_candidate_record_ids,
                evidence=evidence,
                authorization_status="permitted",
            ),
        )

    def transduce(
        self,
        *,
        mode: str,
        source_record_ids: list[str],
        mapping_record_id: str,
        parameters: Mapping[str, Any],
        approved: bool,
    ) -> OperationResult:
        canonical_mode = TRANSDUCTION_MODES.get(mode)
        if canonical_mode is None:
            return failure_result(
                "qste:transduce/0.1.0",
                ContractError("invalid_input", "unknown P13 transduction mode"),
            )
        return self._mutation(
            f"qste:transduce_{canonical_mode}/0.1.0",
            approved,
            parameters,
            lambda: transduce(
                self.policy.workspace,
                mode=canonical_mode,
                source_record_ids=source_record_ids,
                mapping_record_id=mapping_record_id,
                parameters=parameters,
                authorization_status="permitted",
            ),
        )

    def _read(self, operation: str, function: Callable[[], OperationResult]) -> OperationResult:
        try:
            return function()
        except ContractError as error:
            return failure_result(operation, error)

    def _mutation(
        self,
        operation: str,
        approved: bool,
        payload: Mapping[str, Any],
        function: Callable[[], OperationResult],
    ) -> OperationResult:
        try:
            self.policy.require_mutation_approval(approved)
            if len(canonical_json_bytes(dict(payload))) > self.policy.maximum_input_bytes:
                raise ContractError("invalid_input", "P13 tool input exceeds its byte bound")
            return function()
        except ContractError as error:
            return failure_result(operation, error)


def _summary(record: Mapping[str, Any], digest: str, sequence: int) -> dict[str, Any]:
    return {
        "storage_sequence": sequence,
        "record_id": record["record_id"],
        "record_type": record["record_type"],
        "created_at": record["created_at"],
        "semantic_key": record.get("semantic_key"),
        "record_digest": digest,
        "evidence_class": _evidence_class(str(record["record_type"])),
        "domain_status": _domain_status(record),
    }


def _evidence_class(record_type: str) -> str:
    if record_type == "ListeningAccount":
        return "human_report"
    if record_type in {"Observation", "AcquisitionEvent"}:
        return "instrument_or_imported_observation"
    if record_type in {"RunManifest", "OperationReceipt", "ArtifactRecord"}:
        return "execution_or_artifact_evidence"
    if record_type in CLAIM_TYPES:
        return "derived_claim_or_assessment"
    return "recorded_state"


def _domain_status(record: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "assessment_status",
        "comparison_status",
        "authorization_status",
        "consent_status",
        "artifact_availability",
        "qste:pilotStatus",
    )
    return {key: record[key] for key in keys if key in record}


def _edge(value: Any) -> dict[str, Any]:
    return {
        "edge_sequence": value.edge_sequence,
        "source_record_id": value.source_record_id,
        "target_record_id": value.target_record_id,
        "relation": value.relation,
    }
