"""Loopback-first MCP surface over bounded QSTE operations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from qste._version import version_info
from qste.interfaces.contracts import INTERFACE_PROFILE, InterfacePolicy
from qste.interfaces.service import InterfaceBroker

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
MUTATING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)


def create_mcp_server(policy: InterfacePolicy) -> MCPServer:
    """Create one fixed-workspace server with no dynamic tool registration."""

    broker = InterfaceBroker(policy)
    server = MCPServer(
        "QSTE",
        version="0.1.0",
        instructions=(
            "Inspect recorded QSTE state without treating inference as measurement, render as "
            "source, or a candidate as a DSQ. Mutations require server enablement and explicit "
            "human approval on the individual call."
        ),
    )

    @server.resource(
        "qste://capabilities",
        name="qste_capabilities",
        description="Bounded QSTE interface identity and capability account.",
        mime_type="application/json",
    )
    def capabilities() -> str:
        return json.dumps(
            {
                **version_info(),
                "interface_profile": INTERFACE_PROFILE,
                "transport_network_default": False,
                "workspace": "caller_owned_explicit_root",
                "mutations_enabled": policy.mutations_enabled,
                "maximum_items": policy.maximum_items,
                "maximum_lineage_depth": policy.maximum_lineage_depth,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @server.tool(
        name="qste_inspect",
        description="Inspect one immutable record occurrence by exact record ID.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def inspect_record(record_id: str) -> dict[str, Any]:
        return broker.inspect(record_id)

    @server.tool(
        name="qste_lineage",
        description="Trace bounded ancestor or descendant edges for one record occurrence.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def lineage(
        record_id: str, direction: str = "ancestors", maximum_depth: int = 16
    ) -> dict[str, Any]:
        return broker.lineage(record_id, direction=direction, maximum_depth=maximum_depth)

    @server.tool(
        name="qste_verify",
        description="Verify the fixed local workspace without repairing or rewriting it.",
        annotations=READ_ONLY,
        structured_output=True,
    )
    def verify_workspace() -> dict[str, Any]:
        return broker.verify()

    @server.tool(
        name="qste_workbench_snapshot",
        description=(
            "Summarize bounded records, lineage, relations, disagreements, mappings, claims, "
            "and evidence without merging identities."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    def workbench_snapshot(
        record_id: str | None = None, maximum_items: int | None = None
    ) -> dict[str, Any]:
        return broker.snapshot(record_id=record_id, maximum_items=maximum_items)

    @server.tool(
        name="qste_compare_relations",
        description=(
            "Run one registered QSTE relation comparison. Disabled unless the server was "
            "started with mutations enabled and this call has human_approved=true."
        ),
        annotations=MUTATING,
        structured_output=True,
    )
    def compare_relations(
        comparison_spec_record_id: str,
        source_candidate_record_ids: list[str],
        target_candidate_record_ids: list[str],
        evidence: dict[str, Any],
        human_approved: bool = False,
    ) -> dict[str, Any]:
        return broker.compare(
            comparison_spec_record_id=comparison_spec_record_id,
            source_candidate_record_ids=source_candidate_record_ids,
            target_candidate_record_ids=target_candidate_record_ids,
            evidence=evidence,
            approved=human_approved,
        )

    @server.tool(
        name="qste_transduce",
        description=(
            "Run one declared sonify, desonify, resonify, transform, or contrast transduction. "
            "Disabled unless the server was started with mutations enabled and this call has "
            "human_approved=true."
        ),
        annotations=MUTATING,
        structured_output=True,
    )
    def transduce_records(
        mode: str,
        source_record_ids: list[str],
        mapping_record_id: str,
        parameters: dict[str, Any],
        human_approved: bool = False,
    ) -> dict[str, Any]:
        return broker.transduce(
            mode=mode,
            source_record_ids=source_record_ids,
            mapping_record_id=mapping_record_id,
            parameters=parameters,
            approved=human_approved,
        )

    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded local QSTE MCP server")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--allowed-root", type=Path, required=True, action="append")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--enable-mutations", action="store_true")
    parser.add_argument("--maximum-items", type=int, default=256)
    parser.add_argument("--maximum-lineage-depth", type=int, default=64)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    policy = InterfacePolicy.create(
        workspace=arguments.workspace,
        allowed_roots=tuple(arguments.allowed_root),
        mutations_enabled=bool(arguments.enable_mutations),
        maximum_items=arguments.maximum_items,
        maximum_lineage_depth=arguments.maximum_lineage_depth,
    )
    server = create_mcp_server(policy)
    if arguments.transport == "stdio":
        server.run("stdio")
        return 0
    if arguments.host != "127.0.0.1":
        raise SystemExit("P13 Streamable HTTP binds only to 127.0.0.1")
    if arguments.port < 1024 or arguments.port > 65535:
        raise SystemExit("P13 port must be between 1024 and 65535")
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"127.0.0.1:{arguments.port}", "127.0.0.1", "localhost"],
        allowed_origins=[f"http://127.0.0.1:{arguments.port}"],
    )
    server.run(
        "streamable-http",
        host="127.0.0.1",
        port=arguments.port,
        stateless_http=True,
        max_request_body_size=policy.maximum_input_bytes,
        transport_security=security,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
