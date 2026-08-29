.PHONY: sync format lint type contracts storage-contracts ingress-contracts representation-contracts quanta-contracts relation-contracts transduction-governance-contracts external-representation-contracts agent-harness-contracts ecosystem-engine-contracts experiment-preparation-contracts interface-contracts model-research-contracts test build smoke offline-smoke verify

sync:
	uv sync --all-groups

format:
	uv run ruff format .

lint:
	uv run ruff check .

type:
	uv run mypy

contracts:
	uv run python tools/verify_contracts.py

storage-contracts:
	uv run python tools/verify_storage.py

ingress-contracts:
	uv run python tools/verify_ingress.py

representation-contracts:
	uv run python tools/verify_representations.py

quanta-contracts:
	uv run python tools/verify_quanta.py

relation-contracts:
	uv run python tools/verify_relations.py

transduction-governance-contracts:
	uv run python tools/verify_transduction_governance.py

external-representation-contracts:
	uv run python tools/verify_external_representations.py

agent-harness-contracts:
	uv run python tools/verify_agent_harness.py

ecosystem-engine-contracts:
	uv run python tools/verify_ecosystem_engines.py

experiment-preparation-contracts:
	uv run python tools/verify_experiment_preparation.py

interface-contracts:
	uv run python tools/verify_interfaces.py

model-research-contracts:
	uv run python tools/verify_model_research.py

test:
	uv run pytest

build:
	uv build

smoke:
	uv run qste version --json

offline-smoke:
	UV_OFFLINE=1 uv run --frozen --no-sync qste version --json
	UV_OFFLINE=1 uv run --frozen --no-sync pytest tests/test_authority_files.py tests/test_contracts.py tests/test_identity.py tests/test_storage.py tests/test_dense.py tests/test_bundle.py tests/test_operations.py tests/test_p4_apparatus.py tests/test_p4_ingress.py tests/test_p4_audio_aperture.py tests/test_p4_operations.py tests/test_p5_reconstruction.py tests/test_p5_candidates_refinement.py tests/test_p5_interventions.py tests/test_p5_operations.py tests/test_p6_assessment.py tests/test_p6_indeterminate.py tests/test_p6_execution_invalidation.py tests/test_p6_operations.py tests/test_p7_projection_coverage.py tests/test_p7_outcomes.py tests/test_p7_matching.py tests/test_p7_operations.py tests/test_p8_transduction.py tests/test_p8_governance.py tests/test_p8_operations.py tests/test_p9_adapters.py tests/test_p9_operations.py tests/test_p10_harness.py tests/test_p10_treatments.py tests/test_p10_revision.py tests/test_p10_evaluation.py tests/test_p10_operations.py tests/test_p11_ecosystem.py tests/test_p11_engine.py tests/test_p11_operations.py tests/test_p12_preparation.py tests/test_p12_operations.py tests/test_p13_interfaces.py tests/test_p13_mcp.py tests/test_p13_workbench.py tests/test_p14_model_research.py tests/test_p14_operations.py tests/test_version.py

verify: lint type contracts storage-contracts ingress-contracts representation-contracts quanta-contracts relation-contracts transduction-governance-contracts external-representation-contracts agent-harness-contracts ecosystem-engine-contracts experiment-preparation-contracts interface-contracts model-research-contracts test build offline-smoke
