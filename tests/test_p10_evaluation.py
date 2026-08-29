from __future__ import annotations

from pathlib import Path

from p10_helpers import build_p10_fixture, plan_and_revise, treatments


def test_four_condition_study_and_held_out_utility_remain_separate(tmp_path: Path) -> None:
    fixture = build_p10_fixture(tmp_path)
    materials = treatments(fixture)
    decision_ids: dict[str, list[str]] = {}
    authentic = plan_and_revise(fixture, materials["authentic"], action_id="revise_action_set")
    decision_ids["authentic"] = [authentic["items"][0]["record_id"]]
    for treatment in ("absent", "placebo", "permuted"):
        outcome = plan_and_revise(fixture, materials[treatment], action_id="no_change")
        decision_ids[treatment] = [outcome["items"][0]["record_id"]]
    study = fixture.service.assess_study(
        decision_record_ids=decision_ids,
        preregistration={
            "minimum_opportunities_per_condition": 1,
            "randomization_or_matching": "randomized",
            "matching_complete": True,
            "leakage_detected": False,
            "outside_information_matched": True,
            "budgets_matched": True,
            "action_surface_matched": True,
            "initial_state_matched": True,
            "executor_resources_matched": True,
        },
    ).value
    assert study["qste:evidenceDependenceStatus"] == "supported_synthetic_conformance"
    assert study["scope"]["empirical_or_causal_research_claim"] is False
    assert study["qste:utilityStatus"] == "not_assessed_separate_axis"
    utility = fixture.service.evaluate_utility(
        decision_record_id=decision_ids["authentic"][0],
        evaluation={
            "held_out": True,
            "task_metric": "synthetic_detection_at_fixed_false_positive_rate",
            "task_score": 0.8,
            "false_positive_rate": 0.05,
            "compute_units": 1,
            "latency_ms": 2,
            "intervention_count": 1,
            "refusal_cost": 0,
        },
    ).value
    assert utility["qste:evidenceDependenceStatus"] == "not_inferred_from_utility"
    assert utility["qste:creativeConsequence"] == "not_assessed"


def test_leakage_prevents_synthetic_study_support(tmp_path: Path) -> None:
    fixture = build_p10_fixture(tmp_path)
    materials = treatments(fixture)
    decisions: dict[str, list[str]] = {}
    for treatment in ("authentic", "absent", "placebo", "permuted"):
        action = "revise_action_set" if treatment == "authentic" else "no_change"
        result = plan_and_revise(fixture, materials[treatment], action_id=action)
        decisions[treatment] = [result["items"][0]["record_id"]]
    study = fixture.service.assess_study(
        decision_record_ids=decisions,
        preregistration={
            "minimum_opportunities_per_condition": 1,
            "randomization_or_matching": "matched",
            "matching_complete": True,
            "leakage_detected": True,
            "outside_information_matched": True,
            "budgets_matched": True,
            "action_surface_matched": True,
            "initial_state_matched": True,
            "executor_resources_matched": True,
        },
    ).value
    assert study["qste:evidenceDependenceStatus"] == "not_supported"
