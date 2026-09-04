"""Validate, bind, and render a P2 Gate A direction without approving it."""

from __future__ import annotations

from typing import Any


class DirectionContractError(ValueError):
    """Raised when a Gate A direction is incomplete or selects outside its candidates."""


_TEXT_FIELDS = {
    "option_id",
    "title",
    "speaker",
    "target_audience",
    "core_judgment",
    "promise",
    "why_now",
    "writer_mode_reason",
    "voice_mode",
    "business_connection",
}

_LIST_FIELDS = {
    "structure",
    "benchmark_transfer",
    "forbidden_transfer",
    "knowledge_materials",
    "fact_boundaries",
    "first_person_claims",
    "must_keep",
    "must_avoid",
    "professional_judgments",
    "reader_situations",
    "verification_actions",
}


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_source_list(sources: Any, key: str) -> list[str]:
    value = sources.get(key) if isinstance(sources, dict) else None
    if not isinstance(value, list) or any(not _nonempty_text(item) for item in value):
        raise DirectionContractError(f"selected_sources.{key} must be a string list")
    if len(value) != len(set(value)):
        raise DirectionContractError(f"selected_sources.{key} contains duplicates")
    return value


def build_direction(
    template: Any,
    run: dict[str, Any],
    retrieval: dict[str, Any],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(template, dict) or template.get("schema_version") != 1:
        raise DirectionContractError("direction template must be a schema_version 1 object")
    mode = template.get("mode")
    options = template.get("options")
    if mode not in {"single", "options"} or not isinstance(options, list):
        raise DirectionContractError("direction mode and options are invalid")

    task_input = run["task_input"]
    has_direction = bool(task_input.get("topic") or task_input.get("user_thoughts"))
    expected_count = 1 if has_direction else 3
    expected_mode = "single" if has_direction else "options"
    if mode != expected_mode or len(options) != expected_count:
        raise DirectionContractError(
            f"direction requires {expected_count} option(s) in {expected_mode} mode"
        )

    candidate_sets = {
        "business_refs": {item["ref"] for item in retrieval["business_candidates"]},
        "peer_refs": {item["ref"] for item in retrieval["peer_candidates"]},
        "method_refs": {item["ref"] for item in retrieval["method_candidates"]},
        "reference_refs": {
            item["reference_ref"] for item in analysis["reference_analyses"]
        },
    }
    business_status = {
        item["ref"]: item["fact_status"] for item in retrieval["business_candidates"]
    }
    ip_status = run["ip_identity"]["status"]

    option_ids = []
    for option in options:
        if not isinstance(option, dict):
            raise DirectionContractError("every direction option must be an object")
        missing_text = sorted(field for field in _TEXT_FIELDS if not _nonempty_text(option.get(field)))
        if missing_text:
            raise DirectionContractError(
                f"direction option is missing text fields: {', '.join(missing_text)}"
            )
        if option.get("writer_mode") not in {"ganhuo", "huati"}:
            raise DirectionContractError("writer_mode must be ganhuo or huati")
        for field in _LIST_FIELDS:
            if not isinstance(option.get(field), list):
                raise DirectionContractError(f"direction option {field} must be a list")
            if field != "structure" and any(
                not _nonempty_text(item) for item in option[field]
            ):
                raise DirectionContractError(
                    f"direction option {field} must contain only non-empty strings"
                )
        for field in ("professional_judgments", "reader_situations", "verification_actions"):
            if not option[field]:
                raise DirectionContractError(f"direction option {field} must not be empty")
        if not option["structure"] or not all(
            isinstance(section, dict)
            and _nonempty_text(section.get("section"))
            and _nonempty_text(section.get("purpose"))
            for section in option["structure"]
        ):
            raise DirectionContractError("direction structure must state each section purpose")

        selected_sources = option.get("selected_sources")
        for key, allowed in candidate_sets.items():
            selected = _validate_source_list(selected_sources, key)
            if not set(selected).issubset(allowed):
                raise DirectionContractError(f"direction selected an out-of-bundle {key}")
        for selected_ref in selected_sources["business_refs"]:
            if business_status[selected_ref] != "confirmed":
                raise DirectionContractError("unconfirmed business candidate cannot support a fact")
        if ip_status in {"limited", "unused", "none"} and option["first_person_claims"]:
            raise DirectionContractError(
                "limited, unused, or none IP cannot add unsupported first-person claims"
            )
        option_ids.append(option["option_id"])

    if len(option_ids) != len(set(option_ids)):
        raise DirectionContractError("direction option ids must be unique")

    return {
        "schema_version": 1,
        "run_id": run["run_id"],
        "mode": mode,
        "knowledge_base_identity": run["knowledge_base_identity"],
        "ip_identity": run["ip_identity"],
        "task_input": task_input,
        "ip_notices": retrieval["warnings"],
        "options": options,
        "approval_status": "waiting",
        "legal_decisions": ["确认方向", "需要修改：<具体意见>", "不采用"],
    }


def classify_gate_a_decision(reply: str) -> str:
    normalized = reply.strip() if isinstance(reply, str) else ""
    if normalized == "确认方向":
        return "approve"
    if normalized == "不采用":
        return "reject"
    if normalized.startswith("需要修改：") and normalized.removeprefix("需要修改：").strip():
        return "revise"
    return "ambiguous"


def _refs_line(label: str, refs: list[str]) -> str:
    return f"- {label}：" + ("、".join(refs) if refs else "无")


def render_gate_a(direction: dict[str, Any]) -> str:
    task = direction["task_input"]
    ip = direction["ip_identity"]
    lines = [
        "# Gate A：方向确认",
        "",
        f"- 知识库：{task['knowledge_base']}",
        f"- IP：{ip['requested_name']}（{ip['status']}）",
    ]
    for notice in direction["ip_notices"]:
        lines.append(f"- 提醒：{notice}")

    for index, option in enumerate(direction["options"], start=1):
        sources = option["selected_sources"]
        lines.extend(
            [
                "",
                f"## 方向 {index}：{option['title']}",
                "",
                f"- 谁在说：{option['speaker']}",
                f"- 讲给谁：{option['target_audience']}",
                f"- 核心判断：{option['core_judgment']}",
                f"- 核心承诺：{option['promise']}",
                f"- 为什么现在值得写：{option['why_now']}",
                f"- 类型：{option['writer_mode']}；{option['writer_mode_reason']}",
                f"- 表达方式：{option['voice_mode']}",
                "- 专业判断：" + "；".join(option["professional_judgments"]),
                "- 读者处境：" + "；".join(option["reader_situations"]),
                "- 可执行核验：" + "；".join(option["verification_actions"]),
                "- 结构：",
            ]
        )
        lines.extend(
            f"  {position}. {section['section']}：{section['purpose']}"
            for position, section in enumerate(option["structure"], start=1)
        )
        lines.extend(
            [
                _refs_line("05 IP 锚点", [ip["resolved_ref"]] if ip["resolved_ref"] else []),
                _refs_line("03 业务素材", sources["business_refs"]),
                _refs_line("04 同行内容", sources["peer_refs"]),
                _refs_line("04 内容方法", sources["method_refs"]),
                _refs_line("显式对标", sources["reference_refs"]),
                "- 对标可迁移：" + ("；".join(option["benchmark_transfer"]) or "无"),
                "- 绝不迁移：" + ("；".join(option["forbidden_transfer"]) or "无"),
                "- 知识库素材用途：" + ("；".join(option["knowledge_materials"]) or "无"),
                f"- 业务连接：{option['business_connection']}",
                "- 事实边界：" + ("；".join(option["fact_boundaries"]) or "无"),
            ]
        )

    lines.extend(
        [
            "",
            "请只回复以下一种：",
            "- `确认方向`",
            "- `需要修改：<具体意见>`",
            "- `不采用`",
            "",
            "其他模糊回复不会批准 Gate A。",
        ]
    )
    return "\n".join(lines)
