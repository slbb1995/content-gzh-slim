#!/usr/bin/env python3
"""Build and optionally install a privacy-scanned P7 candidate bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = (
    "content-gzh-slim",
    "content-gzh-analyzer",
    "content-gzh-context-retriever",
    "content-gzh-writer",
    "content-gzh-headline",
    "content-gzh-distribution-pack",
)
TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ""}
FORBIDDEN_TEXT = (
    re.compile(r"/Users/[^/\s]+/"),
    re.compile(r"\brun_[0-9a-f]{20,}\b"),
    re.compile(r"\b(?:access_token|refresh_token|app_secret)\b", re.I),
    re.compile(r"xhslink\.cn", re.I),
)


def _revision() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def _scan(root: Path) -> list[str]:
    failures: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in FORBIDDEN_TEXT:
            if pattern.search(text):
                failures.append(f"{path.relative_to(root)} matches {pattern.pattern}")
    return failures


def _manifest(root: Path, revision: str) -> dict:
    files = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "PACKAGE-MANIFEST.json":
            continue
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "schema_version": 1,
        "package": "content-gzh-slim-p7-candidate",
        "source_revision": revision,
        "skills": list(SKILLS),
        "public_entry": "content-gzh-slim",
        "internal_skill_count": 5,
        "human_gate_count": 2,
        "reviewer_count": 0,
        "credentials_included": False,
        "customer_data_included": False,
        "files": files,
    }


def _same_tree(left: Path, right: Path) -> bool:
    if not left.is_dir() or not right.is_dir() or left.is_symlink() or right.is_symlink():
        return False
    left_files = {path.relative_to(left).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in left.rglob("*") if path.is_file()}
    right_files = {path.relative_to(right).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in right.rglob("*") if path.is_file()}
    return left_files == right_files


def _can_symlink(parent: Path, target: Path) -> bool:
    if os.name != "nt":
        return True
    probe = parent / f".content-gzh-link-probe-{uuid.uuid4().hex}"
    try:
        probe.symlink_to(target, target_is_directory=True)
        return probe.is_symlink() and probe.resolve() == target.resolve()
    except OSError:
        return False
    finally:
        if probe.is_symlink() or probe.exists():
            probe.unlink(missing_ok=True)


def _install(candidate: Path, project: Path) -> Path:
    project = project.expanduser().resolve()
    if not (project / ".git").is_dir():
        raise ValueError("project install target must be a Git repository")
    agents = project / ".agents"
    agents.mkdir(exist_ok=True)
    link = agents / "skills"
    expected = candidate / ".agents" / "skills"
    if link.exists() or link.is_symlink():
        if not ((link.is_symlink() and link.resolve() == expected.resolve()) or _same_tree(link, expected)):
            raise ValueError("project .agents/skills already exists with another target")
        return link
    if _can_symlink(agents, expected):
        relative = os.path.relpath(expected, agents)
        link.symlink_to(relative, target_is_directory=True)
    else:
        staging = agents / f".content-gzh-skills-{uuid.uuid4().hex}"
        try:
            _copy_tree(expected, staging)
            os.replace(staging, link)
        finally:
            if staging.exists() or staging.is_symlink():
                shutil.rmtree(staging, ignore_errors=True)
    return link


def main() -> int:
    parser = argparse.ArgumentParser(description="Build content-gzh-slim P7 candidate")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--install-project", type=Path)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        print("candidate output already exists; refusing to replace it", file=sys.stderr)
        return 2
    try:
        output.mkdir(parents=True)
        _copy_tree(ROOT / "runtime", output / "runtime")
        _copy_tree(ROOT / "schemas", output / "schemas")
        skill_root = output / ".agents" / "skills"
        skill_root.mkdir(parents=True)
        for name in SKILLS:
            _copy_tree(ROOT / "skills" / name, skill_root / name)
        bin_root = output / "bin"
        bin_root.mkdir()
        shutil.copy2(ROOT / "scripts" / "content-gzh-slim", bin_root / "content-gzh-slim")
        (bin_root / "content-gzh-slim").chmod(0o755)
        failures = _scan(output)
        if failures:
            raise ValueError("privacy scan failed: " + "; ".join(failures))
        manifest = _manifest(output, _revision())
        (output / "PACKAGE-MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        link = _install(output, args.install_project) if args.install_project else None
        print(
            json.dumps(
                {
                    "ok": True,
                    "candidate": str(output),
                    "installed_skill_link": str(link) if link else None,
                    "skill_count": len(SKILLS),
                    "privacy_scan": "pass",
                    "credentials_copied": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"P7 candidate build failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
