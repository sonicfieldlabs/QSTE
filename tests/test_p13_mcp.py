from __future__ import annotations

import asyncio
from pathlib import Path

from mcp import Client
from p4_helpers import apparatus_declaration

from qste.ingress import declare_apparatus
from qste.interfaces import InterfacePolicy
from qste.interfaces.mcp import create_mcp_server


def test_in_memory_mcp_exposes_only_fixed_bounded_tools(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    apparatus = declare_apparatus(workspace, apparatus_declaration()).apparatus_record
    policy = InterfacePolicy.create(workspace=workspace, allowed_roots=(tmp_path,))
    server = create_mcp_server(policy)

    async def scenario() -> None:
        async with Client(server) as client:
            tools = await client.list_tools()
            assert {item.name for item in tools.tools} == {
                "qste_compare_relations",
                "qste_inspect",
                "qste_lineage",
                "qste_transduce",
                "qste_verify",
                "qste_workbench_snapshot",
            }
            annotations = {item.name: item.annotations for item in tools.tools}
            inspect_annotations = annotations["qste_inspect"]
            transduce_annotations = annotations["qste_transduce"]
            assert inspect_annotations is not None
            assert transduce_annotations is not None
            assert inspect_annotations.read_only_hint is True
            assert transduce_annotations.destructive_hint is True
            inspected = await client.call_tool(
                "qste_inspect", {"record_id": apparatus["record_id"]}
            )
            assert inspected.structured_content["operation"] == "qste:inspect/0.3.0"
            refused = await client.call_tool(
                "qste_transduce",
                {
                    "mode": "sonify",
                    "source_record_ids": [apparatus["record_id"]],
                    "mapping_record_id": apparatus["record_id"],
                    "parameters": {},
                    "human_approved": True,
                },
            )
            assert refused.structured_content["operation_status"] == "unavailable"
            assert refused.structured_content["reason_code"] == "capability_unavailable"
            resources = await client.list_resources()
            assert [str(item.uri) for item in resources.resources] == ["qste://capabilities"]

    asyncio.run(scenario())
