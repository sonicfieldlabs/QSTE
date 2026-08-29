from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from p5_helpers import build_p5_fixture, explicit_candidates

from qste.core.contracts import ContractError
from qste.storage import RecordStore, WorkspacePaths


def test_candidate_occurrence_semantics_and_native_support_remain_separate(
    tmp_path: Path,
) -> None:
    fixture = build_p5_fixture(tmp_path, np.ones(256) * 0.1)
    mask = [[[0, 3, 4], [0, 4, 4]]]
    first = explicit_candidates(fixture, mask)[0]
    second = explicit_candidates(fixture, mask)[0]
    assert first["record_id"] != second["record_id"]
    assert first["semantic_key"] == second["semantic_key"]
    assert first["semantic_key"] != fixture.instance["semantic_key"]
    assert first["record_type"] == "CandidateUnit"
    assert first["qste:dsqStatus"] == "candidate_only"
    assert first["native_support"]["atom_spread_substitution"] is False


def test_complete_boolean_refinement_is_constructed_before_effects(tmp_path: Path) -> None:
    fixture = build_p5_fixture(tmp_path, np.arange(512) / 1024)
    candidate = explicit_candidates(
        fixture,
        [[[[0, 2, 4], [0, 3, 4], [0, 2, 5], [0, 3, 5]]][0]],
    )[0]
    outcome = fixture.service.refine(
        candidate_record_id=candidate["record_id"],
        procedure={"procedure_id": "boolean-subsets", "maximum_nodes": 20},
    )
    graph = outcome.value
    assert graph["closed"] is True
    assert len(graph["required_closure"]) == 14
    assert len(graph["nodes"]) == 15
    assert graph["completion_certificate"]["proper_node_count"] == 14
    assert graph["completion_certificate"]["effect_pruning"] is False
    assert graph["qste:gaborBoundUsedAsRefinementEvidence"] is False
    assert graph["qste:dsqAssessmentStatus"] == "available_in_P6_as_separate_record"
    node_metadata = graph["qste:nodeMetadata"]
    assert sum(item["cell_count"] == 1 for item in node_metadata) == 4


def test_singleton_empty_proper_set_is_unavailable_and_receipted(tmp_path: Path) -> None:
    fixture = build_p5_fixture(tmp_path, np.ones(128) * 0.2)
    singleton = explicit_candidates(fixture, [[[[0, 2, 3]]][0]])[0]
    with pytest.raises(ContractError, match="empty proper-node set") as caught:
        fixture.service.refine(
            candidate_record_id=singleton["record_id"],
            procedure={"procedure_id": "boolean-subsets", "maximum_nodes": 10},
        )
    receipt_id = caught.value.receipt_id  # type: ignore[attr-defined]
    store = RecordStore(WorkspacePaths.open(fixture.workspace))
    receipt = store.get_record(receipt_id).record
    assert receipt["operation_status"] == "unavailable"
    assert not any(record.record_type == "DSQAssessment" for record in store.iter_records())
