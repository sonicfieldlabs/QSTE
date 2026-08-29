"""Package, contract, and source-checkout identity."""

from __future__ import annotations

import os
import re
from importlib import metadata
from pathlib import Path

CONTRACT_ID = "qste-contract/0.3.0"
CAPABILITY_PROFILE = "qste-foundation/0.1"
IMPLEMENTATION_PHASE = "P14-infrastructure"
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

try:
    __version__ = metadata.version("qste")
except metadata.PackageNotFoundError:
    __version__ = "0.0.0"


def _declared_commit() -> str | None:
    value = os.environ.get("QSTE_BUILD_GIT_COMMIT", "").strip().lower()
    return value if _COMMIT_PATTERN.fullmatch(value) else None


def _checkout_commit(repository_root: Path | None = None) -> str | None:
    """Resolve HEAD without executing a program from the caller's PATH."""

    repository_root = repository_root or Path(__file__).resolve().parents[2]
    git_entry = repository_root / ".git"
    if not git_entry.exists():
        return None
    try:
        if git_entry.is_file():
            declaration = git_entry.read_text(encoding="utf-8").strip()
            if not declaration.startswith("gitdir: "):
                return None
            git_directory = (repository_root / declaration.removeprefix("gitdir: ")).resolve()
        elif git_entry.is_dir():
            git_directory = git_entry.resolve()
        else:
            return None
        head = (git_directory / "HEAD").read_text(encoding="utf-8").strip().lower()
        if _COMMIT_PATTERN.fullmatch(head):
            return head
        if not head.startswith("ref: "):
            return None
        reference = head.removeprefix("ref: ")
        if not reference.startswith("refs/") or ".." in Path(reference).parts:
            return None
        reference_roots = [git_directory]
        common_directory_file = git_directory / "commondir"
        if common_directory_file.is_file():
            common_directory = (
                git_directory / common_directory_file.read_text(encoding="utf-8").strip()
            ).resolve()
            if not common_directory.is_dir():
                return None
            reference_roots.append(common_directory)
        for reference_root in reference_roots:
            loose_reference = reference_root.joinpath(*reference.split("/"))
            if loose_reference.is_file():
                value = loose_reference.read_text(encoding="utf-8").strip().lower()
                return value if _COMMIT_PATTERN.fullmatch(value) else None
        suffix = f" {reference}"
        for reference_root in reference_roots:
            packed_references = reference_root / "packed-refs"
            if not packed_references.is_file():
                continue
            for line in packed_references.read_text(encoding="utf-8").splitlines():
                if line.startswith(("#", "^")) or not line.endswith(suffix):
                    continue
                value = line.split(" ", 1)[0].lower()
                return value if _COMMIT_PATTERN.fullmatch(value) else None
    except (OSError, UnicodeError):
        return None
    return None


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
        "inspection_skill_capability_status": "available",
        "mcp_stdio_capability_status": "available",
        "mcp_loopback_http_capability_status": "available",
        "mcp_remote_binding_status": "prohibited",
        "mcp_mutation_default_status": "disabled",
        "inspection_workbench_capability_status": "available",
        "model_research_program_capability_status": "available",
        "model_dataset_manifest_capability_status": "available",
        "model_dataset_bytes_status": "unavailable",
        "model_checkpoint_download_status": "unavailable",
        "model_fine_tuning_execution_status": "authorization_required",
        "trained_qste_model_status": "unavailable",
        "learned_model_gain_evidence_status": "unavailable",
        "model_analysis_evaluation_status": "unavailable",
        "model_generation_evaluation_status": "unavailable",
        "custom_model_status": "unavailable",
        "model_public_projection_status": "prohibited",
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
        "interface_conformance_profile_id": "qste-interface-conformance/0.1",
        "model_research_conformance_profile_id": "qste-model-research-conformance/0.1",
    }
