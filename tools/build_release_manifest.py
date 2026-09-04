#!/usr/bin/env python3
"""Regenerate release-manifest.json and SHA256SUMS from deliverable files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = (
    "content-gzh-analyzer",
    "content-gzh-context-retriever",
    "content-gzh-distribution-pack",
    "content-gzh-headline",
    "content-gzh-slim",
    "content-gzh-writer",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files() -> list[dict[str, object]]:
    paths: list[Path] = []
    for root_name in ("runtime", "schemas", "skills", "workbuddy"):
        paths.extend(path for path in (ROOT / root_name).rglob("*") if path.is_file())
    paths.append(ROOT / "scripts" / "content-gzh-slim")
    paths.append(ROOT / "install.py")
    paths.append(ROOT / "tools" / "build_universal_package.py")
    result = []
    for path in sorted(set(paths)):
        if path.name == "__pycache__" or path.suffix in {".pyc", ".pyo"} or path.is_symlink():
            continue
        result.append({"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    return result


def main() -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    runtime_files = files()
    tree = hashlib.sha256("".join(f"{item['path']}\0{item['sha256']}\n" for item in runtime_files).encode()).hexdigest()
    manifest = {
        "schema_version": "content-gzh-slim-release-v1",
        "package": {"id": "content-gzh-slim", "version": version},
        "runtime": {"file_count": len(runtime_files), "files": runtime_files, "skill_count": len(SKILLS), "skills": list(SKILLS), "tree_sha256": tree},
        "integrity": {"hash_algorithm": "sha256"},
    }
    manifest_path = ROOT / "release-manifest.json"
    manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    checksum_paths = [*(ROOT / item["path"] for item in runtime_files), ROOT / "VERSION", ROOT / "LICENSE", manifest_path]
    (ROOT / "SHA256SUMS").write_bytes("".join(f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}\n" for path in checksum_paths).encode("utf-8"))
    print(f"Updated {version}: {len(runtime_files)} deliverable files, tree {tree}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
