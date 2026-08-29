#!/usr/bin/env python3
"""Execute deterministic P12a preparation-boundary checks."""

from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

from qste.core import loads_json
from qste.experiments.contracts import (
    CONFORMANCE_PROFILE,
    PILOT_PROFILE,
    PREPARATION_PROFILE,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance/p12-experiment-preparation/0.1/profile.json"
FIXTURE_ROOT = ROOT / "fixtures/experiment-preparation/0.1"
FIXTURE_MANIFEST = FIXTURE_ROOT / "fixture-manifest.json"
TESTS = ("tests/test_p12_preparation.py", "tests/test_p12_operations.py")


def _object(path: Path) -> dict[str, Any]:
    value = loads_json(path.read_bytes())
    if not isinstance(value, dict):
        raise SystemExit(f"{path.relative_to(ROOT)} is not an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    profile = _object(PROFILE)
    fixtures = _object(FIXTURE_MANIFEST)
    if profile.get("profile_id") != CONFORMANCE_PROFILE:
        raise SystemExit("invalid P12a conformance profile")
    if profile.get("preparation_profile") != PREPARATION_PROFILE:
        raise SystemExit("invalid P12a preparation profile")
    if profile.get("pilot_profile") != PILOT_PROFILE:
        raise SystemExit("invalid P12a pilot profile")
    if len(profile.get("gates", [])) != 10:
        raise SystemExit("P12a conformance gate set differs")
    if fixtures.get("fixture_scope") != "synthetic_conformance_only":
        raise SystemExit("P12a fixtures exceed synthetic conformance scope")
    for item in fixtures.get("fixtures", []):
        path = FIXTURE_ROOT / item["path"]
        if _sha256(path) != item["sha256"]:
            raise SystemExit(f"P12a fixture digest differs: {item['path']}")
    for key in (
        "confirmatory_research",
        "held_out_outcomes",
        "human_data",
        "listener_data",
        "external_execution",
        "network_access",
        "playback",
        "public_research_projection",
    ):
        if fixtures.get(key) is not False:
            raise SystemExit(f"P12a fixture boundary is false: {key}")

    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "pytest", "-q", *TESTS], cwd=ROOT
    )
    if result.returncode != 0:
        return result.returncode
    print(
        json.dumps(
            {
                "fixture_count": len(fixtures["fixtures"]),
                "gate_count": len(profile["gates"]),
                "profile_id": profile["profile_id"],
                "status": "passed",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
