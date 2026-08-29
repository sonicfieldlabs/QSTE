# Authority layer

`authority-manifest.json` resolves the current public semantic contract,
schema index, conformance profiles, compatibility targets, repository, and
implementation commit in their separate version domains. Non-public
governance, sequencing, experiment preparation, and superseded snapshots are
kept outside this repository projection.

The manifest binds the preceding exact implementation commit. This avoids a
self-referential Git hash while preserving verifiable public authority.
