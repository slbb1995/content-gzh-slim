"""Freeze one approved P4 version into the only P5 approved_final artifact."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .approved_direction import canonical_digest
from .artifact_store import ArtifactStore
from .draft_contract import validate_context_binding, validate_draft_body


class SaveContractError(ValueError):
    """Raised when a final version, title, target, or Gate B receipt is unsafe."""


_PLACEHOLDERS = (
    "{{",
    "}}",
    "[TODO]",
    "[TBD]",
    "[待补]",
    "<placeholder>",
    "PLACEHOLDER",
    "虚构示例",
    "示例占位",
    "fixture://",
)


def is_protected_segment(value: str) -> bool:
    """Match 01-05 roots with common separators, without blocking names such as 051."""

    return bool(re.match(r"^0[1-5](?:$|[ ._\-])", value))


def validate_target_preview(
    context: dict[str, Any], adapter_backend: str
) -> dict[str, str]:
    preview = context.get("save_target_preview")
    if not isinstance(preview, dict):
        raise SaveContractError("save target preview is missing")
    backend = preview.get("backend")
    target_ref = preview.get("target_ref")
    status = preview.get("status")
    if backend != context.get("knowledge_base_identity", {}).get("backend"):
        raise SaveContractError("save backend differs from frozen knowledge base")
    if backend != adapter_backend:
        raise SaveContractError("save adapter backend mismatch")
    if status != "preview_only_not_writable":
        raise SaveContractError("save target was not a frozen preview")
    if not isinstance(target_ref, str) or not target_ref.strip() or "\x00" in target_ref:
        raise SaveContractError("save target ref is invalid")
    if (
        target_ref.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", target_ref)
        or "\\" in target_ref
        or Path(target_ref).is_absolute()
    ):
        raise SaveContractError("absolute save target refs are forbidden")
    parts = [part for part in re.split(r"[\\/]", urlsplit(target_ref).path) if part]
    if ".." in parts:
        raise SaveContractError("save target escapes its controlled boundary")
    if any(is_protected_segment(part) for part in parts):
        raise SaveContractError("save target may not write 01-05")
    return {"backend": backend, "target_ref": target_ref, "status": status}


def _current_version(artifacts: ArtifactStore, run_id: str) -> int:
    run_dir = artifacts.boundary.child("runs", run_id)
    drafts = {
        int(match.group(1))
        for path in run_dir.glob("draft_v*.md")
        if (match := re.fullmatch(r"draft_v(\d+)\.md", path.name))
    }
    headlines = {
        int(match.group(1))
        for path in run_dir.glob("headline_v*.json")
        if (match := re.fullmatch(r"headline_v(\d+)\.json", path.name))
    }
    if not drafts or drafts != headlines:
        raise SaveContractError("draft and headline versions are missing or unmatched")
    return max(drafts)


def _validate_no_placeholders(title: str, body: str) -> None:
    combined = f"{title}\n{body}"
    if any(marker.casefold() in combined.casefold() for marker in _PLACEHOLDERS):
        raise SaveContractError("final article contains a placeholder or fictional fixture residue")
    if any(character in title for character in ("\n", "\r", "\x00")):
        raise SaveContractError("final title must be one line")


def build_approved_final(
    run: dict[str, Any],
    artifacts: ArtifactStore,
    *,
    adapter_backend: str,
    final_title: str | None = None,
) -> dict[str, Any]:
    if run.get("status") not in {"final_approved", "saving", "saved"}:
        raise SaveContractError("save requires final_approved")
    gate_b = [item for item in run.get("gate_approvals", []) if item.get("gate") == "B"]
    if len(gate_b) != 1:
        raise SaveContractError("save requires one exact Gate B approval receipt")
    decision = gate_b[0].get("decision", "")
    if decision != "确认正文和标题" and not (
        isinstance(decision, str)
        and decision.startswith("使用标题：")
        and decision.removeprefix("使用标题：").strip()
    ):
        raise SaveContractError("Gate B decision is not an explicit final approval")

    context = artifacts.read_json(run["run_id"], "article_context_v1.json")
    approved_direction = artifacts.read_json(run["run_id"], "approved_direction.json")
    validate_context_binding(run, context, approved_direction)
    version = _current_version(artifacts, run["run_id"])
    draft_file = f"draft_v{version}.md"
    headline_file = f"headline_v{version}.json"
    body = artifacts.read_text(run["run_id"], draft_file).rstrip()
    body = validate_draft_body(body, context)
    headline = artifacts.read_json(run["run_id"], headline_file)
    context_digest = canonical_digest(context)
    body_digest = canonical_digest(body)
    if headline.get("run_id") != run["run_id"]:
        raise SaveContractError("headline belongs to another Run")
    if headline.get("draft_version") != version:
        raise SaveContractError("headline version does not match current draft")
    if headline.get("context_digest") != context_digest:
        raise SaveContractError("headline Context digest mismatch")
    if headline.get("draft_digest") != body_digest:
        raise SaveContractError("headline draft digest mismatch")
    top3 = [item.get("title") for item in headline.get("top3", [])]
    if len(top3) != 3 or any(not isinstance(title, str) for title in top3):
        raise SaveContractError("stored headline does not contain exact Top 3")

    if decision == "确认正文和标题":
        recommended = headline.get("recommended")
        if recommended not in top3:
            raise SaveContractError("recommended title is not in the displayed Top 3")
        if final_title is not None and final_title != recommended:
            raise SaveContractError("confirmed Gate B locks the displayed recommended title")
        selected_title = recommended
        title_source = "displayed_top3"
    else:
        explicit_title = decision.removeprefix("使用标题：").strip()
        if final_title is not None and final_title != explicit_title:
            raise SaveContractError("final title differs from the explicit Gate B title")
        selected_title = explicit_title
        title_source = "explicit_gate_b_input"
    if not isinstance(selected_title, str) or not selected_title.strip():
        raise SaveContractError("final title is empty")
    selected_title = selected_title.strip()
    _validate_no_placeholders(selected_title, body)
    target = validate_target_preview(context, adapter_backend)
    return {
        "schema_version": 1,
        "run_id": run["run_id"],
        "input_digest": run["input_digest"],
        "knowledge_base_identity": run["knowledge_base_identity"],
        "ip_identity": run["ip_identity"],
        "gate_b_receipt": gate_b[0],
        "context_digest": context_digest,
        "draft": {
            "version": version,
            "file": draft_file,
            "digest": body_digest,
            "body": body,
        },
        "headline": {
            "version": version,
            "file": headline_file,
            "digest": canonical_digest(headline),
            "displayed_top3": top3,
            "final_title": selected_title,
            "title_source": title_source,
        },
        "save_target": target,
    }
