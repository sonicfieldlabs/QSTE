"""QSTE command line for bounded local P3-P14 operations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

from qste._version import version_info
from qste.core.contracts import ContractError
from qste.operations import (
    adapter_encode,
    adapter_enumerate,
    adapter_operate,
    adapter_probe,
    agent_initialize,
    agent_payloads,
    agent_plan,
    agent_revise,
    agent_study,
    agent_treatments,
    agent_utility,
    appeal_adjudicate,
    appeal_open,
    bundle,
    declare_apparatus,
    derive_aperture,
    ecosystem_account,
    ecosystem_import,
    ecosystem_inspect,
    ecosystem_live_loopback,
    ecosystem_project,
    engine_account,
    engine_execute,
    engine_loopback,
    experiment_account,
    experiment_freeze,
    experiment_pilot,
    export_projection,
    failure_result,
    governance_declare,
    ingest,
    inspect,
    mapping_declare,
    model_dataset_register,
    model_program_freeze,
    model_research_account,
    quanta_assess,
    quanta_baseline,
    quanta_invalidate,
    read_json_object,
    relation_compare,
    relation_declare_comparison,
    relation_declare_projection,
    relation_invalidate,
    repair_apply,
    representation_account,
    representation_address,
    representation_decode,
    representation_encode,
    representation_enumerate,
    representation_intervene,
    representation_measure,
    representation_perturb,
    representation_project,
    representation_refine,
    representation_support,
    task_declare,
    task_execute,
    trace_lineage,
    transduce,
    verify,
)


def _print_version(*, as_json: bool) -> None:
    payload = version_info()
    if as_json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return
    print(
        "{package} {code_version} "
        "(commit {git_commit}; {contract_id}; phase {implementation_phase}; "
        "capability {capability_status})".format(**payload)
    )


def _emit(payload: dict[str, Any], *, as_json: bool) -> int:
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":") if as_json else None,
            indent=None if as_json else 2,
        )
    )
    return int(payload["cli_exit_class"])


def _path(value: str) -> Path:
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qste",
        description="QSTE local foundation with bounded P14 declaration infrastructure.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="report package, Git, contract, phase, and capability identity",
    )
    subparsers = parser.add_subparsers(dest="command")
    version_parser = subparsers.add_parser("version", help="report bounded identity")
    version_parser.add_argument("--json", action="store_true", help="emit canonical JSON")

    inspect_parser = subparsers.add_parser("inspect", help="inspect one stored record occurrence")
    inspect_parser.add_argument("--workspace", required=True, type=_path)
    inspect_parser.add_argument("--record", required=True)
    inspect_parser.add_argument("--json", action="store_true")

    lineage_parser = subparsers.add_parser("lineage", help="trace bounded record lineage")
    lineage_parser.add_argument("--workspace", required=True, type=_path)
    lineage_parser.add_argument("--record", required=True)
    lineage_parser.add_argument(
        "--direction", choices=("ancestors", "descendants"), default="ancestors"
    )
    lineage_parser.add_argument("--max-depth", type=int, default=64)
    lineage_parser.add_argument("--json", action="store_true")

    verify_parser = subparsers.add_parser("verify", help="verify a workspace or bundle")
    target = verify_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--workspace", type=_path)
    target.add_argument("--bundle", dest="bundle_root", type=_path)
    verify_parser.add_argument("--json", action="store_true")

    bundle_parser = subparsers.add_parser("bundle", help="seal one private local bundle")
    bundle_parser.add_argument("--workspace", required=True, type=_path)
    bundle_parser.add_argument("--authority", required=True, type=_path)
    bundle_parser.add_argument("--bundle-id")
    bundle_parser.add_argument("--json", action="store_true")

    ingest_parser = subparsers.add_parser("ingest", help="import one bounded typed source")
    ingest_parser.add_argument("--workspace", required=True, type=_path)
    ingest_parser.add_argument("--input", required=True, type=_path)
    ingest_parser.add_argument(
        "--kind",
        required=True,
        choices=("audio", "json_observations", "csv_observations", "text", "model_observations"),
    )
    ingest_parser.add_argument("--apparatus", required=True)
    ingest_parser.add_argument("--origin", required=True)
    ingest_parser.add_argument("--rights", required=True, type=_path)
    ingest_parser.add_argument("--retention", required=True, type=_path)
    ingest_parser.add_argument("--allowed-root", required=True, action="append", type=_path)
    ingest_parser.add_argument("--authorization", choices=("permitted", "refused"), required=True)
    ingest_parser.add_argument("--json", action="store_true")

    apparatus_parser = subparsers.add_parser("apparatus", help="apparatus operations")
    apparatus_subparsers = apparatus_parser.add_subparsers(dest="apparatus_command", required=True)
    apparatus_validate = apparatus_subparsers.add_parser(
        "validate", help="validate and persist one apparatus"
    )
    apparatus_validate.add_argument("--workspace", required=True, type=_path)
    apparatus_validate.add_argument("--declaration", required=True, type=_path)
    apparatus_validate.add_argument("--json", action="store_true")

    aperture_parser = subparsers.add_parser("aperture", help="aperture operations")
    aperture_subparsers = aperture_parser.add_subparsers(dest="aperture_command", required=True)
    aperture_derive = aperture_subparsers.add_parser("derive", help="derive one evidenced aperture")
    aperture_derive.add_argument("--workspace", required=True, type=_path)
    aperture_derive.add_argument("--apparatus", required=True)
    aperture_derive.add_argument("--input", required=True)
    aperture_derive.add_argument("--policy", required=True, type=_path)
    aperture_derive.add_argument("--json", action="store_true")

    representation_parser = subparsers.add_parser("representation", help="P5 STFT/Gabor operations")
    representation_subparsers = representation_parser.add_subparsers(
        dest="representation_command", required=True
    )

    encode_parser = representation_subparsers.add_parser("encode")
    encode_parser.add_argument("--workspace", required=True, type=_path)
    encode_parser.add_argument("--artifact", required=True)
    encode_parser.add_argument("--aperture", required=True)
    encode_parser.add_argument("--config", required=True, type=_path)

    enumerate_parser = representation_subparsers.add_parser("enumerate")
    enumerate_parser.add_argument("--workspace", required=True, type=_path)
    enumerate_parser.add_argument("--instance", required=True)
    enumerate_parser.add_argument("--rule", required=True, type=_path)

    refine_parser = representation_subparsers.add_parser("refine")
    refine_parser.add_argument("--workspace", required=True, type=_path)
    refine_parser.add_argument("--candidate", required=True)
    refine_parser.add_argument("--procedure", required=True, type=_path)

    support_parser = representation_subparsers.add_parser("support")
    support_parser.add_argument("--workspace", required=True, type=_path)
    support_parser.add_argument("--candidate", required=True)
    support_parser.add_argument("--spec", required=True, type=_path)

    address_parser = representation_subparsers.add_parser("address")
    address_parser.add_argument("--workspace", required=True, type=_path)
    address_parser.add_argument("--candidate", required=True)
    address_parser.add_argument("--intervention", required=True)

    intervene_parser = representation_subparsers.add_parser("intervene")
    intervene_parser.add_argument("--workspace", required=True, type=_path)
    intervene_parser.add_argument("--candidate", required=True)
    intervene_parser.add_argument("--intervention", required=True)
    intervene_parser.add_argument(
        "--mode", required=True, choices=("mask", "isolate", "phase_coherent_replace")
    )
    intervene_parser.add_argument(
        "--control",
        default="authentic",
        choices=("authentic", "resynthesis_only", "off_target", "alternate"),
    )

    decode_parser = representation_subparsers.add_parser("decode")
    decode_parser.add_argument("--workspace", required=True, type=_path)
    decode_parser.add_argument("--target", required=True)

    project_parser = representation_subparsers.add_parser("project")
    project_parser.add_argument("--workspace", required=True, type=_path)
    project_parser.add_argument("--candidate", required=True)
    project_parser.add_argument("--projection", required=True)

    measure_parser = representation_subparsers.add_parser("measure")
    measure_parser.add_argument("--workspace", required=True, type=_path)
    measure_parser.add_argument("--left", required=True)
    measure_parser.add_argument("--right", required=True)
    measure_parser.add_argument("--metric", required=True, type=_path)

    perturb_parser = representation_subparsers.add_parser("perturb")
    perturb_parser.add_argument("--workspace", required=True, type=_path)
    perturb_parser.add_argument("--instance", required=True)
    perturb_parser.add_argument("--spec", required=True, type=_path)

    account_parser = representation_subparsers.add_parser("account")
    account_parser.add_argument("--workspace", required=True, type=_path)
    account_parser.add_argument("--instance", required=True)

    for operation_parser in (
        encode_parser,
        enumerate_parser,
        refine_parser,
        support_parser,
        address_parser,
        intervene_parser,
        decode_parser,
        project_parser,
        measure_parser,
        perturb_parser,
        account_parser,
    ):
        operation_parser.add_argument(
            "--authorization", required=True, choices=("permitted", "refused")
        )
        operation_parser.add_argument("--json", action="store_true")

    ecosystem_parser = subparsers.add_parser(
        "ecosystem", help="P11 frozen ecosystem adapter operations"
    )
    ecosystem_subparsers = ecosystem_parser.add_subparsers(dest="ecosystem_command", required=True)
    ecosystem_targets = (
        "masa",
        "cosmoaudition",
        "akouo",
        "oida",
        "earworm",
        "akousmata",
        "listening_stack",
    )
    for name in ("import", "project", "inspect", "live", "account"):
        command_parser = ecosystem_subparsers.add_parser(name)
        command_parser.add_argument("--workspace", required=True, type=_path)
        command_parser.add_argument("--target", required=True, choices=ecosystem_targets)
        command_parser.add_argument("--context", required=True)
        if name in {"import", "project", "inspect"}:
            command_parser.add_argument("--payload", required=True, type=_path)
        if name == "project":
            command_parser.add_argument("--human-authorized", action="store_true")
        command_parser.add_argument(
            "--authorization",
            required=True,
            choices=("unknown", "permitted", "refused", "deferred", "revoked"),
        )
        command_parser.add_argument("--json", action="store_true")

    engine_parser = subparsers.add_parser("engine", help="P11 bounded engine operations")
    engine_subparsers = engine_parser.add_subparsers(dest="engine_command", required=True)
    engine_targets = (
        "pure_data",
        "max_msp",
        "supercollider",
        "csound",
        "qste_fixture_process",
        "qste_fixture_osc_loopback",
        "required_untested_fixture",
        "prohibited_fixture",
    )
    for name in ("execute", "loopback", "account"):
        command_parser = engine_subparsers.add_parser(name)
        command_parser.add_argument("--workspace", required=True, type=_path)
        command_parser.add_argument("--target", required=True, choices=engine_targets)
        command_parser.add_argument("--context", required=True)
        if name in {"execute", "loopback"}:
            command_parser.add_argument("--request", required=True, type=_path)
        command_parser.add_argument(
            "--authorization",
            required=True,
            choices=("unknown", "permitted", "refused", "deferred", "revoked"),
        )
        command_parser.add_argument("--json", action="store_true")

    experiment_parser = subparsers.add_parser(
        "experiment", help="P12a preparation and nonconfirmatory method-pilot operations"
    )
    experiment_subparsers = experiment_parser.add_subparsers(
        dest="experiment_command", required=True
    )
    experiment_freeze_parser = experiment_subparsers.add_parser("freeze")
    experiment_freeze_parser.add_argument("--workspace", required=True, type=_path)
    experiment_freeze_parser.add_argument("--context", required=True)
    experiment_freeze_parser.add_argument("--packet", required=True, type=_path)
    experiment_pilot_parser = experiment_subparsers.add_parser("pilot")
    experiment_pilot_parser.add_argument("--workspace", required=True, type=_path)
    experiment_pilot_parser.add_argument("--preparation", required=True)
    experiment_pilot_parser.add_argument("--evidence", required=True, type=_path)
    experiment_account_parser = experiment_subparsers.add_parser("account")
    experiment_account_parser.add_argument("--workspace", required=True, type=_path)
    experiment_account_parser.add_argument("--context", required=True)
    for command_parser in (
        experiment_freeze_parser,
        experiment_pilot_parser,
        experiment_account_parser,
    ):
        command_parser.add_argument(
            "--authorization",
            required=True,
            choices=("unknown", "permitted", "refused", "deferred", "revoked"),
        )
        command_parser.add_argument("--json", action="store_true")

    model_parser = subparsers.add_parser(
        "model", help="P14 model-research declarations without model execution"
    )
    model_subparsers = model_parser.add_subparsers(dest="model_command", required=True)
    model_freeze_parser = model_subparsers.add_parser("freeze")
    model_freeze_parser.add_argument("--workspace", required=True, type=_path)
    model_freeze_parser.add_argument("--context", required=True)
    model_freeze_parser.add_argument("--program", required=True, type=_path)
    model_dataset_parser = model_subparsers.add_parser("dataset")
    model_dataset_parser.add_argument("--workspace", required=True, type=_path)
    model_dataset_parser.add_argument("--program-record", required=True)
    model_dataset_parser.add_argument("--manifest", required=True, type=_path)
    model_account_parser = model_subparsers.add_parser("account")
    model_account_parser.add_argument("--workspace", required=True, type=_path)
    model_account_parser.add_argument("--context", required=True)
    for command_parser in (model_freeze_parser, model_dataset_parser, model_account_parser):
        command_parser.add_argument(
            "--authorization",
            required=True,
            choices=("unknown", "permitted", "refused", "deferred", "revoked"),
        )
        command_parser.add_argument("--json", action="store_true")

    agent_parser = subparsers.add_parser(
        "agent", help="P10 harness, payload, treatment, study, and utility operations"
    )
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command", required=True)
    agent_initialize_parser = agent_subparsers.add_parser("initialize")
    agent_initialize_parser.add_argument("--workspace", required=True, type=_path)
    agent_initialize_parser.add_argument("--boundary", required=True)
    agent_initialize_parser.add_argument("--authority", required=True)
    agent_initialize_parser.add_argument("--source", required=True)
    agent_initialize_parser.add_argument("--completed-run", required=True)
    agent_initialize_parser.add_argument("--predecessor", required=True)
    agent_initialize_parser.add_argument("--spec", required=True, type=_path)
    agent_payloads_parser = agent_subparsers.add_parser("payloads")
    agent_payloads_parser.add_argument("--workspace", required=True, type=_path)
    agent_payloads_parser.add_argument("--assessment", required=True)
    agent_payloads_parser.add_argument("--spec", required=True, type=_path)
    agent_treatments_parser = agent_subparsers.add_parser("treatments")
    agent_treatments_parser.add_argument("--workspace", required=True, type=_path)
    agent_treatments_parser.add_argument("--opportunity", required=True)
    agent_treatments_parser.add_argument("--payload", required=True)
    agent_treatments_parser.add_argument("--allocation", required=True, type=_path)
    agent_study_parser = agent_subparsers.add_parser("study")
    agent_study_parser.add_argument("--workspace", required=True, type=_path)
    agent_study_parser.add_argument("--decisions", required=True, type=_path)
    agent_study_parser.add_argument("--preregistration", required=True, type=_path)
    agent_utility_parser = agent_subparsers.add_parser("utility")
    agent_utility_parser.add_argument("--workspace", required=True, type=_path)
    agent_utility_parser.add_argument("--decision", required=True)
    agent_utility_parser.add_argument("--evaluation", required=True, type=_path)
    for operation_parser in (
        agent_initialize_parser,
        agent_payloads_parser,
        agent_treatments_parser,
        agent_study_parser,
        agent_utility_parser,
    ):
        operation_parser.add_argument(
            "--authorization",
            required=True,
            choices=("unknown", "permitted", "refused", "deferred", "revoked"),
        )
        operation_parser.add_argument("--json", action="store_true")

    plan_parser = subparsers.add_parser("plan", help="record an inert P10 revision plan")
    plan_parser.add_argument("--workspace", required=True, type=_path)
    plan_parser.add_argument("--opportunity", required=True)
    plan_parser.add_argument("--treatment", required=True)
    plan_parser.add_argument("--proposal", required=True, type=_path)
    plan_parser.add_argument(
        "--authorization",
        required=True,
        choices=("unknown", "permitted", "refused", "deferred", "revoked"),
    )
    plan_parser.add_argument("--json", action="store_true")

    revise_parser = subparsers.add_parser("revise", help="validate and execute a P10 plan")
    revise_parser.add_argument("--workspace", required=True, type=_path)
    revise_parser.add_argument("--plan", required=True)
    revise_parser.add_argument("--authority", required=True)
    revise_parser.add_argument(
        "--source-authorization",
        required=True,
        choices=("unknown", "permitted", "refused", "deferred", "revoked"),
    )
    revise_parser.add_argument("--enforcement-mode", required=True, choices=("active", "shadow"))
    revise_parser.add_argument(
        "--fixture-authorization", required=True, choices=("synthetic", "fully_authorized")
    )
    revise_parser.add_argument("--human-authorized", action="store_true")
    revise_parser.add_argument(
        "--authorization",
        required=True,
        choices=("unknown", "permitted", "refused", "deferred", "revoked"),
    )
    revise_parser.add_argument("--json", action="store_true")

    adapter_parser = subparsers.add_parser(
        "adapter", help="P9 external representation adapter operations"
    )
    adapter_subparsers = adapter_parser.add_subparsers(dest="adapter_command", required=True)
    adapter_probe_parser = adapter_subparsers.add_parser("probe")
    adapter_probe_parser.add_argument("--workspace", required=True, type=_path)
    adapter_probe_parser.add_argument(
        "--adapter", required=True, choices=("samplebrain", "encodec")
    )
    adapter_probe_parser.add_argument("--context", required=True)
    adapter_probe_parser.add_argument("--spec", required=True, type=_path)
    adapter_encode_parser = adapter_subparsers.add_parser("encode")
    adapter_encode_parser.add_argument("--workspace", required=True, type=_path)
    adapter_encode_parser.add_argument(
        "--adapter", required=True, choices=("samplebrain", "encodec")
    )
    adapter_encode_parser.add_argument("--artifact", required=True)
    adapter_encode_parser.add_argument("--aperture", required=True)
    adapter_encode_parser.add_argument("--capture", required=True, type=_path)
    adapter_enumerate_parser = adapter_subparsers.add_parser("enumerate")
    adapter_enumerate_parser.add_argument("--workspace", required=True, type=_path)
    adapter_enumerate_parser.add_argument("--instance", required=True)
    adapter_enumerate_parser.add_argument("--rule", required=True, type=_path)
    adapter_run_parser = adapter_subparsers.add_parser("run")
    adapter_run_parser.add_argument("--workspace", required=True, type=_path)
    adapter_run_parser.add_argument(
        "--operation",
        required=True,
        choices=(
            "refine",
            "address",
            "intervene",
            "decode",
            "support",
            "project",
            "measure",
            "perturb",
            "account",
        ),
    )
    adapter_run_parser.add_argument("--target", required=True, action="append")
    adapter_run_parser.add_argument("--spec", required=True, type=_path)
    for operation_parser in (
        adapter_probe_parser,
        adapter_encode_parser,
        adapter_enumerate_parser,
        adapter_run_parser,
    ):
        operation_parser.add_argument(
            "--authorization",
            required=True,
            choices=("unknown", "permitted", "refused", "deferred", "revoked"),
        )
        operation_parser.add_argument("--json", action="store_true")

    task_parser = subparsers.add_parser("task", help="P6 paired task operations")
    task_subparsers = task_parser.add_subparsers(dest="task_command", required=True)
    task_declare_parser = task_subparsers.add_parser("declare")
    task_declare_parser.add_argument("--workspace", required=True, type=_path)
    task_declare_parser.add_argument("--candidate", required=True)
    task_declare_parser.add_argument("--graph")
    task_declare_parser.add_argument("--spec", required=True, type=_path)
    task_execute_parser = task_subparsers.add_parser("execute")
    task_execute_parser.add_argument("--workspace", required=True, type=_path)
    task_execute_parser.add_argument("--task", required=True)
    task_execute_parser.add_argument("--evidence", required=True, type=_path)

    quanta_parser = subparsers.add_parser("quanta", help="P6 assessment operations")
    quanta_subparsers = quanta_parser.add_subparsers(dest="quanta_command", required=True)
    quanta_assess_parser = quanta_subparsers.add_parser("assess")
    quanta_assess_parser.add_argument("--workspace", required=True, type=_path)
    quanta_assess_parser.add_argument("--candidate", required=True)
    quanta_assess_parser.add_argument("--task", required=True)
    quanta_assess_parser.add_argument("--run", required=True)
    quanta_assess_parser.add_argument("--graph")
    quanta_baseline_parser = quanta_subparsers.add_parser("baseline")
    quanta_baseline_parser.add_argument("--workspace", required=True, type=_path)
    quanta_baseline_parser.add_argument("--assessment", required=True)
    quanta_invalidate_parser = quanta_subparsers.add_parser("invalidate")
    quanta_invalidate_parser.add_argument("--workspace", required=True, type=_path)
    quanta_invalidate_parser.add_argument("--assessment", required=True)
    quanta_invalidate_parser.add_argument("--reason", required=True)
    quanta_invalidate_parser.add_argument("--evidence", required=True, type=_path)
    for operation_parser in (
        task_declare_parser,
        task_execute_parser,
        quanta_assess_parser,
        quanta_baseline_parser,
        quanta_invalidate_parser,
    ):
        operation_parser.add_argument(
            "--authorization", required=True, choices=("permitted", "refused")
        )
        operation_parser.add_argument("--json", action="store_true")

    relation_parser = subparsers.add_parser("relation", help="P7 cross-arm relation operations")
    relation_subparsers = relation_parser.add_subparsers(dest="relation_command", required=True)
    projection_declare_parser = relation_subparsers.add_parser("projection-declare")
    projection_declare_parser.add_argument("--workspace", required=True, type=_path)
    projection_declare_parser.add_argument("--arm", required=True)
    projection_declare_parser.add_argument("--spec", required=True, type=_path)
    comparison_declare_parser = relation_subparsers.add_parser("comparison-declare")
    comparison_declare_parser.add_argument("--workspace", required=True, type=_path)
    comparison_declare_parser.add_argument("--projection", required=True, action="append")
    comparison_declare_parser.add_argument("--spec", required=True, type=_path)
    relation_compare_parser = relation_subparsers.add_parser("compare")
    relation_compare_parser.add_argument("--workspace", required=True, type=_path)
    relation_compare_parser.add_argument("--comparison", required=True)
    relation_compare_parser.add_argument("--source", required=True, action="append")
    relation_compare_parser.add_argument("--target", required=True, action="append")
    relation_compare_parser.add_argument("--evidence", required=True, type=_path)
    relation_invalidate_parser = relation_subparsers.add_parser("invalidate")
    relation_invalidate_parser.add_argument("--workspace", required=True, type=_path)
    relation_invalidate_parser.add_argument("--relation", required=True)
    relation_invalidate_parser.add_argument("--reason", required=True)
    relation_invalidate_parser.add_argument("--evidence", required=True, type=_path)
    for operation_parser in (
        projection_declare_parser,
        comparison_declare_parser,
        relation_compare_parser,
        relation_invalidate_parser,
    ):
        operation_parser.add_argument(
            "--authorization", required=True, choices=("permitted", "refused")
        )
        operation_parser.add_argument("--json", action="store_true")

    transduce_parser = subparsers.add_parser("transduce", help="P8 bounded transduction")
    transduce_subparsers = transduce_parser.add_subparsers(dest="transduce_command", required=True)
    mapping_parser = transduce_subparsers.add_parser("mapping-declare")
    mapping_parser.add_argument("--workspace", required=True, type=_path)
    mapping_parser.add_argument("--context", required=True)
    mapping_parser.add_argument("--spec", required=True, type=_path)
    run_transduction_parser = transduce_subparsers.add_parser("run")
    run_transduction_parser.add_argument("--workspace", required=True, type=_path)
    run_transduction_parser.add_argument(
        "--mode",
        required=True,
        choices=(
            "sonification",
            "desonification",
            "resonification",
            "sonic_transformation",
            "cross_domain_contrast",
        ),
    )
    run_transduction_parser.add_argument("--source", required=True, action="append")
    run_transduction_parser.add_argument("--mapping", required=True)
    run_transduction_parser.add_argument("--parameters", required=True, type=_path)
    for operation_parser in (mapping_parser, run_transduction_parser):
        operation_parser.add_argument(
            "--authorization",
            required=True,
            choices=("unknown", "permitted", "refused", "deferred", "revoked"),
        )
        operation_parser.add_argument("--json", action="store_true")

    policy_parser = subparsers.add_parser("policy", help="P8 governance boundaries")
    policy_subparsers = policy_parser.add_subparsers(dest="policy_command", required=True)
    boundary_parser = policy_subparsers.add_parser("boundary-declare")
    boundary_parser.add_argument("--workspace", required=True, type=_path)
    boundary_parser.add_argument("--context", required=True)
    boundary_parser.add_argument("--spec", required=True, type=_path)
    boundary_parser.add_argument(
        "--authorization",
        required=True,
        choices=("unknown", "permitted", "refused", "deferred", "revoked"),
    )
    boundary_parser.add_argument("--json", action="store_true")

    appeal_parser = subparsers.add_parser("appeal", help="P8 appeal and adjudication")
    appeal_subparsers = appeal_parser.add_subparsers(dest="appeal_command", required=True)
    appeal_open_parser = appeal_subparsers.add_parser("open")
    appeal_open_parser.add_argument("--workspace", required=True, type=_path)
    appeal_open_parser.add_argument("--boundary", required=True)
    appeal_open_parser.add_argument("--appellant", required=True)
    appeal_open_parser.add_argument("--authority", required=True)
    appeal_open_parser.add_argument("--target", required=True)
    appeal_open_parser.add_argument("--spec", required=True, type=_path)
    appeal_adjudicate_parser = appeal_subparsers.add_parser("adjudicate")
    appeal_adjudicate_parser.add_argument("--workspace", required=True, type=_path)
    appeal_adjudicate_parser.add_argument("--case", required=True)
    appeal_adjudicate_parser.add_argument("--authority", required=True)
    appeal_adjudicate_parser.add_argument(
        "--outcome",
        required=True,
        choices=("upheld", "denied", "partial", "escalated", "withdrawn"),
    )
    appeal_adjudicate_parser.add_argument("--evidence", required=True, action="append")
    for operation_parser in (appeal_open_parser, appeal_adjudicate_parser):
        operation_parser.add_argument(
            "--authorization",
            required=True,
            choices=("unknown", "permitted", "refused", "deferred", "revoked"),
        )
        operation_parser.add_argument("--json", action="store_true")

    repair_parser = subparsers.add_parser("repair", help="P8 authorized repair")
    repair_subparsers = repair_parser.add_subparsers(dest="repair_command", required=True)
    repair_apply_parser = repair_subparsers.add_parser("apply")
    repair_apply_parser.add_argument("--workspace", required=True, type=_path)
    repair_apply_parser.add_argument("--case", required=True)
    repair_apply_parser.add_argument("--authority", required=True)
    repair_apply_parser.add_argument(
        "--action",
        required=True,
        choices=("pause", "correct", "revoke", "delete", "restrict", "restore", "release_pause"),
    )
    repair_apply_parser.add_argument("--spec", required=True, type=_path)
    repair_apply_parser.add_argument(
        "--authorization",
        required=True,
        choices=("unknown", "permitted", "refused", "deferred", "revoked"),
    )
    repair_apply_parser.add_argument("--json", action="store_true")

    export_parser = subparsers.add_parser("export", help="create one bounded P8 projection")
    export_parser.add_argument("--workspace", required=True, type=_path)
    export_parser.add_argument("--target", required=True)
    export_parser.add_argument("--boundary", required=True)
    export_parser.add_argument(
        "--disclosure",
        required=True,
        choices=("private", "restricted", "project_internal", "public"),
    )
    export_parser.add_argument("--human-authorized", action="store_true")
    export_parser.add_argument(
        "--authorization",
        required=True,
        choices=("unknown", "permitted", "refused", "deferred", "revoked"),
    )
    export_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.version:
        _print_version(as_json=False)
        return 0
    if arguments.command == "version":
        _print_version(as_json=bool(arguments.json))
        return 0
    if arguments.command == "apparatus" and arguments.apparatus_command == "validate":
        operation = "qste:apparatus-validate/0.1.0"
        try:
            result = declare_apparatus(arguments.workspace, read_json_object(arguments.declaration))
        except ContractError as error:
            result = failure_result(operation, error)
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "aperture" and arguments.aperture_command == "derive":
        operation = "qste:aperture-derive/0.1.0"
        try:
            result = derive_aperture(
                arguments.workspace,
                apparatus_record_id=arguments.apparatus,
                input_artifact_record_id=arguments.input,
                policy=read_json_object(arguments.policy),
            )
        except ContractError as error:
            result = failure_result(operation, error)
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "representation":
        name = cast(str, arguments.representation_command)
        operation = f"qste:{name}/0.1.0"
        try:
            if name == "encode":
                result = representation_encode(
                    arguments.workspace,
                    artifact_record_id=arguments.artifact,
                    aperture_record_id=arguments.aperture,
                    config=read_json_object(arguments.config),
                    authorization_status=arguments.authorization,
                )
            elif name == "enumerate":
                result = representation_enumerate(
                    arguments.workspace,
                    instance_record_id=arguments.instance,
                    candidate_rule=read_json_object(arguments.rule),
                    authorization_status=arguments.authorization,
                )
            elif name == "refine":
                result = representation_refine(
                    arguments.workspace,
                    candidate_record_id=arguments.candidate,
                    procedure=read_json_object(arguments.procedure),
                    authorization_status=arguments.authorization,
                )
            elif name == "support":
                result = representation_support(
                    arguments.workspace,
                    candidate_record_id=arguments.candidate,
                    support_spec=read_json_object(arguments.spec),
                    authorization_status=arguments.authorization,
                )
            elif name == "address":
                result = representation_address(
                    arguments.workspace,
                    candidate_record_id=arguments.candidate,
                    intervention_record_id=arguments.intervention,
                    authorization_status=arguments.authorization,
                )
            elif name == "intervene":
                result = representation_intervene(
                    arguments.workspace,
                    candidate_record_id=arguments.candidate,
                    intervention_record_id=arguments.intervention,
                    mode=arguments.mode,
                    control=arguments.control,
                    authorization_status=arguments.authorization,
                )
            elif name == "decode":
                result = representation_decode(
                    arguments.workspace,
                    target_record_id=arguments.target,
                    authorization_status=arguments.authorization,
                )
            elif name == "project":
                result = representation_project(
                    arguments.workspace,
                    candidate_record_id=arguments.candidate,
                    projection_record_id=arguments.projection,
                    authorization_status=arguments.authorization,
                )
            elif name == "measure":
                result = representation_measure(
                    arguments.workspace,
                    left_candidate_record_id=arguments.left,
                    right_candidate_record_id=arguments.right,
                    metric_spec=read_json_object(arguments.metric),
                    authorization_status=arguments.authorization,
                )
            elif name == "perturb":
                result = representation_perturb(
                    arguments.workspace,
                    instance_record_id=arguments.instance,
                    perturbation_spec=read_json_object(arguments.spec),
                    authorization_status=arguments.authorization,
                )
            else:
                result = representation_account(
                    arguments.workspace,
                    instance_record_id=arguments.instance,
                    authorization_status=arguments.authorization,
                )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "adapter":
        name = cast(str, arguments.adapter_command)
        operation_name = cast(str, arguments.operation) if name == "run" else name
        operation = f"qste:adapter_{operation_name}/0.1.0"
        try:
            if name == "probe":
                result = adapter_probe(
                    arguments.workspace,
                    adapter_id=arguments.adapter,
                    context_record_id=arguments.context,
                    specification=read_json_object(arguments.spec),
                    authorization_status=arguments.authorization,
                )
            elif name == "encode":
                result = adapter_encode(
                    arguments.workspace,
                    adapter_id=arguments.adapter,
                    artifact_record_id=arguments.artifact,
                    aperture_record_id=arguments.aperture,
                    capture=read_json_object(arguments.capture),
                    authorization_status=arguments.authorization,
                )
            elif name == "enumerate":
                result = adapter_enumerate(
                    arguments.workspace,
                    instance_record_id=arguments.instance,
                    candidate_rule=read_json_object(arguments.rule),
                    authorization_status=arguments.authorization,
                )
            else:
                result = adapter_operate(
                    arguments.workspace,
                    operation=arguments.operation,
                    target_record_ids=arguments.target,
                    specification=read_json_object(arguments.spec),
                    authorization_status=arguments.authorization,
                )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "ecosystem":
        name = cast(str, arguments.ecosystem_command)
        operation = f"qste:ecosystem_{'live_loopback' if name == 'live' else name}/0.1.0"
        try:
            if name == "import":
                result = ecosystem_import(
                    arguments.workspace,
                    target_id=arguments.target,
                    context_record_id=arguments.context,
                    payload=read_json_object(arguments.payload),
                    authorization_status=arguments.authorization,
                )
            elif name == "project":
                result = ecosystem_project(
                    arguments.workspace,
                    target_id=arguments.target,
                    context_record_id=arguments.context,
                    payload=read_json_object(arguments.payload),
                    human_authorized=bool(arguments.human_authorized),
                    authorization_status=arguments.authorization,
                )
            elif name == "inspect":
                result = ecosystem_inspect(
                    arguments.workspace,
                    target_id=arguments.target,
                    context_record_id=arguments.context,
                    payload=read_json_object(arguments.payload),
                    authorization_status=arguments.authorization,
                )
            elif name == "live":
                result = ecosystem_live_loopback(
                    arguments.workspace,
                    target_id=arguments.target,
                    context_record_id=arguments.context,
                    authorization_status=arguments.authorization,
                )
            else:
                result = ecosystem_account(
                    arguments.workspace,
                    target_id=arguments.target,
                    context_record_id=arguments.context,
                    authorization_status=arguments.authorization,
                )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "engine":
        name = cast(str, arguments.engine_command)
        operation = f"qste:engine_{'osc_loopback' if name == 'loopback' else name}/0.1.0"
        try:
            if name == "execute":
                result = engine_execute(
                    arguments.workspace,
                    target_id=arguments.target,
                    context_record_id=arguments.context,
                    request=read_json_object(arguments.request),
                    authorization_status=arguments.authorization,
                )
            elif name == "loopback":
                result = engine_loopback(
                    arguments.workspace,
                    target_id=arguments.target,
                    context_record_id=arguments.context,
                    request=read_json_object(arguments.request),
                    authorization_status=arguments.authorization,
                )
            else:
                result = engine_account(
                    arguments.workspace,
                    target_id=arguments.target,
                    context_record_id=arguments.context,
                    authorization_status=arguments.authorization,
                )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "experiment":
        name = cast(str, arguments.experiment_command)
        operation = f"qste:experiment_{name}/0.1.0"
        try:
            if name == "freeze":
                result = experiment_freeze(
                    arguments.workspace,
                    context_record_id=arguments.context,
                    packet=read_json_object(arguments.packet),
                    authorization_status=arguments.authorization,
                )
            elif name == "pilot":
                result = experiment_pilot(
                    arguments.workspace,
                    preparation_record_id=arguments.preparation,
                    evidence=read_json_object(arguments.evidence),
                    authorization_status=arguments.authorization,
                )
            else:
                result = experiment_account(
                    arguments.workspace,
                    context_record_id=arguments.context,
                    authorization_status=arguments.authorization,
                )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "model":
        name = cast(str, arguments.model_command)
        operation = {
            "freeze": "qste:model_program_freeze/0.1.0",
            "dataset": "qste:model_dataset_register/0.1.0",
            "account": "qste:model_research_account/0.1.0",
        }[name]
        try:
            if name == "freeze":
                result = model_program_freeze(
                    arguments.workspace,
                    context_record_id=arguments.context,
                    specification=read_json_object(arguments.program),
                    authorization_status=arguments.authorization,
                )
            elif name == "dataset":
                result = model_dataset_register(
                    arguments.workspace,
                    program_record_id=arguments.program_record,
                    manifest=read_json_object(arguments.manifest),
                    authorization_status=arguments.authorization,
                )
            else:
                result = model_research_account(
                    arguments.workspace,
                    context_record_id=arguments.context,
                    authorization_status=arguments.authorization,
                )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "agent":
        name = cast(str, arguments.agent_command)
        operation = {
            "initialize": "qste:initialize_harness/0.1.0",
            "payloads": "qste:create_information_payloads/0.1.0",
            "treatments": "qste:prepare_revision_treatments/0.1.0",
            "study": "qste:assess_revision_study/0.1.0",
            "utility": "qste:evaluate_agent_utility/0.1.0",
        }[name]
        try:
            if name == "initialize":
                result = agent_initialize(
                    arguments.workspace,
                    governance_boundary_record_id=arguments.boundary,
                    authority_record_id=arguments.authority,
                    source_record_id=arguments.source,
                    completed_run_record_id=arguments.completed_run,
                    predecessor_record_id=arguments.predecessor,
                    specification=read_json_object(arguments.spec),
                    authorization_status=arguments.authorization,
                )
            elif name == "payloads":
                result = agent_payloads(
                    arguments.workspace,
                    assessment_record_id=arguments.assessment,
                    specification=read_json_object(arguments.spec),
                    authorization_status=arguments.authorization,
                )
            elif name == "treatments":
                result = agent_treatments(
                    arguments.workspace,
                    opportunity_record_id=arguments.opportunity,
                    authentic_payload_record_id=arguments.payload,
                    allocation=read_json_object(arguments.allocation),
                    authorization_status=arguments.authorization,
                )
            elif name == "study":
                decisions = read_json_object(arguments.decisions)
                result = agent_study(
                    arguments.workspace,
                    decision_record_ids=cast(dict[str, list[str]], decisions),
                    preregistration=read_json_object(arguments.preregistration),
                    authorization_status=arguments.authorization,
                )
            else:
                result = agent_utility(
                    arguments.workspace,
                    decision_record_id=arguments.decision,
                    evaluation=read_json_object(arguments.evaluation),
                    authorization_status=arguments.authorization,
                )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "plan":
        operation = "qste:plan/0.1.0"
        try:
            result = agent_plan(
                arguments.workspace,
                opportunity_record_id=arguments.opportunity,
                treatment_record_id=arguments.treatment,
                proposal=read_json_object(arguments.proposal),
                authorization_status=arguments.authorization,
            )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "revise":
        operation = "qste:revise/0.1.0"
        try:
            result = agent_revise(
                arguments.workspace,
                plan_record_id=arguments.plan,
                authority_record_id=arguments.authority,
                source_authorization_status=arguments.source_authorization,
                enforcement_mode=arguments.enforcement_mode,
                fixture_authorization=arguments.fixture_authorization,
                human_authorized=bool(arguments.human_authorized),
                authorization_status=arguments.authorization,
            )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "task":
        name = cast(str, arguments.task_command)
        operation = f"qste:{'declare_task' if name == 'declare' else 'execute_task'}/0.1.0"
        try:
            if name == "declare":
                result = task_declare(
                    arguments.workspace,
                    candidate_record_id=arguments.candidate,
                    refinement_graph_record_id=arguments.graph,
                    specification=read_json_object(arguments.spec),
                    authorization_status=arguments.authorization,
                )
            else:
                result = task_execute(
                    arguments.workspace,
                    task_record_id=arguments.task,
                    score_evidence=read_json_object(arguments.evidence),
                    authorization_status=arguments.authorization,
                )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "quanta":
        name = cast(str, arguments.quanta_command)
        operation_name = "invalidate_dependency" if name == "invalidate" else name
        operation = f"qste:{operation_name}/0.1.0"
        try:
            if name == "assess":
                result = quanta_assess(
                    arguments.workspace,
                    candidate_record_id=arguments.candidate,
                    task_record_id=arguments.task,
                    run_record_id=arguments.run,
                    refinement_graph_record_id=arguments.graph,
                    authorization_status=arguments.authorization,
                )
            elif name == "baseline":
                result = quanta_baseline(
                    arguments.workspace,
                    assessment_record_id=arguments.assessment,
                    authorization_status=arguments.authorization,
                )
            else:
                result = quanta_invalidate(
                    arguments.workspace,
                    assessment_record_id=arguments.assessment,
                    invalidation_reason=arguments.reason,
                    evidence=read_json_object(arguments.evidence),
                    authorization_status=arguments.authorization,
                )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "relation":
        name = cast(str, arguments.relation_command)
        operation_name = {
            "projection-declare": "declare_projection",
            "comparison-declare": "declare_comparison",
            "compare": "compare_relations",
            "invalidate": "invalidate_relation",
        }[name]
        operation = f"qste:{operation_name}/0.1.0"
        try:
            if name == "projection-declare":
                result = relation_declare_projection(
                    arguments.workspace,
                    source_arm_record_id=arguments.arm,
                    specification=read_json_object(arguments.spec),
                    authorization_status=arguments.authorization,
                )
            elif name == "comparison-declare":
                result = relation_declare_comparison(
                    arguments.workspace,
                    projection_record_ids=arguments.projection,
                    specification=read_json_object(arguments.spec),
                    authorization_status=arguments.authorization,
                )
            elif name == "compare":
                result = relation_compare(
                    arguments.workspace,
                    comparison_spec_record_id=arguments.comparison,
                    source_candidate_record_ids=arguments.source,
                    target_candidate_record_ids=arguments.target,
                    evidence=read_json_object(arguments.evidence),
                    authorization_status=arguments.authorization,
                )
            else:
                result = relation_invalidate(
                    arguments.workspace,
                    relation_assertion_record_id=arguments.relation,
                    invalidation_reason=arguments.reason,
                    evidence=read_json_object(arguments.evidence),
                    authorization_status=arguments.authorization,
                )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "transduce":
        name = cast(str, arguments.transduce_command)
        operation_name = (
            "declare_mapping" if name == "mapping-declare" else f"transduce_{arguments.mode}"
        )
        operation = f"qste:{operation_name}/0.1.0"
        try:
            if name == "mapping-declare":
                result = mapping_declare(
                    arguments.workspace,
                    context_record_id=arguments.context,
                    specification=read_json_object(arguments.spec),
                    authorization_status=arguments.authorization,
                )
            else:
                result = transduce(
                    arguments.workspace,
                    mode=arguments.mode,
                    source_record_ids=arguments.source,
                    mapping_record_id=arguments.mapping,
                    parameters=read_json_object(arguments.parameters),
                    authorization_status=arguments.authorization,
                )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "policy":
        operation = "qste:declare_governance_boundary/0.1.0"
        try:
            result = governance_declare(
                arguments.workspace,
                context_record_id=arguments.context,
                specification=read_json_object(arguments.spec),
                authorization_status=arguments.authorization,
            )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "appeal":
        name = cast(str, arguments.appeal_command)
        operation = f"qste:{'open_appeal' if name == 'open' else 'adjudicate'}/0.1.0"
        try:
            if name == "open":
                result = appeal_open(
                    arguments.workspace,
                    governance_boundary_record_id=arguments.boundary,
                    appellant_record_id=arguments.appellant,
                    responding_authority_record_id=arguments.authority,
                    target_record_id=arguments.target,
                    specification=read_json_object(arguments.spec),
                    authorization_status=arguments.authorization,
                )
            else:
                result = appeal_adjudicate(
                    arguments.workspace,
                    appeal_case_record_id=arguments.case,
                    authority_record_id=arguments.authority,
                    outcome=arguments.outcome,
                    evidence_record_ids=arguments.evidence,
                    authorization_status=arguments.authorization,
                )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "repair":
        operation = "qste:apply_repair/0.1.0"
        try:
            result = repair_apply(
                arguments.workspace,
                appeal_case_record_id=arguments.case,
                authority_record_id=arguments.authority,
                repair_action=arguments.action,
                specification=read_json_object(arguments.spec),
                authorization_status=arguments.authorization,
            )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    if arguments.command == "export":
        operation = "qste:export/0.1.0"
        try:
            result = export_projection(
                arguments.workspace,
                target_record_id=arguments.target,
                governance_boundary_record_id=arguments.boundary,
                disclosure_status=arguments.disclosure,
                human_authorized=bool(arguments.human_authorized),
                authorization_status=arguments.authorization,
            )
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    handlers: dict[str, tuple[str, Callable[[], dict[str, Any]]]] = {
        "inspect": (
            "qste:inspect/0.3.0",
            lambda: inspect(arguments.workspace, arguments.record),
        ),
        "lineage": (
            "qste:lineage/0.3.0",
            lambda: trace_lineage(
                arguments.workspace,
                arguments.record,
                direction=arguments.direction,
                maximum_depth=arguments.max_depth,
            ),
        ),
        "verify": (
            "qste:verify/0.3.0",
            lambda: verify(workspace=arguments.workspace, bundle_root=arguments.bundle_root),
        ),
        "bundle": (
            "qste:bundle/0.3.0",
            lambda: bundle(
                arguments.workspace,
                read_json_object(arguments.authority),
                bundle_id=arguments.bundle_id,
            ),
        ),
        "ingest": (
            "qste:ingest/0.1.0",
            lambda: ingest(
                arguments.workspace,
                arguments.input,
                kind=arguments.kind,
                apparatus_record_id=arguments.apparatus,
                attributed_origin=arguments.origin,
                rights=read_json_object(arguments.rights),
                retention=read_json_object(arguments.retention),
                authorization_status=arguments.authorization,
                allowed_roots=tuple(arguments.allowed_root),
            ),
        ),
    }
    if arguments.command in handlers:
        operation, handler = handlers[arguments.command]
        try:
            result = handler()
        except ContractError as error:
            result = failure_result(operation, error)
        except Exception as error:  # pragma: no cover - defensive CLI boundary
            result = failure_result(
                operation,
                ContractError(
                    "internal_error", f"unexpected local failure: {type(error).__name__}"
                ),
            )
        return _emit(result, as_json=bool(arguments.json))
    parser.print_help()
    return 0
