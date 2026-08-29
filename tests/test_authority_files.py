from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, cast

from qste.core import SchemaRegistry, semantic_key_from_value

ROOT = Path(__file__).resolve().parents[1]

PUBLIC_DIGEST_KEYS = (
    "semantic_contract",
    "schema_set",
    "conformance_profile",
    "qste:methodologicalBasis",
    "qste:storageConformance",
    "qste:ingressConformance",
    "qste:representationConformance",
    "qste:quantaConformance",
    "qste:relationConformance",
    "qste:transductionGovernanceConformance",
    "qste:externalRepresentationConformance",
    "qste:agentHarnessConformance",
    "qste:compatibilityTargetManifest",
    "qste:ecosystemEngineConformance",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict[str, Any]:
    value = json.loads((ROOT / "authority" / "authority-manifest.json").read_text())
    return cast(dict[str, Any], value)


def test_public_authority_sources_match_declared_digests() -> None:
    manifest = _manifest()
    for key in PUBLIC_DIGEST_KEYS:
        record = manifest[key]
        path = ROOT / record["path"]
        assert path.is_file()
        assert _sha256(path) == record["sha256"]
    for profile in [*manifest["adapter_contracts"], *manifest["model_checkpoint_manifests"]]:
        path = ROOT / profile["path"]
        assert path.is_file()
        assert _sha256(path) == profile["sha256"]


def test_private_authority_inputs_have_no_public_locator_or_digest() -> None:
    manifest = _manifest()
    for key in ("architecture", "development_plan"):
        value = manifest[key]
        assert value["availability"] == "private_local_not_disclosed"
        assert "path" not in value
        assert "sha256" not in value
    assert manifest["experiment_profiles"] == [
        {
            "availability": "private_local_not_disclosed",
            "evidence_status": "not_public",
            "id": "qste-experiment-profiles/private",
        }
    ]
    assert "qste:predecessorManifest" not in manifest


def test_authority_capability_boundary_is_explicit() -> None:
    capability = _manifest()["qste:capabilityProfile"]
    assert capability["current_phase"] == "P11"
    assert capability["ecosystem_adapter_capability_status"] == "available"
    assert capability["ecosystem_live_interoperability_status"] == "untested"
    assert capability["bounded_engine_fixture_capability_status"] == "available"
    assert capability["osc_loopback_fixture_capability_status"] == "available"
    assert capability["external_audio_engine_execution_status"] == "unavailable"
    assert capability["autonomous_agent_model_status"] == "unavailable"
    assert capability["agentic_hearing_research_evidence_status"] == "unavailable"
    assert capability["creative_consequence_evidence_status"] == "unavailable"
    assert capability["numerical_reproducibility_status"] == "unavailable"


def test_public_authority_is_schema_valid_and_commit_is_bound() -> None:
    manifest = _manifest()
    SchemaRegistry().validate_record(manifest)
    assert manifest["manifest_profile"] == "qste-authority/0.3.0"
    assert manifest["integrity_status"] == "verified"
    commit = manifest["code"]["commit"]
    assert commit == "c4229071733bed112b826b7e199e7c0d1aefcec2"
    assert re.fullmatch(r"[0-9a-f]{40}", commit)
    result = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0


def test_current_authority_semantic_key_uses_its_declared_snapshot_spec() -> None:
    manifest = _manifest()
    spec = manifest["qste:semanticKeySpec"]
    value = {key: manifest[key] for key in manifest if key not in spec["excluded_fields"]}
    assert manifest["semantic_key"] == semantic_key_from_value(spec["id"], value)


def test_runtime_source_has_no_machine_specific_dependency() -> None:
    forbidden = ("/Users/", "algoacoulogy", "/Downloads/")
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text()
        assert not any(value in text for value in forbidden), path


def test_private_repository_material_is_not_tracked() -> None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = set(result.stdout.splitlines())
    forbidden_exact = {
        "AGENTS.md",
        "docs/foundation/QSTE_devplan.md",
        "docs/foundation/QSTE_repo_v1.md",
        "ontology/0.3.0/QSTE_devplan.md",
        "ontology/0.3.0/QSTE_repo_v1.md",
        "authority/sources/README.md",
        "docs/experiments/README.md",
        "docs/ethics/README.md",
    }
    forbidden_prefixes = (
        "authority/history/",
        "docs/status/",
        "docs/feasibility/",
        "profiles/leonardo-birdcall-example/",
    )
    assert tracked.isdisjoint(forbidden_exact)
    assert not any(path.startswith(forbidden_prefixes) for path in tracked)
