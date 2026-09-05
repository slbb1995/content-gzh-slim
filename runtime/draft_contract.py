"""Validate P4's single Context input and body-only Writer output."""

from __future__ import annotations

import re
from typing import Any

from .approved_direction import canonical_digest
from .context_contract import CONTEXT_ROOT_FIELDS

_FORBIDDEN_SECTION_MARKER = re.compile(
    r"(?m)^(?:分析|状态|来源清单|保存说明|推荐标题|Top 3)\s*(?:[:：]|$)"
)

_INTERNAL_EDITORIAL_NARRATION = (
    re.compile(
        r"(?:这里|本文|这篇文章|下文)[^。！？\n]{0,16}"
        r"(?:不讲|不写|不采用|只看|只用|只使用|仅看|仅使用)[^。！？\n]{0,32}"
        r"(?:客户故事|客户案例|入库资料|项目资料|知识库素材|素材说明)"
    ),
    re.compile(
        r"(?:最后|文末)[^。！？\n]{0,30}(?:写作要求|素材说明|事实边界|素材边界)"
        r"[^。！？\n]{0,16}(?:说清楚|说明|交代|展示)"
    ),
    re.compile(
        r"(?:因为|由于)[^。！？\n]{0,36}(?:知识库没有|资料中没有|缺少可核验)"
        r"[^。！？\n]{0,20}(?:客户故事|客户案例|案例)[^。！？\n]{0,24}"
        r"(?:所以|因此)[^。！？\n]{0,20}(?:本文|这篇文章)[^。！？\n]{0,20}"
        r"(?:改用|只用|只写)"
    ),
)


class DraftContractError(ValueError):
    """Raised when P4 identity or article-body boundaries are violated."""


def validate_context_binding(
    run: dict[str, Any], context: dict[str, Any], approved: dict[str, Any]
) -> None:
    identity = context.get("run_identity", {})
    gate_a = identity.get("gate_a", {})
    checks = (
        (set(context) == CONTEXT_ROOT_FIELDS, "Context root differs from SPEC 11.2"),
        (identity.get("run_id") == run.get("run_id"), "Context belongs to another Run"),
        (identity.get("input_digest") == run.get("input_digest"), "Context input digest mismatch"),
        (
            context.get("knowledge_base_identity") == run.get("knowledge_base_identity"),
            "Context knowledge base mismatch",
        ),
        (context.get("ip_identity_and_status") == run.get("ip_identity"), "Context IP mismatch"),
        (context.get("task_input") == run.get("task_input"), "Context task input mismatch"),
        (approved.get("run_id") == run.get("run_id"), "approved direction Run mismatch"),
        (
            approved.get("knowledge_base_identity") == run.get("knowledge_base_identity"),
            "approved direction knowledge base mismatch",
        ),
        (approved.get("ip_identity") == run.get("ip_identity"), "approved direction IP mismatch"),
        (
            gate_a.get("direction_digest") == approved.get("direction_digest"),
            "Gate A direction digest mismatch",
        ),
        (
            gate_a.get("approved_option_id")
            == approved.get("approved_option", {}).get("option_id"),
            "Gate A approved option mismatch",
        ),
        (
            context.get("approved_direction") == approved.get("approved_option"),
            "Context approved direction mismatch",
        ),
        (gate_a.get("decision") == "确认方向", "Gate A was not explicitly approved"),
    )
    for valid, message in checks:
        if not valid:
            raise DraftContractError(message)
    if context.get("writer_mode") not in {"ganhuo", "huati"}:
        raise DraftContractError("Writer mode must be exactly ganhuo or huati")
    if context["writer_mode"] != context["approved_direction"].get("writer_mode"):
        raise DraftContractError("Writer mode differs from approved direction")


def writer_invocation(context: dict[str, Any]) -> dict[str, Any]:
    """Describe the isolated invocation without exposing any source or backend entry."""

    return {
        "formal_input_files": ["article_context_v1.json"],
        "formal_input_file_count": 1,
        "writer_mode": context["writer_mode"],
        "context_digest": canonical_digest(context),
        "source_access": "none",
    }


def revision_invocation(context: dict[str, Any], draft_version: int, feedback: str) -> dict[str, Any]:
    if not isinstance(feedback, str) or not feedback.strip():
        raise DraftContractError("revision requires one concrete user feedback item")
    return {
        **writer_invocation(context),
        "current_draft_file": f"draft_v{draft_version}.md",
        "user_feedback": feedback.strip(),
        "user_feedback_count": 1,
    }


def validate_draft_body(body: Any, context: dict[str, Any]) -> str:
    if not isinstance(body, str) or not body.strip():
        raise DraftContractError("Writer output must be a non-empty article body")
    normalized = body.strip()
    first_line = normalized.splitlines()[0].strip()
    if first_line.startswith("# ") or re.match(r"^(标题|题目|Title)\s*[:：]", first_line, re.I):
        raise DraftContractError("Writer output must not contain an article title")
    if _FORBIDDEN_SECTION_MARKER.search(normalized):
        raise DraftContractError("Writer output contains analysis, title, status, source, or save material")
    if any(pattern.search(normalized) for pattern in _INTERNAL_EDITORIAL_NARRATION):
        raise DraftContractError("Writer output exposes an internal production requirement")

    for required in context.get("must_keep", []):
        if required not in normalized:
            raise DraftContractError(f"draft omitted must_keep: {required}")
    for forbidden in context.get("must_avoid", []):
        if forbidden in normalized:
            raise DraftContractError(f"draft contains must_avoid: {forbidden}")

    boundaries = context.get("fact_and_candidate_boundaries", {})
    for candidate in boundaries.get("excluded_business_candidates", []):
        candidate_text = candidate.get("fragment") or candidate.get("claim")
        if candidate.get("fact_status") != "confirmed" and candidate_text and candidate_text in normalized:
            raise DraftContractError("draft promoted an excluded candidate to article content")
    missing = " ".join(boundaries.get("missing_evidence", []))
    if ("增长" in missing or "数字" in missing) and re.search(
        r"(?:增长|提升|转化|效果)[^。；\n]{0,16}(?:\d+(?:\.\d+)?%|\d+(?:\.\d+)?倍)",
        normalized,
    ):
        raise DraftContractError("draft turns missing growth evidence into a numeric claim")
    if any(word in missing for word in ("未实测", "没有本人实测", "尚需", "待补", "待核验")):
        if re.search(r"(?:我|本人)(?:已经|已)(?:全面)?实测", normalized):
            raise DraftContractError("draft turns missing test evidence into a completed first-person fact")
    return normalized
