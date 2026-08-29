from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from qste.storage import RecordStore, WorkspacePaths

ROOT = Path(__file__).resolve().parents[1]


def fixture_record(record_type: str, profile: str = "minimal.valid") -> dict[str, Any]:
    slug = "".join(
        ("-" + character.lower()) if character.isupper() else character for character in record_type
    ).lstrip("-")
    value = json.loads(
        (ROOT / "fixtures" / "schema" / "0.3.0" / slug / f"{profile}.json").read_text()
    )
    return deepcopy(cast(dict[str, Any], value))


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[WorkspacePaths, RecordStore]:
    store = RecordStore.initialize(tmp_path / "workspace")
    return store.paths, store
