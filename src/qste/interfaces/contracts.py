"""P13 interface contracts and root policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qste.core.contracts import ContractError
from qste.storage import WorkspacePaths

INTERFACE_PROFILE = "qste-local-interface/v0.1"
CONFORMANCE_PROFILE = "qste-interface-conformance/0.1"
MAX_ALLOWED_ROOTS = 16


@dataclass(frozen=True, slots=True)
class InterfacePolicy:
    """Caller-owned workspace and resource bounds for one interface process."""

    workspace: Path
    allowed_roots: tuple[Path, ...]
    mutations_enabled: bool = False
    maximum_items: int = 256
    maximum_lineage_depth: int = 64
    maximum_input_bytes: int = 1024 * 1024

    @classmethod
    def create(
        cls,
        *,
        workspace: Path,
        allowed_roots: tuple[Path, ...],
        mutations_enabled: bool = False,
        maximum_items: int = 256,
        maximum_lineage_depth: int = 64,
        maximum_input_bytes: int = 1024 * 1024,
    ) -> InterfacePolicy:
        if not allowed_roots or len(allowed_roots) > MAX_ALLOWED_ROOTS:
            raise ContractError("invalid_input", "P13 requires 1-16 explicit allowed roots")
        roots = tuple(_directory(value, "allowed root") for value in allowed_roots)
        resolved_workspace = _directory(workspace, "workspace")
        if not any(resolved_workspace.is_relative_to(root) for root in roots):
            raise ContractError("policy_refused", "workspace is outside the explicit allowed roots")
        WorkspacePaths.open(resolved_workspace)
        if not isinstance(mutations_enabled, bool):
            raise ContractError("invalid_input", "mutations enabled must be an exact boolean")
        if (
            not isinstance(maximum_items, int)
            or isinstance(maximum_items, bool)
            or maximum_items < 1
            or maximum_items > 1024
        ):
            raise ContractError("invalid_input", "maximum items must be between 1 and 1024")
        if (
            not isinstance(maximum_lineage_depth, int)
            or isinstance(maximum_lineage_depth, bool)
            or maximum_lineage_depth < 1
            or maximum_lineage_depth > 128
        ):
            raise ContractError("invalid_input", "maximum lineage depth must be between 1 and 128")
        if (
            not isinstance(maximum_input_bytes, int)
            or isinstance(maximum_input_bytes, bool)
            or maximum_input_bytes < 1024
            or maximum_input_bytes > 8 * 1024 * 1024
        ):
            raise ContractError(
                "invalid_input", "maximum input bytes must be between 1 KiB and 8 MiB"
            )
        return cls(
            workspace=resolved_workspace,
            allowed_roots=roots,
            mutations_enabled=mutations_enabled,
            maximum_items=maximum_items,
            maximum_lineage_depth=maximum_lineage_depth,
            maximum_input_bytes=maximum_input_bytes,
        )

    def bounded_items(self, requested: int | None) -> int:
        if requested is None:
            return self.maximum_items
        if (
            not isinstance(requested, int)
            or isinstance(requested, bool)
            or requested < 1
            or requested > self.maximum_items
        ):
            raise ContractError(
                "invalid_input", f"requested item count must be between 1 and {self.maximum_items}"
            )
        return requested

    def bounded_depth(self, requested: int) -> int:
        if (
            not isinstance(requested, int)
            or isinstance(requested, bool)
            or requested < 1
            or requested > self.maximum_lineage_depth
        ):
            raise ContractError(
                "invalid_input",
                f"requested lineage depth must be between 1 and {self.maximum_lineage_depth}",
            )
        return requested

    def require_mutation_approval(self, approved: bool) -> None:
        if not isinstance(approved, bool):
            raise ContractError("invalid_input", "human approval must be an exact boolean")
        if not self.mutations_enabled:
            error = ContractError("capability_unavailable", "mutating P13 tools are disabled")
            error.capability_status = "unavailable"
            raise error
        if not approved:
            error = ContractError("policy_refused", "mutating P13 tool requires human approval")
            error.authorization_status = "refused"
            raise error


def _directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ContractError("invalid_input", f"{label} must be absolute")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ContractError("invalid_input", f"{label} is absent") from error
    if not resolved.is_dir():
        raise ContractError("invalid_input", f"{label} is not a directory")
    return resolved
