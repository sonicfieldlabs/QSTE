from __future__ import annotations

from typing import Any, cast

import pytest
from p12_helpers import build_p12_fixture, fixture

from qste.core.contracts import ContractError
from qste.storage import RecordStore, WorkspacePaths


def test_freeze_and_pilot_preserve_nonconfirmatory_boundary(tmp_path: Any) -> None:
    p12 = build_p12_fixture(tmp_path)
    preparation = p12.service.freeze(
        context_record_id=p12.context["record_id"], packet=fixture("preparation.json")
    ).value
    assert preparation["qste:preparationStatus"] == "frozen"
    assert preparation["qste:confirmatoryStatus"] == "not_started"
    assert preparation["qste:humanDataStatus"] == "not_collected"
    pilot = p12.service.pilot(
        preparation_record_id=preparation["record_id"], evidence=fixture("pilot.json")
    ).value
    assert pilot["qste:pilotStatus"] == "feasible_parameters_frozen"
    assert pilot["qste:p12mStatus"] == "unavailable"
    assert pilot["qste:p12hStatus"] == "authorization_required"
    assert pilot["qste:publicProjection"] is False
    RecordStore(WorkspacePaths.open(p12.workspace)).verify()


def test_confirmatory_or_human_flags_are_refused_with_receipt(tmp_path: Any) -> None:
    p12 = build_p12_fixture(tmp_path)
    packet = fixture("preparation.json")
    packet["safety_flags"]["human_data_collected"] = True
    before = len(p12.service.store.iter_records())
    with pytest.raises(ContractError) as caught:
        p12.service.freeze(context_record_id=p12.context["record_id"], packet=packet)
    assert caught.value.reason_code == "policy_refused"
    assert cast(Any, caught.value).receipt_id
    assert len(p12.service.store.iter_records()) == before + 1


def test_uncleared_corpus_is_refused(tmp_path: Any) -> None:
    p12 = build_p12_fixture(tmp_path)
    packet = fixture("preparation.json")
    packet["corpus"]["rights_status"] = "unknown"
    with pytest.raises(ContractError) as caught:
        p12.service.freeze(context_record_id=p12.context["record_id"], packet=packet)
    assert caught.value.reason_code == "policy_refused"


def test_pilot_must_bind_exact_frozen_parameters(tmp_path: Any) -> None:
    p12 = build_p12_fixture(tmp_path)
    preparation = p12.service.freeze(
        context_record_id=p12.context["record_id"], packet=fixture("preparation.json")
    ).value
    evidence = fixture("pilot.json")
    evidence["frozen_parameter_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ContractError) as caught:
        p12.service.pilot(preparation_record_id=preparation["record_id"], evidence=evidence)
    assert caught.value.reason_code == "conformance_failed"


def test_capability_account_keeps_later_gates_closed(tmp_path: Any) -> None:
    p12 = build_p12_fixture(tmp_path)
    outcome = p12.service.account(context_record_id=p12.context["record_id"])
    data = outcome.value["data"]
    assert data["preparation"] == "available"
    assert data["method_pilot"] == "available"
    assert data["confirmatory_machine_study"] == "unavailable"
    assert data["human_data_collection"] == "prohibited"
    assert data["public_research_projection"] == "prohibited"
