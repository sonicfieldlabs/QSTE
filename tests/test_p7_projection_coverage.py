from __future__ import annotations

from pathlib import Path

import pytest
from p7_helpers import (
    EFFECT_CONTRACT,
    comparison_evidence,
    comparison_spec,
    declared_engine,
    p7_candidates,
    projection_spec,
)

from qste.core.contracts import ContractError
from qste.relations import RelationService


def test_unit_integral_energy_coverage_is_symmetric_and_resolves_overlap(
    tmp_path: Path,
) -> None:
    fixture, sources, targets = p7_candidates(tmp_path)
    service, comparison, _projections = declared_engine(fixture, sources, targets)
    footprints = {
        sources[0]["record_id"]: [2.0, 2.0, 0.0],
        targets[0]["record_id"]: [1.0, 1.0, 0.0],
    }
    outcome = service.compare(
        comparison_spec_record_id=comparison["record_id"],
        source_candidate_record_ids=[sources[0]["record_id"]],
        target_candidate_record_ids=[targets[0]["record_id"]],
        evidence=comparison_evidence(sources, targets, footprints),
    )
    relation = outcome.value["items"][0]
    assert (relation["relation_type"], relation["reason_code"]) == (
        "overlap",
        "matched_overlap",
    )
    pair = relation["coverage"]["pairs"][0]
    assert pair["source_to_target"]["point_estimate"] == pytest.approx(1.0)
    assert pair["target_to_source"]["point_estimate"] == pytest.approx(1.0)
    assert relation["qste:nativeIdentityPreserved"] is True


def test_probability_coverage_can_be_directional(tmp_path: Path) -> None:
    fixture, sources, targets = p7_candidates(tmp_path)
    service, comparison, _projections = declared_engine(
        fixture,
        sources,
        targets,
        kind="exceedance_probability",
        comparison_overrides={"coverage_threshold": 0.4},
    )
    footprints = {
        sources[0]["record_id"]: [1.0, 1.0],
        targets[0]["record_id"]: [1.0, 0.0],
    }
    relation = service.compare(
        comparison_spec_record_id=comparison["record_id"],
        source_candidate_record_ids=[sources[0]["record_id"]],
        target_candidate_record_ids=[targets[0]["record_id"]],
        evidence=comparison_evidence(sources, targets, footprints),
    ).value["items"][0]
    pair = relation["coverage"]["pairs"][0]
    assert pair["source_to_target"]["point_estimate"] == pytest.approx(0.5)
    assert pair["target_to_source"]["point_estimate"] == pytest.approx(1.0)
    assert relation["relation_type"] == "overlap"


def test_projection_address_and_fidelity_precedence_is_exact(tmp_path: Path) -> None:
    fixture, sources, targets = p7_candidates(tmp_path)
    service, comparison, _projections = declared_engine(fixture, sources, targets)
    footprints = {
        sources[0]["record_id"]: [1.0, 0.0],
        targets[0]["record_id"]: [1.0, 0.0],
    }
    pair = (sources[0]["record_id"], targets[0]["record_id"])
    invalid = comparison_evidence(
        sources,
        targets,
        footprints,
        projection_status={sources[0]["record_id"]: "invalid"},
        pair_overrides={pair: {"target_address": "absent", "fidelity": "failed"}},
    )
    invalid["units"][sources[0]["record_id"]].pop("footprint")
    invalid["units"][sources[0]["record_id"]].pop("effect_interval")
    invalid["units"][sources[0]["record_id"]].pop("effect_contract")
    omission = comparison_evidence(
        sources, targets, footprints, pair_overrides={pair: {"target_address": "absent"}}
    )
    loss = comparison_evidence(
        sources, targets, footprints, pair_overrides={pair: {"fidelity": "failed"}}
    )
    expected = [
        (invalid, "incomparable", "projection_invalid"),
        (omission, "omission", "target_address_absent"),
        (loss, "loss", "fidelity_failed"),
    ]
    for evidence, relation_type, reason in expected:
        relation = service.compare(
            comparison_spec_record_id=comparison["record_id"],
            source_candidate_record_ids=[sources[0]["record_id"]],
            target_candidate_record_ids=[targets[0]["record_id"]],
            evidence=evidence,
        ).value["items"][0]
        assert (
            relation["comparison_status"],
            relation["relation_type"],
            relation["reason_code"],
        ) == (
            "resolved",
            relation_type,
            reason,
        )


def test_effect_conversion_must_be_explicit_and_versioned(tmp_path: Path) -> None:
    fixture, sources, targets = p7_candidates(tmp_path)
    service = RelationService(fixture.workspace)
    source_projection = service.declare_projection(
        source_arm_record_id=sources[0]["representation_instance_ref"]["record_id"],
        specification=projection_spec(),
    ).value
    native_target = dict(EFFECT_CONTRACT) | {"units": "native_mock_score"}
    target_projection = service.declare_projection(
        source_arm_record_id=targets[0]["representation_instance_ref"]["record_id"],
        specification=projection_spec(effect_contract=native_target),
    ).value
    projection_ids = [source_projection["record_id"], target_projection["record_id"]]
    with pytest.raises(ContractError, match="effect estimands are incompatible"):
        service.declare_comparison(
            projection_record_ids=projection_ids,
            specification=comparison_spec(),
        )
    conversion = {
        target_projection["record_id"]: {
            "id": "mock-score-to-logit",
            "version": "v0.1",
            "source_units": "native_mock_score",
            "target_units": "logit",
        }
    }
    comparison = service.declare_comparison(
        projection_record_ids=projection_ids,
        specification=comparison_spec(effect_conversions=conversion),
    ).value
    assert comparison["qste:effectConversions"] == conversion
