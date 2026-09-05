"""Small dependency-free validator for the P1 normalized task contract."""

from __future__ import annotations

import re
from typing import Any


class ContractError(ValueError):
    """Raised when user input cannot satisfy the P1 task contract."""


_ALLOWED_KEYS = {
    "knowledge_base",
    "ip",
    "topic",
    "references",
    "user_thoughts",
    "must_keep",
    "must_avoid",
    "target_audience_override",
    "article_length_preference",
}

_OPTIONAL_TEXT_KEYS = {
    "topic",
    "user_thoughts",
    "target_audience_override",
    "article_length_preference",
}

_PRIVATE_MUST_KEEP_PATTERNS = (
    re.compile(
        r"(?:这里|本文|这篇文章).{0,12}(?:不讲|不写|不采用|只看|只用|只使用|仅看|仅使用)"
        r".{0,24}(?:客户故事|客户案例|素材|资料|知识库)"
    ),
    re.compile(r"(?:写作要求|素材说明|内部需求|生产要求|事实边界|素材边界)"),
    re.compile(
        r"(?:不得|不要|不准|禁止).{0,12}(?:虚构|编造|展示|写入)"
        r".{0,20}(?:客户|案例|素材|内部|要求)"
    ),
    re.compile(r"(?:只|仅)(?:使用|看).{0,20}(?:入库|知识库).{0,12}(?:素材|资料)"),
)


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ContractError(f"{field} must be a string")
    return value.strip()


def _string_set(value: Any, field: str, *, maximum: int | None = None) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ContractError(f"{field} must be a list of strings")
    normalized = {_required_text(item, field) for item in value}
    if maximum is not None and len(normalized) > maximum:
        raise ContractError(f"{field} may contain at most {maximum} items")
    return sorted(normalized)


def _validate_reader_visible_must_keep(items: list[str]) -> list[str]:
    for item in items:
        if any(pattern.search(item) for pattern in _PRIVATE_MUST_KEEP_PATTERNS):
            raise ContractError(
                "must_keep is reader-visible exact content; put private production requirements "
                "in user_thoughts or must_avoid"
            )
    return items


def validate_task_input(payload: Any) -> dict[str, Any]:
    """Validate and canonicalize one user task without resolving real resources."""

    if not isinstance(payload, dict):
        raise ContractError("task input must be an object")

    unknown = sorted(set(payload) - _ALLOWED_KEYS)
    if unknown:
        raise ContractError(f"unknown task input fields: {', '.join(unknown)}")

    knowledge_base = _required_text(payload.get("knowledge_base"), "knowledge_base")
    raw_ip = _required_text(payload.get("ip"), "ip")
    ip = "none" if raw_ip.casefold() == "none" or raw_ip == "无IP" else raw_ip

    normalized: dict[str, Any] = {
        "knowledge_base": knowledge_base,
        "ip": ip,
        "topic": "",
        "references": _string_set(payload.get("references"), "references", maximum=5),
        "user_thoughts": "",
        "must_keep": _validate_reader_visible_must_keep(
            _string_set(payload.get("must_keep"), "must_keep")
        ),
        "must_avoid": _string_set(payload.get("must_avoid"), "must_avoid"),
        "target_audience_override": "",
        "article_length_preference": "",
    }
    for key in _OPTIONAL_TEXT_KEYS:
        normalized[key] = _optional_text(payload.get(key), key)
    return normalized
