# Quantum Sound Transduction Engine

QSTE is a proposed local-first research harness for forming, testing, relating,
transducing, and preserving representation-relative digital sonic quanta.

## Current status

The repository now exposes **P14 model-research infrastructure** on top of
the completed P13 skills, MCP, and inspection workbench, P12a
experiment-preparation infrastructure, and P11
ecosystem and audio-engine adapter boundary, and the closed Milestone F
`qste-foundation/0.1` profile. It
validates explicit mappings; executes the five canonical transduction
modes as bounded local, nonplaying operations; enforces authorization before
execution; and persists appeals, adjudications, repair actions, repair
receipts, and dependency-wide policy events without rewriting history.

A candidate becomes DSQ-label eligible only when its adjusted interval is
meaningful and every required proper-node interval lies inside the declared
equivalence region of a closed, nonempty graph. Valid decisive negative
evidence may reject; missing, boundary-crossing, unadjusted, uncalibrated,
artifact-confounded, or dependency-invalid evidence remains indeterminate.
`overlap`, `split`, `merge`, `omission`, `loss`, and `incomparable` remain
situated relation types rather than identity. Conclusive coverage/effect
failure and unique unmatched outcomes are resolved null relations; incomplete,
boundary-crossing, zero-footprint, ambiguous, unavailable, or exhausted
evidence remains indeterminate. P9 adds bounded supervised/captured external
representation adapters, not external execution or a scientific result.
Samplebrain blocks and EnCodec frame/codebook tokens retain native identities
and remain candidate-only because neither arm exposes a verified closed
refinement graph. The adapters declare all eleven ontology operations; seven
captured operations are available and four are explicitly unavailable. P10
adds an action registry,
inert plan records, authority-checked semantic/behavioral successors,
authentic/absent/placebo/permuted controls, three invariant-core information
levels, shadow-policy fixtures, and separate held-out utility/cost records.
These are synthetic conformance capabilities, not evidence that agentic hearing
or creative consequence occurred. P8 availability remains a reference-kernel
claim, not a scientific result: analytical outputs are distinct from controls, safety
descendants, optional renders, and heard outputs. External Samplebrain or
EnCodec execution, autonomous agent models, human/empirical studies, playback,
network services, trained QSTE models, learned-gain evidence, and model
execution remain unavailable.
General scientific numerical reproducibility also remains `unavailable`.

P12a adds an exact, content-addressed preparation packet, frozen parameter
binding, synthetic method-feasibility evidence, and durable success, failure,
and refusal receipts. This is infrastructure and contract conformance only:
the included fixtures are not a research plan, scientific pilot, registered
protocol, result, or evidence for QSTE. An actual research method pilot,
confirmatory machine study, integrated analysis, and numerical reproducibility
remain unavailable. Human protocol submission requires separate authorization;
human collection and public research projection are prohibited here.

P13 adds the `qste-inspection` skill, a fixed six-tool MCP server, and a
read-only browser workbench. Every interface binds one existing workspace under
explicit allowed roots. MCP uses stdio by default; optional HTTP and the
workbench bind only to `127.0.0.1`. Relation comparison and transduction are
disabled unless a human enables mutations at server startup and approves the
individual call. Interface availability does not upgrade any deferred P12
research capability or authorize playback, external execution, or publication.

P14 adds an immutable model-research program declaration, a metadata-only
dataset-manifest registry, exact governance requirements, paired DSQ-derived
and ordinary-segment representation contracts, held-out evaluation
declarations, bounded compute/environment fields, a complete model-card
template, failure/recovery rules, and an explicit route toward a separately
authorized custom model. It does not access dataset bytes, select or download
a checkpoint, train or run a model, generate outputs, execute evaluation, or
assert a learned gain. P12c research evidence and separate training
authorization remain prerequisites for any such work. Model tokens are never
promoted to universal particles, and recursive evaluation cannot revise the
ontology or benchmark definitions.

