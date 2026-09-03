"""Create-only Obsidian article writes under one explicitly injected root."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .path_boundary import PathBoundary, PathBoundaryError
from .save_contract import is_protected_segment


class SaveAdapterError(RuntimeError):
    """Raised when a backend write, conflict, or readback cannot be verified."""


def _slug(title: str) -> str:
    value = re.sub(r"[^\w\-]+", "-", title, flags=re.UNICODE).strip("-._")
    return (value[:80] or "article") + ".md"


class ObsidianAdapter:
    backend = "obsidian"

    def __init__(self, isolated_root: str | Path, target_map: dict[str, str]) -> None:
        self.boundary = PathBoundary(isolated_root)
        self.boundary.root.mkdir(parents=True, exist_ok=True)
        self.target_map = dict(target_map)

    def _directory(self, target_ref: str) -> Path:
        relative = self.target_map.get(target_ref)
        if not isinstance(relative, str) or not relative.strip():
            raise SaveAdapterError("Obsidian target ref is not in the injected target map")
        parts = Path(relative).parts
        if any(is_protected_segment(part) for part in parts):
            raise SaveAdapterError("Obsidian target map may not write 01-05")
        try:
            return self.boundary.child(relative)
        except PathBoundaryError as exc:
            raise SaveAdapterError("Obsidian target map escapes the injected root") from exc

    @staticmethod
    def _render(approved: dict[str, Any]) -> str:
        draft = approved["draft"]
        headline = approved["headline"]
        return (
            "---\n"
            f"content_gzh_version: {draft['version']}\n"
            f"content_gzh_body_digest: {draft['digest']}\n"
            f"content_gzh_context_digest: {approved['context_digest']}\n"
            "---\n"
            f"# {headline['final_title']}\n\n"
            f"{draft['body'].rstrip()}\n"
        )

    def write_create_only(self, approved: dict[str, Any]) -> dict[str, Any]:
        directory = self._directory(approved["save_target"]["target_ref"])
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / _slug(approved["headline"]["final_title"])
        payload = self._render(approved)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing = path.read_text(encoding="utf-8")
            if existing != payload:
                raise SaveAdapterError("Obsidian article name conflicts with different content")
            return {"backend": self.backend, "object_ref": str(path), "created": False}
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload.encode("utf-8"))
        return {"backend": self.backend, "object_ref": str(path), "created": True}

    def read_back(self, target: dict[str, Any]) -> dict[str, Any]:
        path = Path(target.get("object_ref", "")).resolve()
        if path != self.boundary.root and self.boundary.root not in path.parents:
            raise SaveAdapterError("Obsidian readback escaped the injected root")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SaveAdapterError("Obsidian article readback failed") from exc
        match = re.fullmatch(
            r"---\ncontent_gzh_version: (\d+)\n"
            r"content_gzh_body_digest: ([a-f0-9]{64})\n"
            r"content_gzh_context_digest: ([a-f0-9]{64})\n---\n"
            r"# ([^\n]+)\n\n([\s\S]*)\n",
            text,
        )
        if not match:
            raise SaveAdapterError("Obsidian article readback format mismatch")
        return {
            "backend": self.backend,
            "object_ref": str(path),
            "version": int(match.group(1)),
            "body_digest": match.group(2),
            "context_digest": match.group(3),
            "title": match.group(4),
            "body": match.group(5),
        }
