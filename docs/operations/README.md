# P3-P13 local operations

All P3 operations require an explicit workspace or bundle root. They perform
no network access, playback, imported-code execution, implicit repair, or
search outside that root.

## Formats

- Workspace marker: `qste-workspace/0.1`
- SQLite metadata: `qste-sqlite/0.1`
- Dense manifests: `qste-dense/0.1` over Zarr v3
- Private bundles: `qste-private-bundle/0.1`
- Behavioral profile: `qste-storage-conformance/0.1`
- Ingress profile: `qste-ingress-conformance/0.1`
- Reference representation: `qste-stft-gabor/v0.1`
- Representation profile: `qste-stft-gabor-conformance/0.1`
- Paired-task profile: `qste-paired-score-task/v0.1`
- DSQ assessment profile: `qste-dsq-assessment/v0.1`
- P6 conformance profile: `qste-dsq-conformance/0.1`
- Projection profile: `qste-cross-arm-projection/v0.1`
- Comparison profile: `qste-cross-arm-comparison/v0.1`
- Relation profile: `qste-cross-arm-relation/v0.1`
- Exact matcher: `qste-bounded-exact-b-matching/v0.1`
- P7 conformance profile: `qste-relation-conformance/0.1`
- Mapping profile: `qste-transduction-mapping/v0.1`
- Bounded transduction profile: `qste-bounded-transduction/v0.1`
- Governance boundary profile: `qste-governance-boundary/v0.1`
- Appeal profile: `qste-appeal-case/v0.1`
- Repair profile: `qste-repair-chain/v0.1`
- P8 conformance profile: `qste-transduction-governance-conformance/0.1`
- External adapter profile: `qste-external-representation-adapter/v0.1`
- External capture profile: `qste-external-representation-capture/0.1`
- P9 conformance profile: `qste-external-representation-conformance/0.1`
- Listening harness profile: `qste-listening-harness/v0.1`
- Evidence-dependent revision profile: `qste-evidence-dependent-revision/v0.1`
- P10 conformance profile: `qste-agent-harness-conformance/0.1`
- Ecosystem adapter profile: `qste-ecosystem-adapter/v0.1`
- Bounded engine profile: `qste-bounded-engine-adapter/v0.1`
- Compatibility target profile: `qste-compatibility-target-manifest/0.1`
- P11 conformance profile: `qste-ecosystem-engine-conformance/0.1`
- P12a preparation profile: `qste-experiment-preparation/v0.1`
- P12a method-pilot profile: `qste-method-pilot/v0.1`
- P12a conformance profile: `qste-experiment-preparation-conformance/0.1`
- P13 interface profile: `qste-local-interface/v0.1`
- P13 conformance profile: `qste-interface-conformance/0.1`

Records, events, edges, artifact registrations, and dense registrations are
append-only. Artifact bytes are addressed by SHA-256. Dense and bundle
manifests bind every contained file. Symlinks and paths escaping the declared
root fail conformance.

## Verification

```sh
uv run qste verify --workspace /absolute/workspace --json
uv run qste verify --bundle /absolute/relocated-bundle --json
uv run python tools/verify_storage.py
```

Verification never repairs. A bundle reports integrity, logical replay, and
numerical reproducibility separately. In P3, the first two can be `verified`;
the third is always `unavailable`.

## Deterministic STFT reference arm

P5 encodes only an evidenced P4 audio artifact/aperture pair. Its periodic
Hann analysis window, canonical dual, centered padding, FFT length, hop,
dtype, coordinate convention, and reconstruction tolerances are part of the
representation record. Coefficients are one dense artifact; they are not
emitted coefficient-per-record.

```sh
uv run qste representation encode \
  --workspace /absolute/workspace \
  --artifact qste:artifact-record:... \
  --aperture qste:aperture-spec:... \
  --config config.json --authorization permitted --json

uv run qste representation enumerate \
  --workspace /absolute/workspace \
  --instance qste:representation-instance:... \
  --rule candidates.json --authorization permitted --json

uv run qste representation refine \
  --workspace /absolute/workspace \
  --candidate qste:candidate-unit:... \
  --procedure refinement.json --authorization permitted --json
```

