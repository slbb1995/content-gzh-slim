"""Validate P4 headline output and bind it to one stored draft."""

from __future__ import annotations

from typing import Any

from .approved_direction import canonical_digest


class HeadlineContractError(ValueError):
    """Raised when headline output violates the bounded candidate contract."""


_CANDIDATE_FIELDS = {"diagnosis", "top3", "recommended"}
_DIAGNOSIS_FIELDS = {"target_audience", "core_judgment", "click_tension"}
_TITLE_FIELDS = {"title", "reason"}


def build_headline_artifact(
    candidate: Any,
    *,
    run_id: str,
    context: dict[str, Any],
    draft_version: int,
    draft_body: str,
) -> dict[str, Any]:
    if not isinstance(candidate, dict) or set(candidate) != _CANDIDATE_FIELDS:
        raise HeadlineContractError("headline output must contain diagnosis, top3, and recommended only")
    diagnosis = candidate.get("diagnosis")
    if not isinstance(diagnosis, dict) or set(diagnosis) != _DIAGNOSIS_FIELDS:
        raise HeadlineContractError("headline diagnosis fields are invalid")
    if not all(isinstance(value, str) and value.strip() for value in diagnosis.values()):
        raise HeadlineContractError("headline diagnosis values must be non-empty")
    top3 = candidate.get("top3")
    if not isinstance(top3, list) or not 1 <= len(top3) <= 3:
        raise HeadlineContractError("headline output must contain one to three candidates")
    if any(not isinstance(item, dict) or set(item) != _TITLE_FIELDS for item in top3):
        raise HeadlineContractError("each headline must contain title and reason only")
    if any(
        not isinstance(item["title"], str)
        or not item["title"].strip()
        or not isinstance(item["reason"], str)
        or not item["reason"].strip()
        for item in top3
    ):
        raise HeadlineContractError("headline title and reason must be non-empty")
    titles = [item["title"].strip() for item in top3]
    if len(set(titles)) != len(titles):
        raise HeadlineContractError("headline candidates must be unique")
    recommended = candidate.get("recommended")
    if recommended not in titles:
        raise HeadlineContractError("recommended headline must come from the candidates")
    for forbidden in context.get("must_avoid", []):
        if any(forbidden in title for title in titles):
            raise HeadlineContractError(f"headline contains must_avoid: {forbidden}")
    return {
        "schema_version": 1,
        "run_id": run_id,
        "context_digest": canonical_digest(context),
        "draft_version": draft_version,
        "draft_digest": canonical_digest(draft_body),
        "diagnosis": {key: value.strip() for key, value in diagnosis.items()},
        "top3": [{"title": item["title"].strip(), "reason": item["reason"].strip()} for item in top3],
        "recommended": recommended,
    }