P11 freezes exact compatibility targets for MASA, Cosmoaudition, AKOÚŌ, Oída,
Earworm, Akousmata, and Listening Stack. Fixture imports and inspections
preserve native identities and carry status, attribution, uncertainty, units,
and times with their values. Each target exposes only its declared operations;
missing implementations, required-but-untested paths, and prohibited paths
produce distinct durable failures. A valid frozen schema proves structural
validity only, never live interoperability. P11 also provides a fixed bounded
synthetic process fixture and an ephemeral `127.0.0.1` OSC round trip. It does
not install or run Pure Data, Max/MSP, SuperCollider, Csound, or any adjacent
project, and it performs no playback, provider access, or external write.

The installed command exposes bounded P3/P4 operations over explicit roots:

```sh
uv run qste version --json
uv run qste inspect --workspace /path/to/workspace --record qste:source-record:... --json
uv run qste lineage --workspace /path/to/workspace --record qste:source-record:... --json
uv run qste verify --workspace /path/to/workspace --json
uv run qste verify --bundle /path/to/relocated-bundle --json
uv run qste bundle --workspace /path/to/workspace --authority authority/authority-manifest.json --json
uv run qste apparatus validate --workspace /path/to/workspace --declaration apparatus.json --json
uv run qste ingest --workspace /path/to/workspace --input source.wav --kind audio --apparatus qste:apparatus-spec:... --origin "declared source" --rights rights.json --retention retention.json --allowed-root /path/to/inputs --authorization permitted --json
uv run qste aperture derive --workspace /path/to/workspace --apparatus qste:apparatus-spec:... --input qste:artifact-record:... --policy policy.json --json
uv run qste representation encode --workspace /path/to/workspace --artifact qste:artifact-record:... --aperture qste:aperture-spec:... --config config.json --authorization permitted --json
uv run qste representation enumerate --workspace /path/to/workspace --instance qste:representation-instance:... --rule candidate-rule.json --authorization permitted --json
uv run qste representation refine --workspace /path/to/workspace --candidate qste:candidate-unit:... --procedure refinement.json --authorization permitted --json
uv run qste representation account --workspace /path/to/workspace --instance qste:representation-instance:... --authorization permitted --json
uv run qste task declare --workspace /path/to/workspace --candidate qste:candidate-unit:... --graph qste:refinement-graph:... --spec task.json --authorization permitted --json
uv run qste task execute --workspace /path/to/workspace --task qste:task-spec:... --evidence paired-scores.json --authorization permitted --json
uv run qste quanta assess --workspace /path/to/workspace --candidate qste:candidate-unit:... --task qste:task-spec:... --run qste:run-manifest:... --graph qste:refinement-graph:... --authorization permitted --json
uv run qste relation projection-declare --workspace /path/to/workspace --arm qste:representation-instance:... --spec projection.json --authorization permitted --json
uv run qste relation comparison-declare --workspace /path/to/workspace --projection qste:projection-spec:... --projection qste:projection-spec:... --spec comparison.json --authorization permitted --json
uv run qste relation compare --workspace /path/to/workspace --comparison qste:comparison-spec:... --source qste:candidate-unit:... --target qste:candidate-unit:... --evidence relation-evidence.json --authorization permitted --json
uv run qste transduce mapping-declare --workspace /path/to/workspace --context qste:observation:... --spec mapping.json --authorization permitted --json
uv run qste transduce run --workspace /path/to/workspace --mode sonification --source qste:observation:... --mapping qste:mapping-spec:... --parameters parameters.json --authorization permitted --json
uv run qste policy boundary-declare --workspace /path/to/workspace --context qste:artifact-record:... --spec boundary.json --authorization permitted --json
uv run qste appeal open --workspace /path/to/workspace --boundary qste:governance-boundary:... --appellant qste:source-record:... --authority qste:apparatus-spec:... --target qste:artifact-record:... --spec appeal.json --authorization permitted --json
uv run qste appeal adjudicate --workspace /path/to/workspace --case qste:appeal-case:... --authority qste:apparatus-spec:... --outcome upheld --evidence qste:observation:... --authorization permitted --json
uv run qste repair apply --workspace /path/to/workspace --case qste:appeal-case:... --authority qste:apparatus-spec:... --action revoke --spec repair.json --authorization permitted --json
uv run qste export --workspace /path/to/workspace --target qste:artifact-record:... --boundary qste:governance-boundary:... --disclosure project_internal --authorization permitted --json
uv run qste adapter probe --workspace /path/to/workspace --adapter samplebrain --context qste:apparatus-spec:... --spec probe.json --authorization permitted --json
uv run qste adapter encode --workspace /path/to/workspace --adapter samplebrain --artifact qste:artifact-record:... --aperture qste:aperture-spec:... --capture capture.json --authorization permitted --json
uv run qste adapter enumerate --workspace /path/to/workspace --instance qste:representation-instance:... --rule candidate-rule.json --authorization permitted --json
uv run qste adapter run --workspace /path/to/workspace --operation account --target qste:representation-instance:... --spec empty.json --authorization permitted --json
uv run qste agent initialize --workspace /path/to/workspace --boundary qste:governance-boundary:... --authority qste:apparatus-spec:... --source qste:artifact-record:... --completed-run qste:run-manifest:... --predecessor qste:aperture-spec:... --spec harness.json --authorization permitted --json
uv run qste agent treatments --workspace /path/to/workspace --opportunity qste:revision-opportunity:... --payload qste:artifact-record:... --allocation allocation.json --authorization permitted --json
uv run qste plan --workspace /path/to/workspace --opportunity qste:revision-opportunity:... --treatment qste:artifact-record:... --proposal proposal.json --authorization permitted --json
uv run qste revise --workspace /path/to/workspace --plan qste:artifact-record:... --authority qste:apparatus-spec:... --source-authorization permitted --enforcement-mode active --fixture-authorization synthetic --authorization permitted --json
uv run qste ecosystem import --workspace /path/to/workspace --target masa --context qste:apparatus-spec:... --payload fixtures/ecosystem-adapters/0.1/masa-record.json --authorization permitted --json
uv run qste ecosystem inspect --workspace /path/to/workspace --target listening_stack --context qste:apparatus-spec:... --payload fixtures/ecosystem-adapters/0.1/listening-stack-metadata.json --authorization permitted --json
uv run qste ecosystem account --workspace /path/to/workspace --target oida --context qste:apparatus-spec:... --authorization permitted --json
uv run qste engine execute --workspace /path/to/workspace --target qste_fixture_process --context qste:apparatus-spec:... --request fixtures/ecosystem-adapters/0.1/engine-process-request.json --authorization permitted --json
uv run qste engine loopback --workspace /path/to/workspace --target qste_fixture_osc_loopback --context qste:apparatus-spec:... --request fixtures/ecosystem-adapters/0.1/engine-loopback-request.json --authorization permitted --json
uv run qste experiment freeze --workspace /path/to/workspace --context qste:apparatus-spec:... --packet fixtures/experiment-preparation/0.1/preparation.json --authorization permitted --json
uv run qste experiment pilot --workspace /path/to/workspace --preparation qste:artifact-record:... --evidence fixtures/experiment-preparation/0.1/pilot.json --authorization permitted --json
uv run qste experiment account --workspace /path/to/workspace --context qste:apparatus-spec:... --authorization permitted --json
uv run qste model freeze --workspace /path/to/workspace --context qste:apparatus-spec:... --program fixtures/model-research/0.1/program.json --authorization permitted --json
uv run qste model dataset --workspace /path/to/workspace --program-record qste:artifact-record:... --manifest dataset-manifest.json --authorization permitted --json
uv run qste model account --workspace /path/to/workspace --context qste:apparatus-spec:... --authorization permitted --json
uv run qste-mcp --workspace /path/to/workspace --allowed-root /path/to --transport stdio
uv run qste-workbench --workspace /path/to/workspace --allowed-root /path/to --port 8787
```

