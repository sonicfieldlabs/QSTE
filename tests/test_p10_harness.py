from __future__ import annotations

from pathlib import Path

import pytest
from p10_helpers import build_p10_fixture

from qste.agent import ACTION_REGISTRY, EXECUTOR_CLASSES
from qste.storage import RecordStore, WorkspacePaths


@pytest.mark.parametrize("executor_class", EXECUTOR_CLASSES)
def test_executor_class_is_nondecisive_and_cannot_originate_authority(
    tmp_path: Path, executor_class: str
) -> None:
    fixture = build_p10_fixture(tmp_path, executor_class)
    assert fixture.harness["qste:executorClass"] == executor_class
    assert fixture.harness["action_surface"]["prompt_authority"] is False
    assert fixture.harness["action_surface"]["model_execution"] is False
    assert fixture.initial["semantic_diff"]["semantic_or_behavioral_difference"] is True
    assert (
        fixture.initial["qste:nextOpportunityRef"]["record_id"] == fixture.opportunity["record_id"]
    )
    assert set(fixture.harness["action_surface"]["permitted_actions"]) == set(ACTION_REGISTRY)
    RecordStore(WorkspacePaths.open(fixture.base.workspace)).verify()


def test_completed_run_remains_byte_frozen_after_harness_initialization(tmp_path: Path) -> None:
    fixture = build_p10_fixture(tmp_path)
    store = RecordStore(WorkspacePaths.open(fixture.base.workspace))
    before = store.get_record(fixture.run["record_id"])
    after = store.get_record(fixture.run["record_id"])
    assert before.record_digest == after.record_digest
    assert fixture.opportunity["completed_run_ref"]["record_id"] == fixture.run["record_id"]
