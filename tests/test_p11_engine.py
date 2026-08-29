from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from p11_helpers import build_p11_fixture, fixture

from qste.core.contracts import ContractError
from qste.storage import RecordStore, WorkspacePaths


def test_bounded_fixture_process_returns_parameters_logs_digest_and_timeout_state(
    tmp_path: Path,
) -> None:
    p11 = build_p11_fixture(tmp_path)
    artifact = p11.engine.execute(
        target_id="qste_fixture_process",
        context_record_id=p11.context["record_id"],
        request=fixture("engine-process-request.json"),
    ).value
    execution = artifact["qste:engineExecution"]
    assert execution["parameters"] == {"gain": 0.5, "mode": "scale"}
    assert execution["command_identity"] == "packaged-file:qste.adapters/engine_fixture.py"
    assert execution["logs"]["stdout_digest"] == execution["output_digest"]
    assert execution["logs"]["stderr_bytes"] == 0
    assert execution["timeout_state"] is False
    assert execution["output"]["output"] == [0.0, 0.25, -0.25, 0.5]
    assert execution["external_engine_executed"] is False
    assert execution["disk_write"] is False
    RecordStore(WorkspacePaths.open(p11.workspace)).verify()


def test_process_timeout_is_durable_and_reports_timeout_state(tmp_path: Path) -> None:
    p11 = build_p11_fixture(tmp_path)
    request = fixture("engine-process-request.json")
    request["delay_ms"] = 100
    request["timeout_seconds"] = 0.01
    before = len(p11.engine.store.iter_records())
    with pytest.raises(ContractError) as caught:
        p11.engine.execute(
            target_id="qste_fixture_process",
            context_record_id=p11.context["record_id"],
            request=request,
        )
    assert caught.value.reason_code == "execution_failed"
    assert cast(Any, caught.value).diagnostics_extra["timeout_state"] is True
    assert len(p11.engine.store.iter_records()) == before + 1


def test_osc_demonstration_is_fixed_to_loopback_and_preserves_packet_digest(
    tmp_path: Path,
) -> None:
    p11 = build_p11_fixture(tmp_path)
    artifact = p11.engine.osc_loopback(
        target_id="qste_fixture_osc_loopback",
        context_record_id=p11.context["record_id"],
        request=fixture("engine-loopback-request.json"),
    ).value
    execution = artifact["qste:engineExecution"]
    assert execution["loopback_host"] == "127.0.0.1"
    assert execution["logs"]["sent_digest"] == execution["logs"]["received_digest"]
    assert execution["timeout_state"] is False
    assert execution["external_engine_executed"] is False
    assert execution["adjacent_checkout_write"] is False


@pytest.mark.parametrize("target_id", ["pure_data", "max_msp", "supercollider", "csound"])
def test_absent_engine_is_unavailable_with_durable_receipt(tmp_path: Path, target_id: str) -> None:
    p11 = build_p11_fixture(tmp_path)
    before = len(p11.engine.store.iter_records())
    with pytest.raises(ContractError) as caught:
        p11.engine.execute(
            target_id=target_id,
            context_record_id=p11.context["record_id"],
            request=fixture("engine-process-request.json"),
        )
    assert caught.value.reason_code == "capability_unavailable"
    assert cast(Any, caught.value).capability_status == "unavailable"
    assert len(p11.engine.store.iter_records()) == before + 1


def test_untested_and_prohibited_capabilities_remain_distinct(tmp_path: Path) -> None:
    p11 = build_p11_fixture(tmp_path)
    with pytest.raises(ContractError) as untested:
        p11.engine.execute(
            target_id="required_untested_fixture",
            context_record_id=p11.context["record_id"],
            request=fixture("engine-process-request.json"),
        )
    assert untested.value.reason_code == "capability_unavailable"
    assert cast(Any, untested.value).capability_status == "untested"

    with pytest.raises(ContractError) as prohibited:
        p11.engine.execute(
            target_id="prohibited_fixture",
            context_record_id=p11.context["record_id"],
            request=fixture("engine-process-request.json"),
        )
    assert prohibited.value.reason_code == "policy_refused"
    assert cast(Any, prohibited.value).capability_status == "prohibited"


def test_process_request_cannot_supply_an_unchecked_command(tmp_path: Path) -> None:
    p11 = build_p11_fixture(tmp_path)
    request = fixture("engine-process-request.json")
    request["command"] = ["sh", "-c", "echo forbidden"]
    with pytest.raises(ContractError) as caught:
        p11.engine.execute(
            target_id="qste_fixture_process",
            context_record_id=p11.context["record_id"],
            request=request,
        )
    assert caught.value.reason_code == "invalid_input"
