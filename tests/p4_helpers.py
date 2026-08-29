from __future__ import annotations

from typing import Any


def apparatus_declaration(*, calibrated: bool = False) -> dict[str, Any]:
    frequency: dict[str, Any] = {"status": "uncalibrated"}
    level: dict[str, Any] = {"status": "uncalibrated"}
    if calibrated:
        frequency = {
            "status": "calibrated",
            "evidence": ["calibration://frequency/fixture"],
            "range_hz": [5.0, 40_000.0],
        }
        level = {
            "status": "calibrated",
            "evidence": ["calibration://level/fixture"],
            "units": "dB_SPL",
            "reference_pa": 0.00002,
            "uncertainty_db": 0.5,
        }
    return {
        "apparatus_version": "p4-test/0.1",
        "configuration": {"execution": "local_offline"},
        "acquisition_surface": {
            "media_kinds": [
                "audio",
                "json_observations",
                "csv_observations",
                "text",
                "model_observations",
            ],
            "timebase": {
                "kind": "sample_clock_or_atemporal",
                "sample_rates_hz": [48_000, 96_000],
            },
            "channel_map": [
                {"source_index": 0, "label": "channel_1"},
                {"source_index": 1, "label": "channel_2"},
            ],
            "calibration": {
                "frequency": frequency,
                "level": level,
                "time": {"status": "uncalibrated"},
            },
        },
        "computation_surface": {
            "numeric_dtypes": ["float32", "float64"],
            "preprocessing_operations": [
                "decode",
                "resample",
                "normalize",
                "parse_observations",
            ],
        },
        "action_surface": {
            "permitted_operations": [
                "ingest",
                "inspect",
                "lineage",
                "verify",
                "bundle",
                "decode",
                "resample",
                "normalize",
            ],
            "network_access": False,
        },
        "authorization_status": "permitted",
    }


RIGHTS = {"use": "research", "redistribution": "prohibited"}
RETENTION = {"mode": "retain", "redistribution": "prohibited"}
