"""Frozen P11 ecosystem and bounded engine adapter identities."""

from __future__ import annotations

from dataclasses import dataclass

from qste.core.contracts import ContractError

ECOSYSTEM_PROFILE = "qste-ecosystem-adapter/v0.1"
ENGINE_PROFILE = "qste-bounded-engine-adapter/v0.1"
COMPATIBILITY_PROFILE = "qste-compatibility-target-manifest/0.1"
CONFORMANCE_PROFILE = "qste-ecosystem-engine-conformance/0.1"

ECOSYSTEM_OPERATIONS = ("import", "project", "inspect", "live_loopback")


@dataclass(frozen=True, slots=True)
class EcosystemTarget:
    target_id: str
    name: str
    version: str
    revision: str
    contracts: tuple[str, ...]
    capabilities: dict[str, str]
    fixture_path: str
    validation_mode: str


def _capabilities(
    *, import_: str, project: str, inspect: str = "available", live: str = "untested"
) -> dict[str, str]:
    return {
        "import": import_,
        "project": project,
        "inspect": inspect,
        "live_loopback": live,
    }


TARGETS = {
    "masa": EcosystemTarget(
        "masa",
        "MASA",
        "0.2.0",
        "a967339d77cb7adfb977061e6f3299ff27e55619",
        ("https://masa.sonicfield.org/schemas/0.2.0/matter-record.schema.json",),
        _capabilities(import_="available", project="available"),
        "fixtures/ecosystem-adapters/0.1/masa-record.json",
        "frozen_json_schema",
    ),
    "cosmoaudition": EcosystemTarget(
        "cosmoaudition",
        "Cosmoaudition",
        "0.2.0",
        "d56e76a2be7b3385fc3b0ce5a9f3b307f502b4f6",
        ("cosmo/modulation/v0.2", "cosmo/signal-catalog/v0.2"),
        _capabilities(import_="available", project="unavailable"),
        "fixtures/ecosystem-adapters/0.1/cosmo-frame.json",
        "frozen_typescript_contract_structural",
    ),
    "akouo": EcosystemTarget(
        "akouo",
        "AKOÚŌ",
        "0.9.2",
        "d3c0405279ae00e3b6e1ebc46136aefa0889ab7a",
        ("https://akouo.dev/schemas/route-decision.schema.json", "akouo/v0.9"),
        _capabilities(import_="available", project="unavailable"),
        "fixtures/ecosystem-adapters/0.1/akouo-route-decision.json",
        "frozen_json_schema",
    ),
    "oida": EcosystemTarget(
        "oida",
        "Oída",
        "0.10.0",
        "c595c22e373589c6d0ef244f7d8f38af6b2c30dd",
        ("https://oida.local/schemas/perception-report.schema.json",),
        _capabilities(import_="available", project="unavailable"),
        "fixtures/ecosystem-adapters/0.1/oida-perception-report.json",
        "frozen_json_schema",
    ),
    "earworm": EcosystemTarget(
        "earworm",
        "Earworm",
        "0.7.0",
        "c130fa61423517a0cc2ca8071124537978fad825",
        ("https://earworm.dev/schemas/akousma.schema.json", "earworm/auditum/v2"),
        _capabilities(import_="available", project="available"),
        "fixtures/ecosystem-adapters/0.1/earworm-akousma.json",
        "frozen_json_schema",
    ),
    "akousmata": EcosystemTarget(
        "akousmata",
        "Akousmata",
        "0.7.0",
        "838029d80360e04a01149437f30610503fd66794",
        ("akousmata/v0.7", "https://earworm.dev/schemas/akousma.schema.json"),
        _capabilities(import_="unavailable", project="unavailable"),
        "fixtures/ecosystem-adapters/0.1/earworm-akousma.json",
        "read_only_earworm_schema_inspection",
    ),
    "listening_stack": EcosystemTarget(
        "listening_stack",
        "Listening Stack",
        "0.4.1",
        "c0b91588c8fb7da0becf16a32809af9024fefb77",
        ("qste-listening-stack-read-only-snapshot/0.1",),
        _capabilities(import_="unavailable", project="unavailable"),
        "fixtures/ecosystem-adapters/0.1/listening-stack-metadata.json",
        "read_only_metadata_structural",
    ),
}

ENGINE_CAPABILITIES = {
    "pure_data": "unavailable",
    "max_msp": "unavailable",
    "supercollider": "unavailable",
    "csound": "unavailable",
    "qste_fixture_process": "available",
    "qste_fixture_osc_loopback": "available",
    "required_untested_fixture": "untested",
    "prohibited_fixture": "prohibited",
}


def ecosystem_target(target_id: str) -> EcosystemTarget:
    try:
        return TARGETS[target_id]
    except KeyError as error:
        raise ContractError(
            "invalid_input", f"unknown P11 ecosystem target: {target_id}"
        ) from error


def engine_capability(target_id: str) -> str:
    try:
        return ENGINE_CAPABILITIES[target_id]
    except KeyError as error:
        raise ContractError("invalid_input", f"unknown P11 engine target: {target_id}") from error
