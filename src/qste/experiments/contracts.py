"""Frozen public P12a preparation contract."""

PREPARATION_PROFILE = "qste-experiment-preparation/v0.1"
PILOT_PROFILE = "qste-method-pilot/v0.1"
CONFORMANCE_PROFILE = "qste-experiment-preparation-conformance/0.1"

PARAMETER_FIELDS = frozenset(
    {
        "meaningful_bound",
        "equivalence_region",
        "coverage_tolerance",
        "effect_tolerance",
        "capacities",
        "unmatched_penalty_lambda",
        "perturbation_plan",
        "treatment_construction",
        "leakage_checks",
        "uncertainty",
        "multiplicity",
        "power_assumptions",
    }
)

SAFETY_FLAGS = frozenset(
    {
        "confirmatory_hypotheses_tested",
        "held_out_outcomes_accessed",
        "human_data_collected",
        "listener_data_collected",
    }
)
