# P13 local-interface conformance

This profile covers the public QSTE inspection skill, fixed-workspace MCP
server, and loopback read-only workbench. The surface delegates to existing
versioned Python operations and preserves their `OperationResult` statuses.

The fixture is synthetic interface policy, not research evidence. MCP defaults
to stdio. Optional HTTP and the workbench bind only to `127.0.0.1`. Mutations
are disabled unless a human enables them when starting the server and approves
the individual tool call.

Run `make interface-contracts` to verify this boundary.
