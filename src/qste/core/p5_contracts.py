"""Behavioral record constraints for the deterministic P5 STFT/Gabor arm."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, cast

from qste.core.contracts import ContractError

STFT_PROFILE = "qste-stft-gabor/v0.1"
FAMILY_PROFILE = "qste-representation-family/stft-gabor-v0.1"
REFINEMENT_PROFILE = "qste-refinement/strict-nonempty-mask-subset-v0.1"
INTERVENTION_PROFILE = "qste-intervention/stft-native-v0.1"
PROJECTION_PROFILE = "qste-projection/stft-mock-footprint-v0.1"
THEORETICAL_BOUND = 1.0 / (4.0 * math.pi)


def validate_p5_semantics(record: Mapping[str, Any]) -> None:
    """Validate namespaced P5 records without redefining the P2 schema set."""

    if record.get("qste:gaborProfile") == STFT_PROFILE:
        _validate_gabor_record(record)
    if record.get("qste:refinementProfile") == REFINEMENT_PROFILE:
        _validate_refinement(record)
    if record.get("qste:interventionProfile") == INTERVENTION_PROFILE:
        _require_type(record, "InterventionSpec")
    if record.get("qste:projectionProfile") == PROJECTION_PROFILE:
        _require_type(record, "ProjectionSpec")
    if record.get("qste:familyProfile") == FAMILY_PROFILE:
        _require_type(record, "RepresentationFamilySpec")


def _validate_gabor_record(record: Mapping[str, Any]) -> None:
    record_type = record.get("record_type")
    if record_type == "RepresentationSpec":
        atom_bound = _object(record.get("qste:gaborAtomBound"), "Gabor atom bound")
        realized = _object(record.get("qste:realizedAtomSpread"), "realized atom spread")
        lattice = _object(record.get("qste:lattice"), "Gabor lattice")
        refinement = _object(record.get("qste:refinementContract"), "refinement contract")
        terminal = _object(record.get("qste:pTerminal"), "P-terminal contract")
        if atom_bound.get("constant") != THEORETICAL_BOUND:
            raise ContractError("conformance_failed", "Gabor bound constant is not canonical")
        if atom_bound.get("convention") != "standard_deviation_hz_seconds":
            raise ContractError("conformance_failed", "Gabor width convention is not canonical")
        temporal = realized.get("temporal_std_seconds")
        spectral = realized.get("spectral_std_hz")
        product = realized.get("product_hz_seconds")
        if not all(_positive_finite(value) for value in (temporal, spectral, product)):
            raise ContractError("conformance_failed", "realized Gabor spreads must be positive")
        if not math.isclose(cast(float, temporal) * cast(float, spectral), cast(float, product)):
            raise ContractError("conformance_failed", "realized Gabor product is inconsistent")
        if cast(float, product) + 1e-12 < THEORETICAL_BOUND:
            raise ContractError("conformance_failed", "realized Gabor product violates bound")
        required_lattice = {
            "fft_length",
            "hop_length",
            "bin_spacing_hz",
            "lattice_cell_hz_seconds",
            "redundancy",
            "coefficient_density_per_second",
        }
        if set(lattice) != required_lattice:
            raise ContractError("conformance_failed", "lattice fields are incomplete or mixed")
        if refinement.get("order") != "strict_nonempty_mask_subset":
            raise ContractError("conformance_failed", "P5 refinement order is not canonical")
        if terminal.get("rule") != "singleton_native_leaf":
            raise ContractError("conformance_failed", "P-terminal rule is not canonical")
    elif record_type == "RepresentationInstance":
        if (
            cast(Mapping[str, Any], record.get("representation_spec_ref", {})).get("record_type")
            != "RepresentationSpec"
        ):
            raise ContractError("conformance_failed", "Gabor instance requires RepresentationSpec")
        if not isinstance(record.get("qste:originalFrameCount"), int):
            raise ContractError(
                "conformance_failed", "Gabor instance requires original frame count"
            )
    elif record_type == "CandidateUnit":
        address = _object(record.get("native_address"), "candidate native address")
        cells = address.get("cells")
        if address.get("kind") != "stft_mask" or not isinstance(cells, list) or not cells:
            raise ContractError("conformance_failed", "candidate requires a nonempty STFT mask")
        canonical = [tuple(cell) for cell in cells if isinstance(cell, list)]
        if len(canonical) != len(cells) or canonical != sorted(set(canonical)):
            raise ContractError("conformance_failed", "candidate cells must be unique and sorted")
        terminal = _object(record.get("qste:pTerminal"), "candidate P-terminal state")
        if terminal.get("is_terminal") != (len(cells) == 1):
            raise ContractError("conformance_failed", "candidate terminal state is inconsistent")
        if record.get("qste:dsqStatus") != "candidate_only":
            raise ContractError("conformance_failed", "P5 candidates cannot carry a DSQ verdict")
    elif record_type == "ArtifactRecord":
        if record.get("qste:representationArtifactRole") not in {
            "coefficient_dense_manifest",
            "intervened_coefficient_dense_manifest",
            "decoded_waveform",
            "perturbed_coefficient_dense_manifest",
        }:
            raise ContractError("conformance_failed", "unknown P5 representation artifact role")
    else:
        raise ContractError("conformance_failed", "Gabor profile is on an invalid record type")


def _validate_refinement(record: Mapping[str, Any]) -> None:
    _require_type(record, "RefinementGraph")
    nodes = record.get("nodes")
    edges = record.get("edges")
    closure = record.get("required_closure")
    certificate = _object(record.get("completion_certificate"), "completion certificate")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not isinstance(closure, list):
        raise ContractError("conformance_failed", "refinement graph collections are invalid")
    if record.get("closed") is not True or certificate.get("complete") is not True:
        raise ContractError("conformance_failed", "P5 refinement graph must certify closure")
    if certificate.get("effect_pruning") is not False:
        raise ContractError("conformance_failed", "refinement cannot use effect pruning")
    if len(closure) < 1 or certificate.get("proper_node_count") != len(closure):
        raise ContractError("conformance_failed", "proper-node closure is empty or inconsistent")


def _require_type(record: Mapping[str, Any], expected: str) -> None:
    if record.get("record_type") != expected:
        raise ContractError("conformance_failed", f"P5 profile requires {expected}")


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
