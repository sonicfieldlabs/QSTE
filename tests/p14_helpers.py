from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from p4_helpers import apparatus_declaration

from qste.core import loads_json
from qste.ingress import declare_apparatus
from qste.model_research import ModelResearchService

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "model-research" / "0.1"


@dataclass(frozen=True, slots=True)
class P14Fixture:
    workspace: Path
    context: dict[str, Any]
    service: ModelResearchService


def fixture(name: str) -> dict[str, Any]:
    value = loads_json((FIXTURES / name).read_bytes())
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def build_p14_fixture(tmp_path: Path) -> P14Fixture:
    workspace = tmp_path / "workspace"
    context = declare_apparatus(workspace, apparatus_declaration()).apparatus_record
    return P14Fixture(workspace, context, ModelResearchService(workspace))


def registered_manifest(program: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    manifest = fixture("dataset-manifest.json")
    manifest["program_digest"] = program["content_digest"]
    for item in manifest["items"]:
        item["source_record_id"] = context["record_id"]
    return manifest