The other bounded routes are `support`, `address`, `intervene`, `decode`,
`project`, `measure`, `perturb`, and `account`; run `qste representation
<route> --help` for their exact arguments. Every route requires an explicit
authorization state and produces a durable receipt. `project` is a calibrated
digital mock only, `measure` is native-only, and `refine` builds the complete
finite nonempty proper-mask graph before any effects. Neither a candidate nor
a closed graph is a `DSQAssessment`; P6 assessment remains a separate
operation and record.

## Paired tasks and DSQ assessment

P6 freezes one task-local response scale, direction, meaningful bound,
equivalence region, estimator, seeds, uncertainty method, complete
multiplicity family, selection/confirmation split, artifact controls,
alternate intervention, calibration requirement, and evaluation budget.

```sh
uv run qste task declare \
  --workspace /absolute/workspace \
  --candidate qste:candidate-unit:... \
  --graph qste:refinement-graph:... \
  --spec task.json --authorization permitted --json

uv run qste task execute \
  --workspace /absolute/workspace \
  --task qste:task-spec:... \
  --evidence paired-scores.json --authorization permitted --json

uv run qste quanta assess \
  --workspace /absolute/workspace \
  --candidate qste:candidate-unit:... \
  --task qste:task-spec:... \
  --run qste:run-manifest:... \
  --graph qste:refinement-graph:... \
  --authorization permitted --json
```

The executable score interface accepts bounded raw reference/intervened score
pairs in native task units. It preserves the raw signed difference and the
preregistered direction-normalized effect. Deterministic tasks use a declared
numerical tolerance; stochastic tasks use pinned seeds and full-family
Bonferroni-normal intervals.

`qualified` requires candidate interval lower bound at or above the meaningful
bound and every required proper-node interval contained in the closed
equivalence region. `rejected` requires valid decisive negative evidence.
Nonsignificance, a boundary overlap, empty/incomplete closure, missing
multiplicity, exhausted budget, missing calibration, failed controls, missing
evidence, or invalid dependencies cannot qualify and cannot reject. Use
`qste quanta baseline` for matched stopping-rule diagnostics and `qste quanta
invalidate` to append a dependency defect without rewriting the assessment.

## Cross-arm relations

P7 compares two declared representation instances only after both projections
freeze the same calibrated substrate, measure, footprint kind, normalization,
alignment, and calibration contract. Effect estimands must match exactly or
use an explicit versioned conversion.

```sh
uv run qste relation projection-declare \
  --workspace /absolute/workspace \
  --arm qste:representation-instance:... \
  --spec projection.json --authorization permitted --json

uv run qste relation comparison-declare \
  --workspace /absolute/workspace \
  --projection qste:projection-spec:... \
  --projection qste:projection-spec:... \
  --spec comparison.json --authorization permitted --json

uv run qste relation compare \
  --workspace /absolute/workspace \
  --comparison qste:comparison-spec:... \
  --source qste:candidate-unit:... \
  --target qste:candidate-unit:... \
  --evidence relation-evidence.json \
  --authorization permitted --json
```

Expected-energy footprints are normalized to unit integral; probability
footprints remain bounded and unnormalized. Adjusted interval lower bounds
decide mutual-coverage and effect eligibility, while upper bounds decide
conclusive failure. Point estimates rank only eligible edges. The exact
reference matcher records capacities, allowed cardinalities, unmatched
penalty, optimum set, cardinality preference, and a diagnostic lexicographic
representative without converting structural ambiguity into a relation.

An unmatched unit is never automatically an omission or loss. Those labels
require target-address absence or failed fidelity/consequentiality evidence
before matching. A resolved comparison may have `relation_type=null` for
`coverage_failed`, `effect_incompatible`, or `unmatched_by_spec`.

`qste relation invalidate` appends a canonical dependency defect and queues
descendant review. It never rewrites the frozen `RelationAssertion`.

## Transduction and governance

P8 exposes exactly five modes: `sonification`, `desonification`,
`resonification`, `sonic_transformation`, and `cross_domain_contrast`. A
`MappingSpec` freezes variables, units, ranges, normalization, missing-data
behavior, interpolation, uncertainty, loss, reversibility, and eligible modes.
Execution is local and bounded; it creates analytical fixtures and separate
safety descendants, never playback or evidence that an output was heard.

