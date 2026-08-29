from __future__ import annotations

import json
import re

from qste._version import version_info
from qste.cli import main


def test_version_payload_is_explicit() -> None:
    payload = version_info()
    assert payload["package"] == "qste"
    assert payload["contract_id"] == "qste-contract/0.3.0"
    assert payload["capability_profile"] == "qste-foundation/0.1"
    assert payload["implementation_phase"] == "P14-infrastructure"
    assert payload["capability_status"] == "available"
    assert payload["schema_capability_status"] == "available"
    assert payload["identity_storage_capability_status"] == "available"
    assert payload["bundle_capability_status"] == "available"
    assert payload["typed_ingress_capability_status"] == "available"
    assert payload["apparatus_aperture_capability_status"] == "available"
    assert payload["stft_reference_arm_capability_status"] == "available"
    assert payload["candidate_formation_capability_status"] == "available"
    assert payload["paired_task_execution_capability_status"] == "available"
    assert payload["dsq_assessment_capability_status"] == "available"
    assert payload["dependency_invalidation_capability_status"] == "available"
    assert payload["calibrated_mock_substrate_capability_status"] == "available"
    assert payload["cross_arm_relation_capability_status"] == "available"
    assert payload["exact_b_matching_capability_status"] == "available"
    assert payload["relation_invalidation_capability_status"] == "available"
    assert payload["transduction_capability_status"] == "available"
    assert payload["governance_policy_capability_status"] == "available"
    assert payload["appeal_repair_capability_status"] == "available"
    assert payload["bounded_export_projection_capability_status"] == "available"
    assert payload["external_representation_adapter_capability_status"] == "available"
    assert payload["samplebrain_supervised_capture_capability_status"] == "available"
    assert payload["samplebrain_external_execution_status"] == "unavailable"
    assert payload["encodec_captured_fixture_capability_status"] == "available"
    assert payload["encodec_external_execution_status"] == "unavailable"
    assert payload["encodec_checkpoint_status"] == "unavailable"
    assert payload["agent_harness_capability_status"] == "available"
    assert payload["comparative_treatment_capability_status"] == "available"
    assert payload["information_payload_capability_status"] == "available"
    assert payload["shadow_policy_fixture_capability_status"] == "available"
    assert payload["autonomous_agent_model_status"] == "unavailable"
    assert payload["agentic_hearing_research_evidence_status"] == "unavailable"
    assert payload["creative_consequence_evidence_status"] == "unavailable"
    assert payload["ecosystem_adapter_capability_status"] == "available"
    assert payload["ecosystem_live_interoperability_status"] == "untested"
    assert payload["bounded_engine_fixture_capability_status"] == "available"
    assert payload["external_audio_engine_execution_status"] == "unavailable"
    assert payload["osc_loopback_fixture_capability_status"] == "available"
    assert payload["numerical_reproducibility_status"] == "unavailable"
    assert payload["experiment_preparation_capability_status"] == "available"
    assert payload["synthetic_method_pilot_capability_status"] == "available"
    assert payload["research_method_pilot_status"] == "unavailable"
    assert payload["confirmatory_machine_study_status"] == "unavailable"
    assert payload["human_protocol_submission_status"] == "authorization_required"
    assert payload["human_data_collection_status"] == "prohibited"
    assert payload["integrated_research_analysis_status"] == "unavailable"
    assert payload["public_research_projection_status"] == "prohibited"
    assert payload["inspection_skill_capability_status"] == "available"
    assert payload["mcp_stdio_capability_status"] == "available"
    assert payload["mcp_loopback_http_capability_status"] == "available"
    assert payload["mcp_remote_binding_status"] == "prohibited"
    assert payload["mcp_mutation_default_status"] == "disabled"
    assert payload["inspection_workbench_capability_status"] == "available"
    assert payload["model_research_program_capability_status"] == "available"
    assert payload["model_dataset_manifest_capability_status"] == "available"
    assert payload["model_dataset_bytes_status"] == "unavailable"
    assert payload["model_checkpoint_download_status"] == "unavailable"
    assert payload["model_fine_tuning_execution_status"] == "authorization_required"
    assert payload["trained_qste_model_status"] == "unavailable"
    assert payload["learned_model_gain_evidence_status"] == "unavailable"
    assert payload["model_analysis_evaluation_status"] == "unavailable"
    assert payload["model_generation_evaluation_status"] == "unavailable"
    assert payload["custom_model_status"] == "unavailable"
    assert payload["model_public_projection_status"] == "prohibited"
    assert payload["schema_set_id"] == "qste-schema/0.3.0"
    assert payload["conformance_profile_id"] == "qste-conformance/0.3.0"
    assert payload["representation_conformance_profile_id"] == "qste-stft-gabor-conformance/0.1"
    assert payload["quanta_conformance_profile_id"] == "qste-dsq-conformance/0.1"
    assert payload["relation_conformance_profile_id"] == "qste-relation-conformance/0.1"
    assert (
        payload["transduction_governance_conformance_profile_id"]
        == "qste-transduction-governance-conformance/0.1"
    )
    assert (
        payload["external_representation_conformance_profile_id"]
        == "qste-external-representation-conformance/0.1"
    )
    assert payload["agent_harness_conformance_profile_id"] == ("qste-agent-harness-conformance/0.1")
    assert payload["ecosystem_engine_conformance_profile_id"] == (
        "qste-ecosystem-engine-conformance/0.1"
    )
    assert payload["experiment_preparation_conformance_profile_id"] == (
        "qste-experiment-preparation-conformance/0.1"
    )
    assert payload["interface_conformance_profile_id"] == "qste-interface-conformance/0.1"
    assert payload["model_research_conformance_profile_id"] == (
        "qste-model-research-conformance/0.1"
    )
    assert payload["git_commit"] == "uncommitted" or re.fullmatch(
        r"[0-9a-f]{40}", payload["git_commit"]
    )


