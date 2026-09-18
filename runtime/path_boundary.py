"""Keep all P1 RunStore artifacts under one explicit local root."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
import stat


class PathBoundaryError(ValueError):
    """Raised when an artifact path would leave the configured RunStore root."""


class PathBoundary:
    def __init__(self, root: str | Path) -> None:
        raw = Path(root).expanduser().absolute()
        self._reject_links(raw)
        self.root = raw.resolve()

    @staticmethod
    def _reject_links(path: Path) -> None:
        for current in (path, *path.parents):
            if current.is_symlink() or (current.exists() and getattr(current.stat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise PathBoundaryError("path contains a symlink or reparse point")

    def child(self, *parts: str) -> Path:
        if not parts or any(not part or Path(part).is_absolute() or PurePosixPath(part).is_absolute() or PureWindowsPath(part).drive or chr(0) in part for part in parts):
            raise PathBoundaryError("artifact path must be relative to the RunStore root")
        raw = self.root.joinpath(*parts)
        self._reject_links(raw)
        candidate = raw.resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PathBoundaryError("artifact path escapes the RunStore root")
        return candidate
