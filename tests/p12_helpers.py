from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from p4_helpers import apparatus_declaration

from qste.core import loads_json
from qste.experiments import ExperimentPreparationService
from qste.ingress import declare_apparatus

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "experiment-preparation" / "0.1"


@dataclass(frozen=True, slots=True)
class P12Fixture:
    workspace: Path
    context: dict[str, Any]
    service: ExperimentPreparationService


def build_p12_fixture(tmp_path: Path) -> P12Fixture:
    workspace = tmp_path / "workspace"
    context = declare_apparatus(workspace, apparatus_declaration()).apparatus_record
    return P12Fixture(workspace, context, ExperimentPreparationService(workspace))


def fixture(name: str) -> dict[str, Any]:
    value = loads_json((FIXTURES / name).read_bytes())
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)
