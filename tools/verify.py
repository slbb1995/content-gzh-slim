#!/usr/bin/env python3
"""Verify the standalone Content 公众号 Slim release."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SKILLS = {"content-gzh-slim", "content-gzh-analyzer", "content-gzh-context-retriever", "content-gzh-writer", "content-gzh-headline", "content-gzh-distribution-pack"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_utf8(arguments: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a bundled Python entrypoint with deterministic output decoding."""
    return subprocess.run(
        arguments,
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )


def main() -> int:
    manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if manifest.get("schema_version") != "content-gzh-slim-release-v1" or manifest.get("package") != {"id": "content-gzh-slim", "version": version}:
        raise RuntimeError("release manifest identity differs from VERSION")
    runtime = manifest.get("runtime", {})
    files = runtime.get("files", [])
    if runtime.get("file_count") != len(files) or runtime.get("skill_count") != 6 or set(runtime.get("skills", [])) != SKILLS:
        raise RuntimeError("release manifest file or Skill budget is invalid")
    for item in files:
        path = ROOT / item["path"]
        if not path.is_file() or path.is_symlink() or path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise RuntimeError(f"release file mismatch: {item['path']}")
    actual_skills = {path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")}
    if actual_skills != SKILLS:
        raise RuntimeError("repository Skill set differs from release manifest")
    for line in (ROOT / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split(maxsplit=1)
        path = ROOT / relative.strip()
        if not path.is_file() or path.is_symlink() or sha256(path) != expected:
            raise RuntimeError(f"checksum mismatch: {relative}")
    forbidden = [path for path in ROOT.rglob("*") if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"}]
    if forbidden:
        raise RuntimeError(f"generated Python files found: {forbidden}")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    tests = _run_utf8([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"], env=env)
    if tests.returncode != 0:
        raise RuntimeError("tests failed:\n" + tests.stdout + tests.stderr)
    cli = _run_utf8([sys.executable, "-B", str(ROOT / "scripts" / "content-gzh-slim"), "--help"], env=env)
    if cli.returncode != 0 or "content-gzh-slim installed-host runtime" not in cli.stdout:
        raise RuntimeError("CLI smoke test failed")
    print(f"PASS: Content 公众号 Slim {version}, 6 skills / {len(files)} deliverable files verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
