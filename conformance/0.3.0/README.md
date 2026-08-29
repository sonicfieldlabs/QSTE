# QSTE conformance profile 0.3.0

Status: `available` for the P2 schema and semantic-contract surface.

The executable profile binds `qste-contract/0.3.0` to
`qste-schema/0.3.0`. It checks schema self-validity, positive and negative
fixtures, extension preservation, identity non-substitution, record-type and
state-axis separation, canonical relation semantics, task bounds, operation
exit classes, typed reference closure, and refinement family/intervention/
mapping dependencies.

Run it with:

```sh
uv run python tools/verify_contracts.py
```

`conformance-index.json` binds every profile component and the fixture manifest
by SHA-256. The indexed profile files have separate roles:

- `conformance-profile.json` lists the P2 executable gate;
- `entity-coverage.json` separates abstract concepts, 31 records, typed
  payloads, the operation envelope, and the sealed container;
- `controlled-vocabularies.json` is the exact token registry;
- `reader-writer-profile.json` defines strict JSON and extension behavior;
- `state-transitions.json` preserves independent state axes and CLI classes;
- `obligation-coverage.json` maps all 28 ontology obligations to their P2
  representational status and first behavioral phase.

This is not a claim that later scientific or governance behavior exists.
Obligations owned by P3–P12 have a schema surface only and remain explicitly
unavailable until their executable phase gates pass.
