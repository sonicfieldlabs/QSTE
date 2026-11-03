"""Verify a non-activating dependency candidate, without loading an EnCodec model."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import socket
import tempfile
import tomllib
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "environments/encodec-successor/0.2"
EXPECTED = {"encodec": "0.1.1", "torch": "2.13.0", "torchaudio": "2.11.0", "torchcodec": "0.17.0"}


def verify_candidate() -> list[dict]:
    target = json.loads((CANDIDATE / "compatibility-target.json").read_text())
    assert target["candidate_id"] == "qste-encodec-environment/0.2"
    assert target["execution_mode"] == "dependency_qualification_only"
    assert target["adapter_activation_authorized"] is False
    assert target["checkpoint_download_authorized"] is False
    assert target["model_execution_authorized"] is False
    assert target["checkpoint_license_status"] == "unresolved_checkpoint_license_not_declared"
    assert target["environment_lock"]["path"] == "environments/encodec-successor/0.2/uv.lock"
    assert (
        target["environment_lock"]["sha256"]
        == hashlib.sha256((CANDIDATE / "uv.lock").read_bytes()).hexdigest()
    )
    assert set(target["frozen_reference_sha256"]) == {
        "environments/encodec/pyproject.toml",
        "environments/encodec/uv.lock",
        "profiles/adapters/encodec/0.1/compatibility-target.json",
        "profiles/adapters/encodec/0.1/checkpoint-manifest.json",
    }
    for name, digest in target["frozen_reference_sha256"].items():
        file = (ROOT / name).resolve(strict=True)
        assert file.is_relative_to(ROOT)
        assert hashlib.sha256(file.read_bytes()).hexdigest() == digest
    assert target["frozen_reference_sha256"]["environments/encodec/uv.lock"] == (
        "f19aa296e4fed10bbb018cfc950280adf86b1f4e5a0b3246f7e70abe3f9612c3"
    )
    checkpoint = json.loads(
        (ROOT / "profiles/adapters/encodec/0.1/checkpoint-manifest.json").read_text()
    )
    assert checkpoint["availability"] == "unavailable"
    assert checkpoint["download_authorized"] is False
    assert checkpoint["execution_authorized"] is False
    assert checkpoint["model_loaded"] is False
    locked = tomllib.loads((CANDIDATE / "uv.lock").read_text())
    versions = {package["name"]: package["version"] for package in locked["package"]}
    assert {name: versions[name] for name in EXPECTED} == EXPECTED
    assert locked["requires-python"] == "==3.12.*"
    return locked["package"]


def verify_registry(packages: list[dict]) -> None:
    def check(package: dict) -> None:
        if package["source"].get("virtual") is not None:
            return
        assert package["source"] == {"registry": "https://pypi.org/simple"}
        name, version = package["name"], package["version"]
        url = f"https://pypi.org/pypi/{quote(name, safe='')}/{quote(version, safe='')}/json"
        with urllib.request.urlopen(url, timeout=30) as response:  # nosec B310
            info = json.load(response)
        assert not info.get("vulnerabilities"), f"Registry advisory requires review: {name}"
        files = {item["url"]: "sha256:" + item["digests"]["sha256"] for item in info["urls"]}
        for artifact in [
            *package.get("wheels", []),
            *([package["sdist"]] if "sdist" in package else []),
        ]:
            assert files.get(artifact["url"]) == artifact["hash"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(check, packages))
    print(json.dumps({"registry_packages": len(packages) - 1, "advisory_matches": 0}))


def verify_native() -> None:
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert {name: metadata.version(name) for name in EXPECTED} == EXPECTED
    # Dependency installation and registry checks precede this block. No network
    # or pretrained checkpoint is allowed during the synthetic native probe.
    blocked = AssertionError("Network/model download is outside dependency qualification")
    with patch.object(socket.socket, "connect", side_effect=blocked):
        torch = importlib.import_module("torch")
        with patch("torch.hub.load_state_dict_from_url", side_effect=blocked):
            torchaudio = importlib.import_module("torchaudio")
            decoder = importlib.import_module("torchcodec.decoders").AudioDecoder
            encodec = importlib.import_module("encodec")
            assert callable(encodec.EncodecModel)
            signal = (torch.sin(torch.arange(1600) * 0.1) * 0.25).unsqueeze(0)
            with tempfile.TemporaryDirectory(prefix="qste-native-") as directory:
                file = Path(directory) / "synthetic.wav"
                torchaudio.save(str(file), signal, 16000)
                decoded, rate = torchaudio.load(str(file))
                assert rate == 16000 and tuple(decoded.shape) == (1, 1600)
                assert torch.isfinite(decoded).all()
                assert torch.max(torch.abs(decoded - signal)).item() < 0.001
                output = decoder(str(file)).get_all_samples()
                assert output.sample_rate == 16000 and tuple(output.data.shape) == (1, 1600)
                assert torch.isfinite(output.data).all()
                assert torch.max(torch.abs(output.data - signal)).item() < 0.001
    print(
        json.dumps(
            {
                "native_versions": EXPECTED,
                "synthetic_frames": 1600,
                "encodec_model_constructed": False,
                "checkpoint_loaded": False,
                "adapter_activated": False,
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", action="store_true")
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    packages = verify_candidate()
    if args.registry:
        verify_registry(packages)
    if args.native:
        verify_native()
    print("Non-activating EnCodec dependency candidate verified; model gates remain closed.")


if __name__ == "__main__":
    main()
