#!/usr/bin/env python3
"""Verify that the shared repository and reachable history are sanitized."""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")
if GIT is None:
    raise SystemExit("public repository verifier requires Git")

FORBIDDEN_EXACT = {
    "agents.md",
    "docs/foundation/qste_devplan.md",
    "docs/foundation/qste_repo_v1.md",
    "ontology/0.3.0/qste_devplan.md",
    "ontology/0.3.0/qste_repo_v1.md",
    "authority/sources/readme.md",
    "docs/experiments/readme.md",
    "docs/ethics/readme.md",
}
FORBIDDEN_PREFIXES = (
    "authority/history/",
    "docs/status/",
    "docs/feasibility/",
    "profiles/leonardo-birdcall-example/",
)
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


def _git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        [GIT, "-C", str(ROOT), *arguments],
        check=check,
        capture_output=True,
        text=True,
    )


def _forbidden_path(path_text: str) -> bool:
    normalized = PurePosixPath(path_text).as_posix().casefold().lstrip("./")
    parts = PurePosixPath(normalized).parts
    basename = parts[-1] if parts else ""
    stem = PurePosixPath(basename).stem
    return (
        normalized in FORBIDDEN_EXACT
        or normalized.startswith(FORBIDDEN_PREFIXES)
        or any(part in {"internal", "private"} for part in parts)
        or "audit" in stem
        or ("plan" in stem and basename.endswith((".md", ".txt", ".docx", ".pdf")))
        or (basename.startswith(".env") and basename != ".env.example")
    )


def _candidate_paths() -> tuple[str, ...]:
    result = _git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return tuple(path for path in result.stdout.split("\0") if path)


def _history_paths() -> tuple[str, ...]:
    result = _git("rev-list", "--objects", "--all")
    return tuple(line.split(" ", 1)[1] for line in result.stdout.splitlines() if " " in line)


def _text(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _verify_current_content(paths: tuple[str, ...]) -> int:
    checked = 0
    for relative in paths:
        path = ROOT / relative
        if path.is_symlink() or not path.is_file():
            continue
        value = _text(path)
        if value is None:
            continue
        checked += 1
        if MACHINE_PATH_PATTERN.search(value):
            raise SystemExit(f"machine-specific filesystem route found: {relative}")
        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
            raise SystemExit(f"credential-shaped value found: {relative}")
    return checked


def _verify_historical_content() -> int:
    commits = tuple(line for line in _git("rev-list", "--all").stdout.splitlines() if line)
    patterns = (
        r"/(Users|home)/[A-Za-z0-9._-]+/|[A-Za-z]:[/\\]Users[/\\]|" + "file" + r"://",
        "gh"
        + r"p_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
        + "sk"
        + r"-([A-Za-z0-9]{32,}|(proj|svcacct)-[A-Za-z0-9_-]{40,})|"
        + r"AKIA[0-9A-Z]{16}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY",
    )
    for commit in commits:
        for pattern in patterns:
            result = _git("grep", "-I", "-E", "-n", pattern, commit, "--", ".", check=False)
            if result.returncode == 0:
                raise SystemExit(f"sensitive content found in reachable commit {commit}")
            if result.returncode not in {1}:
                raise SystemExit(f"cannot scan reachable commit {commit}: {result.stderr.strip()}")
    return len(commits)


def _verify_symlinks(paths: tuple[str, ...]) -> int:
    checked = 0
    resolved_root = ROOT.resolve(strict=True)
    for relative in paths:
        path = ROOT / relative
        if not path.is_symlink():
            continue
        checked += 1
        resolved = path.resolve(strict=True)
        if resolved != resolved_root and resolved_root not in resolved.parents:
            raise SystemExit(f"tracked symlink escapes repository: {relative}")
    return checked


def main() -> int:
    if _git("rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        raise SystemExit("public repository verifier requires a Git worktree")
    paths = _candidate_paths()
    forbidden = sorted(path for path in paths if _forbidden_path(path))
    historical_forbidden = sorted(path for path in _history_paths() if _forbidden_path(path))
    if forbidden:
        raise SystemExit(f"private or internal path is present: {forbidden[0]}")
    if historical_forbidden:
        raise SystemExit(
            f"private or internal path is reachable in Git history: {historical_forbidden[0]}"
        )
    checked_text = _verify_current_content(paths)
    commits = _verify_historical_content()
    symlinks = _verify_symlinks(paths)
    print(
        json.dumps(
            {
                "current_paths": len(paths),
                "history_commits": commits,
                "history_paths": len(_history_paths()),
                "status": "passed",
                "symlinks": symlinks,
                "text_files": checked_text,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
