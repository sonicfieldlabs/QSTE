from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
from p11_helpers import ROOT, build_p11_fixture, fixture

from qste.adapters import TARGETS
from qste.core.contracts import ContractError
from qste.storage import RecordStore, WorkspacePaths


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_compatibility_manifest_binds_exact_targets_and_frozen_digests() -> None:
    path = ROOT / "profiles/adapters/ecosystem/0.1/compatibility-target-manifest.json"
    manifest = json.loads(path.read_text())
    assert manifest["profile_name"] == "CompatibilityTargetManifest"
    assert manifest["core_record_type"] == "AuthorityManifest"
    assert manifest["platform"] == {
        "operating_system": "macOS 26.5.2",
        "architecture": "arm64",
        "python": "3.12.13",
    }
    assert {item["target_id"] for item in manifest["targets"]} == set(TARGETS)
    assert manifest["adapter_commit"] == "ff4f483fa391dc647db788019d834a0e4fee3e4a"
    for target in manifest["targets"]:
        assert target["revision"] == TARGETS[target["target_id"]].revision
        assert _sha256(ROOT / target["fixture_path"]) == target["fixture_sha256"]
        for schema_path, digest in zip(
            target["schema_paths"], target["schema_sha256"], strict=True
        ):
            assert _sha256(ROOT / schema_path) == digest


@pytest.mark.parametrize(
    ("target_id", "filename"),
    [
        ("masa", "masa-record.json"),
        ("cosmoaudition", "cosmo-frame.json"),
        ("akouo", "akouo-route-decision.json"),
        ("oida", "oida-perception-report.json"),
        ("earworm", "earworm-akousma.json"),
    ],
)
def test_fixture_imports_preserve_native_identity_and_no_external_side_effect(
    tmp_path: Path, target_id: str, filename: str
) -> None:
    p11 = build_p11_fixture(tmp_path)
    outcome = p11.ecosystem.import_payload(
        target_id=target_id,
        context_record_id=p11.context["record_id"],
        payload=fixture(filename),
    )
    artifact = outcome.value
    assert artifact["qste:adapterTarget"] == target_id
    assert artifact["qste:targetRevision"] == TARGETS[target_id].revision
    assert artifact["qste:validation"]["structural_status"] == "passed"
    assert artifact["qste:externalWrite"] is False
    assert artifact["qste:externalExecution"] is False
    assert artifact["qste:networkAccess"] is False
    RecordStore(WorkspacePaths.open(p11.workspace)).verify()


def test_cosmo_frame_transports_status_attribution_uncertainty_units_and_time(
    tmp_path: Path,
) -> None:
    p11 = build_p11_fixture(tmp_path)
    artifact = p11.ecosystem.import_payload(
        target_id="cosmoaudition",
        context_record_id=p11.context["record_id"],
        payload=fixture("cosmo-frame.json"),
    ).value
    evidence = artifact["qste:transportedEvidence"]
    for key in ("native_identifiers", "statuses", "attribution", "uncertainty", "units", "times"):
        assert evidence[key], key
    assert artifact["qste:validation"]["schema_status"] == (
        "unavailable_external_schema_not_published"
    )
    assert artifact["qste:validation"]["interoperability_status"] == ("fixture_structural_only")


@pytest.mark.parametrize(
    ("target_id", "filename"),
    [("masa", "masa-record.json"), ("earworm", "earworm-akousma.json")],
)
def test_projection_validates_frozen_external_schema(
    tmp_path: Path, target_id: str, filename: str
) -> None:
    p11 = build_p11_fixture(tmp_path)
    artifact = p11.ecosystem.project_payload(
        target_id=target_id,
        context_record_id=p11.context["record_id"],
        payload=fixture(filename),
    ).value
    assert artifact["qste:adapterOperation"] == "project"
    assert artifact["qste:validation"]["schema_status"] == "passed"
    assert artifact["qste:validation"]["interoperability_status"] == ("passed_frozen_fixture")


@pytest.mark.parametrize(
    ("target_id", "filename", "expected"),
    [
        ("akousmata", "earworm-akousma.json", "read_only_inspection_fixture"),
        ("listening_stack", "listening-stack-metadata.json", "not_claimed_by_association"),
    ],
)
def test_read_only_inspection_never_becomes_interoperability_by_association(
    tmp_path: Path, target_id: str, filename: str, expected: str
) -> None:
    p11 = build_p11_fixture(tmp_path)
    artifact = p11.ecosystem.inspect_payload(
        target_id=target_id,
        context_record_id=p11.context["record_id"],
        payload=fixture(filename),
    ).value
    assert artifact["qste:validation"]["interoperability_status"] == expected
    assert artifact["qste:externalWrite"] is False


def test_required_untested_live_project_is_explicitly_unavailable(tmp_path: Path) -> None:
    p11 = build_p11_fixture(tmp_path)
    before = len(p11.ecosystem.store.iter_records())
    with pytest.raises(ContractError) as caught:
        p11.ecosystem.live_loopback(
            target_id="oida",
            context_record_id=p11.context["record_id"],
        )
    assert caught.value.reason_code == "capability_unavailable"
    assert cast(Any, caught.value).capability_status == "untested"
    assert len(p11.ecosystem.store.iter_records()) == before + 1


def test_schema_failure_is_durable_and_creates_no_derivative(tmp_path: Path) -> None:
    p11 = build_p11_fixture(tmp_path)
    invalid: dict[str, Any] = fixture("akouo-route-decision.json")
    invalid["outcome"] = "invented-outcome"
    before = len(p11.ecosystem.store.iter_records())
    with pytest.raises(ContractError) as caught:
        p11.ecosystem.import_payload(
            target_id="akouo",
            context_record_id=p11.context["record_id"],
            payload=invalid,
        )
    assert caught.value.reason_code == "conformance_failed"
    assert len(p11.ecosystem.store.iter_records()) == before + 1
