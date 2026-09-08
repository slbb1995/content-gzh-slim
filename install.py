#!/usr/bin/env python3
"""Create-only installer for the self-contained Content 公众号 Slim package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
SKILLS = (
    "content-gzh-slim",
    "content-gzh-analyzer",
    "content-gzh-context-retriever",
    "content-gzh-writer",
    "content-gzh-headline",
    "content-gzh-distribution-pack",
    "content-gzh-cover",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))


def _package_manifest(root: Path) -> dict:
    files = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "PACKAGE-MANIFEST.json":
            continue
        files[path.relative_to(root).as_posix()] = _sha(path)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    return {
        "schema_version": 1,
        "package": f"content-gzh-slim-{(ROOT / 'VERSION').read_text(encoding='utf-8').strip()}",
        "source_revision": revision,
        "source_revision_semantics": "base commit; exact installed bytes are pinned in files",
        "skills": list(SKILLS),
        "public_entry": "content-gzh-slim",
        "internal_skill_count": 6,
        "human_gate_count": 2,
        "reviewer_count": 0,
        "credentials_included": False,
        "customer_data_included": False,
        "files": files,
    }


def _build(destination: Path) -> None:
    _copy(ROOT / "runtime", destination / "runtime")
    _copy(ROOT / "schemas", destination / "schemas")
    skill_root = destination / ".agents" / "skills"
    skill_root.mkdir(parents=True)
    for name in SKILLS:
        _copy(ROOT / "skills" / name, skill_root / name)
    bin_root = destination / "bin"
    bin_root.mkdir()
    shutil.copy2(ROOT / "scripts" / "content-gzh-slim", bin_root / "content-gzh-slim")
    (bin_root / "content-gzh-slim").chmod(0o755)
    manifest = _package_manifest(destination)
    (destination / "PACKAGE-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _same_package(left: Path, right: Path) -> bool:
    try:
        left_manifest = json.loads((left / "PACKAGE-MANIFEST.json").read_text(encoding="utf-8"))
        right_manifest = json.loads((right / "PACKAGE-MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return left_manifest == right_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Content 公众号 Slim without overwriting local drift")
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--package-name", default="content-gzh-slim-main")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args(argv)
    verified = subprocess.run([sys.executable, "-B", str(ROOT / "tools" / "verify.py")], cwd=ROOT, check=False)
    if verified.returncode != 0:
        print("release verification failed; nothing installed", file=sys.stderr)
        return 2
    skills_root = args.codex_home.expanduser().resolve() / "skills"
    packages = skills_root / ".packages"
    packages.mkdir(parents=True, exist_ok=True)
    target = packages / args.package_name
    with tempfile.TemporaryDirectory(prefix="content-gzh-install-", dir=packages) as directory:
        candidate = Path(directory) / args.package_name
        candidate.mkdir()
        _build(candidate)
        if target.exists() or target.is_symlink():
            if not target.is_dir() or target.is_symlink() or not _same_package(candidate, target):
                print(f"existing package differs; back it up before retrying: {target}", file=sys.stderr)
                return 2
        else:
            os.replace(candidate, target)
    if args.activate:
        for name in SKILLS:
            link = skills_root / name
            wanted = target / ".agents" / "skills" / name
            if link.exists() or link.is_symlink():
                if not link.is_symlink() or link.resolve() != wanted.resolve():
                    print(f"active Skill differs; refusing to overwrite: {link}", file=sys.stderr)
                    return 2
                continue
            link.symlink_to(os.path.relpath(wanted, skills_root), target_is_directory=True)
    probe = subprocess.run([sys.executable, "-B", str(target / "bin" / "content-gzh-slim"), "probe"], check=False)
    return probe.returncode


if __name__ == "__main__":
    raise SystemExit(main())
