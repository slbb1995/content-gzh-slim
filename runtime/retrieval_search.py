"""Bounded 05→03→04 candidate retrieval from a frozen source catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RetrievalError(ValueError):
    """Raised when fixture retrieval would cross a Run boundary or exceed its contract."""


class ControlledFixtureRetriever:
    BUSINESS_LIMIT = 5
    PEER_LIMIT = 3
    METHOD_LIMIT = 2

    def __init__(self, catalog_path: str | Path) -> None:
        with Path(catalog_path).open("r", encoding="utf-8") as handle:
            catalog = json.load(handle)
        entries = catalog.get("knowledge_bases") if isinstance(catalog, dict) else None
        if not isinstance(entries, list):
            raise RetrievalError("fixture catalog must contain knowledge_bases")
        self._entries = entries

    def _knowledge_base(self, ref: str) -> dict[str, Any]:
        matches = [entry for entry in self._entries if entry.get("ref") == ref]
        if len(matches) != 1:
            raise RetrievalError("Run knowledge base must match exactly one fixture knowledge base")
        return matches[0]

    @staticmethod
    def _bounded_candidates(
        assets: Any,
        query: str,
        limit: int,
        role: str,
        asset_type: str,
        preselected: bool = False,
    ) -> list[dict[str, Any]]:
        if not isinstance(assets, list):
            raise RetrievalError(f"fixture {role} assets must be a list")
        ranked: list[tuple[int, str, dict[str, Any]]] = []
        folded_query = query.casefold()
        for asset in assets:
            keywords = asset.get("keywords", [])
            if not isinstance(keywords, list):
                raise RetrievalError(f"fixture {role} keywords must be a list")
            score = sum(
                1
                for keyword in keywords
                if isinstance(keyword, str) and keyword.casefold() in folded_query
            )
            if score > 0 or preselected:
                ranked.append((score, str(asset.get("ref", "")), asset))
        ranked.sort(key=lambda item: (-item[0], item[1]))

        candidates = []
        for score, _, asset in ranked[:limit]:
            ref = asset.get("ref")
            excerpt = asset.get("excerpt")
            if not isinstance(ref, str) or not ref.startswith(("fixture://", "content-source://", "obsidian://", "feishu://")):
                raise RetrievalError(f"{role} ref must use a controlled source scheme")
            if not isinstance(excerpt, str) or not excerpt.strip():
                raise RetrievalError(f"fixture {role} excerpt is required")
            candidates.append(
                {
                    "role": role,
                    "asset_type": asset_type,
                    "ref": ref,
                    "title": str(asset.get("title", "")),
                    "excerpt": excerpt.strip(),
                    "fact_status": asset.get("fact_status", "not_applicable"),
                    "score": score,
                    "snippet_count": 1,
                    "character_count": len(excerpt.strip()),
                    "source_metadata": asset.get("source_metadata", {}),
                }
            )
        return candidates

    def prepare(
        self,
        task_input: dict[str, Any],
        knowledge_base_identity: dict[str, Any],
        ip_identity: dict[str, Any],
    ) -> dict[str, Any]:
        knowledge_base = self._knowledge_base(knowledge_base_identity["ref"])
        access_log: list[dict[str, Any]] = []
        warnings: list[str] = []

        ip_anchor = None
        ip_status = ip_identity["status"]
        if ip_status == "none":
            access_log.append({"sequence": 1, "role": "05", "operation": "skipped_none_ip"})
        elif ip_status == "unused":
            warnings.append("指定 IP 没有可靠 fixture 资料，本次按无 IP 写法继续。")
            access_log.append({"sequence": 1, "role": "05", "operation": "missing_ip_continue"})
        else:
            profiles = knowledge_base.get("profiles", [])
            matches = [
                profile
                for profile in profiles
                if profile.get("ref") == ip_identity.get("resolved_ref")
                and profile.get("name") == ip_identity.get("requested_name")
            ]
            if len(matches) != 1:
                raise RetrievalError("resolved IP must match exactly one profile in this knowledge base")
            profile = matches[0]
            if profile.get("status") != ip_status:
                raise RetrievalError("Run IP status does not match the current knowledge base fixture")
            anchors = profile.get("anchors")
            if not isinstance(anchors, dict):
                raise RetrievalError("fixture IP anchors must be an object")
            ip_anchor = {
                "ref": profile["ref"],
                "name": profile["name"],
                "status": ip_status,
                "anchors": anchors,
                "snippet_count": len(anchors),
                "character_count": len(json.dumps(anchors, ensure_ascii=False)),
            }
            if ip_status == "limited":
                warnings.append("指定 IP 的 fixture 资料有限，只使用已确认锚点，不补造个人事实。")
            access_log.append(
                {
                    "sequence": 1,
                    "role": "05",
                    "operation": "read_requested_ip_anchor",
                    "ref": profile["ref"],
                }
            )

        anchor_text = ""
        if ip_anchor:
            anchor_text = json.dumps(ip_anchor["anchors"], ensure_ascii=False)
        query = " ".join(
            [
                task_input.get("topic", ""),
                task_input.get("user_thoughts", ""),
                task_input.get("target_audience_override", ""),
                anchor_text,
            ]
        )

        business = self._bounded_candidates(
            knowledge_base.get("business_assets", []),
            query,
            self.BUSINESS_LIMIT,
            "03",
            "business_asset",
            knowledge_base.get("candidates_preselected", False),
        )
        access_log.append(
            {
                "sequence": 2,
                "role": "03",
                "operation": "metadata_search_then_excerpt_read",
                "candidate_count": len(business),
                "full_document_count": knowledge_base.get("source_read_counts", {}).get("03", 0),
            }
        )

        peer = self._bounded_candidates(
            knowledge_base.get("peer_content_assets", []),
            query,
            self.PEER_LIMIT,
            "04",
            "peer_content_asset",
            knowledge_base.get("candidates_preselected", False),
        )
        method = self._bounded_candidates(
            knowledge_base.get("content_method_assets", []),
            query,
            self.METHOD_LIMIT,
            "04",
            "content_method_asset",
            knowledge_base.get("candidates_preselected", False),
        )
        access_log.append(
            {
                "sequence": 3,
                "role": "04",
                "operation": "metadata_search_then_excerpt_read",
                "peer_candidate_count": len(peer),
                "method_candidate_count": len(method),
                "full_document_count": knowledge_base.get("source_read_counts", {}).get("04", len(peer) + len(method) if knowledge_base.get("candidates_preselected") else 0),
            }
        )
        if not task_input.get("references"):
            if not peer:
                warnings.append("本次未找到可用的 04 同行内容；不能宣称已借鉴库内同行，需检查当前想法与业务资料是否足以展开。")
            if not method:
                warnings.append("本次未找到可用的 04 方法；不能宣称已使用库内结构，需说明自行组织的依据或补充资料。")
        return {
            "ip_anchor": ip_anchor,
            "ip_status": ip_status,
            "warnings": warnings,
            "business_candidates": business,
            "peer_candidates": peer,
            "method_candidates": method,
            "access_log": access_log,
        }
