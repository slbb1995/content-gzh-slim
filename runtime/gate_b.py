"""Render and classify the single P4 Gate B interaction."""

from __future__ import annotations

from typing import Any


def classify_gate_b_decision(reply: str) -> str:
    normalized = reply.strip() if isinstance(reply, str) else ""
    if normalized == "确认正文和标题":
        return "approve"
    if normalized.startswith("需要修改正文：") and normalized.removeprefix("需要修改正文：").strip():
        return "revise_body"
    if normalized.startswith("只修改标题：") and normalized.removeprefix("只修改标题：").strip():
        return "revise_headline"
    if normalized.startswith("使用标题：") and normalized.removeprefix("使用标题：").strip():
        return "select_headline"
    if normalized == "不采用":
        return "reject"
    return "ambiguous"


def render_gate_b(
    draft_body: str, headline: dict[str, Any], context: dict[str, Any]
) -> str:
    top3 = "\n".join(
        f"{index}. {item['title']}\n   理由：{item['reason']}"
        for index, item in enumerate(headline["top3"], 1)
    )
    save = context["save_target_preview"]
    gaps = context["fact_and_candidate_boundaries"].get("missing_evidence", [])
    gap_text = "\n".join(f"- {item}" for item in gaps) or "- 无"
    return (
        "# Gate B：正文与标题确认\n\n"
        "## 完整正文\n\n"
        f"{draft_body.rstrip()}\n\n"
        "## 标题建议\n\n"
        f"{top3}\n\n"
        f"## 推荐标题\n\n{headline['recommended']}\n\n"
        "## 保存目标预览\n\n"
        f"- 后端：{save.get('backend', '')}\n"
        f"- 目标：{save.get('target_ref', '')}\n"
        f"- 状态：{save.get('status', '')}\n\n"
        "## 事实缺口\n\n"
        f"{gap_text}\n\n"
        "合法决定为：`确认正文和标题`、`需要修改正文：<具体意见>`、"
        "`只修改标题：<具体意见>`、`使用标题：<当前候选或用户明确标题>`。"
        "`不采用`表示明确拒绝。"
        "其他模糊回复不会批准，也不会保存。"
    )
