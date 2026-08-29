# Security policy

QSTE is pre-release research software. No version currently has a supported
public security lifecycle.

## Reporting

Use a private GitHub security advisory for vulnerabilities, credential
exposure, unsafe filesystem behavior, policy bypass, provenance corruption, or
audio-output hazards. Do not place secrets, restricted source details, or
participant information in a public issue.

## Current P14-infrastructure posture

QSTE exposes local library and CLI operations, a fixed synthetic subprocess
fixture, an ephemeral loopback OSC fixture, MCP over stdio or optional
loopback HTTP, and a read-only loopback inspection workbench. It does not
authorize remote binding, playback, adjacent-project execution, provider
access, model execution, dataset-byte access, human collection, or public
research projection.

Security-relevant invariants include:

- every workspace, source, and interface is constrained by explicit roots;
- the exact SQLite schema, foreign keys, uniqueness constraints, and
  immutability triggers are verified before record, event, lineage, artifact,
  or dense-object closure is accepted;
- bundle manifests are exactly typed, checksum-closed, relocatable,
  symlink/special-file-free, and revalidate dense Zarr semantics;
- MCP mutations are disabled by default and require both process-level
  enablement and per-call human approval as exact booleans;
- interface record-list and lineage queries are bounded before rows are
  materialized, while aggregate record counts remain database-side;
- HTTP services bind only to `127.0.0.1`; the workbench also validates its
  exact `Host` and optional `Origin` headers;
- the only subprocess route selects the packaged synthetic fixture itself,
  uses a fixed argument vector and empty `PATH`, and enforces time and byte
  limits;
- generated material, runtime databases, model files, and private data are
  ignored by Git; and
- repository and package verification reject private/internal documents,
  machine-specific filesystem paths, credential-shaped values, and escaping
  symlinks.

No ontology, schema, conformance profile, fixture, bundle, replay result, or
passing check is proof of safe scientific, human-subject, audio-output, or
model execution. State-changing operations still require explicit
authorization, resource bounds, validation, and a durable operation receipt.

## Dependency and release checks

The committed `uv.lock` is the exact dependency authority for development and
continuous verification. `make verify` checks contracts, repository hygiene,
the built wheel and source distribution, static types, behavior, and offline
operation. A clean release review should additionally scan the complete Git
history for secrets and check the exported lock against a current
vulnerability database. GitHub-hosted security features are used when the
private repository and organization plan make them available.
