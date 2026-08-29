# P3 storage conformance

`qste-storage-conformance/0.1` is the executable behavioral profile for the
P3 identity, storage, lineage, dense-plane, and private-bundle kernel. It is
subordinate to `qste-contract/0.3.0`; it does not extend the ontology or the
P2 schema set.

Run it with:

```sh
uv run python tools/verify_storage.py
```

The profile proves local integrity and logical replay of the stored event and
record state. It deliberately leaves numerical reproducibility `unavailable`:
P3 has no representation arm, scientific operation, or numerical replay claim.
