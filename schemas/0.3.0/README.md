# QSTE schemas 0.3.0

Status: `available` for exact P2 contract validation.

[`schema-index.json`](schema-index.json) is the closed index for
`qste-schema/0.3.0`. Its 35 Draft 2020-12 schemas comprise:

- one common identity/reference contract with every exact ontology registry;
- 31 non-interchangeable serialized-record schemas;
- one `OperationResult<T>` envelope and one typed-payload schema; and
- one `Bundle` sealed-container manifest schema.

Schema identifiers use the non-resolving `schemas.qste.invalid` namespace.
Readers resolve them from the bundled offline registry; they never dereference
that namespace over the network. Writers accept exact v0.3.0 tokens and
namespaced extensions only. There is no legacy alias reader or migration map.

Schema availability is not operational availability. Candidate formation,
assessment, comparison, storage, bundles, governance actions, and external
adapters remain unavailable until their named phases close.