```sh
uv run qste transduce mapping-declare \
  --workspace /absolute/workspace --context qste:observation:... \
  --spec mapping.json --authorization permitted --json

uv run qste transduce run \
  --workspace /absolute/workspace --mode sonification \
  --source qste:observation:... --mapping qste:mapping-spec:... \
  --parameters parameters.json --authorization permitted --json
```

Governance boundaries name authorities, permitted and human-gated actions,
budgets, roots, stop/resume rules, and appeal/escalation conditions. Appeal
intake requires verified standing evidence, jurisdiction, deadlines, a duty to
respond, and an in-bound named authority. `appeal_status`, `pause_status`,
`adjudication_outcome`, and `repair_status` remain independent event-sourced
axes.

```sh
uv run qste policy boundary-declare \
  --workspace /absolute/workspace --context qste:artifact-record:... \
  --spec boundary.json --authorization permitted --json

uv run qste appeal open \
  --workspace /absolute/workspace --boundary qste:governance-boundary:... \
  --appellant qste:source-record:... --authority qste:apparatus-spec:... \
  --target qste:artifact-record:... --spec appeal.json \
  --authorization permitted --json

uv run qste repair apply \
  --workspace /absolute/workspace --case qste:appeal-case:... \
  --authority qste:apparatus-spec:... --action revoke --spec repair.json \
  --authorization permitted --json
```

Repair actions are `pause`, `correct`, `revoke`, `delete`, `restrict`,
`restore`, and `release_pause`. They require a favorable adjudication for the
same typed action. Feasible non-deletion repairs create a behavior-changing
`SuccessorSpec`; every attempt creates durable receipts. Partial or impossible
repair reports retention conflicts, propagation failures, uncontrolled
external copies, and immutable-history limits. Revocation and pause propagate
over the bounded descendant closure. Public projection additionally requires
explicit human authorization, and `qste export` only creates an internal
allowlisted artifact with `external_write=false`.

## Apparatus and ingress

An apparatus declaration is exact JSON with these fields:
`apparatus_version`, `configuration`, `acquisition_surface`,
`computation_surface`, `action_surface`, and `authorization_status`. The
acquisition surface must explicitly declare admitted media kinds, timebase and
sample rates, channel map, and frequency/level/time calibration states. The
action surface must set `network_access` to `false`.

```sh
uv run qste apparatus validate \
  --workspace /absolute/workspace \
  --declaration apparatus.json --json

uv run qste ingest \
  --workspace /absolute/workspace \
  --input /absolute/input/source.wav \
  --kind audio \
  --apparatus qste:apparatus-spec:... \
  --origin "declared source" \
  --rights rights.json \
  --retention retention.json \
  --allowed-root /absolute/input \
  --authorization permitted --json
```

`rights.json` requires nonempty `use` and an explicit `redistribution` state.
`retention.json` requires `mode` and the same redistribution state. Imported
paths must be ordinary files under an allowed root. Symlinks, changing files,
oversized data, malformed typed profiles, non-finite numbers, duplicate JSON
members, and undeclared apparatus operations fail closed.

JSON numerical observations use `qste-numerical-observations/0.1`; external
model results use `qste-model-observations/0.1` with an exact model ID, version,
and checkpoint digest. P4 stores model results but does not run a model. Text is
strict UTF-8 and remains opaque `dataOnly` content.

## External representation captures

P9 freezes Samplebrain `v0.18.5_release` and EnCodec `v0.1.1` plus the
`facebook/encodec_24khz` checkpoint identity. QSTE does not execute either
implementation in the P9 reference profile. `adapter probe` reads only exact
caller-supplied ordinary files under caller-supplied roots, verifies supplied
digests, and never invokes a subprocess, network, model, decoder, or playback.

`adapter encode` imports a bounded supervised or synthetic capture whose exact
source digest, target revision, configuration, resampling, native values,
candidate addresses/support, decoder capture, controls, opaque fields, and
refinement status are declared. `enumerate`, `support`, `address`, `intervene`,
`decode`, and `account` operate on captured state. `refine`, `project`,
`measure`, and `perturb` return `capability_unavailable` with durable receipts.

