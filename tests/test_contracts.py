from __future__ import annotations

import json
from copy import deepcopy
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from qste.core import (
    ContractError,
    SchemaRegistry,
    dumps_json,
    loads_json,
    validate_reference_closure,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "schema" / "0.3.0"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    assert isinstance(value, dict)
    return value


def validate_fixture(
    registry: SchemaRegistry, case: dict[str, Any], payload: dict[str, Any]
) -> None:
    record_types = {
        entry["name"] for entry in registry.index["schemas"] if entry["kind"] == "serialized_record"
    }
    if case["record_type"] in record_types:
        registry.validate_record(payload)
    elif case["record_type"] == "OperationResult":
        registry.validate_operation_result(payload)
    else:
        registry.validate(payload, case["schema_id"])


def test_all_schemas_self_validate_and_all_fixture_expectations_hold() -> None:
    registry = SchemaRegistry()
    manifest = read(FIXTURES / "fixture-manifest.json")
    assert len(registry.schema_ids) == 35
    assert len(manifest["fixtures"]) == 198
    for case in manifest["fixtures"]:
        payload = read(ROOT / case["path"])
        if case["expected_valid"]:
            validate_fixture(registry, case, payload)
        else:
            with pytest.raises(ContractError):
                validate_fixture(registry, case, payload)


def test_namespaced_extension_round_trip_is_lossless() -> None:
    registry = SchemaRegistry()
    record = read(FIXTURES / "candidate-unit" / "forward-extension.valid.json")
    decoded = registry.read_record(registry.write_record(record))
    assert decoded["ext:futureField"] == record["ext:futureField"]


def test_identity_layers_and_noncanonical_relation_tokens_fail() -> None:
    registry = SchemaRegistry()
    assessment = read(FIXTURES / "dsq-assessment" / "minimal.valid.json")
    assessment["content_digest"] = assessment["semantic_key"]
    with pytest.raises(ContractError, match="non-substitutable"):
        registry.validate_record(assessment)

    relation = read(FIXTURES / "relation-assertion" / "minimal.valid.json")
    relation["relation_type"] = "overlapping"
    with pytest.raises(ContractError):
        registry.write_record(relation)


def test_task_math_and_assessment_status_are_semantically_checked() -> None:
    registry = SchemaRegistry()
    task = read(FIXTURES / "task-spec" / "minimal.valid.json")
    task["equivalence_region"]["epsilon_plus"] = task["meaningful_bound"]
    with pytest.raises(ContractError) as failure:
        registry.validate_record(task)
    assert failure.value.reason_code == "invalid_assessment_spec"

    for field_path in ("meaningful_bound", "epsilon_plus", "epsilon_minus"):
        invalid_task = deepcopy(task)
        invalid_task["equivalence_region"]["epsilon_plus"] = 0.1
        if field_path == "meaningful_bound":
            invalid_task[field_path] = True
        else:
            invalid_task["equivalence_region"][field_path] = True
        with pytest.raises(ContractError):
            registry.validate_record(invalid_task)

    assessment = read(FIXTURES / "dsq-assessment" / "minimal.valid.json")
    assessment["closure_certificate"]["nonempty"] = False
    with pytest.raises(ContractError, match="closed, nonempty"):
        registry.validate_record(assessment)


def test_relation_type_and_comparison_status_do_not_substitute() -> None:
    registry = SchemaRegistry()
    relation = read(FIXTURES / "relation-assertion" / "minimal.valid.json")
    relation["relation_type"] = None
    relation["reason_code"] = "coverage_failed"
    registry.validate_record(relation)
    relation["comparison_status"] = "indeterminate"
    with pytest.raises(ContractError):
        registry.validate_record(relation)


def test_reference_closure_and_refinement_mapping() -> None:
    registry = SchemaRegistry()
    closed = read(FIXTURES / "reference-closure" / "closed.valid.json")
    validate_reference_closure(closed["objects"], registry=registry)
    refinement = read(FIXTURES / "reference-closure" / "refinement.valid.json")
    validate_reference_closure(refinement["objects"], registry=registry)

    invalid = deepcopy(refinement)
    family = next(
        record
        for record in invalid["objects"]
        if record["record_type"] == "RepresentationFamilySpec"
    )
    family["mapping_refs"] = []
    with pytest.raises(ContractError):
        validate_reference_closure(invalid["objects"], registry=registry)


def test_reader_rejects_duplicate_members_and_nonfinite_numbers() -> None:
    with pytest.raises(ContractError, match="duplicate"):
        loads_json('{"value":1,"value":2}')
    with pytest.raises(ContractError, match="non-finite"):
        loads_json('{"value":NaN}')
    assert loads_json(dumps_json({"z": 1, "a": True})) == {"a": True, "z": 1}


def test_explicit_absent_and_withheld_alternatives_do_not_require_fictional_values() -> None:
    registry = SchemaRegistry()
    for record_type in (
        "acquisition-event",
        "source-record",
        "artifact-record",
        "observation-record",
    ):
        registry.validate_record(read(FIXTURES / record_type / "withheld.valid.json"))


def test_operation_result_value_matches_declared_t() -> None:
    registry = SchemaRegistry()
    result = read(FIXTURES / "operation-result" / "completed.valid.json")
    registry.validate_operation_result(result)
    result["value"]["payload_type"] = "RelationSet"
    with pytest.raises(ContractError, match="typed-payload identifier"):
        registry.validate_operation_result(result)


def test_packaged_contract_resource_location_is_declared() -> None:
    package_root = resources.files("qste")
    # An editable checkout resolves root schemas; wheel tests assert this packaged path exists.
    packaged = package_root.joinpath("contracts", "schemas", "0.3.0", "schema-index.json")
    if packaged.is_file():
        assert json.loads(packaged.read_text())["schema_set_id"] == "qste-schema/0.3.0"
