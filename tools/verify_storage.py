#!/usr/bin/env python3
"""Execute the bounded P3 behavioral conformance profile."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from qste.core import SchemaRegistry, canonical_json_text, loads_json

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance" / "p3-storage" / "0.1" / "storage-profile.json"
VECTORS = ROOT / "fixtures" / "storage" / "0.1" / "canonicalization-vectors.json"
TESTS = (
    "tests/test_identity.py",
    "tests/test_storage.py",
    "tests/test_dense.py",
    "tests/test_bundle.py",
    "tests/test_operations.py",
)


def main() -> int:
    profile = loads_json(PROFILE.read_bytes())
    vectors = loads_json(VECTORS.read_bytes())
    if not isinstance(profile, dict) or profile.get("profile_id") != "qste-storage-conformance/0.1":
        raise SystemExit("invalid P3 storage profile")
    if not isinstance(vectors, dict):
        raise SystemExit("invalid canonicalization vectors")
    for vector in vectors["vectors"]:
        if canonical_json_text(vector["input"]) != vector["canonical_utf8"]:
            raise SystemExit("RFC 8785 canonicalization vector failed")
    SchemaRegistry()
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
