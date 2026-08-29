"""Semantic invariants for P11 ecosystem and bounded engine artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qste.core.contracts import ContractError

ECOSYSTEM_PROFILE = "qste-ecosystem-adapter/v0.1"
ENGINE_PROFILE = "qste-bounded-engine-adapter/v0.1"
ECOSYSTEM_TARGETS = {
    "masa",
    "cosmoaudition",
    "akouo",
    "oida",
    "earworm",
    "akousmata",
    "listening_stack",
}
ENGINE_TARGETS = {"qste_fixture_process", "qste_fixture_osc_loopback"}


def validate_p11_semantics(record: Mapping[str, Any]) -> None:
    if record.get("qste:adapterProfile") == ECOSYSTEM_PROFILE:
        _ecosystem_artifact(record)
    if record.get("qste:engineProfile") == ENGINE_PROFILE:
        _engine_artifact(record)


def _ecosystem_artifact(record: Mapping[str, Any]) -> None:
    if record.get("record_type") != "ArtifactRecord":
        raise ContractError("conformance_failed", "P11 ecosystem profile requires an artifact")
    if record.get("qste:adapterTarget") not in ECOSYSTEM_TARGETS:
        raise ContractError("conformance_failed", "P11 ecosystem target is not canonical")
    if record.get("qste:adapterOperation") not in {"import", "project", "inspect"}:
        raise ContractError("conformance_failed", "P11 ecosystem operation is invalid")
    for key in ("qste:targetVersion", "qste:targetRevision", "qste:nativeContracts"):
        if not record.get(key):
            raise ContractError("conformance_failed", f"P11 ecosystem artifact lacks {key}")
    validation = _object(record.get("qste:validation"), "validation")
    if validation.get("structural_status") != "passed":
        raise ContractError("conformance_failed", "P11 structural validation did not pass")
    if not isinstance(validation.get("schema_status"), str) or not isinstance(
        validation.get("interoperability_status"), str
    ):
        raise ContractError(
            "conformance_failed", "P11 schema and interoperability results are not separate"
        )
    transported = _object(record.get("qste:transportedEvidence"), "transported evidence")
    for key in (
        "native_identifiers",
        "statuses",
        "attribution",
        "uncertainty",
        "units",
        "times",
    ):
        if not isinstance(transported.get(key), list):
            raise ContractError("conformance_failed", f"P11 transported evidence lacks {key}")
    if any(
        record.get(key) is not False
        for key in (
            "qste:externalWrite",
            "qste:externalExecution",
            "qste:networkAccess",
            "qste:playback",
            "qste:modelExecution",
        )
    ):
        raise ContractError("conformance_failed", "P11 fixture implies an external side effect")


def _engine_artifact(record: Mapping[str, Any]) -> None:
    if record.get("record_type") != "ArtifactRecord":
        raise ContractError("conformance_failed", "P11 engine profile requires an artifact")
    if record.get("qste:engineTarget") not in ENGINE_TARGETS:
        raise ContractError("conformance_failed", "P11 engine target is not a fixture target")
    execution = _object(record.get("qste:engineExecution"), "engine execution")
    for key in ("parameters", "logs", "output_digest", "timeout_state", "timeout_seconds"):
        if key not in execution:
            raise ContractError("conformance_failed", f"P11 engine execution lacks {key}")
    if execution.get("external_engine_executed") is not False:
        raise ContractError("conformance_failed", "P11 fixture implies external engine execution")
    if execution.get("playback") is not False:
        raise ContractError("conformance_failed", "P11 fixture implies playback")
    if record.get("qste:adjacentCheckoutWrite") is not False:
        raise ContractError("conformance_failed", "P11 fixture implies an adjacent write")
    if record.get("qste:engineTarget") == "qste_fixture_osc_loopback" and (
        execution.get("loopback_host") != "127.0.0.1"
        or execution.get("execution_mode") != "authorized_synthetic_osc_loopback"
    ):
        raise ContractError("conformance_failed", "P11 OSC route is not fixed to loopback")


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError("conformance_failed", f"P11 {label} is not an object")
    return value
