"""P4 orchestration for versioned bodies, one to three headlines, and Gate B."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_store import ArtifactStore, ArtifactStoreError
from .draft_contract import (
    revision_invocation,
    validate_context_binding,
    validate_draft_body,
    writer_invocation,
)
from .gate_b import render_gate_b
from .headline_contract import build_headline_artifact
from .run_store import RunStore, RunStoreError


class P4Pipeline:
    def __init__(self, store_root: str | Path) -> None:
        self.run_store = RunStore(store_root)
        self.artifacts = ArtifactStore(store_root)

    def _load_bound_context(self, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        run = self.run_store.load(run_id)
        context = self.artifacts.read_json(run_id, "article_context_v1.json")
        approved = self.artifacts.read_json(run_id, "approved_direction.json")
        validate_context_binding(run, context, approved)
        return run, context

    def writer_input(self, run_id: str) -> dict[str, Any]:
        run, context = self._load_bound_context(run_id)
        if run["status"] not in {"context_ready", "draft_working"}:
            raise RunStoreError("initial Writer requires context_ready")
        return writer_invocation(context)

    def _materialize_version(
        self,
        run_id: str,
        version: int,
        body: str,
        headline_candidate: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        clean_body = validate_draft_body(body, context)
        headline = build_headline_artifact(
            headline_candidate,
            run_id=run_id,
            context=context,
            draft_version=version,
            draft_body=clean_body,
        )
        self.artifacts.write_text_once_or_verify(run_id, f"draft_v{version}.md", clean_body)
        self.artifacts.write_json_once_or_verify(run_id, f"headline_v{version}.json", headline)
        return clean_body, headline

    def run_initial(
        self, run_id: str, body: str, headline_candidate: dict[str, Any]
    ) -> dict[str, Any]:
        run, context = self._load_bound_context(run_id)
        if run["status"] not in {"context_ready", "draft_working", "waiting_final"}:
            raise RunStoreError("P4 requires context_ready and never approves Gate B itself")
        clean_body, headline = self._materialize_version(
            run_id, 1, body, headline_candidate, context
        )
        resumed = run["status"] == "waiting_final"
        if run["status"] == "context_ready":
            self.run_store.advance(run_id, "draft_working")
            run = self.run_store.load(run_id)
        if run["status"] == "draft_working":
            self.run_store.advance(run_id, "waiting_final")
        return {
            "draft_file": "draft_v1.md",
            "headline_file": "headline_v1.json",
            "draft": clean_body,
            "headline": headline,
            "gate_b": render_gate_b(clean_body, headline, context),
            "writer_invocation": writer_invocation(context),
            "resumed": resumed,
        }

    def revise(
        self,
        run_id: str,
        *,
        base_version: int,
        feedback: str,
        body: str,
        headline_candidate: dict[str, Any],
    ) -> dict[str, Any]:
        run, context = self._load_bound_context(run_id)
        if run["status"] != "waiting_final":
            raise RunStoreError("revision requires waiting_final")
        if base_version < 1:
            raise RunStoreError("base draft version must be positive")
        base_body = self.artifacts.read_text(run_id, f"draft_v{base_version}.md").rstrip()
        self.artifacts.read_json(run_id, f"headline_v{base_version}.json")
        invocation = revision_invocation(context, base_version, feedback)
        target_version = base_version + 1
        clean_body = validate_draft_body(body, context)
        if clean_body == base_body:
            raise RunStoreError("revision must not create an unchanged draft version")
        headline = build_headline_artifact(
            headline_candidate,
            run_id=run_id,
            context=context,
            draft_version=target_version,
            draft_body=clean_body,
        )
        try:
            self.artifacts.read_text(run_id, f"draft_v{target_version + 1}.md")
        except ArtifactStoreError:
            pass
        else:
            raise RunStoreError("revision base is stale; a later draft already exists")
        self.artifacts.write_text_once_or_verify(
            run_id, f"draft_v{target_version}.md", clean_body
        )
        self.artifacts.write_json_once_or_verify(
            run_id, f"headline_v{target_version}.json", headline
        )
        return {
            "draft_file": f"draft_v{target_version}.md",
            "headline_file": f"headline_v{target_version}.json",
            "draft": clean_body,
            "headline": headline,
            "gate_b": render_gate_b(clean_body, headline, context),
            "writer_invocation": invocation,
        }
