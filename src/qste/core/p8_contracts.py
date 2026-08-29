"""Semantic invariants for P8 transduction, governance, and repair records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from qste.core.contracts import ContractError

MAPPING_PROFILE = "qste-transduction-mapping/v0.1"
GOVERNANCE_PROFILE = "qste-governance-boundary/v0.1"
APPEAL_PROFILE = "qste-appeal-case/v0.1"
REPAIR_PROFILE = "qste-repair-chain/v0.1"
MODES = {
    "sonification",
    "desonification",
    "resonification",
    "sonic_transformation",
    "cross_domain_contrast",
}


def validate_p8_semantics(record: Mapping[str, Any]) -> None:
    """Reject P8 records that collapse mapping, policy, or repair boundaries."""

    if record.get("qste:mappingProfile") == MAPPING_PROFILE:
        _validate_mapping(record)
    if record.get("qste:governanceProfile") == GOVERNANCE_PROFILE:
        _validate_boundary(record)
    if record.get("qste:appealProfile") == APPEAL_PROFILE:
        _validate_appeal(record)
    if record.get("qste:repairProfile") == REPAIR_PROFILE:
        if record.get("record_type") == "RepairAction":
            _validate_repair_action(record)
        elif record.get("record_type") == "RepairReceipt":
            _validate_repair_receipt(record)
        elif record.get("record_type") == "SuccessorSpec":
            _validate_successor(record)
    if record.get("qste:transductionProfile") == "qste-bounded-transduction/v0.1":
        _validate_transduction_artifact(record)
    if record.get("qste:safetyProfile") == "qste-safety-descendant/v0.1":
        _validate_safety_descendant(record)


def _validate_mapping(record: Mapping[str, Any]) -> None:
    if record.get("record_type") != "MappingSpec":
        raise ContractError("conformance_failed", "P8 mapping profile requires MappingSpec")
    modes = record.get("qste:allowedTransductionModes")
    if (
        not isinstance(modes, list)
        or not modes
        or len(set(modes)) != len(modes)
        or not set(modes).issubset(MODES)
    ):
        raise ContractError("conformance_failed", "P8 mapping modes are noncanonical")
    units = _object(record.get("units"), "mapping units")
    ranges = _object(record.get("range"), "mapping range")
    if set(units) != {"source", "target"} or set(ranges) != {"source", "target"}:
        raise ContractError("conformance_failed", "P8 source/target contracts are incomplete")
    if record.get("reversibility_claim") not in {
        "reversible",
        "partially_reversible",
        "irreversible",
        "untested",
    }:
        raise ContractError("conformance_failed", "P8 reversibility claim is invalid")
    _object(record.get("uncertainty"), "mapping uncertainty")
    loss = _object(record.get("loss"), "mapping loss")
    if not isinstance(loss.get("known"), bool) or not loss.get("description"):
        raise ContractError("conformance_failed", "P8 mapping loss is not explicit")
    bounded = _object(record.get("qste:boundedOutput"), "bounded output")
    if bounded.get("playback") != "prohibited" or bounded.get("network") != "prohibited":
        raise ContractError("conformance_failed", "P8 mapping enlarged the execution surface")


def _validate_boundary(record: Mapping[str, Any]) -> None:
    if record.get("record_type") != "GovernanceBoundary":
        raise ContractError("conformance_failed", "P8 governance profile requires boundary")
    immutable = record.get("immutable_fields")
    mutable = record.get("mutable_successor_fields")
    if not isinstance(immutable, list) or not isinstance(mutable, list):
        raise ContractError("conformance_failed", "P8 governance fields are absent")
    if set(immutable) & set(mutable):
        raise ContractError("conformance_failed", "P8 immutable and successor fields overlap")
    roots = _object(record.get("qste:roots"), "governance roots")
    if roots.get("network") != "disabled" or roots.get("model") != "disabled":
        raise ContractError("conformance_failed", "P8 boundary enables a later-phase capability")
    authorities = {
        value.get("record_id")
        for value in cast(Sequence[Mapping[str, Any]], record.get("authority_refs", []))
    }
    for key in ("qste:approvingAuthorityIds", "qste:revokingAuthorityIds"):
        values = record.get(key)
        if not isinstance(values, list) or not values or not set(values).issubset(authorities):
            raise ContractError("conformance_failed", "P8 authority role is unresolved")


def _validate_appeal(record: Mapping[str, Any]) -> None:
    if record.get("record_type") != "AppealCase":
        raise ContractError("conformance_failed", "P8 appeal profile requires AppealCase")
    if (
        record.get("qste:standingValidation") != "verified"
        or record.get("qste:dutyToRespond") is not True
    ):
        raise ContractError("conformance_failed", "P8 appeal lacks standing or duty")
    axes = {
        "appeal_status": {"opened", "under_review", "adjudicated", "closed"},
        "pause_status": {"not_requested", "requested", "active", "denied", "released"},
        "adjudication_outcome": {
            "not_decided",
            "upheld",
            "denied",
            "partial",
            "escalated",
            "withdrawn",
        },
        "repair_status": {
            "not_requested",
            "pending",
            "applied",
            "partially_applied",
            "impossible",
            "superseded",
        },
    }
    for key, allowed in axes.items():
        if record.get(key) not in allowed:
            raise ContractError("conformance_failed", f"P8 {key} is noncanonical")
    if record.get("appeal_status") == "closed" and record.get("repair_status") == "pending":
        raise ContractError("conformance_failed", "closed P8 appeal has pending repair")
    transitions = record.get("qste:eventTransitions")
    if not isinstance(transitions, list) or not transitions:
        raise ContractError("conformance_failed", "P8 appeal lacks event transition evidence")


def _validate_successor(record: Mapping[str, Any]) -> None:
    if record.get("record_type") != "SuccessorSpec":
        raise ContractError("conformance_failed", "P8 successor profile requires SuccessorSpec")
    diff = _object(record.get("semantic_diff"), "successor semantic diff")
    if diff.get("semantic_or_behavioral_difference") is not True:
        raise ContractError("conformance_failed", "P8 successor is hash-only or no-change")
    changes = diff.get("changed_fields")
    if not isinstance(changes, list) or not changes:
        raise ContractError("conformance_failed", "P8 successor has no changed field")
    volatile = {"record_id", "created_at", "semantic_key", "content_digest"}
    for change in changes:
        if not isinstance(change, Mapping) or change.get("field") in volatile:
            raise ContractError("conformance_failed", "P8 successor changes only identity metadata")


def _validate_repair_action(record: Mapping[str, Any]) -> None:
    if record.get("authorization_status") != "permitted":
        raise ContractError("conformance_failed", "P8 repair action is unauthorized")
    if record.get("adjudication_outcome") not in {"upheld", "partial"}:
        raise ContractError("conformance_failed", "P8 repair lacks favorable adjudication")
    if record.get("repair_action") not in {
        "pause",
        "correct",
        "revoke",
        "delete",
        "restrict",
        "restore",
        "release_pause",
    }:
        raise ContractError("conformance_failed", "P8 repair action is noncanonical")
    _object(record.get("target_closure"), "repair target closure")
    _object(record.get("predecessor_state"), "repair predecessor state")
    _object(record.get("successor_state"), "repair successor state")


def _validate_repair_receipt(record: Mapping[str, Any]) -> None:
    status = record.get("repair_status")
    if status not in {"applied", "partially_applied", "impossible"}:
        raise ContractError("conformance_failed", "P8 repair receipt has no terminal outcome")
    limits = record.get("unresolved_limits")
    copies = record.get("external_copies")
    if not isinstance(limits, list) or not limits or not isinstance(copies, list) or not copies:
        raise ContractError("conformance_failed", "P8 repair receipt hides limits or copies")
    if status in {"partially_applied", "impossible"} and all(
        isinstance(value, Mapping) and value.get("availability") == "not_applicable"
        for value in limits
    ):
        raise ContractError("conformance_failed", "limited P8 repair reports no unresolved limit")


def _validate_transduction_artifact(record: Mapping[str, Any]) -> None:
    if record.get("record_type") != "ArtifactRecord":
        raise ContractError("conformance_failed", "P8 transduction output is not an artifact")
    if record.get("qste:transductionMode") not in MODES - {
        "desonification",
        "cross_domain_contrast",
    }:
        raise ContractError("conformance_failed", "P8 artifact transduction mode is invalid")
    if (
        record.get("qste:analyticalOutput") is not True
        or record.get("qste:heardOutput") != "not_produced"
    ):
        raise ContractError("conformance_failed", "P8 analytical and heard outputs collapsed")
    _object(record.get("qste:controlRef"), "transduction control")
    _object(record.get("qste:mappingRef"), "transduction mapping")


def _validate_safety_descendant(record: Mapping[str, Any]) -> None:
    if record.get("record_type") != "ArtifactRecord":
        raise ContractError("conformance_failed", "P8 safety output is not an artifact")
    parent = _object(record.get("qste:analyticalParentRef"), "safety parent")
    references = record.get("references")
    if not isinstance(references, list) or not any(
        isinstance(value, Mapping)
        and value.get("record_id") == parent.get("record_id")
        and value.get("relation") == "descendant_of"
        for value in references
    ):
        raise ContractError("conformance_failed", "P8 safety output is not a descendant")
    if record.get("qste:heardOutput") != "not_produced":
        raise ContractError("conformance_failed", "P8 safety fixture claims a heard output")


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ContractError("conformance_failed", f"{name} must be a nonempty object")
    return value
