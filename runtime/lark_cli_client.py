"""Controlled Feishu document client backed by the authenticated lark-cli."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .obsidian_adapter import SaveAdapterError


class LarkCliError(SaveAdapterError):
    """Raised when the real Feishu client cannot create or verify a document."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_from_output(output: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise LarkCliError("lark-cli returned no JSON object")


class LarkCliFeishuClient:
    """Create one Markdown document and verify its remote readback.

    The local state contains only idempotency metadata and document references. It
    never copies or persists lark-cli credentials.
    """

    def __init__(
        self,
        state_path: str | Path,
        *,
        binary: str | None = None,
        identity: str = "user",
    ) -> None:
        if identity not in {"user", "bot"}:
            raise LarkCliError("lark-cli identity must be user or bot")
        resolved = binary or shutil.which("lark-cli")
        if not resolved:
            raise LarkCliError("lark-cli is not installed")
        self.binary = resolved
        self.identity = identity
        self.state_path = Path(state_path).expanduser().resolve()

    def _call(self, arguments: list[str]) -> dict[str, Any]:
        completed = subprocess.run(
            [self.binary, "--as", self.identity, "--format", "json", *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout).strip()
            raise LarkCliError(f"lark-cli failed without creating a verified document: {message}")
        value = _json_from_output(completed.stdout)
        if value.get("ok") is not True:
            raise LarkCliError("lark-cli returned an unsuccessful response")
        return value

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"schema_version": 1, "documents": {}}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LarkCliError("Feishu idempotency state is unreadable") from exc
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or not isinstance(value.get("documents"), dict)
        ):
            raise LarkCliError("Feishu idempotency state is invalid")
        return value

    def _write_state(self, value: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=self.state_path.parent,
            prefix=".feishu-state-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write((_canonical(value) + "\n").encode("utf-8"))
            temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.state_path)

    @staticmethod
    def _document(payload: dict[str, Any]) -> dict[str, Any]:
        document = payload.get("data", {}).get("document", {})
        if not isinstance(document, dict):
            raise LarkCliError("lark-cli document response is missing")
        return document

    def create_document_once(
        self, parent_ref: str, title: str, body: str, metadata: dict[str, Any]
    ) -> str:
        if not isinstance(parent_ref, str) or not parent_ref.strip():
            raise LarkCliError("Feishu parent ref is empty")
        identity = {
            "parent_ref": parent_ref.strip(),
            "title": title,
            "body_digest": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "metadata": metadata,
        }
        key = hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()
        state = self._read_state()
        documents = state["documents"]
        existing = documents.get(key)
        if isinstance(existing, dict) and isinstance(existing.get("object_ref"), str):
            return existing["object_ref"]
        if any(
            item.get("parent_ref") == parent_ref.strip() and item.get("title") == title
            for item in documents.values()
            if isinstance(item, dict)
        ):
            raise LarkCliError("Feishu title already belongs to different approved content")

        content = f"# {title}\n\n{body.rstrip()}\n"
        arguments = [
            "docs",
            "+create",
            "--api-version",
            "v2",
            "--doc-format",
            "markdown",
            "--content",
            content,
        ]
        if parent_ref.strip() == "my_library":
            arguments.extend(["--parent-position", "my_library"])
        else:
            arguments.extend(["--parent-token", parent_ref.strip()])
        document = self._document(self._call(arguments))
        object_ref = document.get("url") or document.get("document_id")
        if not isinstance(object_ref, str) or not object_ref.strip():
            raise LarkCliError("lark-cli create response has no document reference")
        documents[key] = {
            **identity,
            "object_ref": object_ref.strip(),
        }
        self._write_state(state)
        return object_ref.strip()

    def read_document(self, object_ref: str) -> dict[str, Any]:
        state = self._read_state()
        matches = [
            item
            for item in state["documents"].values()
            if isinstance(item, dict) and item.get("object_ref") == object_ref
        ]
        if len(matches) != 1:
            raise LarkCliError("Feishu document is not bound to this client state")
        record = matches[0]
        document = self._document(
            self._call(
                [
                    "docs",
                    "+fetch",
                    "--api-version",
                    "v2",
                    "--doc",
                    object_ref,
                    "--doc-format",
                    "markdown",
                    "--detail",
                    "simple",
                ]
            )
        )
        content = document.get("content")
        if not isinstance(content, str):
            raise LarkCliError("Feishu readback contains no Markdown content")
        normalized = content.replace("\r\n", "\n").strip()
        lines = normalized.splitlines()
        if lines and lines[0].startswith("# "):
            remote_title = lines[0][2:].strip()
            remote_body = "\n".join(lines[1:]).strip()
        else:
            remote_title = document.get("title") or record["title"]
            remote_body = normalized
        return {
            "title": remote_title,
            "body": remote_body,
            "metadata": record["metadata"],
        }
