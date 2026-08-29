from __future__ import annotations

import json
from pathlib import Path

import pytest
from p7_helpers import comparison_evidence, declared_engine, p7_candidates

from qste.cli import main
from qste.core import canonical_json_bytes
from qste.core.contracts import ContractError
from qste.operations import relation_compare
from qste.storage import RecordStore, WorkspacePaths


def test_invalid_comparison_request_fails_without_relation_status_and_is_receipted(
    tmp_path: Path,
) -> None:
    fixture, sources, targets = p7_candidates(tmp_path)
    service, comparison, _projections = declared_engine(fixture, sources, targets)
    source_id = sources[0]["record_id"]
    target_id = targets[0]["record_id"]
    evidence = comparison_evidence(
        sources,
        targets,
        {source_id: [1.0, 0.0], target_id: [1.0, 0.0]},
    )
    evidence["units"][source_id]["effect_contract"] = {
        **evidence["units"][source_id]["effect_contract"],
        "units": "native_metric",
    }
    before = len(
        [
            value
            for value in service.store.iter_records()
            if value.record["record_type"] == "RelationAssertion"
        ]
    )
    with pytest.raises(ContractError) as caught:
        service.compare(
            comparison_spec_record_id=comparison["record_id"],
            source_candidate_record_ids=[source_id],
            target_candidate_record_ids=[target_id],
            evidence=evidence,
        )
    assert caught.value.reason_code == "invalid_comparison_spec"
    assert hasattr(caught.value, "receipt_id")
    after = len(
        [
            value
            for value in service.store.iter_records()
            if value.record["record_type"] == "RelationAssertion"
        ]
    )
    assert after == before


def test_relation_operation_and_cli_preserve_indeterminate_exit_class(
    tmp_path: Path, capsys: object
) -> None:
    fixture, sources, targets = p7_candidates(tmp_path)
    _service, comparison, _projections = declared_engine(fixture, sources, targets)
    source_id = sources[0]["record_id"]
    target_id = targets[0]["record_id"]
    evidence = comparison_evidence(
        sources,
        targets,
        {source_id: [0.0, 0.0], target_id: [1.0, 0.0]},
    )
    result = relation_compare(
        fixture.workspace,
        comparison_spec_record_id=comparison["record_id"],
        source_candidate_record_ids=[source_id],
        target_candidate_record_ids=[target_id],
        evidence=evidence,
        authorization_status="permitted",
    )
    assert result["operation_status"] == "completed"
    assert result["domain_status"] == {"comparison_status": "indeterminate"}
    assert result["reason_code"] == "zero_footprint_undefined"
    assert result["cli_exit_class"] == 5

    evidence_path = tmp_path / "relation-evidence.json"
    evidence_path.write_text(json.dumps(evidence))
    exit_class = main(
        [
            "relation",
            "compare",
            "--workspace",
            str(fixture.workspace),
            "--comparison",
            comparison["record_id"],
            "--source",
            source_id,
            "--target",
            target_id,
            "--evidence",
            str(evidence_path),
            "--authorization",
            "permitted",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert exit_class == 5
    assert payload["domain_status"] == {"comparison_status": "indeterminate"}
    RecordStore(WorkspacePaths.open(fixture.workspace)).get_record(payload["receipt_id"])


def test_relation_invalidation_is_append_only_and_keeps_assertion_bytes_frozen(
    tmp_path: Path,
) -> None:
    fixture, sources, targets = p7_candidates(tmp_path)
    service, comparison, _projections = declared_engine(fixture, sources, targets)
    source_id = sources[0]["record_id"]
    target_id = targets[0]["record_id"]
    relation = service.compare(
        comparison_spec_record_id=comparison["record_id"],
        source_candidate_record_ids=[source_id],
        target_candidate_record_ids=[target_id],
        evidence=comparison_evidence(
            sources,
            targets,
            {source_id: [1.0, 0.0], target_id: [1.0, 0.0]},
        ),
    ).value["items"][0]
    frozen = canonical_json_bytes(relation)
    outcome = service.invalidate_relation(
        relation_assertion_record_id=relation["record_id"],
        invalidation_reason="implementation_defect",
        evidence={"ticket": "P7-CONFORMANCE-INJECTED"},
    )
    stored = service.store.get_record(relation["record_id"]).record
    assert canonical_json_bytes(stored) == frozen
    assert outcome.value["data"]["current_dependency_validity"] == "invalidated"
    assert service.current_dependency_validity(relation["record_id"]) == {
        "stored_dependency_validity": "valid",
        "current_dependency_validity": "invalidated",
        "invalidation_events": 1,
        "latest_invalidation_reason": "implementation_defect",
    }
