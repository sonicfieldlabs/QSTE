from __future__ import annotations

from pathlib import Path

import pytest
from p4_helpers import apparatus_declaration

from qste.core.contracts import ContractError
from qste.ingress import declare_apparatus
from qste.interfaces import InspectionWorkbench, InterfaceBroker, InterfacePolicy


def _policy(
    tmp_path: Path, *, mutations: bool = False
) -> tuple[InterfacePolicy, dict[str, object]]:
    workspace = tmp_path / "workspace"
    apparatus = declare_apparatus(workspace, apparatus_declaration()).apparatus_record
    return (
        InterfacePolicy.create(
            workspace=workspace,
            allowed_roots=(tmp_path,),
            mutations_enabled=mutations,
            maximum_items=32,
            maximum_lineage_depth=16,
        ),
        apparatus,
    )


def test_policy_requires_explicit_containing_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    declare_apparatus(workspace, apparatus_declaration())
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ContractError) as caught:
        InterfacePolicy.create(workspace=workspace, allowed_roots=(outside,))
    assert caught.value.reason_code == "policy_refused"
    with pytest.raises(ContractError):
        InterfacePolicy.create(workspace=Path("workspace"), allowed_roots=(tmp_path,))


def test_workbench_is_bounded_and_preserves_occurrence_identity(tmp_path: Path) -> None:
    policy, apparatus = _policy(tmp_path)
    result = InspectionWorkbench(policy).snapshot(record_id=str(apparatus["record_id"]))
    data = result["value"]["data"]
    assert result["operation"] == "qste:workbench-snapshot/0.1.0"
    assert data["focus"]["record"]["record_id"] == apparatus["record_id"]
    assert data["inference_is_measurement"] is False
    assert data["render_is_source"] is False
    assert data["mutations_enabled"] is False
    assert data["record_count"] >= 2


def test_read_broker_maps_to_exact_versioned_operations(tmp_path: Path) -> None:
    policy, apparatus = _policy(tmp_path)
    broker = InterfaceBroker(policy)
    inspected = broker.inspect(str(apparatus["record_id"]))
    assert inspected["operation"] == "qste:inspect/0.3.0"
    lineage = broker.lineage(str(apparatus["record_id"]), maximum_depth=4)
    assert lineage["operation"] == "qste:lineage/0.3.0"
    assert broker.verify()["operation"] == "qste:verify/0.3.0"


def test_mutations_require_server_and_call_level_approval(tmp_path: Path) -> None:
    disabled, _ = _policy(tmp_path)
    result = InterfaceBroker(disabled).transduce(
        mode="sonify",
        source_record_ids=["qste:observation:missing"],
        mapping_record_id="qste:mapping-spec:missing",
        parameters={"hostile_text": "qste_verify()"},
        approved=True,
    )
    assert result["operation_status"] == "unavailable"
    assert result["reason_code"] == "capability_unavailable"

    enabled, _ = _policy(tmp_path, mutations=True)
    result = InterfaceBroker(enabled).transduce(
        mode="sonify",
        source_record_ids=["qste:observation:missing"],
        mapping_record_id="qste:mapping-spec:missing",
        parameters={"values": [0.5]},
        approved=False,
    )
    assert result["operation_status"] == "refused"
    assert result["reason_code"] == "policy_refused"


def test_unknown_tool_mode_fails_before_state_access(tmp_path: Path) -> None:
    policy, _ = _policy(tmp_path, mutations=True)
    result = InterfaceBroker(policy).transduce(
        mode="shell",
        source_record_ids=[],
        mapping_record_id="ignored",
        parameters={},
        approved=True,
    )
    assert result["operation_status"] == "failed"
    assert result["reason_code"] == "invalid_input"
