#!/usr/bin/env python3
"""Execute the deterministic P6 task/DSQ conformance profile."""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys
from pathlib import Path

from qste.core import loads_json

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance" / "p6-dsq" / "0.1" / "quanta-profile.json"
FIXTURE_ROOT = ROOT / "fixtures" / "quanta" / "0.1"
MANIFEST = FIXTURE_ROOT / "fixture-manifest.json"
VECTORS = FIXTURE_ROOT / "assessment-vectors.json"
TESTS = (
    "tests/test_p6_assessment.py",
    "tests/test_p6_indeterminate.py",
    "tests/test_p6_execution_invalidation.py",
    "tests/test_p6_operations.py",
)


def main() -> int:
    profile = loads_json(PROFILE.read_bytes())
    manifest = loads_json(MANIFEST.read_bytes())
    vectors = loads_json(VECTORS.read_bytes())
    if not isinstance(profile, dict) or profile.get("profile_id") != "qste-dsq-conformance/0.1":
        raise SystemExit("invalid P6 conformance profile")
    if not isinstance(manifest, dict) or manifest.get("fixture_set_id") != "qste-dsq-fixtures/0.1":
        raise SystemExit("invalid P6 fixture manifest")
    reasons = {
        item["reason"]
        for item in vectors.get("vectors", [])
        if isinstance(item, dict) and isinstance(item.get("reason"), str)
    }
    expected = {
        "meaningful_closed_equivalent",
        "candidate_nonmeaningful",
        "proper_node_nonequivalent",
        "candidate_boundary_crossing",
        "proper_node_boundary_crossing",
        "closure_unavailable",
        "empty_proper_set",
        "uncertainty_contract_missing",
        "budget_exhausted",
        "calibration_unavailable",
        "artifact_control_failed",
        "required_evidence_unavailable",
    }
    if reasons != expected:
        raise SystemExit("P6 vectors do not cover the canonical reason set")
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "pytest", "-q", *TESTS], cwd=ROOT, check=False
    )
    if result.returncode != 0:
        return result.returncode
    print(
        json.dumps(
            {
                "claim_count": len(profile["claims"]),
                "gate_count": len(profile["gates"]),
                "profile_id": profile["profile_id"],
                "reason_count": len(reasons),
                "status": "passed",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
