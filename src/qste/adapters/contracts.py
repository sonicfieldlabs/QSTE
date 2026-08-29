"""Frozen P9 compatibility targets and complete capability surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from qste.core import content_digest

ADAPTER_PROFILE = "qste-external-representation-adapter/v0.1"
CAPTURE_PROFILE = "qste-external-representation-capture/0.1"
CONFORMANCE_PROFILE = "qste-external-representation-conformance/0.1"
OPERATIONS = (
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
)
IMPLEMENTED_CAPTURE_OPERATIONS = frozenset(
    {"encode", "enumerate", "address", "intervene", "decode", "support", "account"}
)


@dataclass(frozen=True, slots=True)
class AdapterTarget:
    adapter_id: str
    target_id: str
    implementation_ref: str
    implementation_revision: str
    package_digest: str
    native_unit: str
    native_metric: str
    execution_mode: str
    license_status: str
    compatibility_manifest: str
    checkpoint_id: str | None = None
    checkpoint_revision: str | None = None
    checkpoint_digest: str | None = None


SAMPLEBRAIN_TARGET = AdapterTarget(
    adapter_id="samplebrain",
    target_id="samplebrain/v0.18.5_release",
    implementation_ref="https://gitlab.com/then-try-this/samplebrain",
    implementation_revision="bc8002a9f0931f24b8078a956a9b73f09300f566",
    package_digest=content_digest(
        b"samplebrain|v0.18.5_release|bc8002a9f0931f24b8078a956a9b73f09300f566|GPL-2.0-only"
    ),
    native_unit="samplebrain_native_block",
    native_metric="captured_samplebrain_similarity_distance",
    execution_mode="supervised_capture",
    license_status="verified_GPL-2.0-only",
    compatibility_manifest=("profiles/adapters/samplebrain/0.1/compatibility-target.json"),
)

ENCODEC_TARGET = AdapterTarget(
    adapter_id="encodec",
    target_id="encodec/v0.1.1+facebook-encodec-24khz",
    implementation_ref="https://github.com/facebookresearch/encodec",
    implementation_revision="f1479a65a75c0e49e7e5d85bb1418fd57e6a9d62",
    package_digest="sha256:36dde98ccfe6c51a15576476cadfcb3b35a63507b8b8555abd69889a6fba6772",
    native_unit="encodec_frame_codebook_token",
    native_metric="native_token_hamming_distance",
    execution_mode="captured_fixture_only",
    license_status="unresolved_checkpoint_license_not_declared",
    compatibility_manifest="profiles/adapters/encodec/0.1/compatibility-target.json",
    checkpoint_id="facebook/encodec_24khz:model.safetensors",
    checkpoint_revision="c1dbe2ae3f1de713481a3b3e7c47f357092ee040",
    checkpoint_digest="sha256:37a7cb100f71a29e6c1d815aca8666a1d7ea8885ebe44c306c751a5103559d57",
)

TARGETS = {
    SAMPLEBRAIN_TARGET.adapter_id: SAMPLEBRAIN_TARGET,
    ENCODEC_TARGET.adapter_id: ENCODEC_TARGET,
}


def target_for(adapter_id: str) -> AdapterTarget:
    """Resolve one exact P9 adapter target without aliases."""

    try:
        return TARGETS[adapter_id]
    except KeyError as error:
        from qste.core.contracts import ContractError

        raise ContractError("invalid_input", f"unknown P9 adapter: {adapter_id}") from error


def capability_map() -> dict[str, str]:
    """Return the complete REP-01 operation declaration."""

    return {
        operation: "available" if operation in IMPLEMENTED_CAPTURE_OPERATIONS else "unavailable"
        for operation in OPERATIONS
    }
