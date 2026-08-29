#!/usr/bin/env python3
"""Execute the bounded P4 ingress behavioral conformance profile."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from qste.core import loads_json

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance" / "p4-ingress" / "0.1" / "ingress-profile.json"
FIXTURES = ROOT / "fixtures" / "ingress" / "0.1" / "fixture-manifest.json"
TESTS = (
    "tests/test_p4_apparatus.py",
    "tests/test_p4_ingress.py",
    "tests/test_p4_audio_aperture.py",
    "tests/test_p4_operations.py",
)


def main() -> int:
    profile = loads_json(PROFILE.read_bytes())
    fixtures = loads_json(FIXTURES.read_bytes())
    if not isinstance(profile, dict) or profile.get("profile_id") != "qste-ingress-conformance/0.1":
        raise SystemExit("invalid P4 ingress conformance profile")
    if (
        not isinstance(fixtures, dict)
        or fixtures.get("fixture_set_id") != "qste-ingress-fixtures/0.1"
    ):
        raise SystemExit("invalid P4 ingress fixture manifest")
    for name in fixtures["files"]:
        path = FIXTURES.parent / name
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"missing or unsafe P4 ingress fixture: {name}")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        check=False,
    )
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
