# P11 ecosystem and engine conformance

This profile verifies byte-frozen ecosystem fixtures, explicit capability
outcomes, a fixed synthetic subprocess, and an OSC packet round-trip restricted
to `127.0.0.1`. It does not execute an adjacent project or external audio
engine, establish live interoperability, play sound, access a provider, or
authorize a public projection.

Run `uv run python tools/verify_ecosystem_engines.py`.
