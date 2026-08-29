"""Package, contract, and source-checkout identity."""

from __future__ import annotations

import os
import re
import subprocess
from importlib import metadata
from pathlib import Path

CONTRACT_ID = "qste-contract/0.3.0"
CAPABILITY_PROFILE = "qste-foundation/0.1"
IMPLEMENTATION_PHASE = "P12a-infrastructure"
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

try:
    __version__ = metadata.version("qste")
except metadata.PackageNotFoundError:
    __version__ = "0.0.0"


def _declared_commit() -> str | None:
    value = os.environ.get("QSTE_BUILD_GIT_COMMIT", "").strip().lower()
    return value if _COMMIT_PATTERN.fullmatch(value) else None


def _checkout_commit() -> str | None:
    repository_root = Path(__file__).resolve().parents[2]
    if not (repository_root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "--verify", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and _COMMIT_PATTERN.fullmatch(value) else None


def git_commit() -> str:
    """Return an injected build commit, checkout commit, or explicit unbound state."""

    return _declared_commit() or _checkout_commit() or "uncommitted"


def version_info() -> dict[str, str]:
    """Return the bounded identity and capability payload."""

    return {
        "package": "qste",
        "code_version": __version__,
        "git_commit": git_commit(),
        "contract_id": CONTRACT_ID,
        "capability_profile": CAPABILITY_PROFILE,
        "implementation_phase": IMPLEMENTATION_PHASE,
        "capability_status": "available",
        "schema_capability_status": "available",
        "identity_storage_capability_status": "available",
        "bundle_capability_status": "available",
        "typed_ingress_capability_status": "available",
        "apparatus_aperture_capability_status": "available",
        "stft_reference_arm_capability_status": "available",
        "candidate_formation_capability_status": "available",
        "paired_task_execution_capability_status": "available",
        "dsq_assessment_capability_status": "available",
        "dependency_invalidation_capability_status": "available",
        "calibrated_mock_substrate_capability_status": "available",
        "cross_arm_relation_capability_status": "available",
        "exact_b_matching_capability_status": "available",
        "relation_invalidation_capability_status": "available",
        "transduction_capability_status": "available",
        "governance_policy_capability_status": "available",
        "appeal_repair_capability_status": "available",
        "bounded_export_projection_capability_status": "available",
        "external_representation_adapter_capability_status": "available",
        "samplebrain_supervised_capture_capability_status": "available",
        "samplebrain_external_execution_status": "unavailable",
        "encodec_captured_fixture_capability_status": "available",
        "encodec_external_execution_status": "unavailable",
        "encodec_checkpoint_status": "unavailable",
        "agent_harness_capability_status": "available",
        "comparative_treatment_capability_status": "available",
        "information_payload_capability_status": "available",
        "shadow_policy_fixture_capability_status": "available",
        "autonomous_agent_model_status": "unavailable",
        "agentic_hearing_research_evidence_status": "unavailable",
        "creative_consequence_evidence_status": "unavailable",
        "ecosystem_adapter_capability_status": "available",
        "ecosystem_live_interoperability_status": "untested",
        "bounded_engine_fixture_capability_status": "available",
        "external_audio_engine_execution_status": "unavailable",
        "osc_loopback_fixture_capability_status": "available",
        "numerical_reproducibility_status": "unavailable",
        "experiment_preparation_capability_status": "available",
        "synthetic_method_pilot_capability_status": "available",
        "research_method_pilot_status": "unavailable",
        "confirmatory_machine_study_status": "unavailable",
        "human_protocol_submission_status": "authorization_required",
        "human_data_collection_status": "prohibited",
        "integrated_research_analysis_status": "unavailable",
        "public_research_projection_status": "prohibited",
        "schema_set_id": "qste-schema/0.3.0",
        "conformance_profile_id": "qste-conformance/0.3.0",
        "representation_conformance_profile_id": "qste-stft-gabor-conformance/0.1",
        "quanta_conformance_profile_id": "qste-dsq-conformance/0.1",
        "relation_conformance_profile_id": "qste-relation-conformance/0.1",
        "transduction_governance_conformance_profile_id": (
            "qste-transduction-governance-conformance/0.1"
        ),
        "external_representation_conformance_profile_id": (
            "qste-external-representation-conformance/0.1"
        ),
        "agent_harness_conformance_profile_id": "qste-agent-harness-conformance/0.1",
        "ecosystem_engine_conformance_profile_id": "qste-ecosystem-engine-conformance/0.1",
        "experiment_preparation_conformance_profile_id": (
            "qste-experiment-preparation-conformance/0.1"
        ),
    }