## Authority

1. [QSTE ontology v0.3.0](ontology/0.3.0/QSTE_ontology.md) is the sole
   normative semantic contract.
2. [Current authority manifest](authority/authority-manifest.json) binds the
   public contract, schemas, conformance profiles, compatibility targets, and
   verified implementation commit. Private governance material is not part of
   the repository projection.

Schemas, conformance profiles, code, adapters, agents, and interfaces remain
subordinate to the exact contract version they declare. Missing evidence never
authorizes a positive claim.

## Foundation tooling

QSTE targets Python 3.12 with `uv`. The initial package is one
`src/qste/` distribution.

```sh
uv sync --all-groups
make verify
```

After synchronization, `make offline-smoke` runs the P2 contracts, P3 storage,
P4 ingress, P5 representation, P6 task/assessment, P7 relation, P8
transduction/governance, P9 adapter-boundary, P10 agent-host, P11
ecosystem/engine, P12a preparation-boundary, and P13 interface checks with
external network access disabled, plus the P14 model-research declaration
boundary with all model execution disabled.

The library contract surface is intentionally small:

```python
from qste.core import SchemaRegistry
from qste.storage import ArtifactStore, DenseStore, RecordStore
from qste.ingress import IngressLimits, IngressService
from qste.representations import STFTConfig, STFTService
from qste.quanta import QuantaService
from qste.relations import RelationService
from qste.transduction import TransductionService
from qste.policy import PolicyService
from qste.adapters import (
    BoundedEngineService,
    EcosystemAdapterService,
    ExternalRepresentationService,
)
from qste.agent import AgentHostService
from qste.experiments import ExperimentPreparationService
from qste.interfaces import InspectionWorkbench, InterfaceBroker, InterfacePolicy
from qste.model_research import ModelResearchService

registry = SchemaRegistry()
record = registry.read_record(raw_json_bytes)
canonical_json = registry.write_record(record)

store = RecordStore.initialize(workspace_root)
store.insert_record(record)
artifact = ArtifactStore(store.paths).put_bytes(source_bytes)
dense = DenseStore(store.paths, store)
```

