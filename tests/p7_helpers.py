from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from p5_helpers import P5Fixture, build_p5_fixture, explicit_candidates

from qste.core.identity import utc_timestamp
from qste.ingress.records import bind_semantic_key, record_base, record_ref
from qste.relations import RelationService

EFFECT_CONTRACT = {
    "response_variable": "detector_logit",
    "units": "logit",
    "direction_orientation": 1,
    "fixed_context": {"item": "mock-held-out-001"},
    "aggregation_level": "candidate",
    "estimand": "paired_mean_intervention_effect",
}


def p7_candidates(
    tmp_path: Path, *, source_count: int = 1, target_count: int = 1
) -> tuple[P5Fixture, list[dict[str, Any]], list[dict[str, Any]]]:
    signal = 0.35 * np.sin(np.linspace(0, 10 * np.pi, 512))
    fixture = build_p5_fixture(tmp_path, signal)
    masks = [[[0, 2 + index, 4]] for index in range(source_count)]
    source = explicit_candidates(fixture, masks)
    timestamp = utc_timestamp()
    alternate_spec = record_base("RepresentationSpec", created_at=timestamp) | {
        "representation_id": "qste-mock-alternate/v0.1",
        "algorithm_or_model_digest": "sha256:" + "7" * 64,
        "parameters": {"fixture": "known_parameter_segments"},
        "native_unit": "mock_segment",
        "metric": {"id": "mock_native_distance", "cross_arm_use": "prohibited"},
        "capacity": {"maximum_segments": 16},
        "renderer_or_decoder": {"id": "fixture_only", "availability": "known"},
        "qste:mockAlternateRepresentation": True,
    }
    bind_semantic_key(
        alternate_spec,
        "qste-semantic-key/mock-alternate-spec-v1",
        {"representation_id": alternate_spec["representation_id"]},
    )
    alternate_instance = record_base(
        "RepresentationInstance",
        created_at=timestamp,
        references=[
            dict(fixture.instance["source_artifact_ref"]),
            record_ref(alternate_spec["record_id"], "RepresentationSpec"),
            dict(fixture.instance["execution_receipt_ref"]),
            dict(fixture.instance["dense_data_ref"]),
        ],
    ) | {
        "source_artifact_ref": dict(fixture.instance["source_artifact_ref"]),
        "representation_spec_ref": record_ref(alternate_spec["record_id"], "RepresentationSpec"),
        "execution_receipt_ref": dict(fixture.instance["execution_receipt_ref"]),
        "dense_data_ref": dict(fixture.instance["dense_data_ref"]),
        "instance_context": {
            "fixture": "P7 mock alternate arm",
            "source_alignment": "shared_sample_clock",
        },
        "qste:mockAlternateRepresentation": True,
    }
    bind_semantic_key(
        alternate_instance,
        "qste-semantic-key/mock-alternate-instance-v1",
        {
            "spec_semantic_key": alternate_spec["semantic_key"],
            "source_record_id": fixture.ingress_artifact["record_id"],
        },
    )
    targets: list[dict[str, Any]] = []
    for index in range(target_count):
        candidate = record_base(
            "CandidateUnit",
            created_at=timestamp,
            references=[record_ref(alternate_instance["record_id"], "RepresentationInstance")],
        ) | {
            "representation_instance_ref": record_ref(
                alternate_instance["record_id"], "RepresentationInstance"
            ),
            "native_address": {"segment_index": index, "native_unit": "mock_segment"},
            "candidate_rule_version": "mock-segments/v0.1",
            "native_support": {
                "source_time_samples": [index * 16, index * 16 + 31],
                "estimated": False,
            },
            "qste:candidateStatus": "candidate_only",
            "qste:mockAlternateRepresentation": True,
        }
        bind_semantic_key(
            candidate,
            "qste-semantic-key/mock-alternate-candidate-v1",
            {
                "instance_semantic_key": alternate_instance["semantic_key"],
                "native_address": candidate["native_address"],
                "candidate_rule_version": candidate["candidate_rule_version"],
            },
        )
        targets.append(candidate)
    fixture.service.store.insert_records([alternate_spec, alternate_instance, *targets])
    return fixture, source, targets


def projection_spec(
    *,
    kind: str = "expected_energy_change",
    effect_contract: Mapping[str, Any] = EFFECT_CONTRACT,
) -> dict[str, Any]:
    return {
        "comparison_substrate": {
            "id": "qste-mock-source-time-band-energy",
            "version": "v0.1",
            "axes": ["source_time", "channel", "band_energy"],
        },
        "measure": {"id": "weighted_sum", "units": "calibrated_mock_mass"},
        "footprint_method": {
            "kind": kind,
            "normalization": "unit_integral" if kind == "expected_energy_change" else "none",
            "floor": 0.05,
            "weighting": "uniform_mock_cells",
        },
        "calibration": {
            "status": "calibrated",
            "evidence": "known_parameter_mock_substrate/v0.1",
        },
        "alignment": {"id": "shared-source-sample-clock", "version": "v0.1"},
        "uncertainty": {
            "method": "deterministic_known_parameter_fixture",
            "propagates_alignment": True,
        },
        "failure_conditions": [
            "undefined_alignment",
            "nonfinite_footprint",
            "contract_mismatch",
        ],
        "effect_contract": dict(effect_contract),
    }


