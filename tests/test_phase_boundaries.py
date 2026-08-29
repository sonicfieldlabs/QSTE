from __future__ import annotations

import importlib
from typing import Protocol, cast

import pytest


class PlannedModule(Protocol):
    CAPABILITY_STATUS: str
    FIRST_PHASE: str


PLANNED_MODULES = {
    "qste.core": "P2",
    "qste.storage": "P3",
    "qste.ingress": "P4",
    "qste.runtime": "P3",
    "qste.representations": "P5",
    "qste.quanta": "P6",
    "qste.relations": "P7",
    "qste.transduction": "P8",
    "qste.policy": "P8",
    "qste.agent": "P10",
    "qste.adapters": "P9",
    "qste.interfaces": "P13",
}


@pytest.mark.parametrize(("module_name", "first_phase"), PLANNED_MODULES.items())
def test_planned_modules_report_their_exact_phase_boundary(
    module_name: str, first_phase: str
) -> None:
    module = cast(PlannedModule, importlib.import_module(module_name))
    capability_status = module.CAPABILITY_STATUS
    declared_phase = module.FIRST_PHASE
    if module_name in {
        "qste.core",
        "qste.storage",
        "qste.ingress",
        "qste.representations",
        "qste.quanta",
        "qste.relations",
        "qste.transduction",
        "qste.policy",
        "qste.adapters",
        "qste.agent",
        "qste.interfaces",
    }:
        expected_status = "available"
    elif module_name == "qste.runtime":
        expected_status = "degraded"
    else:
        expected_status = "unavailable"
    assert capability_status == expected_status
    assert declared_phase == first_phase
