#!/usr/bin/env python3
"""Execute the deterministic P7 relation conformance profile."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from qste.core import loads_json

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance" / "p7-relations" / "0.1" / "relation-profile.json"
FIXTURE_ROOT = ROOT / "fixtures" / "relations" / "0.1"
MANIFEST = FIXTURE_ROOT / "fixture-manifest.json"
VECTORS = FIXTURE_ROOT / "relation-vectors.json"
MATERIALS = FIXTURE_ROOT / "material-classes.json"
TESTS = (
    "tests/test_p7_projection_coverage.py",
    "tests/test_p7_outcomes.py",
    "tests/test_p7_matching.py",
    "tests/test_p7_operations.py",
)


def main() -> int:
    profile = loads_json(PROFILE.read_bytes())
    manifest = loads_json(MANIFEST.read_bytes())
    vectors = loads_json(VECTORS.read_bytes())
    materials = loads_json(MATERIALS.read_bytes())
    if not isinstance(profile, dict) or profile.get("profile_id") != (
        "qste-relation-conformance/0.1"
    ):
        raise SystemExit("invalid P7 conformance profile")
    if not isinstance(manifest, dict) or manifest.get("fixture_set_id") != (
        "qste-relation-fixtures/0.1"
    ):
        raise SystemExit("invalid P7 fixture manifest")
    reasons = {
        item["reason"]
        for item in vectors.get("vectors", [])
        if isinstance(item, dict) and isinstance(item.get("reason"), str)
    }
    expected = {
        "matched_overlap",
        "matched_split",
        "matched_merge",
        "projection_invalid",
        "target_address_absent",
        "fidelity_failed",
        "zero_footprint_undefined",
        "coverage_failed",
        "effect_incompatible",
        "unmatched_by_spec",
        "coverage_boundary_crossing",
        "effect_boundary_crossing",
        "structural_matching_ambiguity",
        "decomposition_ambiguity",
        "eligible_evidence_incomplete",
        "matching_budget_exhausted",
        "comparison_capability_unavailable",
    }
    if reasons != expected:
        raise SystemExit("P7 vectors do not cover the canonical reason set")
    if (
        not isinstance(materials, dict)
        or materials.get("scientific_or_empirical_outcome") is not False
    ):
        raise SystemExit("P7 material fixtures are not explicitly non-empirical")
    classes = {
        item.get("class") for item in materials.get("materials", []) if isinstance(item, dict)
    }
    if classes != {
        "attributed_source",
        "arm_specific_reconstruction",
        "arm_specific_residual",
        "cross_arm_disagreement_relation",
    }:
        raise SystemExit("P7 material classes are incomplete")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", *TESTS], cwd=ROOT, check=False)
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
