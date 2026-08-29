# P9 external-representation conformance

This profile tests the QSTE capture boundary, not Samplebrain or EnCodec's
scientific validity. The fixtures are synthetic and do not execute either
external implementation. A passing result establishes exact capability
declarations, native candidate identity, bounded captured operations, opaque
boundary records, durable failures, and the absence of a fabricated
refinement graph.

Run `uv run python tools/verify_external_representations.py` from the repository
root. External packages and weights are neither needed nor loaded.
