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
import uuid


ROOT = Path(__file__).resolve().parent
SKILLS = (
    "content-gzh-slim",
    "content-gzh-analyzer",
    "content-gzh-context-retriever",
    "content-gzh-writer",
    "content-gzh-headline",
    "content-gzh-distribution-pack",
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
        "skills": list(SKILLS),
        "public_entry": "content-gzh-slim",
        "internal_skill_count": 5,
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


def _same_tree(left: Path, right: Path) -> bool:
    if not left.is_dir() or not right.is_dir() or left.is_symlink() or right.is_symlink():
        return False
    left_files = {
        path.relative_to(left).as_posix(): _sha(path)
        for path in left.rglob("*")
        if path.is_file()
    }
    right_files = {
        path.relative_to(right).as_posix(): _sha(path)
        for path in right.rglob("*")
        if path.is_file()
    }
    return left_files == right_files


def _activation_mode(skills_root: Path) -> str:
    """Preflight Windows symlink permission and select the safe activation mode."""
    if os.name != "nt":
        return "symlink"
    probe_root = skills_root / f".content-gzh-link-probe-{uuid.uuid4().hex}"
    target = probe_root / "target"
    link = probe_root / "link"
    try:
        target.mkdir(parents=True)
        link.symlink_to(target, target_is_directory=True)
        if not link.is_symlink() or link.resolve() != target.resolve():
            raise OSError("directory symlink probe did not resolve")
        return "symlink"
    except OSError:
        return "copy"
    finally:
        if probe_root.exists() or probe_root.is_symlink():
            shutil.rmtree(probe_root, ignore_errors=True)


def _remove_created(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _activate(skills_root: Path, package: Path) -> str:
    """Atomically expose all skills, rolling back every new entry on failure."""
    skills_root.mkdir(parents=True, exist_ok=True)
    mode = _activation_mode(skills_root)
    wanted_root = package / ".agents" / "skills"
    planned: list[tuple[Path, Path]] = []
    for name in SKILLS:
        link = skills_root / name
        wanted = wanted_root / name
        if link.exists() or link.is_symlink():
            matches = link.is_symlink() and link.resolve() == wanted.resolve()
            matches = matches or (not link.is_symlink() and _same_tree(link, wanted))
            if not matches:
                raise ValueError(f"active Skill differs; refusing to overwrite: {link}")
            continue
        planned.append((link, wanted))

    staging = skills_root / f".content-gzh-activate-{uuid.uuid4().hex}"
    created: list[Path] = []
    try:
        staging.mkdir()
        for link, wanted in planned:
            staged = staging / link.name
            if mode == "symlink":
                staged.symlink_to(os.path.relpath(wanted, skills_root), target_is_directory=True)
            else:
                _copy(wanted, staged)
        for link, _wanted in planned:
            os.replace(staging / link.name, link)
            created.append(link)
    except BaseException:
        for link in reversed(created):
            _remove_created(link)
        raise
    finally:
        if staging.exists() or staging.is_symlink():
            _remove_created(staging)
    return mode


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
        try:
            mode = _activate(skills_root, target)
        except (OSError, ValueError) as exc:
            print(f"activation failed; rolled back new Skill entries: {exc}", file=sys.stderr)
            return 2
        print(f"activation mode: {mode}")
    probe = subprocess.run([sys.executable, "-B", str(target / "bin" / "content-gzh-slim"), "probe"], check=False)
    return probe.returncode


if __name__ == "__main__":
    raise SystemExit(main())
