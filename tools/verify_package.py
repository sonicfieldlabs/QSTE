#!/usr/bin/env python3
"""Verify wheel/sdist completeness and public-distribution hygiene."""

from __future__ import annotations

import json
import re
import stat
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
MACHINE_PATH_PATTERN = re.compile(
    r"/(?:Users|home)/[A-Za-z0-9._-]+/|[A-Za-z]:[\\/]Users[\\/]|" + "file" + r"://",
    re.IGNORECASE,
)
SECRET_PATTERNS = (
    re.compile("gh" + r"p_[A-Za-z0-9]{20,}"),
    re.compile("github" + r"_pat_[A-Za-z0-9_]{20,}"),
    re.compile("sk" + r"-(?:[A-Za-z0-9]{32,}|(?:proj|svcacct)-[A-Za-z0-9_-]{40,})"),
    re.compile("AK" + r"IA[0-9A-Z]{16}"),
    re.compile("BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY"),
)
SDIST_ROOTS = (
    "authority",
    "conformance",
    "docs",
    "environments",
    "examples",
    "fixtures",
    "ontology",
    "profiles",
    "schemas",
    "skills",
    "spec",
    "src",
    "tests",
    "tools",
)
SDIST_TOP_LEVEL = {
    ".gitattributes",
    ".python-version",
    "CONTRIBUTING.md",
    "LICENSE",
    "LICENSES.md",
    "Makefile",
    "README.md",
    "SECURITY.md",
    "pyproject.toml",
    "uv.lock",
}


def _forbidden_member(path_text: str) -> bool:
    normalized = PurePosixPath(path_text).as_posix().casefold()
    parts = PurePosixPath(normalized).parts
    basename = parts[-1] if parts else ""
    stem = PurePosixPath(basename).stem
    return (
        basename == "agents.md"
        or any(part in {"internal", "private"} for part in parts)
        or "audit" in stem
        or ("plan" in stem and basename.endswith((".md", ".txt", ".docx", ".pdf")))
        or (basename.startswith(".env") and basename != ".env.example")
        or "qste_devplan" in normalized
        or "qste_repo_v1" in normalized
        or "/authority/history/" in f"/{normalized}/"
        or "/docs/status/" in f"/{normalized}/"
    )


def _source_wheel_content() -> dict[str, bytes]:
    return {
        f"qste/{path.relative_to(ROOT / 'src/qste').as_posix()}": path.read_bytes()
        for path in (ROOT / "src/qste").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and not path.name.endswith(".pyc")
    }


def _mapped_content(source: Path, destination: str) -> dict[str, bytes]:
    return {
        f"{destination}/{path.relative_to(source).as_posix()}": path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }


def _source_sdist_members() -> set[str]:
    members = set(SDIST_TOP_LEVEL)
    for root_name in SDIST_ROOTS:
        root = ROOT / root_name
        members.update(
            path.relative_to(ROOT).as_posix()
            for path in root.rglob("*")
            if (path.is_file() or path.is_symlink())
            and "__pycache__" not in path.parts
            and not path.name.endswith(".pyc")
        )
    return members


def _source_sdist_content() -> dict[str, bytes]:
    content = {
        name: (ROOT / name).read_bytes()
        for name in SDIST_TOP_LEVEL
        if (ROOT / name).is_file() and not (ROOT / name).is_symlink()
    }
    for root_name in SDIST_ROOTS:
        root = ROOT / root_name
        content.update(
            {
                path.relative_to(ROOT).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and "__pycache__" not in path.parts
                and not path.name.endswith(".pyc")
            }
        )
    return content


def _verify_content(name: str, data: bytes) -> None:
    if b"\0" in data:
        return
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    if MACHINE_PATH_PATTERN.search(value):
        raise SystemExit(f"machine-specific filesystem route packaged in {name}")
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        raise SystemExit(f"credential-shaped value packaged in {name}")


def _verify_member_names(names: Iterable[str], archive: str) -> None:
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise SystemExit(f"unsafe archive member in {archive}: {name}")
        if _forbidden_member(name):
            raise SystemExit(f"private or internal member packaged in {archive}: {name}")