```sh
uv run qste adapter probe \
  --workspace /absolute/workspace --adapter samplebrain \
  --context qste:apparatus-spec:... --spec probe.json \
  --authorization permitted --json

uv run qste adapter encode \
  --workspace /absolute/workspace --adapter encodec \
  --artifact qste:artifact-record:... --aperture qste:aperture-spec:... \
  --capture capture.json --authorization permitted --json

uv run qste adapter run \
  --workspace /absolute/workspace --operation account \
  --target qste:representation-instance:... --spec empty.json \
  --authorization permitted --json
```

A Samplebrain block-size change is not a refinement. An EnCodec frame,
codebook token, prefix, or span is not a refinement without verified mapping
and intervention closure. Captured decoder bytes do not establish that an
external decoder ran in QSTE or that anyone heard an output.

## Bounded agent host

P10 treats every plan and prompt as inert content. `qste plan` stores a bounded
proposal; `qste revise` separately validates source authorization, named
authority, the governance action surface, mutable successor fields, registry
action, and memory/action/information/time/resource budgets. It performs no
model inference or external execution.

An accepted revision creates a new `SuccessorSpec`, preserves its predecessor,
and schedules a nonexecuted next `RunManifest` and `RevisionOpportunity`.
Identity, timestamp, serialization, hash, or explanation-only changes fail the
semantic/behavioral comparator. Refusal creates no successor, narrows the next
eligible action set, and records resumption or escalation conditions.

```sh
uv run qste plan \
  --workspace /absolute/workspace \
  --opportunity qste:revision-opportunity:... \
  --treatment qste:artifact-record:... --proposal proposal.json \
  --authorization permitted --json

uv run qste revise \
  --workspace /absolute/workspace --plan qste:artifact-record:... \
  --authority qste:apparatus-spec:... --source-authorization permitted \
  --enforcement-mode active --fixture-authorization synthetic \
  --authorization permitted --json
```

The treatment constructor records `authentic`, `absent`, byte/schema/timing/
access-matched `placebo`, and payload-preserving `permuted` conditions. The
information constructor records `ordinary`, `formation_only`, and
`full_assessment` payloads with one invariant outcome-core digest. Full content
does not itself create a DSQ label. Synthetic treatment divergence is only a
conformance result. Held-out utility/cost, creative consequence, and empirical
agentic-hearing evidence remain independent and are not inferred.

## Ecosystem and engine adapters

P11 adapters consume QSTE-owned frozen fixtures. They never import code from,
execute, or write to adjacent checkouts. `import`, `project`, `inspect`,
`live`, and `account` resolve the target's exact declared capability before
touching payload data. `project` additionally requires `--human-authorized`;
without it, the operation is refused even when the target supports projection.
`live` remains `untested` for all seven ecosystem targets and cannot be
upgraded by a successful fixture validation.

```sh
uv run qste ecosystem import \
  --workspace /absolute/workspace --target masa \
  --context qste:apparatus-spec:... \
  --payload fixtures/ecosystem-adapters/0.1/masa-record.json \
  --authorization permitted --json

uv run qste ecosystem project \
  --workspace /absolute/workspace --target earworm \
  --context qste:apparatus-spec:... \
  --payload fixtures/ecosystem-adapters/0.1/earworm-akousma.json \
  --human-authorized --authorization permitted --json
```

The fixed process fixture is the sole executable P11 target. The adapter
selects the packaged program itself; request data cannot provide an executable
or arguments. Input, output, logs, and timeout are bounded, and every success
or failure records parameters, digests, return state, and timeout state. This
is a deterministic conformance fixture, not a general process or memory
sandbox. The OSC fixture binds only an ephemeral receiver on `127.0.0.1` and
records matching sent/received packet digests.

```sh
uv run qste engine execute \
  --workspace /absolute/workspace --target qste_fixture_process \
  --context qste:apparatus-spec:... \
  --request fixtures/ecosystem-adapters/0.1/engine-process-request.json \
  --authorization permitted --json

uv run qste engine loopback \
  --workspace /absolute/workspace --target qste_fixture_osc_loopback \
  --context qste:apparatus-spec:... \
  --request fixtures/ecosystem-adapters/0.1/engine-loopback-request.json \
  --authorization permitted --json
```

