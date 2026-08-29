"""Deterministic, local STFT/Gabor reference arm for QSTE P5."""

from __future__ import annotations

import io
import itertools
import math
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
import numpy.typing as npt
from scipy.signal import get_window  # type: ignore[import-untyped]

from qste.core import canonical_json_bytes, content_digest, semantic_key_from_value, utc_timestamp
from qste.core.contracts import BASE_URI, ContractError
from qste.core.p5_contracts import (
    FAMILY_PROFILE,
    INTERVENTION_PROFILE,
    PROJECTION_PROFILE,
    REFINEMENT_PROFILE,
    STFT_PROFILE,
    THEORETICAL_BOUND,
)
from qste.ingress.records import bind_semantic_key, operation_receipt, record_base, record_ref
from qste.representations.models import RepresentationOperationOutcome, STFTConfig
from qste.storage import ArtifactStore, DenseStore, RecordStore, WorkspacePaths

ALGORITHM_DIGEST = content_digest(
    b"qste-stft-gabor/v0.1|manual-rfft|periodic-hann|canonical-periodic-dual|center-pad"
)
CANDIDATE_RULE = "qste-candidate-rule/explicit-stft-masks-v0.1"
MAX_DENSE_ELEMENTS = 50_000_000


class STFTService:
    """Execute the complete bounded P5 representation capability surface."""

    def __init__(self, workspace: Path) -> None:
        self.store = RecordStore(WorkspacePaths.open(workspace))
        self.artifacts = ArtifactStore(self.store.paths)
        self.dense = DenseStore(self.store.paths, self.store)

    def encode(
        self,
        *,
        artifact_record_id: str,
        aperture_record_id: str,
        config: STFTConfig,
        authorization_status: str = "permitted",
    ) -> RepresentationOperationOutcome:
        """Encode one P4 audio artifact into a pinned deterministic STFT instance."""

        timestamp = utc_timestamp()
        artifact = self._record(artifact_record_id, "ArtifactRecord")
        aperture = self._record(aperture_record_id, "ApertureSpec")
        self._authorize(authorization_status)
        self._require_aperture_operation(aperture, "encode")
        if aperture["input_ref"]["record_id"] != artifact_record_id:
            raise ContractError("invalid_input", "aperture input does not match encoded artifact")
        samples = self._waveform(artifact)
        sample_rate = _positive_int(artifact.get("qste:sampleRateHz"), "sample rate")
        _validate_config(config, sample_rate)
        coefficients, times, frequencies, analysis = _analysis(samples, sample_rate, config)
        dense_object, dense_artifact = self._write_dense_artifact(
            coefficients,
            coordinates={
                "channel": np.arange(coefficients.shape[0], dtype=np.int64),
                "frequency_hz": frequencies,
                "frame_time_seconds": times,
            },
            dimension_names=("channel", "frequency_hz", "frame_time_seconds"),
            chunks=(1, min(129, coefficients.shape[1]), min(128, coefficients.shape[2])),
            role="coefficient_dense_manifest",
            timestamp=timestamp,
            references=[record_ref(artifact_record_id, "ArtifactRecord", "derived_from")],
        )

        receipt_id = cast(str, record_base("OperationReceipt", created_at=timestamp)["record_id"])
        spec = self._representation_spec(config, sample_rate, analysis, timestamp)
        instance_id = cast(
            str, record_base("RepresentationInstance", created_at=timestamp)["record_id"]
        )
        mapping = self._identity_mapping(spec, timestamp)
        intervention = self._intervention_spec(spec, timestamp)
        projection = self._projection_spec(spec, timestamp)
        family_id = cast(
            str, record_base("RepresentationFamilySpec", created_at=timestamp)["record_id"]
        )
        instance = record_base(
            "RepresentationInstance", created_at=timestamp, record_id=instance_id
        ) | {
            "source_artifact_ref": record_ref(artifact_record_id, "ArtifactRecord"),
            "representation_spec_ref": record_ref(spec["record_id"], "RepresentationSpec"),
            "execution_receipt_ref": record_ref(receipt_id, "OperationReceipt"),
            "dense_data_ref": record_ref(dense_artifact["record_id"], "ArtifactRecord"),
            "instance_context": {
                "aperture_ref": record_ref(aperture_record_id, "ApertureSpec"),
                "boundary": "center_zero_pad",
                "network_access": False,
            },
            "qste:gaborProfile": STFT_PROFILE,
            "qste:sampleRateHz": sample_rate,
            "qste:originalFrameCount": int(samples.shape[0]),
            "qste:channelCount": int(samples.shape[1]),
            "qste:coefficientShape": list(coefficients.shape),
            "qste:coefficientCount": int(coefficients.size),
            "qste:denseId": dense_object.dense_id,
            "qste:familyRef": record_ref(family_id, "RepresentationFamilySpec"),
            "qste:defaultInterventionRef": record_ref(
                intervention["record_id"], "InterventionSpec"
            ),
            "qste:defaultProjectionRef": record_ref(projection["record_id"], "ProjectionSpec"),
            "qste:dsqCapability": "available_via_qste-dsq-assessment/v0.1",
        }
        bind_semantic_key(
            instance,
            "qste-semantic-key/representation-instance-stft-v1",
            {
                "source_content_digest": artifact.get("content_digest"),
                "representation_spec_semantic_key": spec["semantic_key"],
                "aperture_record_id": aperture_record_id,
                "dense_manifest_digest": dense_object.manifest_digest,
            },
        )
        family = record_base(
            "RepresentationFamilySpec", created_at=timestamp, record_id=family_id
        ) | {
            "family_id": "qste-representation-family/stft-gabor",
            "family_version": "v0.1",
            "spec_refs": [record_ref(spec["record_id"], "RepresentationSpec")],
            "instance_refs": [record_ref(instance_id, "RepresentationInstance")],
            "mapping_refs": [record_ref(mapping["record_id"], "MappingSpec")],
            "permitted_refinements": [
                {
                    "profile": REFINEMENT_PROFILE,
                    "order": "strict_nonempty_mask_subset",
                    "termination": "finite_boolean_subset_lattice",
                }
            ],
            "qste:familyProfile": FAMILY_PROFILE,
            "qste:knownIncomparabilities": [
                "native STFT distance is not a cross-representation metric"
            ],
        }
        bind_semantic_key(
            family,
            "qste-semantic-key/representation-family-instance-v1",
            {
                "profile": FAMILY_PROFILE,
                "spec": spec["semantic_key"],
                "instance": instance["semantic_key"],
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            record_id=receipt_id,
            request_ref=record_ref(aperture_record_id, "ApertureSpec"),
            authorization_status=authorization_status,
            operation="encode",
            inputs=[
                record_ref(artifact_record_id, "ArtifactRecord"),
                record_ref(aperture_record_id, "ApertureSpec"),
            ],
            parameters=_config_value(config),
            outputs=[
                record_ref(instance_id, "RepresentationInstance", "produced_by"),
                record_ref(dense_artifact["record_id"], "ArtifactRecord", "produced_by"),
            ],
            tool_id="qste-stft-gabor",
            tool_version="v0.1",
        )
        records = [
            spec,
            dense_artifact,
            mapping,
            intervention,
            projection,
            instance,
            family,
            receipt,
        ]
        _, event = self.store.insert_records_with_event(
            records,
            domain_event_record_id=None,
            event_type="qste:stft-encoded/0.1",
            subject_record_id=instance_id,
            receipt_record_id=receipt_id,
            payload={
                "profile": STFT_PROFILE,
                "dense_manifest_digest": dense_object.manifest_digest,
                "dsq_status": "not_assessed",
            },
            created_at=timestamp,
        )
        return RepresentationOperationOutcome(
            self.store.get_record(instance_id).record,
            f"{BASE_URI}/records/representation-instance.schema.json",
            receipt,
            event.event_sequence,
        )

    def enumerate(
        self,
        *,
        instance_record_id: str,
        candidate_rule: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> RepresentationOperationOutcome:
        """Materialize only an explicitly bounded sparse candidate selection."""

        self._authorize(authorization_status)
        instance, spec = self._instance_and_spec(instance_record_id)
        masks = _candidate_masks(candidate_rule, instance, spec)
        timestamp = utc_timestamp()
        candidates = [
            self._candidate_record(instance, spec, mask, timestamp, CANDIDATE_RULE)
            for mask in masks
        ]
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(instance_record_id, "RepresentationInstance"),
            authorization_status=authorization_status,
            operation="enumerate",
            inputs=[record_ref(instance_record_id, "RepresentationInstance")],
            parameters=dict(candidate_rule),
            outputs=[
                record_ref(candidate["record_id"], "CandidateUnit", "produced_by")
                for candidate in candidates
            ],
            tool_id="qste-stft-gabor",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [*candidates, receipt],
            domain_event_record_id=None,
            event_type="qste:stft-candidates-enumerated/0.1",
            subject_record_id=instance_record_id,
            receipt_record_id=receipt["record_id"],
            payload={"candidate_count": len(candidates), "rule": CANDIDATE_RULE},
            created_at=timestamp,
        )
        payload = _payload(
            "CandidateSet",
            items=candidates,
            data={
                "representation_instance_ref": record_ref(
                    instance_record_id, "RepresentationInstance"
                ),
                "candidate_rule_version": CANDIDATE_RULE,
                "candidate_only": True,
            },
        )
        return RepresentationOperationOutcome(
            payload,
            "qste-payload/0.3.0/CandidateSet",
            receipt,
            event.event_sequence,
        )

    def refine(
        self,
        *,
        candidate_record_id: str,
        procedure: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> RepresentationOperationOutcome:
        """Build the complete nonempty proper-subset closure before effect evidence."""

        self._authorize(authorization_status)
        candidate = self._record(candidate_record_id, "CandidateUnit")
        instance, spec = self._instance_and_spec(
            cast(str, candidate["representation_instance_ref"]["record_id"])
        )
        cells = _cells(candidate)
        if len(cells) == 1:
            error = ContractError(
                "capability_unavailable",
                "singleton candidate has an empty proper-node set; "
                "qualification route is indeterminate",
            )
            error.receipt_id = self._failure_receipt(
                "refine", candidate, procedure, error, authorization_status
            )
            raise error
        expected = (2 ** len(cells)) - 2
        budget = _positive_int(procedure.get("maximum_nodes"), "refinement node budget")
        configured = cast(int, spec["capacity"]["maximum_refinement_nodes"])
        if expected > min(budget, configured):
            error = ContractError("capability_unavailable", "refinement closure exceeds its budget")
            error.receipt_id = self._failure_receipt(
                "refine", candidate, procedure, error, authorization_status
            )
            raise error
        timestamp = utc_timestamp()
        masks = [
            tuple(combination)
            for size in range(1, len(cells))
            for combination in itertools.combinations(cells, size)
        ]
        nodes = [
            self._candidate_record(instance, spec, mask, timestamp, CANDIDATE_RULE)
            for mask in masks
        ]
        by_mask = {_cell_key(_cells(node)): node for node in nodes}
        root_key = _cell_key(cells)
        node_ids = {root_key: candidate_record_id} | {
            key: cast(str, node["record_id"]) for key, node in by_mask.items()
        }
        all_masks = [cells, *masks]
        edges: list[dict[str, Any]] = []
        for parent in all_masks:
            if len(parent) <= 1:
                continue
            for child in itertools.combinations(parent, len(parent) - 1):
                edges.append(
                    {
                        "parent_candidate_id": node_ids[_cell_key(parent)],
                        "child_candidate_id": node_ids[_cell_key(child)],
                        "relation": "strict_nonempty_mask_subset",
                    }
                )
        family_ref = instance["qste:familyRef"]
        intervention_ref = instance["qste:defaultInterventionRef"]
        graph = record_base("RefinementGraph", created_at=timestamp) | {
            "procedure_id": REFINEMENT_PROFILE,
            "representation_family_ref": dict(family_ref),
            "intervention_ref": dict(intervention_ref),
            "root_candidate_ref": record_ref(candidate_record_id, "CandidateUnit"),
            "nodes": [candidate_record_id, *[node["record_id"] for node in nodes]],
            "edges": edges,
            "required_closure": [node["record_id"] for node in nodes],
            "completion_certificate": {
                "complete": True,
                "proper_node_count": len(nodes),
                "expected_boolean_subset_count": expected,
                "effect_pruning": False,
                "terminal_rule": "singleton_native_leaf",
                "closure_digest": content_digest(
                    canonical_json_bytes([node["semantic_key"] for node in nodes])
                ),
            },
            "closed": True,
            "qste:refinementProfile": REFINEMENT_PROFILE,
            "qste:gaborBoundUsedAsRefinementEvidence": False,
            "qste:dsqAssessmentStatus": "available_in_P6_as_separate_record",
            "qste:nodeMetadata": [
                {
                    "candidate_ref": record_ref(candidate_record_id, "CandidateUnit"),
                    "cell_count": len(cells),
                    "root": True,
                },
                *[
                    {
                        "candidate_ref": record_ref(node["record_id"], "CandidateUnit"),
                        "cell_count": len(_cells(node)),
                        "root": False,
                    }
                    for node in nodes
                ],
            ],
        }
        bind_semantic_key(
            graph,
            "qste-semantic-key/refinement-graph-stft-v1",
            {
                "root_candidate_semantic_key": candidate["semantic_key"],
                "procedure": REFINEMENT_PROFILE,
                "required_closure": [node["semantic_key"] for node in nodes],
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(candidate_record_id, "CandidateUnit"),
            authorization_status=authorization_status,
            operation="refine",
            inputs=[record_ref(candidate_record_id, "CandidateUnit")],
            parameters=dict(procedure),
            outputs=[record_ref(graph["record_id"], "RefinementGraph", "produced_by")],
            tool_id="qste-stft-gabor",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [*nodes, graph, receipt],
            domain_event_record_id=None,
            event_type="qste:stft-refinement-closed/0.1",
            subject_record_id=graph["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"proper_node_count": len(nodes), "effect_pruning": False},
            created_at=timestamp,
        )
        return RepresentationOperationOutcome(
            graph,
            f"{BASE_URI}/records/refinement-graph.schema.json",
            receipt,
            event.event_sequence,
        )

    def support(
        self,
        *,
        candidate_record_id: str,
        support_spec: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> RepresentationOperationOutcome:
        """Estimate native mask support and effective resynthesized intervention support."""

        self._authorize(authorization_status)
        candidate = self._record(candidate_record_id, "CandidateUnit")
        instance, spec = self._instance_and_spec(
            cast(str, candidate["representation_instance_ref"]["record_id"])
        )
        native = dict(candidate["native_support"])
        coefficients, coordinates = self._instance_coefficients(instance)
        modified = coefficients.copy()
        for channel, frequency, frame in _cells(candidate):
            modified[channel, frequency, frame] = 0
        original = _synthesis(coefficients, instance, spec)
        counterfactual = _synthesis(modified, instance, spec)
        floor = _nonnegative_float(
            support_spec.get("difference_floor", spec["parameters"]["footprint_floor"]),
            "support floor",
        )
        difference = np.max(np.abs(original - counterfactual), axis=1)
        active = np.flatnonzero(difference > floor)
        duration = original.shape[0] / cast(float, instance["qste:sampleRateHz"])
        if active.size:
            effective_time: list[float] | str = [
                float(active[0] / instance["qste:sampleRateHz"]),
                float((active[-1] + 1) / instance["qste:sampleRateHz"]),
            ]
            boundary = bool(active[0] == 0 or active[-1] == original.shape[0] - 1)
        else:
            effective_time = "absent"
            boundary = False
        payload = _payload(
            "SupportEstimate",
            items=[],
            data={
                "candidate_ref": record_ref(candidate_record_id, "CandidateUnit"),
                "native_support": native,
                "effective_intervention_support": {
                    "time_seconds": effective_time,
                    "threshold": floor,
                    "boundary_affected": boundary,
                    "maximum_absolute_difference": float(np.max(difference, initial=0.0)),
                    "frequency_support": "estimated_from_native_mask_not_substituted",
                },
                "frame_coordinates_verified": bool(
                    len(coordinates["frame_time_seconds"]) == coefficients.shape[2]
                ),
                "atom_spread_ref": spec["qste:realizedAtomSpread"],
                "candidate_support_is_atom_spread": False,
                "duration_seconds": duration,
            },
        )
        return self._receipt_payload(
            "support",
            candidate,
            support_spec,
            payload,
            "SupportEstimate",
            authorization_status,
        )

    def address(
        self,
        *,
        candidate_record_id: str,
        intervention_record_id: str,
        authorization_status: str = "permitted",
    ) -> RepresentationOperationOutcome:
        """Verify that every candidate cell is independently operable by the native arm."""

        self._authorize(authorization_status)
        candidate = self._record(candidate_record_id, "CandidateUnit")
        intervention = self._record(intervention_record_id, "InterventionSpec")
        instance, spec = self._instance_and_spec(
            cast(str, candidate["representation_instance_ref"]["record_id"])
        )
        _validate_cells(_cells(candidate), cast(list[int], instance["qste:coefficientShape"]))
        payload = _payload(
            "AddressabilityResult",
            items=[],
            data={
                "candidate_ref": record_ref(candidate_record_id, "CandidateUnit"),
                "intervention_ref": record_ref(intervention_record_id, "InterventionSpec"),
                "addressable": True,
                "native_unit": spec["native_unit"],
                "supported_operations": intervention["native_operation"]["modes"],
                "cell_count": len(_cells(candidate)),
                "phase_access": "preserved",
            },
        )
        return self._receipt_payload(
            "address",
            candidate,
            {"intervention_record_id": intervention_record_id},
            payload,
            "AddressabilityResult",
            authorization_status,
        )

    def intervene(
        self,
        *,
        candidate_record_id: str,
        intervention_record_id: str,
        mode: str,
        control: str = "authentic",
        authorization_status: str = "permitted",
    ) -> RepresentationOperationOutcome:
        """Apply one pinned native intervention or its declared artifact control."""

        self._authorize(authorization_status)
        candidate = self._record(candidate_record_id, "CandidateUnit")
        intervention = self._record(intervention_record_id, "InterventionSpec")
        if mode not in intervention["native_operation"]["modes"]:
            raise ContractError("capability_unavailable", "intervention mode is unsupported")
        if control not in {"authentic", "resynthesis_only", "off_target", "alternate"}:
            raise ContractError("invalid_input", "unknown intervention control")
        instance, _ = self._instance_and_spec(
            cast(str, candidate["representation_instance_ref"]["record_id"])
        )
        coefficients, coordinates = self._instance_coefficients(instance)
        modified, applied_cells = _apply_intervention(
            coefficients,
            _cells(candidate),
            mode=mode,
            control=control,
        )
        coefficient_change = float(np.max(np.abs(modified - coefficients), initial=0.0))
        candidate_cell_set = set(_cells(candidate))
        applied_cell_set = set(applied_cells)
        control_diagnostics = {
            "coefficient_maximum_change": coefficient_change,
            "applied_candidate_overlap": len(candidate_cell_set & applied_cell_set),
            "passed": (
                coefficient_change == 0
                if control == "resynthesis_only"
                else (
                    bool(applied_cell_set)
                    and coefficient_change > 0
                    and not bool(candidate_cell_set & applied_cell_set)
                    if control == "off_target"
                    else bool(applied_cell_set) and coefficient_change > 0
                )
            ),
        }
        timestamp = utc_timestamp()
        dense_object, dense_artifact = self._write_dense_artifact(
            modified,
            coordinates=coordinates,
            dimension_names=("channel", "frequency_hz", "frame_time_seconds"),
            chunks=(1, min(129, modified.shape[1]), min(128, modified.shape[2])),
            role="intervened_coefficient_dense_manifest",
            timestamp=timestamp,
            references=[
                record_ref(
                    instance["dense_data_ref"]["record_id"], "ArtifactRecord", "derived_from"
                ),
                record_ref(candidate_record_id, "CandidateUnit", "depends_on"),
                record_ref(intervention_record_id, "InterventionSpec", "depends_on"),
            ],
            extra={
                "qste:representationInstanceRef": record_ref(
                    instance["record_id"], "RepresentationInstance"
                ),
                "qste:interventionSpecRef": record_ref(intervention_record_id, "InterventionSpec"),
                "qste:candidateRef": record_ref(candidate_record_id, "CandidateUnit"),
                "qste:interventionMode": mode,
                "qste:controlMode": control,
                "qste:appliedCells": [list(cell) for cell in applied_cells],
                "qste:controlDiagnostics": control_diagnostics,
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(candidate_record_id, "CandidateUnit"),
            authorization_status=authorization_status,
            operation="intervene",
            inputs=[
                record_ref(candidate_record_id, "CandidateUnit"),
                record_ref(intervention_record_id, "InterventionSpec"),
            ],
            parameters={"mode": mode, "control": control},
            outputs=[record_ref(dense_artifact["record_id"], "ArtifactRecord", "produced_by")],
            tool_id="qste-stft-gabor",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [dense_artifact, receipt],
            domain_event_record_id=None,
            event_type="qste:stft-intervened/0.1",
            subject_record_id=dense_artifact["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={
                "mode": mode,
                "control": control,
                "applied_cell_count": len(applied_cells),
                "dense_manifest_digest": dense_object.manifest_digest,
                "control_passed": control_diagnostics["passed"],
            },
            created_at=timestamp,
        )
        payload = _payload(
            "IntervenedState",
            items=[dense_artifact],
            data={
                "candidate_ref": record_ref(candidate_record_id, "CandidateUnit"),
                "intervention_ref": record_ref(intervention_record_id, "InterventionSpec"),
                "dense_artifact_ref": record_ref(dense_artifact["record_id"], "ArtifactRecord"),
                "mode": mode,
                "control": control,
                "phase_preserved": mode in {"mask", "isolate", "phase_coherent_replace"},
                "control_diagnostics": control_diagnostics,
            },
        )
        return RepresentationOperationOutcome(
            payload,
            "qste-payload/0.3.0/IntervenedState",
            receipt,
            event.event_sequence,
        )

    def decode(
        self,
        *,
        target_record_id: str,
        authorization_status: str = "permitted",
    ) -> RepresentationOperationOutcome:
        """Phase-preservingly reconstruct a waveform from an instance or intervened state."""

        self._authorize(authorization_status)
        target = self.store.get_record(target_record_id).record
        if target["record_type"] == "RepresentationInstance":
            instance = target
            dense_artifact = self._record(
                cast(str, instance["dense_data_ref"]["record_id"]), "ArtifactRecord"
            )
            target_kind = "representation_instance"
        elif target["record_type"] == "ArtifactRecord" and target.get(
            "qste:representationArtifactRole"
        ) in {
            "intervened_coefficient_dense_manifest",
            "perturbed_coefficient_dense_manifest",
        }:
            dense_artifact = target
            instance = self._record(
                cast(str, target["qste:representationInstanceRef"]["record_id"]),
                "RepresentationInstance",
            )
            target_kind = "coefficient_derivative"
        else:
            raise ContractError("invalid_input", "decode target is not a P5 coefficient state")
        _, spec = self._instance_and_spec(cast(str, instance["record_id"]))
        coefficients, _ = self._dense_artifact_values(dense_artifact)
        waveform = _synthesis(coefficients, instance, spec)
        timestamp = utc_timestamp()
        stream = io.BytesIO()
        np.save(stream, waveform, allow_pickle=False)
        object_ = self.artifacts.put_bytes(stream.getvalue())
        self.store.register_artifact(
            object_.content_digest,
            object_.size,
            object_.relative_path,
            media_type="application/x-npy",
            registered_at=timestamp,
        )
        reconstruction = self._reconstruction_diagnostics(instance, waveform, target_kind)
        artifact = record_base(
            "ArtifactRecord",
            created_at=timestamp,
            references=[record_ref(target_record_id, target["record_type"], "derived_from")],
        ) | {
            "media_type": "application/x-npy",
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": object_.content_digest,
            "qste:gaborProfile": STFT_PROFILE,
            "qste:representationArtifactRole": "decoded_waveform",
            "qste:sizeBytes": object_.size,
            "qste:sampleRateHz": instance["qste:sampleRateHz"],
            "qste:frameCount": int(waveform.shape[0]),
            "qste:channelCount": int(waveform.shape[1]),
            "qste:representationInstanceRef": record_ref(
                instance["record_id"], "RepresentationInstance"
            ),
            "qste:reconstructionDiagnostics": reconstruction,
        }
        bind_semantic_key(
            artifact,
            "qste-semantic-key/decoded-representation-artifact-v1",
            {
                "target_record_id": target_record_id,
                "content_digest": object_.content_digest,
                "profile": STFT_PROFILE,
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=record_ref(target_record_id, target["record_type"]),
            authorization_status=authorization_status,
            operation="decode",
            inputs=[record_ref(target_record_id, target["record_type"])],
            parameters={"synthesis": "canonical_periodic_dual", "phase": "preserved"},
            outputs=[record_ref(artifact["record_id"], "ArtifactRecord", "produced_by")],
            tool_id="qste-stft-gabor",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [artifact, receipt],
            domain_event_record_id=None,
            event_type="qste:stft-decoded/0.1",
            subject_record_id=artifact["record_id"],
            receipt_record_id=receipt["record_id"],
            payload={"target_kind": target_kind, **reconstruction},
            created_at=timestamp,
        )
        return RepresentationOperationOutcome(
            artifact,
            f"{BASE_URI}/records/artifact-record.schema.json",
            receipt,
            event.event_sequence,
        )

    def project(
        self,
        *,
        candidate_record_id: str,
        projection_record_id: str,
        authorization_status: str = "permitted",
    ) -> RepresentationOperationOutcome:
        """Project a calibrated mock intervention footprint onto source time/channel."""

        self._authorize(authorization_status)
        candidate = self._record(candidate_record_id, "CandidateUnit")
        projection = self._record(projection_record_id, "ProjectionSpec")
        instance, spec = self._instance_and_spec(
            cast(str, candidate["representation_instance_ref"]["record_id"])
        )
        coefficients, _ = self._instance_coefficients(instance)
        modified = coefficients.copy()
        for cell in _cells(candidate):
            modified[cell] = 0
        baseline = _synthesis(coefficients, instance, spec)
        counterfactual = _synthesis(modified, instance, spec)
        energy = np.square(baseline - counterfactual)
        floor = cast(float, projection["footprint_method"]["floor"])
        energy[energy < floor] = 0
        total = float(np.sum(energy))
        normalized = energy / total if total > 0 else energy
        maximum_bins = cast(int, projection["footprint_method"]["maximum_time_bins"])
        binned, edges = _bin_footprint(normalized, maximum_bins)
        payload = _payload(
            "ProjectedFootprint",
            items=[],
            data={
                "candidate_ref": record_ref(candidate_record_id, "CandidateUnit"),
                "projection_ref": record_ref(projection_record_id, "ProjectionSpec"),
                "substrate": projection["comparison_substrate"],
                "footprint_kind": "expected_energy_change",
                "units": "unit_integral_mock_energy",
                "normalization": "unit_integral" if total > 0 else "zero_mass",
                "mass_before_normalization": total,
                "time_bin_edges_seconds": (
                    edges / cast(float, instance["qste:sampleRateHz"])
                ).tolist(),
                "values": binned.tolist(),
                "calibration": projection["calibration"],
                "zero_mass": total == 0,
                "cross_arm_relation": "not_computed_in_P5",
            },
        )
        return self._receipt_payload(
            "project",
            candidate,
            {"projection_record_id": projection_record_id},
            payload,
            "ProjectedFootprint",
            authorization_status,
        )

    def measure(
        self,
        *,
        left_candidate_record_id: str,
        right_candidate_record_id: str,
        metric_spec: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> RepresentationOperationOutcome:
        """Measure candidate coefficient vectors only in their shared native arm."""

        self._authorize(authorization_status)
        left = self._record(left_candidate_record_id, "CandidateUnit")
        right = self._record(right_candidate_record_id, "CandidateUnit")
        left_instance_id = cast(str, left["representation_instance_ref"]["record_id"])
        right_instance_id = cast(str, right["representation_instance_ref"]["record_id"])
        if left_instance_id != right_instance_id:
            raise ContractError(
                "capability_unavailable", "P5 native measure requires one representation instance"
            )
        instance, spec = self._instance_and_spec(left_instance_id)
        if metric_spec.get("metric") not in {"complex_l2", "magnitude_l2"}:
            raise ContractError("capability_unavailable", "native metric is unsupported")
        coefficients, _ = self._instance_coefficients(instance)
        left_values = np.asarray([coefficients[cell] for cell in _cells(left)])
        right_values = np.asarray([coefficients[cell] for cell in _cells(right)])
        if left_values.shape != right_values.shape:
            raise ContractError("invalid_input", "native measure requires equal candidate capacity")
        if metric_spec["metric"] == "complex_l2":
            distance = float(np.linalg.norm(left_values - right_values))
        else:
            distance = float(np.linalg.norm(np.abs(left_values) - np.abs(right_values)))
        payload = _payload(
            "NativeMeasure",
            items=[],
            data={
                "left_candidate_ref": record_ref(left_candidate_record_id, "CandidateUnit"),
                "right_candidate_ref": record_ref(right_candidate_record_id, "CandidateUnit"),
                "metric": metric_spec["metric"],
                "value": distance,
                "units": spec["metric"]["units"],
                "capacity": int(left_values.size),
                "native_only": True,
                "cross_arm_comparability": False,
            },
        )
        return self._receipt_payload(
            "measure",
            left,
            {
                **dict(metric_spec),
                "right_candidate_record_id": right_candidate_record_id,
            },
            payload,
            "NativeMeasure",
            authorization_status,
        )

    def perturb(
        self,
        *,
        instance_record_id: str,
        perturbation_spec: Mapping[str, Any],
        authorization_status: str = "permitted",
    ) -> RepresentationOperationOutcome:
        """Create a descendant representation instance under a declared perturbation."""

        self._authorize(authorization_status)
        instance, _ = self._instance_and_spec(instance_record_id)
        coefficients, coordinates = self._instance_coefficients(instance)
        mode = perturbation_spec.get("mode")
        modified = coefficients.copy()
        if mode == "coefficient_gain":
            gain = _finite_float(perturbation_spec.get("gain"), "coefficient gain")
            modified *= gain
        elif mode == "frame_shift":
            shift = perturbation_spec.get("frames")
            if not isinstance(shift, int) or isinstance(shift, bool):
                raise ContractError("invalid_input", "frame shift must be an integer")
            if abs(shift) >= modified.shape[2]:
                raise ContractError("invalid_input", "frame shift exceeds the representation")
            shifted = np.zeros_like(modified)
            if shift >= 0:
                shifted[:, :, shift:] = modified[:, :, : modified.shape[2] - shift or None]
            else:
                shifted[:, :, :shift] = modified[:, :, -shift:]
            modified = shifted
        else:
            raise ContractError("capability_unavailable", "perturbation mode is unsupported")
        timestamp = utc_timestamp()
        dense_object, dense_artifact = self._write_dense_artifact(
            modified,
            coordinates=coordinates,
            dimension_names=("channel", "frequency_hz", "frame_time_seconds"),
            chunks=(1, min(129, modified.shape[1]), min(128, modified.shape[2])),
            role="perturbed_coefficient_dense_manifest",
            timestamp=timestamp,
            references=[
                record_ref(
                    instance["dense_data_ref"]["record_id"], "ArtifactRecord", "derived_from"
                )
            ],
            extra={
                "qste:representationInstanceRef": record_ref(
                    instance_record_id, "RepresentationInstance"
                ),
                "qste:perturbation": dict(perturbation_spec),
            },
        )
        receipt_id = cast(str, record_base("OperationReceipt", created_at=timestamp)["record_id"])
        descendant = record_base(
            "RepresentationInstance",
            created_at=timestamp,
            references=[record_ref(instance_record_id, "RepresentationInstance", "derived_from")],
        ) | {
            "source_artifact_ref": dict(instance["source_artifact_ref"]),
            "representation_spec_ref": dict(instance["representation_spec_ref"]),
            "execution_receipt_ref": record_ref(receipt_id, "OperationReceipt"),
            "dense_data_ref": record_ref(dense_artifact["record_id"], "ArtifactRecord"),
            "instance_context": {
                **dict(instance["instance_context"]),
                "perturbation": dict(perturbation_spec),
            },
            **{
                key: value
                for key, value in instance.items()
                if key.startswith("qste:") and key not in {"qste:denseId"}
            },
            "qste:denseId": dense_object.dense_id,
        }
        bind_semantic_key(
            descendant,
            "qste-semantic-key/representation-instance-perturbation-v1",
            {
                "parent_semantic_key": instance["semantic_key"],
                "perturbation": dict(perturbation_spec),
                "dense_manifest_digest": dense_object.manifest_digest,
            },
        )
        receipt = operation_receipt(
            created_at=timestamp,
            record_id=receipt_id,
            request_ref=record_ref(instance_record_id, "RepresentationInstance"),
            authorization_status=authorization_status,
            operation="perturb",
            inputs=[record_ref(instance_record_id, "RepresentationInstance")],
            parameters=dict(perturbation_spec),
            outputs=[record_ref(descendant["record_id"], "RepresentationInstance", "produced_by")],
            tool_id="qste-stft-gabor",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [dense_artifact, descendant, receipt],
            domain_event_record_id=None,
            event_type="qste:stft-perturbed/0.1",
            subject_record_id=descendant["record_id"],
            receipt_record_id=receipt_id,
            payload={"mode": mode, "dense_manifest_digest": dense_object.manifest_digest},
            created_at=timestamp,
        )
        return RepresentationOperationOutcome(
            descendant,
            f"{BASE_URI}/records/representation-instance.schema.json",
            receipt,
            event.event_sequence,
        )

    def account(
        self,
        *,
        instance_record_id: str,
        authorization_status: str = "permitted",
    ) -> RepresentationOperationOutcome:
        """Return explicit supported, bounded, and unavailable P5 capabilities."""

        self._authorize(authorization_status)
        instance, spec = self._instance_and_spec(instance_record_id)
        payload = _payload(
            "CapabilityAccount",
            items=[],
            data={
                "profile": STFT_PROFILE,
                "representation_instance_ref": record_ref(
                    instance_record_id, "RepresentationInstance"
                ),
                "available_operations": [
                    "encode",
                    "enumerate",
                    "refine",
                    "support",
                    "address",
                    "intervene",
                    "decode",
                    "project",
                    "measure",
                    "perturb",
                    "account",
                ],
                "limits": spec["capacity"],
                "known_losses": spec["renderer_or_decoder"]["known_losses"],
                "network_access": False,
                "playback": "unavailable",
                "dsq_assessment": "unavailable_until_P6",
                "cross_representation_relation": "available_in_P7_as_separate_relation_engine",
                "numerical_reproducibility": "verified_within_declared_tolerance",
            },
        )
        return self._receipt_payload(
            "account",
            instance,
            {"profile": STFT_PROFILE},
            payload,
            "CapabilityAccount",
            authorization_status,
        )

    def _representation_spec(
        self,
        config: STFTConfig,
        sample_rate: int,
        analysis: Mapping[str, Any],
        timestamp: str,
    ) -> dict[str, Any]:
        bin_spacing = sample_rate / config.fft_length
        frames_per_second = sample_rate / config.hop_length
        frequency_bins = config.fft_length // 2 + 1
        record = record_base("RepresentationSpec", created_at=timestamp) | {
            "representation_id": STFT_PROFILE,
            "algorithm_or_model_digest": ALGORITHM_DIGEST,
            "parameters": _config_value(config),
            "native_unit": "complex_stft_coefficient_or_bounded_mask",
            "metric": {"id": "complex_l2_or_magnitude_l2", "units": "native_coefficient"},
            "capacity": {
                "maximum_candidates": config.maximum_candidates,
                "maximum_refinement_nodes": config.maximum_refinement_nodes,
                "maximum_dense_elements": MAX_DENSE_ELEMENTS,
            },
            "renderer_or_decoder": {
                "analysis": "manual_rfft_windowing",
                "synthesis": "canonical_periodic_dual_overlap_add",
                "boundary": "center_zero_pad",
                "phase": "preserved",
                "known_losses": [
                    "one-sided coefficients assume real waveform",
                    "intervention support can extend beyond native mask support",
                ],
            },
            "qste:gaborProfile": STFT_PROFILE,
            "qste:gaborAtomBound": {
                "constant": THEORETICAL_BOUND,
                "inequality": "temporal_std_seconds * spectral_std_hz >= constant",
                "convention": "standard_deviation_hz_seconds",
                "units": "Hz*s",
            },
            "qste:realizedAtomSpread": dict(analysis["realized_spread"]),
            "qste:analysisWindow": dict(analysis["analysis_window"]),
            "qste:dualWindow": dict(analysis["dual_window"]),
            "qste:lattice": {
                "fft_length": config.fft_length,
                "hop_length": config.hop_length,
                "bin_spacing_hz": bin_spacing,
                "lattice_cell_hz_seconds": bin_spacing * config.hop_length / sample_rate,
                "redundancy": config.fft_length / config.hop_length,
                "coefficient_density_per_second": frames_per_second * frequency_bins,
            },
            "qste:refinementContract": {
                "profile": REFINEMENT_PROFILE,
                "order": "strict_nonempty_mask_subset",
                "closure": "all_nonempty_proper_subsets",
                "effect_pruning": False,
            },
            "qste:pTerminal": {
                "rule": "singleton_native_leaf",
                "empty_proper_set_qualification": "indeterminate_not_qualified",
            },
            "qste:separationInvariant": {
                "atom_bound_is_lattice": False,
                "lattice_is_refinement": False,
                "candidate_support_is_atom_spread": False,
                "intervention_support_is_candidate_support": False,
                "projection_is_native_support": False,
            },
        }
        bind_semantic_key(
            record,
            "qste-semantic-key/representation-spec-stft-v1",
            {
                "profile": STFT_PROFILE,
                "algorithm_digest": ALGORITHM_DIGEST,
                "sample_rate_hz": sample_rate,
                "config": _config_value(config),
                "atom_bound_convention": record["qste:gaborAtomBound"],
            },
        )
        return record

    def _identity_mapping(self, spec: Mapping[str, Any], timestamp: str) -> dict[str, Any]:
        record = record_base("MappingSpec", created_at=timestamp) | {
            "source_domain": {"name": "stft_native_address", "profile": STFT_PROFILE},
            "target_domain": {"name": "stft_native_address", "profile": STFT_PROFILE},
            "variables": ["channel_index", "frequency_bin", "frame_index"],
            "units": {"source": "native_index", "target": "native_index"},
            "normalization": {"method": "none"},
            "uncertainty": {"propagation": "exact_identity"},
            "missing_data_behavior": "refuse",
            "interpolation": {"method": "none"},
            "range": {"bounded_by": "representation_instance_shape"},
            "loss": {"declared": False},
            "reversibility_claim": "exact_identity_within_one_spec",
            "qste:gaborNativeMapping": True,
        }
        bind_semantic_key(
            record,
            "qste-semantic-key/stft-native-identity-mapping-v1",
            {"representation_spec": spec["semantic_key"], "profile": STFT_PROFILE},
        )
        return record

    def _intervention_spec(self, spec: Mapping[str, Any], timestamp: str) -> dict[str, Any]:
        record = record_base(
            "InterventionSpec",
            created_at=timestamp,
            references=[record_ref(cast(str, spec["record_id"]), "RepresentationSpec")],
        ) | {
            "operator_family": INTERVENTION_PROFILE,
            "native_operation": {
                "modes": ["mask", "isolate", "phase_coherent_replace"],
                "address": "sorted_stft_mask_cells",
                "phase_behavior": "preserve_except_zeroed_coefficients",
            },
            "reference_distribution": {
                "phase_coherent_replace": "adjacent_frame_magnitude_mean_with_original_phase",
                "empty_neighbor_behavior": "zero",
            },
            "renderer_or_decoder": {
                "profile": STFT_PROFILE,
                "synthesis": "canonical_periodic_dual_overlap_add",
            },
            "controls": [
                "resynthesis_only",
                "off_target",
                "alternate_half_gain",
            ],
            "random_source": {"kind": "deterministic", "seed": 0},
            "qste:interventionProfile": INTERVENTION_PROFILE,
            "qste:knownFailureModes": [
                "boundary support expansion",
                "off-target cell unavailable at final frame",
                "replacement neighbor absent",
            ],
        }
        bind_semantic_key(
            record,
            "qste-semantic-key/stft-intervention-spec-v1",
            {"representation_spec": spec["semantic_key"], "profile": INTERVENTION_PROFILE},
        )
        return record

    def _projection_spec(self, spec: Mapping[str, Any], timestamp: str) -> dict[str, Any]:
        record = record_base("ProjectionSpec", created_at=timestamp) | {
            "source_arm_ref": record_ref(cast(str, spec["record_id"]), "RepresentationSpec"),
            "comparison_substrate": {
                "id": "qste-mock-source-time-channel/0.1",
                "axes": ["time_seconds", "channel"],
                "not_physical_calibration": True,
            },
            "measure": {"name": "expected_energy_change", "units": "digital_amplitude_squared"},
            "footprint_method": {
                "name": "decoded_intervention_difference_squared",
                "floor": spec["parameters"]["footprint_floor"],
                "maximum_time_bins": 512,
                "normalization": "unit_integral_when_nonzero",
            },
            "calibration": {
                "status": "mock_digital_exact_scale",
                "scale": 1.0,
                "physical_claims": "prohibited",
            },
            "qste:projectionProfile": PROJECTION_PROFILE,
            "qste:failureConditions": ["zero_mass", "decode_failure", "alignment_failure"],
        }
        bind_semantic_key(
            record,
            "qste-semantic-key/stft-projection-spec-v1",
            {"representation_spec": spec["semantic_key"], "profile": PROJECTION_PROFILE},
        )
        return record

    def _candidate_record(
        self,
        instance: Mapping[str, Any],
        spec: Mapping[str, Any],
        cells: Sequence[tuple[int, int, int]],
        timestamp: str,
        candidate_rule_version: str,
    ) -> dict[str, Any]:
        canonical_cells = tuple(sorted(set(cells)))
        _validate_cells(canonical_cells, cast(list[int], instance["qste:coefficientShape"]))
        sample_rate = cast(float, instance["qste:sampleRateHz"])
        fft_length = cast(int, spec["parameters"]["fft_length"])
        hop_length = cast(int, spec["parameters"]["hop_length"])
        centers = [
            ((cell[2] * hop_length) - fft_length / 2) / sample_rate for cell in canonical_cells
        ]
        frequencies = [cell[1] * sample_rate / fft_length for cell in canonical_cells]
        duration = cast(int, instance["qste:originalFrameCount"]) / sample_rate
        half_window = fft_length / (2 * sample_rate)
        half_bin = sample_rate / fft_length / 2
        native_support = {
            "time_seconds": [
                max(0.0, min(centers) - half_window),
                min(duration, max(centers) + half_window),
            ],
            "frequency_hz": [
                max(0.0, min(frequencies) - half_bin),
                min(sample_rate / 2, max(frequencies) + half_bin),
            ],
            "channels": sorted({cell[0] for cell in canonical_cells}),
            "support_kind": "finite_window_and_bin_interval_estimate",
            "atom_spread_substitution": False,
        }
        record = record_base("CandidateUnit", created_at=timestamp) | {
            "representation_instance_ref": record_ref(
                cast(str, instance["record_id"]), "RepresentationInstance"
            ),
            "native_address": {
                "kind": "stft_mask",
                "cells": [list(cell) for cell in canonical_cells],
                "coordinate_order": ["channel_index", "frequency_bin", "frame_index"],
            },
            "candidate_rule_version": candidate_rule_version,
            "native_support": native_support,
            "qste:gaborProfile": STFT_PROFILE,
            "qste:pTerminal": {
                "rule": "singleton_native_leaf",
                "is_terminal": len(canonical_cells) == 1,
                "required_proper_set": "empty" if len(canonical_cells) == 1 else "nonempty",
                "empty_set_qualification": "indeterminate",
            },
            "qste:candidateMaskCellCount": len(canonical_cells),
            "qste:dsqStatus": "candidate_only",
            "qste:atomBoundEvidence": "not_used_for_candidate_identity_or_refinement",
        }
        record["semantic_key"] = semantic_key_from_value(
            "qste-semantic-key/candidate-unit-v1",
            {
                "representation_instance_semantic_key": instance["semantic_key"],
                "native_address": record["native_address"],
                "candidate_rule_version": candidate_rule_version,
            },
        )
        return record

    def _write_dense_artifact(
        self,
        values: npt.NDArray[Any],
        *,
        coordinates: Mapping[str, npt.ArrayLike],
        dimension_names: Sequence[str],
        chunks: Sequence[int],
        role: str,
        timestamp: str,
        references: Sequence[Mapping[str, Any]],
        extra: Mapping[str, Any] | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        dense_id = f"stft-{uuid.uuid4().hex}"
        dense_object = self.dense.write_array(
            dense_id,
            values,
            chunks=chunks,
            dimension_names=dimension_names,
            coordinates=coordinates,
            created_at=timestamp,
        )
        manifest_bytes = canonical_json_bytes(dense_object.manifest)
        object_ = self.artifacts.put_bytes(manifest_bytes)
        self.store.register_artifact(
            object_.content_digest,
            object_.size,
            object_.relative_path,
            media_type="application/vnd.qste.dense-manifest+json",
            registered_at=timestamp,
        )
        artifact = record_base("ArtifactRecord", created_at=timestamp, references=references) | {
            "media_type": "application/vnd.qste.dense-manifest+json",
            "artifact_availability": "known",
            "byte_state": "immutable_content_addressed",
            "content_digest": object_.content_digest,
            "qste:gaborProfile": STFT_PROFILE,
            "qste:representationArtifactRole": role,
            "qste:denseId": dense_id,
            "qste:denseManifestDigest": dense_object.manifest_digest,
            "qste:denseShape": list(values.shape),
            **dict(extra or {}),
        }
        bind_semantic_key(
            artifact,
            "qste-semantic-key/stft-dense-artifact-v1",
            {
                "dense_manifest_digest": dense_object.manifest_digest,
                "role": role,
                "references": [dict(reference) for reference in references],
            },
        )
        return dense_object, artifact

    def _instance_and_spec(self, instance_record_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        instance = self._record(instance_record_id, "RepresentationInstance")
        if instance.get("qste:gaborProfile") != STFT_PROFILE:
            raise ContractError("invalid_input", "operation requires a P5 STFT instance")
        spec = self._record(
            cast(str, instance["representation_spec_ref"]["record_id"]), "RepresentationSpec"
        )
        return instance, spec

    def _instance_coefficients(
        self, instance: Mapping[str, Any]
    ) -> tuple[npt.NDArray[Any], dict[str, npt.NDArray[Any]]]:
        artifact = self._record(
            cast(str, instance["dense_data_ref"]["record_id"]), "ArtifactRecord"
        )
        return self._dense_artifact_values(artifact)

    def _dense_artifact_values(
        self, artifact: Mapping[str, Any]
    ) -> tuple[npt.NDArray[Any], dict[str, npt.NDArray[Any]]]:
        dense_id = artifact.get("qste:denseId")
        if not isinstance(dense_id, str):
            raise ContractError("conformance_failed", "coefficient artifact has no dense ID")
        manifest = self.dense.verify(dense_id).manifest
        shape = cast(list[int], manifest["values"]["shape"])
        resolved = self.dense.resolve_slice(
            dense_id,
            tuple(slice(0, length) for length in shape),
            maximum_elements=MAX_DENSE_ELEMENTS,
        )
        return resolved.values, resolved.coordinates

    def _waveform(self, artifact: Mapping[str, Any]) -> npt.NDArray[np.float64]:
        if (
            artifact.get("qste:ingressKind") != "audio"
            or artifact.get("media_type") != "application/x-npy"
        ):
            raise ContractError("invalid_input", "STFT encode requires a decoded P4 audio artifact")
        data = self.artifacts.read_bytes(cast(str, artifact["content_digest"]))
        try:
            value = np.load(io.BytesIO(data), allow_pickle=False)
        except (ValueError, OSError) as error:
            raise ContractError("conformance_failed", "decoded waveform NPY is invalid") from error
        array = np.asarray(value, dtype=np.float64)
        if array.ndim != 2 or not array.size or not np.isfinite(array).all():
            raise ContractError(
                "invalid_input", "decoded waveform must be finite frames by channels"
            )
        return array

    def _reconstruction_diagnostics(
        self, instance: Mapping[str, Any], waveform: npt.NDArray[Any], target_kind: str
    ) -> dict[str, Any]:
        if target_kind != "representation_instance":
            return {
                "comparison": "not_applicable_to_modified_coefficients",
                "phase_preserved": True,
            }
        source = self._record(
            cast(str, instance["source_artifact_ref"]["record_id"]), "ArtifactRecord"
        )
        expected = self._waveform(source)
        difference = waveform - expected
        spec = self._record(
            cast(str, instance["representation_spec_ref"]["record_id"]), "RepresentationSpec"
        )
        atol = cast(float, spec["parameters"]["reconstruction_atol"])
        rtol = cast(float, spec["parameters"]["reconstruction_rtol"])
        return {
            "comparison": "source_waveform",
            "maximum_absolute_error": float(np.max(np.abs(difference), initial=0.0)),
            "root_mean_square_error": float(np.sqrt(np.mean(np.square(difference)))),
            "atol": atol,
            "rtol": rtol,
            "passed": bool(np.allclose(waveform, expected, atol=atol, rtol=rtol)),
            "phase_preserved": True,
        }

    def _receipt_payload(
        self,
        operation: str,
        subject: Mapping[str, Any],
        parameters: Mapping[str, Any],
        payload: dict[str, Any],
        payload_type: str,
        authorization_status: str,
    ) -> RepresentationOperationOutcome:
        timestamp = utc_timestamp()
        subject_ref = record_ref(cast(str, subject["record_id"]), cast(str, subject["record_type"]))
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=subject_ref,
            authorization_status=authorization_status,
            operation=operation,
            inputs=[subject_ref],
            parameters=dict(parameters) or {"mode": "default"},
            outputs=[{"payload_type": payload_type, "durable_subject_ref": subject_ref}],
            tool_id="qste-stft-gabor",
            tool_version="v0.1",
        )
        _, event = self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type=f"qste:stft-{operation}-completed/0.1",
            subject_record_id=cast(str, subject["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"payload_type": payload_type, "profile": STFT_PROFILE},
            created_at=timestamp,
        )
        return RepresentationOperationOutcome(
            payload,
            f"qste-payload/0.3.0/{payload_type}",
            receipt,
            event.event_sequence,
        )

    def _failure_receipt(
        self,
        operation: str,
        subject: Mapping[str, Any],
        parameters: Mapping[str, Any],
        error: ContractError,
        authorization_status: str,
    ) -> str:
        timestamp = utc_timestamp()
        subject_ref = record_ref(cast(str, subject["record_id"]), cast(str, subject["record_type"]))
        receipt = operation_receipt(
            created_at=timestamp,
            request_ref=subject_ref,
            authorization_status=authorization_status,
            operation=operation,
            inputs=[subject_ref],
            parameters=dict(parameters) or {"mode": "default"},
            outputs=[{"availability": "unavailable", "reason_code": error.reason_code}],
            operation_status="unavailable",
            tool_id="qste-stft-gabor",
            tool_version="v0.1",
        )
        self.store.insert_records_with_event(
            [receipt],
            domain_event_record_id=None,
            event_type=f"qste:stft-{operation}-unavailable/0.1",
            subject_record_id=cast(str, subject["record_id"]),
            receipt_record_id=receipt["record_id"],
            payload={"reason_code": error.reason_code, "message": str(error)},
            created_at=timestamp,
        )
        return cast(str, receipt["record_id"])

    def _record(self, record_id: str, expected_type: str) -> dict[str, Any]:
        record = self.store.get_record(record_id).record
        if record.get("record_type") != expected_type:
            raise ContractError("invalid_input", f"record must be {expected_type}")
        return record

    @staticmethod
    def _authorize(status: str) -> None:
        if status != "permitted":
            raise ContractError("policy_refused", "representation operation requires permission")

    @staticmethod
    def _require_aperture_operation(aperture: Mapping[str, Any], operation: str) -> None:
        if operation not in aperture.get("permitted_operations", []):
            raise ContractError("policy_refused", f"aperture does not permit {operation}")


def _analysis(
    samples: npt.NDArray[np.float64], sample_rate: int, config: STFTConfig
) -> tuple[
    npt.NDArray[Any],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    dict[str, Any],
]:
    window = np.asarray(
        get_window(config.window_family, config.fft_length, fftbins=True), dtype=np.float64
    )
    dual = _canonical_dual(window, config.hop_length)
    pad_left = config.fft_length
    base_right = config.fft_length
    padded_length = pad_left + samples.shape[0] + base_right
    remainder = (padded_length - config.fft_length) % config.hop_length
    extra_right = (config.hop_length - remainder) % config.hop_length
    padded = np.pad(samples, ((pad_left, base_right + extra_right), (0, 0)))
    starts = np.arange(
        0, padded.shape[0] - config.fft_length + 1, config.hop_length, dtype=np.int64
    )
    frames = np.stack(
        [padded[start : start + config.fft_length] * window[:, None] for start in starts],
        axis=0,
    )
    coefficient_frames = np.fft.rfft(frames, n=config.fft_length, axis=1)
    dtype = np.complex64 if config.coefficient_dtype == "complex64" else np.complex128
    coefficients = np.asarray(np.transpose(coefficient_frames, (2, 1, 0)), dtype=dtype)
    times = (starts + (config.fft_length / 2) - pad_left) / sample_rate
    frequencies = np.fft.rfftfreq(config.fft_length, d=1 / sample_rate)
    spread = _realized_spread(window, sample_rate)
    analysis = {
        "realized_spread": spread,
        "analysis_window": {
            "family": config.window_family,
            "length_samples": config.fft_length,
            "content_digest_float64_le": _array_digest(window),
            "normalization": "none",
        },
        "dual_window": {
            "method": "canonical_periodic_overlap_square_dual",
            "length_samples": config.fft_length,
            "hop_length": config.hop_length,
            "content_digest_float64_le": _array_digest(dual),
        },
    }
    return coefficients, times, frequencies, analysis


def _synthesis(
    coefficients: npt.NDArray[Any],
    instance: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> npt.NDArray[np.float64]:
    fft_length = cast(int, spec["parameters"]["fft_length"])
    hop_length = cast(int, spec["parameters"]["hop_length"])
    window = np.asarray(get_window("hann_periodic", fft_length, fftbins=True), dtype=np.float64)
    dual = _canonical_dual(window, hop_length)
    frames = np.fft.irfft(np.transpose(coefficients, (2, 1, 0)), n=fft_length, axis=1)
    padded_length = ((frames.shape[0] - 1) * hop_length) + fft_length
    output = np.zeros((padded_length, frames.shape[2]), dtype=np.float64)
    for index, frame in enumerate(frames):
        start = index * hop_length
        output[start : start + fft_length] += frame * dual[:, None]
    original_frames = cast(int, instance["qste:originalFrameCount"])
    return output[fft_length : fft_length + original_frames]


def _canonical_dual(window: npt.NDArray[np.float64], hop_length: int) -> npt.NDArray[np.float64]:
    if len(window) % hop_length:
        raise ContractError("invalid_input", "canonical periodic dual requires hop dividing window")
    denominator = np.zeros_like(window)
    for shift in range(0, len(window), hop_length):
        denominator += np.roll(np.square(window), shift)
    if np.any(denominator <= 0):
        raise ContractError("conformance_failed", "analysis window has no stable canonical dual")
    return window / denominator


def _realized_spread(window: npt.NDArray[np.float64], sample_rate: int) -> dict[str, Any]:
    time = (np.arange(len(window), dtype=np.float64) - ((len(window) - 1) / 2)) / sample_rate
    time_mass = np.square(window)
    time_mass /= np.sum(time_mass)
    time_mean = float(np.sum(time_mass * time))
    temporal = float(np.sqrt(np.sum(time_mass * np.square(time - time_mean))))
    oversampled_length = max(65_536, 256 * len(window))
    spectrum = np.fft.fftshift(np.fft.fft(window, n=oversampled_length))
    frequency = np.fft.fftshift(np.fft.fftfreq(oversampled_length, d=1 / sample_rate))
    frequency_mass = np.square(np.abs(spectrum))
    frequency_mass /= np.sum(frequency_mass)
    frequency_mean = float(np.sum(frequency_mass * frequency))
    spectral = float(np.sqrt(np.sum(frequency_mass * np.square(frequency - frequency_mean))))
    return {
        "temporal_std_seconds": temporal,
        "spectral_std_hz": spectral,
        "product_hz_seconds": temporal * spectral,
        "method": "energy_weighted_discrete_window_and_oversampled_dft",
        "frequency_grid_length": oversampled_length,
        "truncated_window": True,
    }


def _candidate_masks(
    rule: Mapping[str, Any], instance: Mapping[str, Any], spec: Mapping[str, Any]
) -> list[tuple[tuple[int, int, int], ...]]:
    rule_id = rule.get("rule_id")
    shape = cast(list[int], instance["qste:coefficientShape"])
    maximum = cast(int, spec["capacity"]["maximum_candidates"])
    masks: list[tuple[tuple[int, int, int], ...]] = []
    if rule_id == "explicit_masks/0.1":
        raw_masks = rule.get("masks")
        if not isinstance(raw_masks, list) or not raw_masks:
            raise ContractError("invalid_input", "explicit candidate masks must be nonempty")
        for raw_mask in raw_masks:
            if not isinstance(raw_mask, list) or not raw_mask:
                raise ContractError("invalid_input", "each candidate mask must be nonempty")
            cells = tuple(_cell(value) for value in raw_mask)
            _validate_cells(cells, shape)
            masks.append(tuple(sorted(set(cells))))
    elif rule_id == "all_cells_lexicographic/0.1":
        budget = _positive_int(rule.get("maximum_candidates"), "candidate budget")
        limit = min(budget, maximum)
        total = math.prod(shape)
        if total > limit:
            raise ContractError("capability_unavailable", "all-cell enumeration exceeds its budget")
        masks = [
            ((channel, frequency, frame),)
            for channel in range(shape[0])
            for frequency in range(shape[1])
            for frame in range(shape[2])
        ]
    else:
        raise ContractError("capability_unavailable", "candidate rule is unsupported")
    if len(masks) > maximum:
        raise ContractError("capability_unavailable", "candidate selection exceeds capacity")
    if len(set(masks)) != len(masks):
        raise ContractError("invalid_input", "duplicate candidate masks are prohibited")
    return masks


def _apply_intervention(
    coefficients: npt.NDArray[Any],
    candidate_cells: Sequence[tuple[int, int, int]],
    *,
    mode: str,
    control: str,
) -> tuple[npt.NDArray[Any], tuple[tuple[int, int, int], ...]]:
    modified = coefficients.copy()
    if control == "resynthesis_only":
        return modified, ()
    cells = tuple(candidate_cells)
    if control == "off_target":
        frames = [cell[2] for cell in cells]
        offset = (max(frames) - min(frames)) + 1
        if max(frames) + offset < coefficients.shape[2]:
            signed_offset = offset
        elif min(frames) - offset >= 0:
            signed_offset = -offset
        else:
            signed_offset = 0
        shifted = [
            (channel, frequency, frame + signed_offset)
            for channel, frequency, frame in cells
            if signed_offset
        ]
        cells = tuple(sorted(set(shifted)))
    if control == "alternate":
        for cell in cells:
            modified[cell] *= 0.5
        return modified, cells
    if mode == "mask":
        for cell in cells:
            modified[cell] = 0
    elif mode == "isolate":
        modified.fill(0)
        for cell in cells:
            modified[cell] = coefficients[cell]
    elif mode == "phase_coherent_replace":
        for channel, frequency, frame in cells:
            neighbors = []
            if frame > 0:
                neighbors.append(abs(coefficients[channel, frequency, frame - 1]))
            if frame + 1 < coefficients.shape[2]:
                neighbors.append(abs(coefficients[channel, frequency, frame + 1]))
            magnitude = float(np.mean(neighbors)) if neighbors else 0.0
            phase = float(np.angle(coefficients[channel, frequency, frame]))
            modified[channel, frequency, frame] = magnitude * np.exp(1j * phase)
    else:  # guarded by InterventionSpec, retained as a defensive boundary
        raise ContractError("capability_unavailable", "intervention mode is unsupported")
    return modified, cells


def _bin_footprint(
    values: npt.NDArray[Any], maximum_bins: int
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.int64]]:
    if values.shape[0] <= maximum_bins:
        return np.asarray(values, dtype=np.float64), np.arange(values.shape[0] + 1)
    groups = np.array_split(np.arange(values.shape[0]), maximum_bins)
    binned = np.stack([np.sum(values[group], axis=0) for group in groups])
    edges = np.asarray([group[0] for group in groups] + [groups[-1][-1] + 1], dtype=np.int64)
    return np.asarray(binned, dtype=np.float64), edges


def _config_value(config: STFTConfig) -> dict[str, Any]:
    return {
        "fft_length": config.fft_length,
        "hop_length": config.hop_length,
        "window_family": config.window_family,
        "coefficient_dtype": config.coefficient_dtype,
        "reconstruction_atol": config.reconstruction_atol,
        "reconstruction_rtol": config.reconstruction_rtol,
        "maximum_candidates": config.maximum_candidates,
        "maximum_refinement_nodes": config.maximum_refinement_nodes,
        "footprint_floor": config.footprint_floor,
    }


def _validate_config(config: STFTConfig, sample_rate: int) -> None:
    if (
        not isinstance(config.fft_length, int)
        or isinstance(config.fft_length, bool)
        or config.fft_length < 16
        or config.fft_length > 8192
        or config.fft_length & (config.fft_length - 1)
    ):
        raise ContractError("invalid_input", "FFT length must be a power of two from 16 to 8192")
    if (
        not isinstance(config.hop_length, int)
        or isinstance(config.hop_length, bool)
        or config.hop_length < 1
        or config.hop_length > config.fft_length
        or config.fft_length % config.hop_length
    ):
        raise ContractError("invalid_input", "hop must positively divide the FFT length")
    if config.fft_length > sample_rate * 2:
        raise ContractError("invalid_input", "FFT window exceeds the two-second P5 bound")
    if (
        not isinstance(config.maximum_candidates, int)
        or isinstance(config.maximum_candidates, bool)
        or not isinstance(config.maximum_refinement_nodes, int)
        or isinstance(config.maximum_refinement_nodes, bool)
        or config.maximum_candidates < 1
        or config.maximum_refinement_nodes < 1
    ):
        raise ContractError("invalid_input", "candidate and refinement capacities must be positive")
    if not _nonnegative(config.reconstruction_atol) or not _nonnegative(config.reconstruction_rtol):
        raise ContractError("invalid_input", "reconstruction tolerances must be finite nonnegative")
    if (
        config.coefficient_dtype == "complex64"
        and max(config.reconstruction_atol, config.reconstruction_rtol) < 1e-7
    ):
        raise ContractError(
            "invalid_input", "complex64 requires a declared tolerance of at least 1e-7"
        )
    _nonnegative_float(config.footprint_floor, "footprint floor")


def _payload(payload_type: str, *, items: Sequence[Any], data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "payload_schema_id": "qste-payload/0.3.0",
        "payload_type": payload_type,
        "items": list(items),
        "data": dict(data),
    }


def _cells(candidate: Mapping[str, Any]) -> tuple[tuple[int, int, int], ...]:
    raw = candidate["native_address"]["cells"]
    return tuple(_cell(item) for item in raw)


def _cell(value: Any) -> tuple[int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
    ):
        raise ContractError("invalid_input", "STFT cell must contain three integer indexes")
    return cast(tuple[int, int, int], tuple(value))


def _validate_cells(cells: Sequence[tuple[int, int, int]], shape: Sequence[int]) -> None:
    if not cells:
        raise ContractError("invalid_input", "STFT mask cannot be empty")
    if len(shape) != 3:
        raise ContractError("conformance_failed", "STFT coefficient shape must have rank three")
    for cell in cells:
        if any(index < 0 or index >= shape[axis] for axis, index in enumerate(cell)):
            raise ContractError("invalid_input", "STFT cell is outside the representation")


def _cell_key(cells: Sequence[tuple[int, int, int]]) -> tuple[tuple[int, int, int], ...]:
    return tuple(sorted(cells))


def _array_digest(value: npt.NDArray[Any]) -> str:
    return content_digest(np.asarray(value, dtype="<f8").tobytes(order="C"))


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ContractError("invalid_input", f"{name} must be a positive integer")
    return value


def _finite_float(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ContractError("invalid_input", f"{name} must be finite numeric")
    return float(value)


def _nonnegative_float(value: Any, name: str) -> float:
    result = _finite_float(value, name)
    if result < 0:
        raise ContractError("invalid_input", f"{name} must be nonnegative")
    return result


def _nonnegative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )
