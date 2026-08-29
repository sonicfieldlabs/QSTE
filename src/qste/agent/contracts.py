"""Frozen P10 agent-host, treatment, and evaluation contracts."""

from __future__ import annotations

from dataclasses import dataclass

HARNESS_PROFILE = "qste-listening-harness/v0.1"
REVISION_PROFILE = "qste-evidence-dependent-revision/v0.1"
TREATMENT_PROFILE = "qste-revision-treatment/v0.1"
PAYLOAD_PROFILE = "qste-dsq-information-payload/v0.1"
STUDY_PROFILE = "qste-revision-comparative-baseline/v0.1"
UTILITY_PROFILE = "qste-held-out-utility-cost/v0.1"
CONFORMANCE_PROFILE = "qste-agent-harness-conformance/0.1"

EXECUTOR_CLASSES = (
    "human",
    "frozen_algorithm",
    "adaptive_algorithm",
    "symbolic_controller",
    "learned_controller",
    "revising_controller",
    "hybrid_procedure",
)
TREATMENTS = ("authentic", "absent", "placebo", "permuted")
PAYLOAD_LEVELS = ("ordinary", "formation_only", "full_assessment")
LIMIT_FIELDS = (
    "maximum_operations",
    "maximum_seconds",
    "maximum_information_records",
    "maximum_memory_items",
    "maximum_resource_units",
)


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    action_id: str
    decision_action: str
    mutable_field: str | None
    creates_successor: bool


ACTION_REGISTRY = {
    value.action_id: value
    for value in (
        ActionDefinition("revise_aperture", "revise", "aperture", True),
        ActionDefinition("revise_task", "revise", "task", True),
        ActionDefinition("revise_bound", "revise", "meaningful_bound", True),
        ActionDefinition("revise_representation", "revise", "representation", True),
        ActionDefinition("revise_plan", "revise", "plan", True),
        ActionDefinition("revise_action_set", "revise", "executable_action_set", True),
        ActionDefinition("refuse", "refuse", None, False),
        ActionDefinition("escalate", "escalate", None, False),
        ActionDefinition("resume", "resume", "executable_action_set", True),
        ActionDefinition("no_change", "no_change", None, False),
    )
}

VOLATILE_FIELDS = frozenset(
    {"record_id", "created_at", "semantic_key", "content_digest", "serialization"}
)
