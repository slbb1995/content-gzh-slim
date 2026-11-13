"""P3 orchestration for one create-only Article Context Pack."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .approved_direction import materialize_approved_direction
from .artifact_store import ArtifactStore, ArtifactStoreError
from .context_contract import build_article_context, verify_writer_input
from .frozen_projection import FrozenFixtureProjector
from .receipt_finalizer import finalize_retrieval_receipt
from .reference_prep import FixtureReferencePreparer
from .run_store import RunStore, RunStoreError


class P3Pipeline:
    def __init__(self, store_root: str | Path, catalog_path: str | Path) -> None:
        self.run_store = RunStore(store_root)
        self.artifacts = ArtifactStore(store_root)
        self.catalog_path = Path(catalog_path)

    @staticmethod
    def _read_object(path: str | Path) -> dict[str, Any]:
        with Path(path).open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("P3 selection must be an object")
        return value

    def run(self, run_id: str, selection_path: str | Path) -> dict[str, Any]:
        selection = self._read_object(selection_path)
        run = self.run_store.load(run_id)
        if run["status"] == "context_ready":
            context = self.artifacts.read_json(run_id, "article_context_v1.json")
            verify_writer_input(context, run_id, selection)
            receipt = self.artifacts.read_json(run_id, "retrieval_receipt.json")
            if receipt.get("totals", {}).get("context_packs") != 1:
                raise RunStoreError("context_ready Run has an unfinished retrieval receipt")
            return {"context": context, "retrieval_receipt": receipt, "resumed": True}
        if run["status"] != "direction_approved":
            raise RunStoreError("P3 requires direction_approved and never approves Gate A itself")

        try:
            existing_context = self.artifacts.read_json(run_id, "article_context_v1.json")
        except ArtifactStoreError:
            existing_context = None
        if existing_context is not None:
            self.artifacts.read_json(run_id, "approved_direction.json")
            verify_writer_input(existing_context, run_id, selection)
            existing_receipt = self.artifacts.read_json(run_id, "retrieval_receipt.json")
            finalized_receipt = finalize_retrieval_receipt(existing_receipt, existing_context)
            self.artifacts.replace_json_if_matches(
                run_id,
                "retrieval_receipt.json",
                existing_receipt,
                finalized_receipt,
            )
            self.run_store.advance(run_id, "context_ready")
            return {
                "context": existing_context,
                "retrieval_receipt": finalized_receipt,
                "resumed": True,
            }

        direction = self.artifacts.read_json(run_id, "direction_v1.json")
        original_receipt = self.artifacts.read_json(run_id, "retrieval_receipt.json")
        analysis = self.artifacts.read_json(run_id, "analysis_v1.json")
        approved = materialize_approved_direction(run, direction, original_receipt)
        frozen_sources = self.artifacts.read_json(run_id, "reference_snapshot_v1.json")
        if frozen_sources != FixtureReferencePreparer(self.catalog_path).prepare(run["task_input"]["references"]):
            raise RunStoreError("P2 reference snapshot differs from the frozen source catalog")
        projection = FrozenFixtureProjector(self.catalog_path).project(
            selection, run, approved, analysis,
            frozen_sources,
        )
        context = build_article_context(run, approved, projection, selection)
        finalized_receipt = finalize_retrieval_receipt(original_receipt, context)

        self.artifacts.write_json_once_or_verify(run_id, "approved_direction.json", approved)
        self.artifacts.write_json_once_or_verify(run_id, "article_context_v1.json", context)
        self.artifacts.replace_json_if_matches(
            run_id,
            "retrieval_receipt.json",
            original_receipt,
            finalized_receipt,
        )
        self.run_store.advance(run_id, "context_ready")
        return {"context": context, "retrieval_receipt": finalized_receipt, "resumed": False}
