#!/usr/bin/env python3
"""Execute the repository-independent P2 QSTE conformance checks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from qste.core import (
    ContractError,
    SchemaRegistry,
    dumps_json,
    loads_json,
    validate_reference_closure,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "schema" / "0.3.0"
CONFORMANCE = ROOT / "conformance" / "0.3.0"


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def must_fail(reason: str, operation: Callable[[], None]) -> None:
    try:
        operation()
    except ContractError as error:
        require(
            error.reason_code == reason,
            f"expected reason {reason}, received {error.reason_code}: {error}",
        )
        return
    raise SystemExit(f"expected failure reason {reason}")


def main() -> None:
    registry = SchemaRegistry()
    indexed_schema_paths = {entry["path"] for entry in registry.index["schemas"]}
    actual_schema_paths = {
        path.relative_to(registry.schema_root).as_posix()
        for path in registry.schema_root.rglob("*.schema.json")
    }
    require(indexed_schema_paths == actual_schema_paths, "schema index and filesystem differ")
    conformance_index = read(CONFORMANCE / "conformance-index.json")
    for entry in conformance_index["files"]:
        path = ROOT / entry["path"]
        require(
            hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"],
            f"conformance digest differs: {entry['path']}",
        )
    fixture_manifest = read(FIXTURES / "fixture-manifest.json")
    positive = 0
    negative = 0
    extensions = 0
    for case in fixture_manifest["fixtures"]:
        payload = read(ROOT / case["path"])
        try:
            validate_case(registry, case, payload)
            valid = True
        except ContractError as error:
            valid = False
            if case["expected_reason"] in {"type", "required", "enum", "additionalProperties"}:
                require(
                    error.keyword == case["expected_reason"],
                    f"fixture keyword differs for {case['path']}: {error.keyword}",
                )
        require(valid == case["expected_valid"], f"fixture expectation differs: {case['path']}")
        if valid:
            positive += 1
        else:
            negative += 1
        if valid and case["expected_reason"] == "namespaced_extension":
            if case["record_type"] == "Bundle":
                encoded = dumps_json(payload)
                decoded = loads_json(encoded)
                registry.validate_bundle_manifest(decoded)
            else:
                encoded = registry.write_record(payload)
                decoded = registry.read_record(encoded)
            require(
                decoded["ext:futureField"] == payload["ext:futureField"],
                f"extension round-trip differs: {case['path']}",
            )
            extensions += 1

    closed = read(FIXTURES / "reference-closure" / "closed.valid.json")
    validate_reference_closure(closed["objects"], registry=registry)
    for filename in ("missing-reference.invalid.json", "wrong-type.invalid.json"):
        payload = read(FIXTURES / "reference-closure" / filename)
        must_fail(
            "conformance_failed",
            lambda payload=payload: validate_reference_closure(
                payload["objects"], registry=registry
            ),
        )

    refinement = read(FIXTURES / "reference-closure" / "refinement.valid.json")
    validate_reference_closure(refinement["objects"], registry=registry)
    missing_mapping = read(
        FIXTURES / "reference-closure" / "refinement-mapping-missing.invalid.json"
    )
    must_fail(
        "conformance_failed",
        lambda: validate_reference_closure(missing_mapping["objects"], registry=registry),
    )

    dsq = read(FIXTURES / "dsq-assessment" / "minimal.valid.json")
    substituted = deepcopy(dsq)
    substituted["content_digest"] = substituted["semantic_key"]
    must_fail("conformance_failed", lambda: registry.validate_record(substituted))

    candidate = read(FIXTURES / "candidate-unit" / "minimal.valid.json")
    conflated = deepcopy(candidate)
    conflated["record_type"] = "DSQAssessment"
    must_fail("conformance_failed", lambda: registry.validate_record(conflated))

    task = read(FIXTURES / "task-spec" / "minimal.valid.json")
    invalid_bound = deepcopy(task)
    invalid_bound["equivalence_region"]["epsilon_plus"] = invalid_bound["meaningful_bound"]
    must_fail("invalid_assessment_spec", lambda: registry.validate_record(invalid_bound))

    unready = deepcopy(dsq)
    unready["tested_proper_nodes"] = []
    must_fail("conformance_failed", lambda: registry.validate_record(unready))
    rejected = deepcopy(dsq)
    rejected["assessment_status"] = "rejected"
    rejected["reason_code"] = "candidate_nonmeaningful"
    rejected["negative_evidence_valid"] = False
    must_fail("conformance_failed", lambda: registry.validate_record(rejected))

    relation = read(FIXTURES / "relation-assertion" / "minimal.valid.json")
    confused_relation = deepcopy(relation)
    confused_relation["comparison_status"] = "indeterminate"
    must_fail("conformance_failed", lambda: registry.validate_record(confused_relation))
    alias_relation = deepcopy(relation)
    alias_relation["relation_type"] = "overlapping"
    must_fail("conformance_failed", lambda: registry.validate_record(alias_relation))
    resolved_null = deepcopy(relation)
    resolved_null["relation_type"] = None
    resolved_null["reason_code"] = "coverage_failed"
    registry.validate_record(resolved_null)

    invalid_result = read(FIXTURES / "operation-result" / "failed-invalid-spec.valid.json")
    with_domain_status = deepcopy(invalid_result)
    with_domain_status["domain_status"] = {"assessment_status": "indeterminate"}
    must_fail("conformance_failed", lambda: registry.validate_operation_result(with_domain_status))
    completed = read(FIXTURES / "operation-result" / "completed.valid.json")
    wrong_payload = deepcopy(completed)
    wrong_payload["value"]["payload_type"] = "RelationSet"
    must_fail("conformance_failed", lambda: registry.validate_operation_result(wrong_payload))

    must_fail("invalid_input", lambda: loads_json('{"a":1,"a":2}'))
    must_fail("invalid_input", lambda: loads_json('{"a":NaN}'))
    require(
        loads_json(dumps_json({"z": 1, "a": [True, None]})) == {"a": [True, None], "z": 1},
        "canonical JSON round-trip differs",
    )

    coverage = read(CONFORMANCE / "entity-coverage.json")["entities"]
    require(
        len([item for item in coverage if item["contract_form"] == "serialized_record"]) == 31,
        "serialized record coverage differs",
    )
    require(
        next(item for item in coverage if item["entity"] == "Phenomenon")["schema"] is None,
        "Phenomenon must remain conceptual",
    )
    require(
        next(item for item in coverage if item["entity"] == "Bundle")["contract_form"]
        == "sealed_container",
        "Bundle contract form differs",
    )

    print(
        json.dumps(
            {
                "schema_set_id": "qste-schema/0.3.0",
                "schemas": len(registry.schema_ids),
                "positive_fixtures": positive,
                "negative_fixtures": negative,
                "extension_roundtrips": extensions,
                "reference_closure": "passed",
                "semantic_invariants": "passed",
            },
            sort_keys=True,
        )
    )


def registry_record_types(registry: SchemaRegistry) -> set[str]:
    return {
        item["name"] for item in registry.index["schemas"] if item["kind"] == "serialized_record"
    }


def validate_case(registry: SchemaRegistry, case: dict[str, Any], payload: Any) -> None:
    if case["record_type"] in registry_record_types(registry):
        registry.validate_record(payload)
    elif case["record_type"] == "OperationResult":
        registry.validate_operation_result(payload)
    else:
        registry.validate(payload, case["schema_id"])


if __name__ == "__main__":
    main()