Pure Data, Max/MSP, SuperCollider, and Csound targets return
`capability_unavailable`; the required-untested fixture returns `untested`;
the prohibited fixture returns `policy_refused` with `prohibited`. None is
silently substituted with the synthetic fixture.

## Experiment preparation

P12a freezes an exact preparation packet as an immutable artifact, then lets a
synthetic method pilot prove that the declared parameters can be bound and
checked without accessing outcomes. Corpus rights and a content digest are
mandatory. Digital reference calibration must be declared; unavailable
physical calibration stays explicit.

```sh
uv run qste experiment freeze \
  --workspace /absolute/workspace --context qste:apparatus-spec:... \
  --packet fixtures/experiment-preparation/0.1/preparation.json \
  --authorization permitted --json

uv run qste experiment pilot \
  --workspace /absolute/workspace --preparation qste:artifact-record:... \
  --evidence fixtures/experiment-preparation/0.1/pilot.json \
  --authorization permitted --json

uv run qste experiment account \
  --workspace /absolute/workspace --context qste:apparatus-spec:... \
  --authorization permitted --json
```

The packaged fixtures are synthetic conformance inputs, not a plan or research
result. Confirmatory tests, held-out outcomes, human or listener data, external
execution, playback, and public research projection are rejected or remain
unavailable. Human protocol submission requires separate authorization.

## Skills, MCP, and inspection workbench

P13 fixes one workspace and one or more containing roots when the process
starts. No tool call can select a new workspace, root, executable, provider, or
network target. The MCP server uses stdio unless loopback HTTP is requested
explicitly.

```sh
uv run qste-mcp \
  --workspace /absolute/workspace \
  --allowed-root /absolute \
  --transport stdio

uv run qste-mcp \
  --workspace /absolute/workspace \
  --allowed-root /absolute \
  --transport streamable-http --host 127.0.0.1 --port 8765

uv run qste-workbench \
  --workspace /absolute/workspace \
  --allowed-root /absolute --host 127.0.0.1 --port 8787
```

The fixed MCP registry contains four read tools—inspect, lineage, verify, and
workbench snapshot—and two state-changing tools for registered relation
comparison and declared transduction. State-changing tools are unavailable by
default. Enabling them at startup is only the first gate; each call must also
carry `human_approved=true`. Neither gate authorizes playback, public
projection, external engines, provider access, or adjacent-checkout writes.

The HTTP workbench accepts GET and HEAD only, returns `Cache-Control: no-store`,
and groups bounded occurrence summaries as relations/disagreements, mappings,
claims, and evidence. It does not merge semantic occurrences or present
inference as measurement. The public `skills/qste-inspection` package gives an
agent the same evidence and authorization boundaries.

## Aperture derivation

```sh
uv run qste aperture derive \
  --workspace /absolute/workspace \
  --apparatus qste:apparatus-spec:... \
  --input qste:artifact-record:... \
  --policy aperture-policy.json --json
```

The policy requires explicit permission and a nonempty `allowed_operations`
list; it may further bound frequency and duration. The result is a new
`ApertureSpec` plus its `RunManifest` and `OperationReceipt`. Resampling may
change the derivative sample domain but never retroactively expands the source
or acquisition aperture. SPL and extra-human-frequency capabilities remain
`unavailable` unless the apparatus declaration contains the matching evidence.

## Recovery and migration

Failed SQLite batches roll back. Failed ingress records a failed receipt/event,
does not alter or delete the external input, and creates no SourceRecord or
AcquisitionEvent. A replay starts again from the unchanged source digest.
Failed dense or bundle writes remain staged or unregistered and are not
authoritative. Recovery may remove only a proven incomplete path under
`.staging`; it must not rewrite a committed record, event, edge, artifact,
dense manifest, or sealed bundle.

A future migration copies into a new workspace or bundle format and verifies
the copy before switching authority. The prior SQLite database and bundle are
retained. There is no in-place migration or legacy compatibility reader in P3-P13.
