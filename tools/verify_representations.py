#!/usr/bin/env python3
"""Execute the deterministic P5 STFT/Gabor conformance profile."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from qste.core import loads_json

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance" / "p5-stft-gabor" / "0.1" / "representation-profile.json"
FIXTURES = ROOT / "fixtures" / "representations" / "stft-gabor" / "0.1" / "fixture-manifest.json"
TESTS = (
    "tests/test_p5_reconstruction.py",
    "tests/test_p5_candidates_refinement.py",
    "tests/test_p5_interventions.py",
    "tests/test_p5_operations.py",
)


def main() -> int:
    profile = loads_json(PROFILE.read_bytes())
    fixtures = loads_json(FIXTURES.read_bytes())
    if (
        not isinstance(profile, dict)
        or profile.get("profile_id") != "qste-stft-gabor-conformance/0.1"
    ):
        raise SystemExit("invalid P5 representation profile")
    if (
        not isinstance(fixtures, dict)
        or fixtures.get("fixture_set_id") != "qste-stft-gabor-fixtures/0.1"
    ):
        raise SystemExit("invalid P5 fixture manifest")
    for name in fixtures["static_files"]:
        path = FIXTURES.parent / name
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"missing or unsafe P5 fixture: {name}")
        if name.endswith(".json") and not isinstance(loads_json(path.read_bytes()), dict):
            raise SystemExit(f"invalid P5 JSON fixture: {name}")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", *TESTS], cwd=ROOT, check=False)
    if result.returncode != 0:
        return result.returncode
    print(
        json.dumps(
            {
                "claims": profile["claims"],
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
