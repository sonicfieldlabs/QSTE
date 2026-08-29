# P14 model-research conformance

This profile verifies only the public declaration and governance infrastructure
for a future, separately authorized model-research program. The fixtures are
synthetic contract templates. They are not datasets, checkpoints, models,
training runs, evaluations, learned gains, research results, or evidence that a
DSQ-derived representation outperforms an ordinary segment.

Run `uv run python tools/verify_model_research.py`. The verifier is local and
offline and keeps dataset-byte access, checkpoint download, training,
generation, empirical evaluation, human interaction, and public projection
false.
