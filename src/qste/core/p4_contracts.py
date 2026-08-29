"""Behavioral record constraints for the QSTE P4 profiles."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, cast

from qste.core.contracts import ContractError

INGRESS_PROFILE = "qste-ingress/0.1"
APPARATUS_PROFILE = "qste-apparatus/0.1"
APERTURE_PROFILE = "qste-aperture/0.1"
RUN_PROFILE = "qste-run/p4-ingress-0.1"

INGRESS_KINDS = frozenset(
    {"audio", "json_observations", "csv_observations", "text", "model_observations"}
)
PREPROCESSING_OPERATIONS = frozenset({"decode", "resample", "normalize", "parse_observations"})
P4_OPERATIONS = frozenset(
    {
        "ingest",
        "inspect",
        "lineage",
        "verify",
        "bundle",
        "decode",
        "resample",
        "normalize",
        "encode",
        "enumerate",
        "refine",
        "support",
        "address",
        "intervene",
        "project",
        "measure",
        "perturb",
        "account",
        "declare_task",
        "execute_task",
        "assess",
        "baseline",
        "invalidate_dependency",
    }
)
CALIBRATION_STATUSES = frozenset({"calibrated", "uncalibrated", "not_applicable"})


def validate_p4_semantics(record: Mapping[str, Any]) -> None:
    """Validate namespaced P4 profiles without changing the P2 schema set."""

    record_type = record.get("record_type")
    if record.get("qste:apparatusProfile") == APPARATUS_PROFILE:
        _validate_apparatus(record)
    if record.get("qste:apertureProfile") == APERTURE_PROFILE:
        _validate_aperture(record)
    if record.get("qste:ingressProfile") == INGRESS_PROFILE:
        _validate_ingress(record)
    if record.get("qste:runProfile") == RUN_PROFILE and record_type != "RunManifest":
        raise ContractError("conformance_failed", "P4 run profile requires RunManifest")


def validate_apparatus_declaration(value: Mapping[str, Any]) -> None:
    required = {
        "apparatus_version",
        "configuration",
        "acquisition_surface",
        "computation_surface",
        "action_surface",
        "authorization_status",
    }
    if set(value) != required:
        raise ContractError(
            "invalid_input",
            f"apparatus declaration fields must be exactly: {', '.join(sorted(required))}",
        )
    if value["authorization_status"] != "permitted":
        raise ContractError("policy_refused", "apparatus declaration requires explicit permission")
    probe = {
        "record_type": "ApparatusSpec",
        "qste:apparatusProfile": APPARATUS_PROFILE,
        **dict(value),
    }
    _validate_apparatus(probe)


def _validate_apparatus(record: Mapping[str, Any]) -> None:
    if record.get("record_type") != "ApparatusSpec":
        raise ContractError("conformance_failed", "apparatus profile requires ApparatusSpec")
    version = record.get("apparatus_version")
    if not isinstance(version, str) or not version:
        raise ContractError("conformance_failed", "apparatus version is required")
    acquisition = _object(record.get("acquisition_surface"), "acquisition_surface")
    computation = _object(record.get("computation_surface"), "computation_surface")
    action = _object(record.get("action_surface"), "action_surface")
    _object(record.get("configuration"), "configuration")

    media_kinds = acquisition.get("media_kinds")
    if (
        not isinstance(media_kinds, list)
        or not media_kinds
        or not all(isinstance(item, str) and item in INGRESS_KINDS for item in media_kinds)
        or len(media_kinds) != len(set(media_kinds))
    ):
        raise ContractError("conformance_failed", "apparatus media kinds are invalid")
    timebase = _object(acquisition.get("timebase"), "acquisition timebase")
    if not isinstance(timebase.get("kind"), str) or not timebase["kind"]:
        raise ContractError("conformance_failed", "apparatus timebase kind is required")
    sample_rates = timebase.get("sample_rates_hz")
    if not isinstance(sample_rates, list) or not sample_rates:
        raise ContractError("conformance_failed", "apparatus sample-rate capability is required")
    if any(not _positive_finite(value) for value in sample_rates):
        raise ContractError("conformance_failed", "apparatus sample rates must be positive finite")

    channel_map = acquisition.get("channel_map")
    if not isinstance(channel_map, list) or not channel_map:
        raise ContractError("conformance_failed", "apparatus channel map is required")
    indices: list[int] = []
    labels: list[str] = []
    for channel in channel_map:
        item = _object(channel, "channel map entry")
        index, label = item.get("source_index"), item.get("label")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ContractError("conformance_failed", "channel source index is invalid")
        if not isinstance(label, str) or not label:
            raise ContractError("conformance_failed", "channel label is required")
        indices.append(index)
        labels.append(label)
    if len(indices) != len(set(indices)) or len(labels) != len(set(labels)):
        raise ContractError("conformance_failed", "channel indexes and labels must be unique")

    calibration = _object(acquisition.get("calibration"), "calibration")
    if set(calibration) != {"frequency", "level", "time"}:
        raise ContractError(
            "conformance_failed", "calibration must declare frequency, level, and time domains"
        )
    for domain in ("frequency", "level", "time"):
        _validate_calibration_domain(domain, _object(calibration[domain], domain))

    dtypes = computation.get("numeric_dtypes")
    if (
        not isinstance(dtypes, list)
        or not dtypes
        or not all(item in {"float32", "float64", "int16", "int32"} for item in dtypes)
    ):
        raise ContractError("conformance_failed", "apparatus numeric dtypes are invalid")
    preprocessing = computation.get("preprocessing_operations")
    if not isinstance(preprocessing, list) or not all(
        item in PREPROCESSING_OPERATIONS for item in preprocessing
    ):
        raise ContractError("conformance_failed", "apparatus preprocessing surface is invalid")
    permitted = action.get("permitted_operations")
    if (
        not isinstance(permitted, list)
        or not permitted
        or not all(item in P4_OPERATIONS for item in permitted)
    ):
        raise ContractError("conformance_failed", "apparatus action surface is invalid")
    if action.get("network_access") is not False:
        raise ContractError("conformance_failed", "P4 apparatus network access must be false")


def _validate_calibration_domain(domain: str, value: Mapping[str, Any]) -> None:
    status = value.get("status")
    if status not in CALIBRATION_STATUSES:
        raise ContractError("conformance_failed", f"invalid {domain} calibration status")
    evidence = value.get("evidence")
    if status == "calibrated" and (
        not isinstance(evidence, list)
        or not evidence
        or not all(isinstance(item, str) and item for item in evidence)
    ):
        raise ContractError("conformance_failed", f"calibrated {domain} requires evidence")
    if domain == "frequency" and status == "calibrated":
        interval = value.get("range_hz")
        if not _finite_interval(interval, nonnegative=True):
            raise ContractError("conformance_failed", "frequency calibration range is invalid")
    if domain == "level" and status == "calibrated":
        if value.get("units") != "dB_SPL" or not _positive_finite(value.get("reference_pa")):
            raise ContractError(
                "conformance_failed", "level calibration requires dB_SPL and reference_pa"
            )
        uncertainty = value.get("uncertainty_db")
        if not _nonnegative_finite(uncertainty):
            raise ContractError("conformance_failed", "level uncertainty must be nonnegative")


def _validate_ingress(record: Mapping[str, Any]) -> None:
    record_type = record.get("record_type")
    kind = record.get("qste:ingressKind")
    if kind not in INGRESS_KINDS:
        raise ContractError("conformance_failed", "P4 ingress kind is invalid")
    if record_type == "SourceRecord":
        retention = _object(record.get("qste:retention"), "source retention")
        if retention.get("mode") not in {"retain", "delete_after", "reference_only"}:
            raise ContractError("conformance_failed", "source retention mode is invalid")
        if retention.get("redistribution") not in {"prohibited", "restricted", "permitted"}:
            raise ContractError("conformance_failed", "source redistribution state is invalid")
        if record.get("qste:dataOnly") is not True:
            raise ContractError("conformance_failed", "imported source must remain data-only")
    elif record_type == "ArtifactRecord":
        role = record.get("qste:artifactRole")
        if role not in {"imported_original", "decoded_derivative", "processed_derivative"}:
            raise ContractError("conformance_failed", "P4 artifact role is invalid")
    elif record_type == "AcquisitionEvent":
        if cast(Mapping[str, Any], record["apparatus_ref"]).get("record_type") != "ApparatusSpec":
            raise ContractError("conformance_failed", "acquisition requires an apparatus reference")
        _object(record.get("qste:timebase"), "acquisition timebase")
        channels = record.get("qste:channelMap")
        if not isinstance(channels, list) or not channels:
            raise ContractError("conformance_failed", "acquisition channel map is required")
    elif record_type == "ObservationRecord":
        acquisition = cast(Mapping[str, Any], record.get("acquisition_ref"))
        if acquisition.get("record_type") != "AcquisitionEvent":
            raise ContractError("conformance_failed", "observation requires AcquisitionEvent")
        if record.get("evidence_basis") == "model_inferred" and not isinstance(
            record.get("qste:modelIdentity"), Mapping
        ):
            raise ContractError("conformance_failed", "model observation requires model identity")
    else:
        raise ContractError("conformance_failed", "P4 ingress profile is on an invalid record type")


def _validate_aperture(record: Mapping[str, Any]) -> None:
    if record.get("record_type") != "ApertureSpec":
        raise ContractError("conformance_failed", "aperture profile requires ApertureSpec")
    typed_refs = {
        "apparatus_ref": "ApparatusSpec",
        "run_ref": "RunManifest",
        "input_ref": "ArtifactRecord",
    }
    for field, expected in typed_refs.items():
        value = cast(Mapping[str, Any], record.get(field))
        if value.get("record_type") != expected:
            raise ContractError("conformance_failed", f"{field} must reference {expected}")
    capabilities = _object(
        record.get("qste:calibrationCapabilities"), "aperture calibration capabilities"
    )
    for name in ("spl", "extra_human_frequency", "digital_sample_domain"):
        capability = _object(capabilities.get(name), f"{name} capability")
        if capability.get("status") not in {"available", "unavailable"}:
            raise ContractError("conformance_failed", f"{name} capability status is invalid")
        if (
            capability["status"] == "unavailable"
            and capability.get("reason") != "calibration_unavailable"
        ):
            raise ContractError("conformance_failed", f"{name} unavailable reason is invalid")


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ContractError("conformance_failed", f"{name} must be a nonempty object")
    return value


def _positive_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _nonnegative_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _finite_interval(value: Any, *, nonnegative: bool) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    lower, upper = value
    if not all(
        isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item)
        for item in value
    ):
        return False
    lower_number = cast(float, lower)
    upper_number = cast(float, upper)
    return (not nonnegative or lower_number >= 0) and lower_number < upper_number