def test_cli_json_reports_all_identity_layers(capsys: object) -> None:
    assert main(["version", "--json"]) == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert set(payload) == {
        "capability_profile",
        "capability_status",
        "bundle_capability_status",
        "typed_ingress_capability_status",
        "apparatus_aperture_capability_status",
        "stft_reference_arm_capability_status",
        "candidate_formation_capability_status",
        "dsq_assessment_capability_status",
        "paired_task_execution_capability_status",
        "dependency_invalidation_capability_status",
        "calibrated_mock_substrate_capability_status",
        "cross_arm_relation_capability_status",
        "exact_b_matching_capability_status",
        "relation_invalidation_capability_status",
        "transduction_capability_status",
        "governance_policy_capability_status",
        "appeal_repair_capability_status",
        "bounded_export_projection_capability_status",
        "external_representation_adapter_capability_status",
        "samplebrain_supervised_capture_capability_status",
        "samplebrain_external_execution_status",
        "encodec_captured_fixture_capability_status",
        "encodec_external_execution_status",
        "encodec_checkpoint_status",
        "agent_harness_capability_status",
        "comparative_treatment_capability_status",
        "information_payload_capability_status",
        "shadow_policy_fixture_capability_status",
        "autonomous_agent_model_status",
        "agentic_hearing_research_evidence_status",
        "creative_consequence_evidence_status",
        "ecosystem_adapter_capability_status",
        "ecosystem_live_interoperability_status",
        "bounded_engine_fixture_capability_status",
        "external_audio_engine_execution_status",
        "osc_loopback_fixture_capability_status",
        "code_version",
        "conformance_profile_id",
        "representation_conformance_profile_id",
        "quanta_conformance_profile_id",
        "relation_conformance_profile_id",
        "transduction_governance_conformance_profile_id",
        "external_representation_conformance_profile_id",
        "agent_harness_conformance_profile_id",
        "ecosystem_engine_conformance_profile_id",
        "experiment_preparation_capability_status",
        "synthetic_method_pilot_capability_status",
        "research_method_pilot_status",
        "confirmatory_machine_study_status",
        "human_protocol_submission_status",
        "human_data_collection_status",
        "integrated_research_analysis_status",
        "public_research_projection_status",
        "experiment_preparation_conformance_profile_id",
        "inspection_skill_capability_status",
        "mcp_stdio_capability_status",
        "mcp_loopback_http_capability_status",
        "mcp_remote_binding_status",
        "mcp_mutation_default_status",
        "inspection_workbench_capability_status",
        "model_research_program_capability_status",
        "model_dataset_manifest_capability_status",
        "model_dataset_bytes_status",
        "model_checkpoint_download_status",
        "model_fine_tuning_execution_status",
        "trained_qste_model_status",
        "learned_model_gain_evidence_status",
        "model_analysis_evaluation_status",
        "model_generation_evaluation_status",
        "custom_model_status",
        "model_public_projection_status",
        "interface_conformance_profile_id",
        "model_research_conformance_profile_id",
        "contract_id",
        "git_commit",
        "implementation_phase",
        "identity_storage_capability_status",
        "numerical_reproducibility_status",
        "package",
        "schema_capability_status",
        "schema_set_id",
    }
