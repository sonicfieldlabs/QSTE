#!/usr/bin/env python3
"""Execute deterministic P11 ecosystem/engine boundary checks."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from qste.adapters.ecosystem_contracts import ENGINE_CAPABILITIES, TARGETS
from qste.core import loads_json

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance/p11-ecosystem-engines/0.1/profile.json"
TARGET_MANIFEST = ROOT / "profiles/adapters/ecosystem/0.1/compatibility-target-manifest.json"
FIXTURE_ROOT = ROOT / "fixtures/ecosystem-adapters/0.1"
FIXTURE_MANIFEST = FIXTURE_ROOT / "fixture-manifest.json"
TESTS = (
    "tests/test_p11_ecosystem.py",
    "tests/test_p11_engine.py",
    "tests/test_p11_operations.py",
)


def _object(path: Path) -> dict[str, Any]:
    value = loads_json(path.read_bytes())
    if not isinstance(value, dict):
        raise SystemExit(f"{path.relative_to(ROOT)} is not an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    profile = _object(PROFILE)
    targets = _object(TARGET_MANIFEST)
    fixtures = _object(FIXTURE_MANIFEST)
    if profile.get("profile_id") != "qste-ecosystem-engine-conformance/0.1":
        raise SystemExit("invalid P11 conformance profile")
    if targets.get("profile_name") != "CompatibilityTargetManifest":
        raise SystemExit("P11 compatibility target profile is not named exactly")
    adapter_commit = targets.get("adapter_commit")
    if adapter_commit != "ff4f483fa391dc647db788019d834a0e4fee3e4a":
        raise SystemExit("compatibility target does not bind the verified P11 implementation")
    declared_targets = targets.get("targets")
    if not isinstance(declared_targets, list) or {
        item.get("target_id") for item in declared_targets if isinstance(item, dict)
    } != set(TARGETS):
        raise SystemExit("P11 ecosystem target set differs")
    for target in declared_targets:
        if not isinstance(target, dict):
            raise SystemExit("P11 target is not an object")
        target_id = target["target_id"]
        if target.get("revision") != TARGETS[target_id].revision:
            raise SystemExit(f"P11 {target_id} revision differs")
        if _sha256(ROOT / target["fixture_path"]) != target.get("fixture_sha256"):
            raise SystemExit(f"P11 {target_id} fixture digest differs")
        paths = target.get("schema_paths")
        digests = target.get("schema_sha256")
        if (
            not isinstance(paths, list)
            or not isinstance(digests, list)
            or len(paths) != len(digests)
        ):
            raise SystemExit(f"P11 {target_id} schema manifest differs")
        for path, digest in zip(paths, digests, strict=True):
            if _sha256(ROOT / path) != digest:
                raise SystemExit(f"P11 {target_id} schema digest differs")
    declared_engines = targets.get("engine_targets")
    if not isinstance(declared_engines, list) or {
        item.get("target_id") for item in declared_engines if isinstance(item, dict)
    } != set(ENGINE_CAPABILITIES):
        raise SystemExit("P11 engine target set differs")
    for target in declared_engines:
        if target["capability_status"] != ENGINE_CAPABILITIES[target["target_id"]]:
            raise SystemExit(f"P11 engine capability differs: {target['target_id']}")
    for key in (
        "live_external_execution",
        "adjacent_checkout_write",
        "structural_validity_is_interoperability",
    ):
        if targets.get(key) is not False:
            raise SystemExit(f"P11 compatibility boundary is false: {key}")
    for item in fixtures.get("fixtures", []):
        if _sha256(FIXTURE_ROOT / item["path"]) != item["sha256"]:
            raise SystemExit(f"P11 fixture digest differs: {item['path']}")
    for key in (
        "external_execution",
        "external_network",
        "adjacent_checkout_write",
        "playback",
        "model_execution",
        "human_data",
    ):
        if fixtures.get(key) is not False:
            raise SystemExit(f"P11 fixture boundary is false: {key}")

    result = subprocess.run([sys.executable, "-m", "pytest", "-q", *TESTS], cwd=ROOT)
    if result.returncode != 0:
        return result.returncode
    print(
        json.dumps(
            {
                "ecosystem_target_count": len(TARGETS),
                "engine_target_count": len(ENGINE_CAPABILITIES),
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
