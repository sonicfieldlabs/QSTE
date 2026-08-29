"""Frozen public P14 model-research preparation contract."""

PROGRAM_PROFILE = "qste-model-research-program/v0.1"
DATASET_PROFILE = "qste-model-dataset-manifest/v0.1"
CONFORMANCE_PROFILE = "qste-model-research-conformance/0.1"

PROGRAM_FIELDS = frozenset(
    {
        "profile_id",
        "stage",
        "research_question",
        "dataset_governance",
        "training_representations",
        "fine_tuning",
        "evaluation_suite",
        "compute_environment_budget",
        "model_card_template",
        "failure_analysis",
        "custom_model_route",
        "safety_flags",
    }
)

PROGRAM_SAFETY_FLAGS = frozenset(
    {
        "training_executed",
        "checkpoint_downloaded",
        "data_collected",
        "generation_performed",
        "human_data_used",
        "ontology_revised",
        "benchmark_revised",
    }
)

DATASET_FIELDS = frozenset(
    {
        "profile_id",
        "manifest_stage",
        "program_digest",
        "dataset_id",
        "version",
        "items",
        "splits",
        "governance",
        "safety_flags",
    }
)

MODEL_CARD_SECTIONS = frozenset(
    {
        "identity",
        "intended_use",
        "out_of_scope_use",
        "training_data",
        "evaluation",
        "limitations",
        "permissions",
        "environmental_budget",
        "failure_analysis",
        "ontology_boundary",
    }
)
