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
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    return {
        "schema_version": 1,
        "package": f"content-gzh-slim-{(ROOT / 'VERSION').read_text(encoding='utf-8').strip()}",
        "source_revision": revision,
        "source_revision_semantics": "base commit; exact installed bytes are pinned in files",
        "skill_root": ".agents/skills",
        "cover_required": True,
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
    from runtime.path_boundary import PathBoundary
    destination = PathBoundary(destination).root
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("build destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
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
    # Keep the POSIX launcher everywhere. Windows gets a .cmd shim that
    # explicitly invokes Python rather than opening an extensionless file.
    if os.name == "nt":
        shutil.copy2(ROOT / "scripts" / "content-gzh-slim.cmd", bin_root / "content-gzh-slim.cmd")
    # A copied public Skill must remain self-contained on hosts without symlink privilege.
    shutil.copyfile(ROOT / "skills" / "content-gzh-slim" / "SKILL.md", destination / "SKILL.md")
    _copy(ROOT / "skills" / "content-gzh-slim" / "references", destination / "references")
    for name in ("VERSION", "README.md", "LICENSE", "requirements.txt"):
        shutil.copyfile(ROOT / name, destination / name)
    manifest = _package_manifest(destination)
    (destination / "PACKAGE-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _verify_package(destination)


def _verify_package(root: Path) -> dict:
    from runtime.path_boundary import PathBoundary
    boundary = PathBoundary(root)
    manifest = json.loads((boundary.root / "PACKAGE-MANIFEST.json").read_text(encoding="utf-8"))
    if set(manifest.get("skills", [])) != set(SKILLS):
        raise ValueError("package must contain exactly seven Skills")
    actual = {p.relative_to(boundary.root).as_posix() for p in boundary.root.rglob("*") if p.is_file() and p.name != "PACKAGE-MANIFEST.json"}
    if actual != set(manifest["files"]):
        raise ValueError("package file set differs from manifest")
    for relative, expected in manifest["files"].items():
        if _sha(boundary.child(relative)) != expected:
            raise ValueError("package file checksum mismatch: " + relative)
    return manifest


def _activate(skills_root: Path, package: Path) -> None:
    from runtime.path_boundary import PathBoundary
    boundary = PathBoundary(skills_root)
    _verify_package(package)
    wanted = {name: package if name == "content-gzh-slim" else package / ".agents" / "skills" / name for name in SKILLS}
    for name, source in wanted.items():
        target = boundary.child(name)
        if target.exists():
            actual = {p.relative_to(target).as_posix(): _sha(p) for p in target.rglob("*") if p.is_file()}
            expected = {p.relative_to(source).as_posix(): _sha(p) for p in source.rglob("*") if p.is_file()}
            if actual != expected:
                raise ValueError("active Skill differs; refusing overwrite: " + name)
    boundary.root.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for name, source in wanted.items():
            target = boundary.child(name)
            if target.exists():
                continue
            with tempfile.TemporaryDirectory(prefix=".gzh-stage-", dir=boundary.root) as directory:
                stage = Path(directory) / "skill"
                _copy(source, stage)
                os.replace(stage, target)
                created.append(target)
    except Exception:
        for target in reversed(created):
            boundary.child(target.name)
            shutil.rmtree(target)
        raise


def _same_package(left: Path, right: Path) -> bool:
    try:
        left_manifest = _verify_package(left)
        right_manifest = _verify_package(right)
    except (OSError, ValueError):
        return False
    return left_manifest == right_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Content 公众号 Slim without overwriting local drift")
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--build-output", type=Path)
    parser.add_argument("--package-name", default="content-gzh-slim-main")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args(argv)
    if args.build_output:
        _build(args.build_output)
        return 0
    if args.codex_home is None:
        parser.error("provide --build-output or an explicit authorized --codex-home")
    if Path(args.package_name).name != args.package_name or any(x in args.package_name for x in ("/", "\\", ":")):
        parser.error("package-name must be one safe leaf")
    from runtime.path_boundary import PathBoundary
    skills_root = PathBoundary(args.codex_home).child("skills")
    packages = PathBoundary(skills_root).child(".packages")
    packages.mkdir(parents=True, exist_ok=True)
    target = PathBoundary(packages).child(args.package_name)
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
        _activate(skills_root, target)
    print(json.dumps({"package": str(target), "activated": args.activate}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
