#!/usr/bin/env python3
"""Execute deterministic P13 skill, MCP, and workbench checks."""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any

from qste.core import loads_json
from qste.interfaces.contracts import CONFORMANCE_PROFILE, INTERFACE_PROFILE

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "conformance/p13-interfaces/0.1/profile.json"
FIXTURE = ROOT / "fixtures/p13-interfaces/0.1/interface-policy.json"
SKILL = ROOT / "skills/qste-inspection"
TESTS = (
    "tests/test_p13_interfaces.py",
    "tests/test_p13_mcp.py",
    "tests/test_p13_workbench.py",
)


def _object(path: Path) -> dict[str, Any]:
    value = loads_json(path.read_bytes())
    if not isinstance(value, dict):
        raise SystemExit(f"{path.relative_to(ROOT)} is not an object")
    return value


def main() -> int:
    profile = _object(PROFILE)
    fixture = _object(FIXTURE)
    if profile.get("profile_id") != CONFORMANCE_PROFILE:
        raise SystemExit("invalid P13 conformance profile")
    if profile.get("interface_profile") != INTERFACE_PROFILE:
        raise SystemExit("invalid P13 interface profile")
    if len(profile.get("gates", [])) != 12:
        raise SystemExit("P13 conformance gate set differs")
    if fixture.get("profile_id") != INTERFACE_PROFILE:
        raise SystemExit("P13 fixture profile differs")
    if fixture.get("transport") != {
        "default": "stdio",
        "streamable_http_host": "127.0.0.1",
        "dns_rebinding_protection": True,
        "remote_binding": False,
    }:
        raise SystemExit("P13 transport boundary differs")
    if fixture.get("mutation_gate", {}).get("default_enabled") is not False:
        raise SystemExit("P13 mutations are not disabled by default")
    if any(fixture.get("boundaries", {}).values()):
        raise SystemExit("P13 external boundary differs")
    if not version("mcp").startswith("2."):
        raise SystemExit("P13 requires the supported MCP 2.x line")

    skill_text = (SKILL / "SKILL.md").read_text()
    agent_text = (SKILL / "agents/openai.yaml").read_text()
    if (
        not skill_text.startswith("---\nname: qste-inspection\n")
        or "description:" not in skill_text.split("---", 2)[1]
        or "TODO" in skill_text
        or "$qste-inspection" not in agent_text
    ):
        raise SystemExit("P13 skill package is incomplete")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", *TESTS], cwd=ROOT)
    if result.returncode != 0:
        return result.returncode
    print(
        json.dumps(
            {
                "gate_count": len(profile["gates"]),
                "mcp_sdk": version("mcp"),
                "profile_id": profile["profile_id"],
                "skill": profile["skill_profile"],
                "status": "passed",
                "tool_count": len(fixture["tools"]["read"]) + len(fixture["tools"]["mutating"]),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
