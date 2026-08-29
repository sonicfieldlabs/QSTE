#!/usr/bin/env python3
"""Execute deterministic P9 adapter-boundary conformance checks."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from qste.adapters import ENCODEC_TARGET, OPERATIONS, SAMPLEBRAIN_TARGET
from qste.adapters.contracts import capability_map
from qste.core import loads_json

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance" / "p9-external-representations" / "0.1" / "profile.json"
FIXTURE_ROOT = ROOT / "fixtures" / "external-representations" / "0.1"
MANIFEST = FIXTURE_ROOT / "fixture-manifest.json"
TARGET_FILES = {
    "samplebrain": ROOT / SAMPLEBRAIN_TARGET.compatibility_manifest,
    "encodec": ROOT / ENCODEC_TARGET.compatibility_manifest,
}
CHECKPOINT = ROOT / "profiles" / "adapters" / "encodec" / "0.1" / "checkpoint-manifest.json"
ENCODEC_LOCK = ROOT / "environments" / "encodec" / "uv.lock"
TESTS = ("tests/test_p9_adapters.py", "tests/test_p9_operations.py")


def _object(path: Path) -> dict[str, Any]:
    value = loads_json(path.read_bytes())
    if not isinstance(value, dict):
        raise SystemExit(f"{path.relative_to(ROOT)} is not an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    profile = _object(PROFILE)
    manifest = _object(MANIFEST)
    if profile.get("profile_id") != "qste-external-representation-conformance/0.1":
        raise SystemExit("invalid P9 conformance profile")
    if profile.get("operations") != list(OPERATIONS) or set(capability_map()) != set(OPERATIONS):
        raise SystemExit("P9 profile does not declare the exact operation surface")
    if manifest.get("fixture_set_id") != "qste-external-representation-fixtures/0.1":
        raise SystemExit("invalid P9 fixture manifest")
    for field in (
        "external_execution",
        "model_execution",
        "playback",
        "scientific_or_empirical_outcome",
    ):
        if manifest.get(field) is not False:
            raise SystemExit(f"P9 fixture boundary is false: {field}")

    target_manifests = {name: _object(path) for name, path in TARGET_FILES.items()}
    targets = {"samplebrain": SAMPLEBRAIN_TARGET, "encodec": ENCODEC_TARGET}
    for adapter_id, target in targets.items():
        declared = target_manifests[adapter_id]
        if (
            declared.get("adapter_id") != adapter_id
            or declared.get("target_id") != target.target_id
        ):
            raise SystemExit(f"{adapter_id} compatibility identity conflicts")
        if declared.get("implementation_revision") != target.implementation_revision:
            raise SystemExit(f"{adapter_id} implementation revision conflicts")
        if adapter_id == "samplebrain" and declared.get("package_digest") != target.package_digest:
            raise SystemExit("Samplebrain target-tuple digest conflicts")

    lock = target_manifests["encodec"].get("environment_lock")
    if not isinstance(lock, dict) or lock.get("sha256") != _sha256(ENCODEC_LOCK):
        raise SystemExit("EnCodec environment lock digest conflicts")
    checkpoint = _object(CHECKPOINT)
    if (
        checkpoint.get("availability") != "unavailable"
        or checkpoint.get("model_loaded") is not False
    ):
        raise SystemExit("EnCodec checkpoint boundary is false")
    if checkpoint.get("content_digest") != ENCODEC_TARGET.checkpoint_digest:
        raise SystemExit("EnCodec checkpoint digest conflicts")
    if checkpoint.get("checkpoint_license") != "not_declared_by_checkpoint_repository":
        raise SystemExit("EnCodec checkpoint license uncertainty is missing")

    for filename, adapter_id in (
        ("samplebrain-capture.json", "samplebrain"),
        ("encodec-capture.json", "encodec"),
    ):
        capture = _object(FIXTURE_ROOT / filename)
        if capture.get("adapter_id") != adapter_id:
            raise SystemExit(f"{filename} adapter identity conflicts")
        refinement = capture.get("refinement")
        opaque = capture.get("opaque_boundary")
        if not isinstance(refinement, dict) or refinement.get("graph_created") is not False:
            raise SystemExit(f"{filename} invents a refinement graph")
        if not isinstance(opaque, dict) or opaque.get("observability") != "captured_outputs_only":
            raise SystemExit(f"{filename} hides its opaque boundary")

    result = subprocess.run([sys.executable, "-m", "pytest", "-q", *TESTS], cwd=ROOT, check=False)
    if result.returncode != 0:
        return result.returncode
    print(
        json.dumps(
            {
                "adapter_count": len(targets),
                "gate_count": len(profile["gates"]),
                "operation_count": len(OPERATIONS),
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