def _resolve_archive_link(member_name: str, link_name: str) -> str:
    if "\\" in link_name or PurePosixPath(link_name).is_absolute():
        raise SystemExit(f"unsafe archive link target: {member_name}")
    combined = PurePosixPath(member_name).parent / link_name
    resolved: list[str] = []
    for part in combined.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not resolved:
                raise SystemExit(f"archive link escapes its root: {member_name}")
            resolved.pop()
        else:
            resolved.append(part)
    return "/".join(resolved)


def main() -> int:
    wheels = sorted(DIST.glob("qste-*.whl"))
    sdists = sorted(DIST.glob("qste-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit("package verifier requires exactly one QSTE wheel and one sdist")

    expected_wheel_content = _source_wheel_content()
    expected_wheel_content.update(
        _mapped_content(ROOT / "schemas/0.3.0", "qste/contracts/schemas/0.3.0")
    )
    expected_wheel_content.update(
        _mapped_content(ROOT / "conformance", "qste/contracts/conformance")
    )
    expected_wheel_content.update(
        _mapped_content(ROOT / "skills/qste-inspection", "qste/contracts/skills/qste-inspection")
    )
    expected_wheel_content.update(
        _mapped_content(ROOT / "profiles/adapters", "qste/contracts/profiles/adapters")
    )
    expected_wheel_content.update(
        _mapped_content(ROOT / "profiles/agents", "qste/contracts/profiles/agents")
    )
    required = set(expected_wheel_content)

    with zipfile.ZipFile(wheels[0]) as archive:
        wheel_names = set(archive.namelist())
        missing = sorted(required - wheel_names)
        if missing:
            raise SystemExit(f"wheel omits required member: {missing[0]}")
        _verify_member_names(wheel_names, wheels[0].name)
        stale = sorted(
            name for name, data in expected_wheel_content.items() if archive.read(name) != data
        )
        if stale:
            raise SystemExit(f"wheel member differs from source: {stale[0]}")
        for info in archive.infolist():
            if stat.S_ISLNK(info.external_attr >> 16):
                raise SystemExit(f"wheel contains a symbolic link: {info.filename}")
            if not info.is_dir():
                _verify_content(info.filename, archive.read(info))

    with tarfile.open(sdists[0], mode="r:gz") as archive:
        all_members = archive.getmembers()
        sdist_names = {member.name for member in all_members}
        _verify_member_names(sdist_names, sdists[0].name)
        roots = {PurePosixPath(name).parts[0] for name in sdist_names if name}
        if len(roots) != 1:
            raise SystemExit("source distribution must have one archive root")
        archive_root = next(iter(roots))
        relative_names = {
            PurePosixPath(name).relative_to(archive_root).as_posix()
            for name in sdist_names
            if name != archive_root
        }
        missing_sdist = sorted(_source_sdist_members() - relative_names)
        if missing_sdist:
            raise SystemExit(f"source distribution omits required member: {missing_sdist[0]}")
        expected_sdist_content = _source_sdist_content()
        for name, data in expected_sdist_content.items():
            member = archive.getmember(f"{archive_root}/{name}")
            handle = archive.extractfile(member)
            if handle is None or handle.read() != data:
                raise SystemExit(f"source distribution member differs from source: {name}")
        for member in all_members:
            if member.issym() or member.islnk():
                target = _resolve_archive_link(member.name, member.linkname)
                if target not in sdist_names:
                    raise SystemExit(f"archive link target is absent: {member.name}")
                continue
            if not (member.isfile() or member.isdir()):
                raise SystemExit(f"source distribution contains a special member: {member.name}")
            if not member.isfile():
                continue
            handle = archive.extractfile(member)
            if handle is not None:
                _verify_content(member.name, handle.read())

    print(
        json.dumps(
            {
                "required_wheel_members": len(required),
                "required_sdist_members": len(_source_sdist_members()),
                "sdist_members": len(sdist_names),
                "status": "passed",
                "wheel": wheels[0].name,
                "wheel_members": len(wheel_names),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
