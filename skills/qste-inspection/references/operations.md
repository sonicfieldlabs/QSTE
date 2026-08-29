# Bounded operations

## Read operations

- `qste_workbench_snapshot`: grouped summaries and an optional exact-record
  focus with bounded ancestor and descendant edges.
- `qste_inspect`: one immutable occurrence, never a merged semantic aggregate.
- `qste_lineage`: `ancestors` or `descendants` under the server depth bound.
- `qste_verify`: integrity and logical replay checks; it does not repair state.

## State-changing operations

`qste_compare_relations` maps only to `qste:compare_relations/0.1.0`. Supply the
registered comparison ID, source and target candidate IDs, and its exact
evidence object. Structural ambiguity, resolved null, and indeterminate are
different outcomes.

`qste_transduce` maps only to the declared QSTE transduction operation. Its mode
must be `sonify`, `desonify`, `resonify`, `transform`, or `contrast`; supply stored
source IDs, a stored mapping ID, and bounded parameters.

Both operations require two gates: server startup with mutations enabled and
`human_approved=true` on the call. Without either gate, preserve the returned
unavailable or refused result. Approval does not authorize playback, public
projection, provider access, external engines, adjacent-checkout writes, or a
different operation.