def comparison_spec(
    *,
    coverage_threshold: float = 0.8,
    effect_tolerance: float = 0.2,
    source_capacity: int = 1,
    target_capacity: int = 1,
    cardinalities: Sequence[str] = ("1:1",),
    unmatched_penalty: float = 1.0,
    cardinality_preference: str = "fewer_edges",
    coverage_half_width: float = 0.0,
    maximum_edges: int = 16,
    maximum_subsets: int = 65_536,
    decompositions: Sequence[Any] = (),
    effect_conversions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "coverage_threshold": coverage_threshold,
        "effect_tolerance": effect_tolerance,
        "capacities": {
            "source_default": source_capacity,
            "target_default": target_capacity,
            "maximum_n": 8,
            "source_overrides": {},
            "target_overrides": {},
        },
        "cardinalities": list(cardinalities),
        "unmatched_penalty": unmatched_penalty,
        "estimators": {
            "coverage": "interval_bounds",
            "edge_cost": "mean_directional_point_coverage",
        },
        "primary_objective": "minimum_cost_b_matching",
        "cardinality_preference": cardinality_preference,
        "optimization_tolerance": 1e-12,
        "ambiguity_rules": {
            "evaluate_before_lexicographic_replay": True,
            "lexicographic_native_address_order": True,
            "many_to_many_decompositions": list(decompositions),
        },
        "budget": {
            "maximum_edges": maximum_edges,
            "maximum_subsets": maximum_subsets,
        },
        "effect_contract": dict(EFFECT_CONTRACT),
        "effect_conversions": dict(effect_conversions or {}),
        "coverage_uncertainty": {
            "method": "deterministic_tolerance",
            "half_width": coverage_half_width,
        },
    }


def declared_engine(
    fixture: P5Fixture,
    sources: Sequence[dict[str, Any]],
    targets: Sequence[dict[str, Any]],
    *,
    kind: str = "expected_energy_change",
    comparison_overrides: Mapping[str, Any] | None = None,
) -> tuple[RelationService, dict[str, Any], list[dict[str, Any]]]:
    service = RelationService(fixture.workspace)
    source_arm = sources[0]["representation_instance_ref"]["record_id"]
    target_arm = targets[0]["representation_instance_ref"]["record_id"]
    source_projection = service.declare_projection(
        source_arm_record_id=source_arm,
        specification=projection_spec(kind=kind),
    ).value
    target_projection = service.declare_projection(
        source_arm_record_id=target_arm,
        specification=projection_spec(kind=kind),
    ).value
    spec = comparison_spec()
    if comparison_overrides:
        spec.update(comparison_overrides)
    comparison = service.declare_comparison(
        projection_record_ids=[source_projection["record_id"], target_projection["record_id"]],
        specification=spec,
    ).value
    return service, comparison, [source_projection, target_projection]


def comparison_evidence(
    sources: Sequence[dict[str, Any]],
    targets: Sequence[dict[str, Any]],
    footprints: Mapping[str, Sequence[float]],
    *,
    effects: Mapping[str, float | tuple[float, float, float]] | None = None,
    projection_status: Mapping[str, str] | None = None,
    pair_overrides: Mapping[tuple[str, str], Mapping[str, str]] | None = None,
    perturbation_stability: str = "not_tested",
) -> dict[str, Any]:
    units: dict[str, Any] = {}
    effects = effects or {}
    projection_status = projection_status or {}
    for candidate in [*sources, *targets]:
        candidate_id = candidate["record_id"]
        effect = effects.get(candidate_id, 0.0)
        if isinstance(effect, tuple):
            lower, upper, point = effect
        else:
            lower = upper = point = float(effect)
        units[candidate_id] = {
            "projection_status": projection_status.get(candidate_id, "valid"),
            "footprint": list(footprints[candidate_id]),
            "effect_interval": {
                "lower": lower,
                "upper": upper,
                "point_estimate": point,
            },
            "effect_contract": dict(EFFECT_CONTRACT),
            "evidence_record_ids": [candidate_id],
            "perturbation_stability": perturbation_stability,
        }
    pairs: dict[str, Any] = {}
    pair_overrides = pair_overrides or {}
    defaults = {
        "target_address": "exists",
        "fidelity": "passed",
        "consequentiality": "passed",
        "artifact_controls": "passed",
    }
    for source in sources:
        for target in targets:
            key = (source["record_id"], target["record_id"])
            pairs[f"{key[0]}|{key[1]}"] = {**defaults, **dict(pair_overrides.get(key, {}))}
    return {"units": units, "pairs": pairs, "decomposition_evidence": []}
