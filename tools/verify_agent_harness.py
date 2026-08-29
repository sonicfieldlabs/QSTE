#!/usr/bin/env python3
"""Execute the deterministic P10 agent-harness conformance profile."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from qste.agent import EXECUTOR_CLASSES, PAYLOAD_LEVELS, TREATMENTS
from qste.core import loads_json

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance" / "p10-agent-harness" / "0.1" / "profile.json"
FIXTURES = ROOT / "fixtures" / "agent-harness" / "0.1" / "fixture-manifest.json"
EXECUTORS = ROOT / "profiles" / "agents" / "executors" / "0.1" / "executor-fixtures.json"
TESTS = (
    "tests/test_p10_harness.py",
    "tests/test_p10_treatments.py",
    "tests/test_p10_revision.py",
    "tests/test_p10_evaluation.py",
    "tests/test_p10_operations.py",
)


def _object(path: Path) -> dict[str, object]:
    value = loads_json(path.read_bytes())
    if not isinstance(value, dict):
        raise SystemExit(f"{path.relative_to(ROOT)} is not an object")
    return value


def main() -> int:
    profile = _object(PROFILE)
    fixtures = _object(FIXTURES)
    executors = _object(EXECUTORS)
    if profile.get("profile_id") != "qste-agent-harness-conformance/0.1":
        raise SystemExit("invalid P10 conformance profile")
    if fixtures.get("fixture_set_id") != "qste-agent-harness-fixtures/0.1":
        raise SystemExit("invalid P10 fixture manifest")
    if fixtures.get("treatments") != list(TREATMENTS):
        raise SystemExit("P10 treatments are not exact")
    if fixtures.get("payload_levels") != list(PAYLOAD_LEVELS):
        raise SystemExit("P10 information payload levels are not exact")
    if any(
        fixtures.get(field) is not False
        for field in (
            "external_execution",
            "model_execution",
            "playback",
            "empirical_or_causal_research_outcome",
        )
    ):
        raise SystemExit("P10 fixture boundary is false")
    declared = executors.get("fixtures")
    if not isinstance(declared, list) or {
        value.get("executor_class") for value in declared if isinstance(value, dict)
    } != set(EXECUTOR_CLASSES):
        raise SystemExit("P10 executor fixture classes are incomplete")
    if executors.get("implementer_class_decisive") is not False:
        raise SystemExit("P10 executor fixture makes implementer class decisive")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", *TESTS], cwd=ROOT, check=False)
    if result.returncode != 0:
        return result.returncode
    print(
        json.dumps(
            {
                "executor_class_count": len(EXECUTOR_CLASSES),
                "gate_count": len(profile["gates"]),
                "payload_level_count": len(PAYLOAD_LEVELS),
                "profile_id": profile["profile_id"],
                "status": "passed",
                "treatment_count": len(TREATMENTS),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
