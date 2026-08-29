#!/usr/bin/env python3
"""Execute the deterministic P8 transduction/governance conformance profile."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from qste.core import loads_json

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance" / "p8-transduction-governance" / "0.1" / "profile.json"
FIXTURE_ROOT = ROOT / "fixtures" / "transduction-governance" / "0.1"
MANIFEST = FIXTURE_ROOT / "fixture-manifest.json"
TRANSDUCTION = FIXTURE_ROOT / "transduction-vectors.json"
GOVERNANCE = FIXTURE_ROOT / "governance-vectors.json"
TESTS = (
    "tests/test_p8_transduction.py",
    "tests/test_p8_governance.py",
    "tests/test_p8_operations.py",
)


def main() -> int:
    profile = loads_json(PROFILE.read_bytes())
    manifest = loads_json(MANIFEST.read_bytes())
    transduction = loads_json(TRANSDUCTION.read_bytes())
    governance = loads_json(GOVERNANCE.read_bytes())
    if not isinstance(profile, dict) or profile.get("profile_id") != (
        "qste-transduction-governance-conformance/0.1"
    ):
        raise SystemExit("invalid P8 conformance profile")
    if not isinstance(manifest, dict) or manifest.get("fixture_set_id") != (
        "qste-transduction-governance-fixtures/0.1"
    ):
        raise SystemExit("invalid P8 fixture manifest")
    if manifest.get("scientific_or_empirical_outcome") is not False:
        raise SystemExit("P8 fixtures are not explicitly non-empirical")
    modes = {item.get("mode") for item in transduction.get("modes", []) if isinstance(item, dict)}
    expected_modes = {
        "sonification",
        "desonification",
        "resonification",
        "sonic_transformation",
        "cross_domain_contrast",
    }
    if modes != expected_modes:
        raise SystemExit("P8 transduction vectors do not cover the canonical modes")
    reasons = set(governance.get("governance_reasons", []))
    expected_reasons = {
        "standing_unverified",
        "standing_denied",
        "authority_unresolved",
        "jurisdiction_declined",
        "pause_risk_threshold_met",
        "pause_risk_threshold_not_met",
        "appeal_withdrawn",
        "requested_remedy_upheld",
        "requested_remedy_denied",
        "requested_remedy_partial",
        "repair_completed",
        "repair_partially_completed",
        "repair_not_feasible",
        "retention_duty_blocks_deletion",
        "external_copy_out_of_scope",
        "superseded_by_successor_case",
    }
    if reasons != expected_reasons:
        raise SystemExit("P8 governance vectors do not cover the canonical reason set")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", *TESTS], cwd=ROOT, check=False)
    if result.returncode != 0:
        return result.returncode
    print(
        json.dumps(
            {
                "claim_count": len(profile["claims"]),
                "gate_count": len(profile["gates"]),
                "governance_reason_count": len(reasons),
                "mode_count": len(modes),
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
