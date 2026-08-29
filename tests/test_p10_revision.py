from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from p10_helpers import (
    build_p10_fixture,
    plan_and_revise,
    proposal,
    treatments,
)

from qste.core.contracts import ContractError
from qste.storage import RecordStore, WorkspacePaths


def _by_type(outcome: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {value["record_type"]: value for value in outcome["items"]}


def test_authentic_evidence_creates_behavioral_successor_and_next_opportunity(
    tmp_path: Path,
) -> None:
    fixture = build_p10_fixture(tmp_path)
    materials = treatments(fixture)
    before_digest = fixture.service.store.get_record(fixture.run["record_id"]).record_digest
    outcome = plan_and_revise(fixture, materials["authentic"], action_id="revise_action_set")
    records = _by_type(outcome)
    decision = records["DecisionEvent"]
    successor = records["SuccessorSpec"]
    next_run = records["RunManifest"]
    next_opportunity = records["RevisionOpportunity"]
    assert decision["revision_treatment"] == "authentic"
    assert decision["decision_action"] == "revise"
    assert decision["predecessor_successor_diff"]["semantic_or_behavioral_difference"] is True
    assert successor["predecessor_ref"]["record_id"] == fixture.initial["record_id"]
    assert successor["qste:nextOpportunityRef"]["record_id"] == next_opportunity["record_id"]
    assert next_opportunity["initial_successor_spec_ref"]["record_id"] == successor["record_id"]
    assert next_run["qste:runStatus"] == "scheduled_not_executed"
    assert fixture.service.store.get_record(fixture.run["record_id"]).record_digest == before_digest
    RecordStore(WorkspacePaths.open(fixture.base.workspace)).verify()


def test_hash_only_or_explanation_only_change_fails_with_durable_receipt(tmp_path: Path) -> None:
    fixture = build_p10_fixture(tmp_path)
    materials = treatments(fixture)
    invalid = proposal(
        fixture,
        action_id="revise_action_set",
        treatment="authentic",
    )
    invalid["changes"] = [
        {
            "field": "record_id",
            "before": fixture.initial["record_id"],
            "after": "qste:successor-spec:hash-only-fixture",
        }
    ]
    plan = fixture.service.plan(
        opportunity_record_id=fixture.opportunity["record_id"],
        treatment_record_id=materials["authentic"]["record_id"],
        proposal=invalid,
    ).value
    before = len(fixture.service.store.iter_records())
    with pytest.raises(ContractError) as caught:
        fixture.service.revise(
            plan_record_id=plan["record_id"],
            authority_record_id=fixture.base.apparatus["record_id"],
            source_authorization_status="permitted",
            enforcement_mode="active",
            fixture_authorization="synthetic",
            human_authorized=False,
        )
    assert caught.value.reason_code == "policy_refused"
    assert isinstance(cast(Any, caught.value).receipt_id, str)
    assert len(fixture.service.store.iter_records()) == before + 1


@pytest.mark.parametrize("treatment", ["absent", "placebo", "permuted"])
def test_control_treatments_can_record_no_change_without_successor(
    tmp_path: Path, treatment: str
) -> None:
    fixture = build_p10_fixture(tmp_path)
    materials = treatments(fixture)
    outcome = plan_and_revise(fixture, materials[treatment], action_id="no_change")
    assert outcome["data"]["successor_created"] is False
    assert [value["record_type"] for value in outcome["items"]] == ["DecisionEvent"]
    assert (
        outcome["items"][0]["predecessor_successor_diff"]["semantic_or_behavioral_difference"]
        is False
    )


def test_source_revocation_cannot_be_overridden_by_shadow_mode(tmp_path: Path) -> None:
    fixture = build_p10_fixture(tmp_path)
    materials = treatments(fixture)
    outcome = plan_and_revise(
        fixture,
        materials["authentic"],
        action_id="revise_action_set",
        enforcement_mode="shadow",
        source_authorization_status="revoked",
        study_policy_permitted=False,
    )
    assert outcome["data"] == {"decision_action": "refuse", "successor_created": False}
    decision = outcome["items"][0]
    assert decision["reason_code"] == "source_authorization_not_permitted"
    assert decision["executable_consequence"]["next_action_set"] != list(
        fixture.initial["executable_action_set"]
    )
    assert decision["executable_consequence"]["resume_conditions"]


def test_shadow_mode_records_would_have_blocked_without_disabling_boundary(
    tmp_path: Path,
) -> None:
    fixture = build_p10_fixture(tmp_path)
    materials = treatments(fixture)
    outcome = plan_and_revise(
        fixture,
        materials["authentic"],
        action_id="revise_action_set",
        enforcement_mode="shadow",
        study_policy_permitted=False,
    )
    decision = _by_type(outcome)["DecisionEvent"]
    assert decision["executable_consequence"]["shadow_mode"] is True
    assert decision["executable_consequence"]["would_have_blocked"] is True
    assert decision["qste:executorOriginatedAuthority"] is False


def test_refusal_changes_next_action_set_and_records_resume_or_escalation(tmp_path: Path) -> None:
    fixture = build_p10_fixture(tmp_path)
    materials = treatments(fixture)
    outcome = plan_and_revise(fixture, materials["authentic"], action_id="refuse")
    decision = outcome["items"][0]
    consequence = decision["executable_consequence"]
    assert decision["decision_action"] == "refuse"
    assert consequence["successor_created"] is False
    assert consequence["next_action_set"] != fixture.initial["executable_action_set"]
    assert consequence["resume_conditions"] or consequence["escalation_conditions"]


def test_resume_requires_explicit_human_authorization(tmp_path: Path) -> None:
    fixture = build_p10_fixture(tmp_path)
    material = treatments(fixture)["authentic"]
    plan = fixture.service.plan(
        opportunity_record_id=fixture.opportunity["record_id"],
        treatment_record_id=material["record_id"],
        proposal=proposal(fixture, action_id="resume", treatment="authentic"),
    ).value

    refused = fixture.service.revise(
        plan_record_id=plan["record_id"],
        authority_record_id=fixture.base.apparatus["record_id"],
        source_authorization_status="permitted",
        enforcement_mode="active",
        fixture_authorization="synthetic",
        human_authorized=False,
    ).value
    refused_decision = refused["items"][0]
    assert refused_decision["decision_action"] == "refuse"
    assert refused_decision["reason_code"] == "human_authorization_required"
    assert refused["data"]["successor_created"] is False

    resumed = fixture.service.revise(
        plan_record_id=plan["record_id"],
        authority_record_id=fixture.base.apparatus["record_id"],
        source_authorization_status="permitted",
        enforcement_mode="active",
        fixture_authorization="synthetic",
        human_authorized=True,
    ).value
    resumed_records = _by_type(resumed)
    assert resumed_records["DecisionEvent"]["decision_action"] == "resume"
    assert resumed["data"]["successor_created"] is True
