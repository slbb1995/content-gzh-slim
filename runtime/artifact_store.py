"""Create-only artifact storage with identical retry verification."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .path_boundary import PathBoundary


class ArtifactStoreError(RuntimeError):
    """Raised when an artifact would be overwritten or cannot be verified."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.boundary = PathBoundary(root)

    def _path(self, run_id: str, name: str) -> Path:
        if not name.endswith((".json", ".md")):
            raise ArtifactStoreError("artifact name must be a JSON or Markdown file")
        return self.boundary.child("runs", run_id, name)

    def read_json(self, run_id: str, name: str) -> dict[str, Any]:
        path = self._path(run_id, name)
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactStoreError(f"artifact is unreadable: {name}") from exc
        if not isinstance(value, dict):
            raise ArtifactStoreError(f"artifact must be an object: {name}")
        return value

    def read_text(self, run_id: str, name: str) -> str:
        path = self._path(run_id, name)
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ArtifactStoreError(f"artifact is unreadable: {name}") from exc

    def write_json_once_or_verify(self, run_id: str, name: str, value: dict[str, Any]) -> None:
        path = self._path(run_id, name)
        payload = _canonical(value) + "\n"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing = self.read_json(run_id, name)
            if _canonical(existing) != _canonical(value):
                raise ArtifactStoreError(f"artifact already exists with different content: {name}")
            return
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload.encode("utf-8"))

    def write_text_once_or_verify(self, run_id: str, name: str, value: str) -> None:
        path = self._path(run_id, name)
        payload = value.rstrip() + "\n"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if self.read_text(run_id, name) != payload:
                raise ArtifactStoreError(f"artifact already exists with different content: {name}")
            return
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload.encode("utf-8"))

    def replace_json_if_matches(
        self,
        run_id: str,
        name: str,
        expected: dict[str, Any],
        replacement: dict[str, Any],
    ) -> None:
        path = self._path(run_id, name)
        existing = self.read_json(run_id, name)
        if _canonical(existing) == _canonical(replacement):
            return
        if _canonical(existing) != _canonical(expected):
            raise ArtifactStoreError(f"artifact changed unexpectedly; refusing to replace: {name}")
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{name}-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write((_canonical(replacement) + "\n").encode("utf-8"))
            temporary = Path(handle.name)
        os.replace(temporary, path)
