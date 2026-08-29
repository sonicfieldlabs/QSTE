"""Strict QSTE 0.3.0 contract loading, validation, and JSON round trips."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from copy import deepcopy
from importlib import resources
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]
from referencing import Registry, Resource

CONTRACT_ID = "qste-contract/0.3.0"
SCHEMA_SET_ID = "qste-schema/0.3.0"
CONFORMANCE_PROFILE_ID = "qste-conformance/0.3.0"
SCHEMA_VERSION = "0.3.0"
BASE_URI = f"https://schemas.qste.invalid/{SCHEMA_VERSION}"

JsonObject = dict[str, Any]


class ContractError(ValueError):
    """A stable, structured QSTE contract failure."""

    # Services may attach these stable diagnostic fields before re-raising.
    # They are deliberately optional at runtime; callers must continue to use
    # ``getattr`` when the originating operation does not supply one.
    receipt_id: str
    authorization_status: str
    capability_status: str
    diagnostics_extra: Mapping[str, Any]

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        path: Iterable[Any] = (),
        keyword: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.path = tuple(path)
        self.keyword = keyword


def _reject_constant(value: str) -> None:
    raise ContractError("invalid_input", f"non-finite JSON number is prohibited: {value}")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("invalid_input", f"duplicate JSON member: {key}", path=(key,))
        result[key] = value
    return result


def loads_json(data: str | bytes | bytearray) -> Any:
    """Load finite JSON and reject duplicate object members."""

    try:
        return json.loads(
            data,
            parse_constant=_reject_constant,
            object_pairs_hook=_object_without_duplicates,
        )
    except ContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError("invalid_input", f"invalid JSON: {error}") from error


def dumps_json(value: Any) -> str:
    """Emit deterministic UTF-8-compatible JSON with a terminal newline."""

    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
    except (TypeError, ValueError) as error:
        raise ContractError("invalid_input", f"value is not finite JSON: {error}") from error


def _source_schema_root() -> Path:
    candidate = Path(__file__).resolve().parents[3] / "schemas" / SCHEMA_VERSION
    if candidate.is_dir():
        return candidate
    packaged = resources.files("qste").joinpath("contracts", "schemas", SCHEMA_VERSION)
    if not packaged.is_dir():
        raise ContractError("capability_unavailable", "packaged QSTE schema resources are absent")
    return Path(str(packaged))


class SchemaRegistry:
    """An offline registry for the exact QSTE 0.3.0 schema set."""

    def __init__(self, schema_root: Path | None = None) -> None:
        self.schema_root = (schema_root or _source_schema_root()).resolve()
        index_path = self.schema_root / "schema-index.json"
        if not index_path.is_file():
            raise ContractError("capability_unavailable", f"schema index absent: {index_path}")
        index = loads_json(index_path.read_bytes())
        if not isinstance(index, dict) or index.get("schema_set_id") != SCHEMA_SET_ID:
            raise ContractError(
                "conformance_failed", "schema index does not identify qste-schema/0.3.0"
            )
        self.index = cast(JsonObject, index)
        self._schemas: dict[str, JsonObject] = {}
        resources_by_uri: list[tuple[str, Resource[Any]]] = []
        for entry in cast(list[JsonObject], self.index["schemas"]):
            path = self.schema_root / cast(str, entry["path"])
            schema = loads_json(path.read_bytes())
            if not isinstance(schema, dict) or schema.get("$id") != entry["id"]:
                raise ContractError("conformance_failed", f"schema identity mismatch: {path}")
            expected_digest = entry.get("sha256")
            actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if expected_digest != actual_digest:
                raise ContractError("conformance_failed", f"schema digest mismatch: {path}")
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as error:
                raise ContractError(
                    "conformance_failed", f"invalid JSON Schema: {path}: {error.message}"
                ) from error
            schema_id = cast(str, entry["id"])
            typed_schema = cast(JsonObject, schema)
            self._schemas[schema_id] = typed_schema
            resources_by_uri.append((schema_id, Resource.from_contents(typed_schema)))
        self._registry: Registry[Any] = Registry().with_resources(resources_by_uri)

    @property
    def schema_ids(self) -> tuple[str, ...]:
        return tuple(self._schemas)

    def schema_for_record_type(self, record_type: str) -> str:
        if record_type == "Bundle":
            return f"{BASE_URI}/bundle-manifest.schema.json"
        for entry in cast(list[JsonObject], self.index["schemas"]):
            if entry.get("kind") == "serialized_record" and entry.get("name") == record_type:
                return cast(str, entry["id"])
        raise ContractError("invalid_input", f"unknown QSTE record type: {record_type}")

    def validate(self, value: Any, schema_id: str) -> None:
        schema = self._schemas.get(schema_id)
        if schema is None:
            raise ContractError("invalid_input", f"schema is not in {SCHEMA_SET_ID}: {schema_id}")
        validator = Draft202012Validator(
            schema,
            registry=self._registry,
            format_checker=FormatChecker(),
        )
        errors = sorted(
            validator.iter_errors(value),
            key=lambda error: (
                error.validator == "unevaluatedProperties",
                tuple(str(p) for p in error.path),
            ),
        )
        if errors:
            error = errors[0]
            raise ContractError(
                "conformance_failed",
                error.message,
                path=error.absolute_path,
                keyword=cast(str, error.validator),
            ) from error

    def validate_record(self, value: Mapping[str, Any]) -> None:
        record_type = value.get("record_type")
        if not isinstance(record_type, str):
            raise ContractError("conformance_failed", "record_type is required")
        self.validate(value, self.schema_for_record_type(record_type))
        _validate_identity_layers(value)
        _validate_semantics(value)

    def validate_bundle_manifest(self, value: Mapping[str, Any]) -> None:
        self.validate(value, self.schema_for_record_type("Bundle"))

    def validate_operation_result(self, value: Mapping[str, Any]) -> None:
        self.validate(value, f"{BASE_URI}/operation-result.schema.json")
        _validate_operation_semantics(value)
        if value["operation_status"] != "completed":
            return
        value_type = cast(str, value["value_type"])
        payload = value["value"]
        if value_type.startswith("qste-payload/0.3.0/"):
            self.validate(payload, f"{BASE_URI}/typed-payload.schema.json")
            expected_payload_type = value_type.rsplit("/", 1)[-1]
            if (
                not isinstance(payload, Mapping)
                or payload.get("payload_type") != expected_payload_type
            ):
                raise ContractError(
                    "conformance_failed",
                    "OperationResult value does not match its typed-payload identifier",
                )
        else:
            self.validate(payload, value_type)

    def read_record(self, data: str | bytes | bytearray) -> JsonObject:
        value = loads_json(data)
        if not isinstance(value, dict):
            raise ContractError("invalid_input", "a QSTE record must be a JSON object")
        self.validate_record(value)
        return deepcopy(cast(JsonObject, value))

    def write_record(self, value: Mapping[str, Any]) -> str:
        copied = deepcopy(dict(value))
        self.validate_record(copied)
        return dumps_json(copied)


def _validate_identity_layers(record: Mapping[str, Any]) -> None:
    identities = {
        name: record[name]
        for name in ("record_id", "semantic_key", "content_digest")
        if name in record
    }
    values = list(identities.values())
    if len(values) != len(set(values)):
        raise ContractError(
            "conformance_failed",
            "record_id, semantic_key, and content_digest are non-substitutable",
        )


def _validate_semantics(record: Mapping[str, Any]) -> None:
    from qste.core.p4_contracts import validate_p4_semantics
    from qste.core.p5_contracts import validate_p5_semantics
    from qste.core.p6_contracts import validate_p6_semantics
    from qste.core.p7_contracts import validate_p7_semantics
    from qste.core.p8_contracts import validate_p8_semantics
    from qste.core.p9_contracts import validate_p9_semantics
    from qste.core.p10_contracts import validate_p10_semantics
    from qste.core.p11_contracts import validate_p11_semantics

    validate_p4_semantics(record)
    validate_p5_semantics(record)
    validate_p6_semantics(record)
    validate_p7_semantics(record)
    validate_p8_semantics(record)
    validate_p9_semantics(record)
    validate_p10_semantics(record)
    validate_p11_semantics(record)
    record_type = record["record_type"]
    if record_type == "TaskSpec":
        bound = record["meaningful_bound"]
        region = record["equivalence_region"]
        if (
            not isinstance(bound, (int, float))
            or isinstance(bound, bool)
            or not math.isfinite(bound)
        ):
            raise ContractError("invalid_assessment_spec", "meaningful_bound must be finite")
        if not isinstance(region, Mapping):
            raise ContractError("invalid_assessment_spec", "equivalence_region must be structured")
        epsilon_minus = region.get("epsilon_minus")
        epsilon_plus = region.get("epsilon_plus")
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            for value in (epsilon_minus, epsilon_plus)
        ):
            raise ContractError("invalid_assessment_spec", "equivalence bounds must be finite")
        if (
            cast(float, epsilon_minus) < 0
            or cast(float, epsilon_plus) < 0
            or cast(float, epsilon_plus) >= bound
        ):
            raise ContractError(
                "invalid_assessment_spec",
                "TaskSpec requires 0 <= epsilon_plus < meaningful_bound and 0 <= epsilon_minus",
            )
        if region.get("units") != record["response_units"]:
            raise ContractError(
                "invalid_assessment_spec", "TaskSpec bounds must use response_units"
            )
    elif record_type == "RefinementGraph":
        nodes = record["nodes"]
        required = record["required_closure"]
        if record["closed"] and not set(required).issubset(set(nodes)):
            raise ContractError(
                "conformance_failed", "required refinement closure must be contained in graph nodes"
            )
        if record["closed"] != bool(record["completion_certificate"].get("complete")):
            raise ContractError(
                "conformance_failed", "closed state and completion certificate disagree"
            )
    elif record_type == "DSQAssessment":
        status = record["assessment_status"]
        if status == "qualified":
            required_true = (
                record["well_formed"],
                record["qualification_ready"],
                record["closure_certificate"].get("complete"),
                record["closure_certificate"].get("nonempty"),
            )
            if (
                not all(value is True for value in required_true)
                or not record["tested_proper_nodes"]
            ):
                raise ContractError(
                    "conformance_failed",
                    "qualified assessment requires ready, closed, nonempty proper-node evidence",
                )
            if record["reason_code"] != "meaningful_closed_equivalent":
                raise ContractError(
                    "conformance_failed", "qualified assessment has a non-qualification reason"
                )
            if (
                record["dependency_validity"] != "valid"
                or record["authorization_status"] != "permitted"
            ):
                raise ContractError(
                    "conformance_failed",
                    "qualified assessment requires valid dependency and permission",
                )
        if status == "rejected" and record["negative_evidence_valid"] is not True:
            raise ContractError("conformance_failed", "rejection requires NegativeEvidenceValid")
    elif record_type == "RelationAssertion":
        status = record["comparison_status"]
        relation = record["relation_type"]
        reason = record["reason_code"]
        null_resolved = {"coverage_failed", "effect_incompatible", "unmatched_by_spec"}
        indeterminate = {
            "projection_invalid",
            "target_address_absent",
            "fidelity_failed",
            "zero_footprint_undefined",
            "coverage_boundary_crossing",
            "effect_boundary_crossing",
            "structural_matching_ambiguity",
            "decomposition_ambiguity",
            "eligible_evidence_incomplete",
            "matching_budget_exhausted",
            "comparison_capability_unavailable",
        }
        relation_reasons = {
            "overlap": "matched_overlap",
            "split": "matched_split",
            "merge": "matched_merge",
            "omission": "target_address_absent",
            "loss": "fidelity_failed",
            "incomparable": "projection_invalid",
        }
        if status == "indeterminate" and (relation is not None or reason not in indeterminate):
            raise ContractError(
                "conformance_failed",
                "indeterminate comparison requires null relation and an indeterminate reason",
            )
        if status == "resolved" and relation is None and reason not in null_resolved:
            raise ContractError(
                "conformance_failed",
                "resolved null relation requires a conclusive no-relation reason",
            )
        if (
            status == "resolved"
            and relation is not None
            and relation_reasons.get(cast(str, relation)) != reason
        ):
            raise ContractError("conformance_failed", "relation type and reason are inconsistent")
    elif record_type == "AuthorityManifest":
        exact = {
            "semantic_contract": CONTRACT_ID,
            "schema_set": SCHEMA_SET_ID,
            "conformance_profile": CONFORMANCE_PROFILE_ID,
        }
        for field, expected in exact.items():
            value = record[field]
            if not isinstance(value, Mapping) or value.get("id") != expected:
                raise ContractError("conformance_failed", f"AuthorityManifest conflict at {field}")


def _validate_operation_semantics(result: Mapping[str, Any]) -> None:
    status = result["operation_status"]
    reason = result["reason_code"]
    exit_class = result["cli_exit_class"]
    if status == "completed":
        domain = result.get("domain_status", {})
        expected = 5 if isinstance(domain, Mapping) and "indeterminate" in domain.values() else 0
        if result["authorization_status"] not in {"permitted", "not_applicable"}:
            raise ContractError(
                "conformance_failed",
                "completed operation requires permission or not_applicable authorization",
            )
        if result["capability_status"] not in {"available", "degraded"}:
            raise ContractError(
                "conformance_failed",
                "completed operation requires available or degraded capability",
            )
    elif status == "refused":
        expected = 3
        if reason != "policy_refused":
            raise ContractError("conformance_failed", "refused operation requires policy_refused")
    elif status == "unavailable":
        expected = 4
        if reason != "capability_unavailable":
            raise ContractError(
                "conformance_failed", "unavailable operation requires capability_unavailable"
            )
        if result["capability_status"] not in {"unavailable", "untested"}:
            raise ContractError(
                "conformance_failed",
                "unavailable operation requires unavailable or untested capability",
            )
    elif status == "partial":
        expected = 6
        if reason != "partial_completion":
            raise ContractError(
                "conformance_failed", "partial operation requires partial_completion"
            )
    else:
        expected_by_reason = {
            "invalid_input": 2,
            "invalid_assessment_spec": 2,
            "invalid_comparison_spec": 2,
            "execution_failed": 7,
            "conformance_failed": 8,
            "internal_error": 9,
        }
        expected = expected_by_reason.get(cast(str, reason), -1)
        if (
            reason in {"invalid_assessment_spec", "invalid_comparison_spec"}
            and "domain_status" in result
        ):
            raise ContractError(
                "conformance_failed", "invalid specification must not receive a domain status"
            )
    if exit_class != expected:
        raise ContractError(
            "conformance_failed",
            f"CLI exit class {exit_class} does not match structured result; expected {expected}",
        )


def validate_reference_closure(
    records: Iterable[Mapping[str, Any]],
    *,
    registry: SchemaRegistry | None = None,
) -> None:
    """Validate all records and every embedded typed internal reference."""

    active = registry or SchemaRegistry()
    materialized = [dict(record) for record in records]
    index: dict[str, str] = {}
    for record in materialized:
        active.validate_record(record)
        record_id = cast(str, record["record_id"])
        if record_id in index:
            raise ContractError("conformance_failed", f"duplicate record_id: {record_id}")
        index[record_id] = cast(str, record["record_type"])
    for record in materialized:
        for reference in _walk_references(record):
            record_id = cast(str, reference["record_id"])
            actual = index.get(record_id)
            if actual is None:
                raise ContractError(
                    "conformance_failed", f"missing internal reference: {record_id}"
                )
            expected = cast(str, reference["record_type"])
            if actual != expected:
                raise ContractError(
                    "conformance_failed",
                    "typed reference mismatch for "
                    f"{record_id}: expected {expected}, found {actual}",
                )
    _validate_refinement_dependencies(materialized, index)


def _walk_references(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if set(("record_id", "record_type", "relation")).issubset(value):
            yield value
            return
        for child in value.values():
            yield from _walk_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_references(child)


def _validate_refinement_dependencies(records: list[JsonObject], index: Mapping[str, str]) -> None:
    by_id = {cast(str, record["record_id"]): record for record in records}
    for graph in (record for record in records if record["record_type"] == "RefinementGraph"):
        family_ref = graph["representation_family_ref"]["record_id"]
        intervention_ref = graph["intervention_ref"]["record_id"]
        if (
            index.get(family_ref) != "RepresentationFamilySpec"
            or index.get(intervention_ref) != "InterventionSpec"
        ):
            raise ContractError(
                "conformance_failed", "refinement requires a representation family and intervention"
            )
        family = by_id[family_ref]
        if not family.get("mapping_refs"):
            raise ContractError(
                "conformance_failed", "refinement family requires an explicit mapping"
            )


def validate_bundle_closure(
    manifest: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    *,
    registry: SchemaRegistry | None = None,
) -> None:
    """Validate a sealed bundle manifest against its ordered object set."""

    active = registry or SchemaRegistry()
    active.validate_bundle_manifest(manifest)
    materialized = list(records)
    validate_reference_closure(materialized, registry=active)
    actual = {
        cast(str, record["record_id"]): cast(str, record["record_type"]) for record in materialized
    }
    declared: dict[str, str] = {}
    sequences: list[int] = []
    for entry in manifest["record_manifest"]:
        declared[entry["record_id"]] = entry["record_type"]
        sequences.append(entry["sequence"])
    if declared != actual:
        raise ContractError(
            "conformance_failed", "bundle record manifest does not equal the supplied record set"
        )
    if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
        raise ContractError(
            "conformance_failed", "bundle record sequence must be ordered and unique"
        )