See [`schemas/0.3.0/schema-index.json`](schemas/0.3.0/schema-index.json) and
[`conformance/0.3.0/conformance-index.json`](conformance/0.3.0/conformance-index.json)
for the digest-bound contract corpus, and
[`conformance/p3-storage/0.1/storage-profile.json`](conformance/p3-storage/0.1/storage-profile.json)
for the P3 behavioral gates, and
[`conformance/p4-ingress/0.1/ingress-profile.json`](conformance/p4-ingress/0.1/ingress-profile.json)
for the P4 gates, and
[`conformance/p5-stft-gabor/0.1/representation-profile.json`](conformance/p5-stft-gabor/0.1/representation-profile.json)
for the P5 gates, and
[`conformance/p6-dsq/0.1/quanta-profile.json`](conformance/p6-dsq/0.1/quanta-profile.json)
for the P6 gates, and
[`conformance/p7-relations/0.1/relation-profile.json`](conformance/p7-relations/0.1/relation-profile.json)
for the P7 gates, and
[`conformance/p8-transduction-governance/0.1/profile.json`](conformance/p8-transduction-governance/0.1/profile.json)
for the P8 gates, and
[`conformance/p9-external-representations/0.1/profile.json`](conformance/p9-external-representations/0.1/profile.json)
for the P9 gates, and
[`conformance/p10-agent-harness/0.1/profile.json`](conformance/p10-agent-harness/0.1/profile.json)
for the P10 gates, and
[`conformance/p11-ecosystem-engines/0.1/profile.json`](conformance/p11-ecosystem-engines/0.1/profile.json)
for the P11 gates, and
[`conformance/p12-experiment-preparation/0.1/profile.json`](conformance/p12-experiment-preparation/0.1/profile.json)
for the P12a infrastructure gates, and
[`conformance/p13-interfaces/0.1/profile.json`](conformance/p13-interfaces/0.1/profile.json)
for the P13 interface gates. The corresponding exact external target profile is
[`CompatibilityTargetManifest`](profiles/adapters/ecosystem/0.1/compatibility-target-manifest.json).

## Boundaries

- Runtime access is restricted to explicit roots.
- Network access and playback are disabled by default.
- Adjacent projects remain external, read-only authorities.
- External integrations are QSTE-owned adapters or frozen fixtures.
- Private material remains private; public output is a separately authorized
  projection.
- A coefficient, block, sample, or codec token is a candidate at most. It is
  not a DSQ without the complete ontology-defined qualification evidence.
