# Contributing

QSTE develops phase by phase against a versioned semantic contract.

## Before changing code

1. Resolve the current authority manifest.
2. Read the ontology section governing the proposed change.
3. Confirm that the public capability profile authorizes the capability.
4. Identify the requirement IDs and conformance evidence affected.

## Workflow

- Work from `main` through a focused branch once branch protection is
  enabled.
- Keep commits small and preserve a recoverable prior state.
- Add negative fixtures before claiming a new valid state.
- Run `make verify`.
- Preserve failed, unavailable, refused, partial, null, and indeterminate
  outcomes.
- Do not push, publish, install external tools, download weights, collect human
  data, or train a model without the applicable authorization gate.

Ontology or contract changes require an RFC, a new compatible contract version
when semantics change, updated schemas and fixtures, migration analysis for a
named corpus, and approval from both project leads.

Original contributions follow [the repository licensing map](LICENSES.md).
Contributors must have the right to submit every source, fixture, model,
dataset, or document they add.
