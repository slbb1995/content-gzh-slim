#!/usr/bin/env python3
"""Build a deterministic Codex + WorkBuddy, Windows + macOS release ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = (".github", "runtime", "schemas", "scripts", "skills", "tests", "tools", "workbuddy")
ROOT_FILES = (
    ".gitattributes",
    "install.py",
    "VERSION",
    "LICENSE",
    "README.md",
    "release-manifest.json",
    "SHA256SUMS",
)
IGNORED_NAMES = {"__pycache__", ".pytest_cache", ".DS_Store"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
TEXT_SUFFIXES = {"", ".md", ".py", ".json", ".yaml", ".yml", ".txt"}
SECRET_PATTERNS = (
    re.compile(r"\bgh[opurs]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(?:access_token|refresh_token|app_secret)\b[\"']?\s*[:=]\s*[\"'][^\"']{8,}[\"']"),
)


def _git(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments], cwd=ROOT, check=check, capture_output=True, text=True,
        encoding="utf-8", errors="strict"
    )


def _source_revision() -> str:
    manifest = ROOT / "UNIVERSAL-PACKAGE-MANIFEST.json"
    if (ROOT / ".git").exists():
        completed = _git(["rev-parse", "HEAD"], check=False)
        if completed.returncode == 0:
            return completed.stdout.strip()
    if manifest.is_file():
        return json.loads(manifest.read_text(encoding="utf-8"))["source_revision"]
    raise RuntimeError("source revision is unavailable")


def _is_dirty() -> bool:
    if not (ROOT / ".git").exists():
        return False
    completed = _git(["status", "--porcelain"], check=False)
    if completed.returncode == 0:
        return bool(completed.stdout.strip())
    return False


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_files() -> dict[str, bytes]:
    result: dict[str, bytes] = {
        "SKILL.md": (ROOT / "workbuddy" / "SKILL.md").read_bytes(),
        "workbuddy.json": (ROOT / "workbuddy" / "workbuddy.json").read_bytes(),
    }
    for name in ROOT_FILES:
        result[name] = (ROOT / name).read_bytes()
    for directory in DIRECTORIES:
        for path in sorted((ROOT / directory).rglob("*")):
            if not path.is_file() or path.name in IGNORED_NAMES or path.suffix in IGNORED_SUFFIXES:
                continue
            result[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    return result


def _manifest(files: dict[str, bytes], revision: str) -> dict:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    return {
        "schema_version": 1,
        "package": "content-gzh-slim-universal",
        "version": version,
        "source_repository": "https://github.com/slbb1995/content-gzh-slim",
        "source_revision": revision,
        "hosts": ["codex", "workbuddy"],
        "operating_systems": ["macos", "windows"],
        "public_entry": "content-gzh-slim",
        "skills": [
            "content-gzh-slim", "content-gzh-analyzer", "content-gzh-context-retriever",
            "content-gzh-writer", "content-gzh-headline", "content-gzh-distribution-pack",
        ],
        "credentials_included": False,
        "customer_data_included": False,
        "privacy_scan": "pass",
        "files": {name: _sha(data) for name, data in sorted(files.items())},
    }


def _privacy_failures(files: dict[str, bytes]) -> list[str]:
    failures: list[str] = []
    for name, data in files.items():
        if Path(name).suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                failures.append(f"{name} matches {pattern.pattern}")
    return failures


def _zip_write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o755 if name == "scripts/content-gzh-slim" else 0o644) << 16
    archive.writestr(info, data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-dirty", action="store_true", help="test-only: build from an uncommitted tree")
    args = parser.parse_args()
    if not args.allow_dirty and _is_dirty():
        raise RuntimeError("release build requires a clean Git worktree")
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    revision = _source_revision()
    files = _source_files()
    failures = _privacy_failures(files)
    if failures:
        raise RuntimeError("privacy scan failed: " + "; ".join(failures))
    package_manifest = {
        "schema_version": 1,
        "package": f"content-gzh-slim-{(ROOT / 'VERSION').read_text(encoding='utf-8').strip()}",
        "source_revision": revision,
        "skill_root": "skills",
        "skills": _manifest(files, revision)["skills"],
        "files": {name: _sha(data) for name, data in sorted(files.items())},
    }
    files["PACKAGE-MANIFEST.json"] = (
        json.dumps(package_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    universal = _manifest(files, revision)
    universal_bytes = (json.dumps(universal, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".content-gzh-", suffix=".zip", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for name, data in sorted(files.items()):
                _zip_write(archive, name, data)
            _zip_write(archive, "UNIVERSAL-PACKAGE-MANIFEST.json", universal_bytes)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"ok": True, "output": str(output), "sha256": _sha(output.read_bytes()), "source_revision": revision}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
