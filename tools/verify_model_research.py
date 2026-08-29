#!/usr/bin/env python3
"""Execute deterministic P14 declaration-boundary checks."""

from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

from qste.core import loads_json
from qste.model_research import CONFORMANCE_PROFILE, DATASET_PROFILE, PROGRAM_PROFILE

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance/p14-model-research/0.1/profile.json"
FIXTURE_ROOT = ROOT / "fixtures/model-research/0.1"
FIXTURE_MANIFEST = FIXTURE_ROOT / "fixture-manifest.json"
TESTS = ("tests/test_p14_model_research.py", "tests/test_p14_operations.py")


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
        raise SystemExit("invalid P14 conformance profile")
    if profile.get("program_profile") != PROGRAM_PROFILE:
        raise SystemExit("invalid P14 program profile")
    if profile.get("dataset_profile") != DATASET_PROFILE:
        raise SystemExit("invalid P14 dataset profile")
    if len(profile.get("gates", [])) != 12:
        raise SystemExit("P14 conformance gate set differs")
    if fixtures.get("fixture_scope") != "synthetic_contract_only":
        raise SystemExit("P14 fixtures exceed synthetic contract scope")
    for item in fixtures.get("fixtures", []):
        path = FIXTURE_ROOT / item["path"]
        if _sha256(path) != item["sha256"]:
            raise SystemExit(f"P14 fixture digest differs: {item['path']}")
    for key in (
        "dataset_bytes_accessed",
        "checkpoint_downloaded",
        "training_executed",
        "generation_performed",
        "evaluation_executed",
        "human_data_used",
        "network_access",
        "public_projection",
    ):
        if fixtures.get(key) is not False:
            raise SystemExit(f"P14 fixture boundary is false: {key}")

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
