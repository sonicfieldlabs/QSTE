from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from p5_helpers import P5Fixture, build_p5_fixture, explicit_candidates

from qste.quanta import QuantaService


def p6_fixture(
    tmp_path: Path, *, cells: int = 2
) -> tuple[P5Fixture, dict[str, Any], dict[str, Any]]:
    signal = 0.4 * np.sin(np.linspace(0, 12 * np.pi, 512))
    fixture = build_p5_fixture(tmp_path, signal)
    mask = [[[0, 2 + index, 4] for index in range(cells)]]
    candidate = explicit_candidates(fixture, mask)[0]
    graph = fixture.service.refine(
        candidate_record_id=candidate["record_id"],
        procedure={"procedure_id": "boolean-subsets", "maximum_nodes": 64},
    ).value
    return fixture, candidate, graph


def task_spec(
    family_size: int,
    *,
    uncertainty: str = "deterministic_tolerance",
    required_calibration: str = "digital_sample_domain",
    maximum_evaluations: int = 1000,
    repeats: int = 3,
) -> dict[str, Any]:
    uncertainty_spec: dict[str, Any]
    multiplicity_method = "complete_family_bonferroni"
    if uncertainty == "deterministic_tolerance":
        uncertainty_spec = {"method": uncertainty, "tolerance": 0.01}
    elif uncertainty == "bonferroni_normal":
        uncertainty_spec = {"method": uncertainty, "confidence": 0.95}
    else:
        uncertainty_spec = {"method": "unavailable", "reason": "not_implemented"}
        multiplicity_method = "unavailable"
    return {
        "task_id": "qste-test-paired-effect",
        "task_version": "v0.1",
        "response_variable": "detector_logit",
        "fixed_context": {"item": "held-out-001", "condition": "offline"},
        "expected_effect_direction": 1,
        "response_units": "logit",
        "meaningful_bound": 0.5,
        "equivalence_region": {
            "epsilon_minus": 0.1,
            "epsilon_plus": 0.1,
            "units": "logit",
        },
        "boundary_semantics": {
            "qualification": "inclusive",
            "equivalence": "inclusive",
            "rejection": "strict",
        },
        "estimator": {"id": "paired_mean"},
        "repeats": repeats,
        "seeds": list(range(101, 101 + repeats)),
        "uncertainty": uncertainty_spec,
        "multiplicity": {"method": multiplicity_method, "family_size": family_size},
        "stopping_rules": {"maximum_repeats": repeats, "optional_stopping": False},
        "selection_confirmation": {
            "mode": "held_out",
            "selection_set": "exploration-a",
            "confirmation_set": "confirmation-b",
            "disjoint": True,
        },
        "artifact_controls": [
            "resynthesis_only",
            "off_target",
            "matched_intervention",
            "renderer_fidelity",
        ],
        "alternate_intervention": {"required": True, "id": "isolate-control/v0.1"},
        "compute_budget": {"maximum_evaluations": maximum_evaluations},
        "success_criterion": {"predicate": "two_bound_dsq_assessment"},
        "required_calibration": required_calibration,
    }


def paired_evidence(
    effects: Mapping[object, float | list[float]],
    *,
    protocol: str = "deterministic",
    repeats: int = 3,
    controls_pass: bool = True,
    dependency_validity: str = "valid",
) -> dict[str, Any]:
    units: dict[str, Any] = {}
    for raw_unit_id, effect in effects.items():
        unit_id = str(raw_unit_id)
        values = [effect] * repeats if isinstance(effect, (int, float)) else list(effect)
        units[unit_id] = {
            "reference_scores": values,
            "intervened_scores": [0.0] * repeats,
        }
    evidence = {
        "protocol": protocol,
        "units": units,
        "artifact_controls": {
            "resynthesis_only": controls_pass,
            "off_target": controls_pass,
            "matched_intervention": controls_pass,
            "renderer_fidelity": controls_pass,
        },
        "alternate_intervention_passed": controls_pass,
        "dependency_validity": dependency_validity,
    }
    if protocol == "stochastic":
        evidence["seeds"] = list(range(101, 101 + repeats))
    return evidence


def declare_and_execute(
    workspace: Path,
    candidate: dict[str, Any],
    graph: dict[str, Any] | None,
    effects: Mapping[object, float | list[float]],
    *,
    spec: dict[str, Any] | None = None,
    evidence_overrides: dict[str, Any] | None = None,
) -> tuple[QuantaService, dict[str, Any], dict[str, Any]]:
    service = QuantaService(workspace)
    family_size = 1 + (len(graph["required_closure"]) if graph is not None else 0)
    task = service.declare_task(
        candidate_record_id=candidate["record_id"],
        refinement_graph_record_id=graph["record_id"] if graph is not None else None,
        specification=spec or task_spec(family_size),
    ).value
    evidence = paired_evidence(effects)
    if evidence_overrides:
        evidence.update(evidence_overrides)
    run = service.execute_task(task_record_id=task["record_id"], score_evidence=evidence).value
    return service, task, run
