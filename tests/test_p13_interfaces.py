from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from conftest import fixture_record
from p4_helpers import apparatus_declaration

from qste.core.contracts import ContractError
from qste.ingress import declare_apparatus
from qste.interfaces import InspectionWorkbench, InterfaceBroker, InterfacePolicy
from qste.interfaces.service import _evidence_class
from qste.storage import RecordStore, WorkspacePaths


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


def test_policy_security_gates_require_exact_booleans_and_integer_bounds(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    declare_apparatus(workspace, apparatus_declaration())
    with pytest.raises(ContractError, match="exact boolean"):
        InterfacePolicy.create(
            workspace=workspace,
            allowed_roots=(tmp_path,),
            mutations_enabled=cast(Any, "false"),
        )
    with pytest.raises(ContractError, match="maximum items"):
        InterfacePolicy.create(
            workspace=workspace,
            allowed_roots=(tmp_path,),
            maximum_items=cast(Any, True),
        )

    policy = InterfacePolicy.create(
        workspace=workspace,
        allowed_roots=(tmp_path,),
        mutations_enabled=True,
    )
    with pytest.raises(ContractError, match="exact boolean"):
        policy.require_mutation_approval(cast(Any, "false"))
    with pytest.raises(ContractError, match="requested item count"):
        policy.bounded_items(cast(Any, True))
    with pytest.raises(ContractError, match="requested lineage depth"):
        policy.bounded_depth(cast(Any, True))


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


def test_workbench_queries_and_lineage_outputs_obey_item_bounds(tmp_path: Path) -> None:
    policy, apparatus = _policy(tmp_path)
    store = RecordStore(WorkspacePaths.open(policy.workspace))
    artifacts = []
    for number in range(40):
        record = fixture_record("ArtifactRecord")
        record["record_id"] = f"qste:artifact-record:71000000-0000-4000-8000-{number:012d}"
        artifacts.append(record)
    store.insert_records(artifacts)
    snapshot = InspectionWorkbench(policy).snapshot()
    data = snapshot["value"]["data"]
    assert data["truncated"] is True
    assert len(data["groups"]["evidence"]) == policy.maximum_items

    for artifact in artifacts:
        store.add_edge(str(artifact["record_id"]), str(apparatus["record_id"]), "derived_from")
    lineage = InterfaceBroker(policy).lineage(
        str(apparatus["record_id"]), direction="descendants", maximum_depth=4
    )
    assert len(lineage["value"]["items"]) == policy.maximum_items
    assert lineage["value"]["data"]["edge_limit_reached"] is True


def test_observation_record_uses_the_instrument_evidence_class() -> None:
    assert _evidence_class("ObservationRecord") == "instrument_or_imported_observation"


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
