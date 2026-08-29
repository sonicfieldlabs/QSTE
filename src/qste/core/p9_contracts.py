"""Semantic invariants for P9 external representation adapter records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qste.core.contracts import ContractError

ADAPTER_PROFILE = "qste-external-representation-adapter/v0.1"
OPERATIONS = {
    "encode",
    "enumerate",
    "refine",
    "address",
    "intervene",
    "decode",
    "support",
    "project",
    "measure",
    "perturb",
    "account",
}


def validate_p9_semantics(record: Mapping[str, Any]) -> None:
    """Validate records that explicitly opt into the P9 adapter profile."""

    if record.get("qste:adapterProfile") != ADAPTER_PROFILE:
        return
    if record.get("qste:adapterId") not in {"samplebrain", "encodec"}:
        raise ContractError("conformance_failed", "P9 adapter identity is not canonical")
    validators = {
        "RepresentationSpec": _representation_spec,
        "RepresentationInstance": _representation_instance,
        "RepresentationFamilySpec": _representation_family,
        "CandidateUnit": _candidate,
        "MappingSpec": _mapping,
        "ClaimRecord": _opaque_claim,
        "ArtifactRecord": _artifact,
    }
    validator = validators.get(str(record.get("record_type")))
    if validator is not None:
        validator(record)


def _representation_spec(record: Mapping[str, Any]) -> None:
    capabilities = _object(record.get("qste:operationCapabilities"), "operation capabilities")
    if set(capabilities) != OPERATIONS:
        raise ContractError("conformance_failed", "P9 adapter does not declare every operation")
    if any(value not in {"available", "unavailable"} for value in capabilities.values()):
        raise ContractError("conformance_failed", "P9 operation capability is invalid")
    _opaque_boundary(_object(record.get("qste:opaqueBoundary"), "opaque boundary"))
    decoder = _object(record.get("renderer_or_decoder"), "renderer or decoder")
    if decoder.get("external_invocation") is not False or decoder.get("playback") is not False:
        raise ContractError("conformance_failed", "P9 captured spec implies external execution")
    checkpoint = _object(record.get("qste:checkpointIdentity"), "checkpoint identity")
    if record.get("qste:adapterId") == "encodec" and (
        checkpoint.get("local_availability") != "unavailable"
        or not isinstance(checkpoint.get("content_digest"), str)
    ):
        raise ContractError("conformance_failed", "P9 EnCodec checkpoint boundary is false")


def _representation_instance(record: Mapping[str, Any]) -> None:
    if record.get("qste:dsqCapability") != "candidate_only_without_closed_refinement_graph":
        raise ContractError("conformance_failed", "P9 instance overclaims DSQ capability")
    refinement = _object(record.get("qste:refinementCapability"), "refinement capability")
    if refinement.get("status") != "unavailable" or refinement.get("graph_created") is not False:
        raise ContractError("conformance_failed", "P9 instance invents refinement closure")
    if (
        record.get("qste:modelExecutedByQste") is not False
        or record.get("qste:heardOutput") != "not_produced"
    ):
        raise ContractError("conformance_failed", "P9 captured instance implies model or hearing")
    _opaque_boundary(_object(record.get("qste:opaqueBoundary"), "opaque boundary"))


def _representation_family(record: Mapping[str, Any]) -> None:
    refinements = record.get("permitted_refinements")
    if not isinstance(refinements, list) or len(refinements) != 1:
        raise ContractError("conformance_failed", "P9 family refinement declaration is incomplete")
    refinement = _object(refinements[0], "family refinement declaration")
    if refinement.get("status") != "unavailable" or refinement.get("graph_created") is not False:
        raise ContractError("conformance_failed", "P9 family declares an unsupported graph")


def _candidate(record: Mapping[str, Any]) -> None:
    if (
        record.get("qste:candidateOnly") is not True
        or record.get("qste:refinementEligibility")
        != "unavailable_without_verified_mapping_and_intervention"
    ):
        raise ContractError("conformance_failed", "P9 candidate is mislabeled")
    if not isinstance(record.get("qste:addressable"), bool):
        raise ContractError("conformance_failed", "P9 candidate addressability is absent")


def _mapping(record: Mapping[str, Any]) -> None:
    if record.get("qste:mappingScope") != "same_instance_only":
        raise ContractError("conformance_failed", "P9 mapping overclaims cross-instance identity")
    if _object(record.get("loss"), "mapping loss").get("known") is not True:
        raise ContractError("conformance_failed", "P9 mapping does not declare known loss")


def _opaque_claim(record: Mapping[str, Any]) -> None:
    _opaque_boundary(_object(record.get("qste:opaqueBoundary"), "opaque boundary"))
    if _object(record.get("scope"), "opaque claim scope").get("scientific_result") is not False:
        raise ContractError("conformance_failed", "P9 opaque claim becomes a result")


def _artifact(record: Mapping[str, Any]) -> None:
    if record.get("qste:heardOutput") not in {None, "not_produced"}:
        raise ContractError("conformance_failed", "P9 artifact overclaims heard output")
    if (
        record.get("qste:externalRendererInvoked") is True
        or record.get("qste:externalDecoderInvoked") is True
    ):
        raise ContractError("conformance_failed", "P9 artifact implies external execution")


def _opaque_boundary(value: Mapping[str, Any]) -> None:
    if value.get("observability") != "captured_outputs_only":
        raise ContractError("conformance_failed", "P9 opaque boundary is not capture-limited")
    for key in ("visible_fields", "opaque_fields"):
        fields = value.get(key)
        if (
            not isinstance(fields, list)
            or not fields
            or not all(isinstance(item, str) and item for item in fields)
        ):
            raise ContractError("conformance_failed", f"P9 opaque boundary lacks {key}")


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError("conformance_failed", f"P9 {label} is not an object")
    return value
