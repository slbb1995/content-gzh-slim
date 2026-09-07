"""Directly project approved fixture refs without any post-Gate search."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FrozenProjectionError(ValueError):
    """Raised when a P3 selection changes IP, candidates, or approved 04 refs."""


def _string_list(value: Any, field: str, maximum: int | None = None) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise FrozenProjectionError(f"{field} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise FrozenProjectionError(f"{field} contains duplicates")
    if maximum is not None and len(value) > maximum:
        raise FrozenProjectionError(f"{field} exceeds limit {maximum}")
    return value


class FrozenFixtureProjector:
    def __init__(self, catalog_path: str | Path) -> None:
        with Path(catalog_path).open("r", encoding="utf-8") as handle:
            catalog = json.load(handle)
        entries = catalog.get("knowledge_bases") if isinstance(catalog, dict) else None
        if not isinstance(entries, list):
            raise FrozenProjectionError("fixture catalog must contain knowledge_bases")
        self._entries = entries

    def _knowledge_base(self, ref: str) -> dict[str, Any]:
        matches = [item for item in self._entries if item.get("ref") == ref]
        if len(matches) != 1:
            raise FrozenProjectionError("approved knowledge base must resolve exactly once")
        return matches[0]

    @staticmethod
    def _assets_by_ref(assets: Any, field: str) -> dict[str, dict[str, Any]]:
        if not isinstance(assets, list):
            raise FrozenProjectionError(f"{field} must be a list")
        result = {}
        for item in assets:
            ref = item.get("ref") if isinstance(item, dict) else None
            if not isinstance(ref, str) or ref in result:
                raise FrozenProjectionError(f"{field} contains an invalid or duplicate ref")
            result[ref] = item
        return result

    def project(
        self,
        selection: dict[str, Any],
        run: dict[str, Any],
        approved_direction: dict[str, Any],
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        if selection.get("schema_version") != 1:
            raise FrozenProjectionError("selection must be schema_version 1")
        knowledge_base = self._knowledge_base(run["knowledge_base_identity"]["ref"])
        option = approved_direction["approved_option"]
        frozen = approved_direction["frozen_candidates"]

        fragment_ids = _string_list(
            selection.get("selected_05_fragment_ids"), "selected_05_fragment_ids", 3
        )
        ip = run["ip_identity"]
        if ip["status"] in {"none", "unused"}:
            if fragment_ids:
                raise FrozenProjectionError("none or unused IP cannot select 05 fragments")
            profile_context = {
                "ip_ref": None,
                "status": ip["status"],
                "core_anchors": {},
                "confirmed_fragments": [],
            }
        else:
            profiles = knowledge_base.get("profiles", [])
            matches = [
                profile
                for profile in profiles
                if profile.get("ref") == ip.get("resolved_ref")
                and profile.get("name") == ip.get("requested_name")
            ]
            if len(matches) != 1:
                raise FrozenProjectionError("P3 may read only the same resolved IP")
            profile = matches[0]
            available_fragments = {
                item.get("fragment_id"): item
                for item in profile.get("confirmed_fragments", [])
                if isinstance(item, dict)
            }
            if not set(fragment_ids).issubset(available_fragments):
                raise FrozenProjectionError("selected 05 fragment is not from the same IP")
            fragments = []
            for fragment_id in fragment_ids:
                fragment = available_fragments[fragment_id]
                if fragment.get("status") != "confirmed":
                    raise FrozenProjectionError("05 fragment must be confirmed")
                fragments.append(
                    {
                        "fragment_id": fragment_id,
                        "fragment_type": fragment.get("fragment_type"),
                        "text": fragment.get("text"),
                        "status": "confirmed",
                    }
                )
            profile_context = {
                "ip_ref": profile["ref"],
                "status": ip["status"],
                "core_anchors": profile.get("anchors", {}),
                "confirmed_fragments": fragments,
            }

        selected_03 = _string_list(selection.get("selected_03_refs"), "selected_03_refs", 5)
        if not set(selected_03).issubset(set(option["selected_sources"]["business_refs"])):
            raise FrozenProjectionError("03 selection must stay inside approved Gate A refs")
        if not set(selected_03).issubset(set(frozen["business_candidate_refs"])):
            raise FrozenProjectionError("03 selection must stay inside P2 frozen candidates")
        business_assets = self._assets_by_ref(knowledge_base.get("business_assets"), "03 assets")
        business_context = []
        for ref in selected_03:
            asset = business_assets.get(ref)
            if asset is None or asset.get("fact_status") != "confirmed":
                raise FrozenProjectionError("selected 03 fragment must be a confirmed frozen fact")
            business_context.append(
                {
                    "ref": ref,
                    "title": asset.get("title"),
                    "fragment": asset.get("excerpt"),
                    "fact_status": "confirmed",
                    "source_metadata": asset.get("source_metadata", {}),
                }
            )

        peer_refs = _string_list(
            selection.get("selected_04_peer_refs"), "selected_04_peer_refs", 3
        )
        method_refs = _string_list(
            selection.get("selected_04_method_refs"), "selected_04_method_refs", 2
        )
        if peer_refs != frozen["selected_peer_refs"]:
            raise FrozenProjectionError("Gate A selected peer refs must be reused exactly")
        if method_refs != frozen["selected_method_refs"]:
            raise FrozenProjectionError("Gate A selected method refs must be reused exactly")
        peer_assets = self._assets_by_ref(
            knowledge_base.get("peer_content_assets"), "04 peer assets"
        )
        method_assets = self._assets_by_ref(
            knowledge_base.get("content_method_assets"), "04 method assets"
        )
        selected_peer = [
            {"ref": ref, "title": peer_assets[ref].get("title"), "fragment": peer_assets[ref].get("excerpt"), "source_metadata": peer_assets[ref].get("source_metadata", {})}
            for ref in peer_refs
            if ref in peer_assets
        ]
        selected_method = [
            {"ref": ref, "title": method_assets[ref].get("title"), "fragment": method_assets[ref].get("excerpt"), "source_metadata": method_assets[ref].get("source_metadata", {})}
            for ref in method_refs
            if ref in method_assets
        ]
        if len(selected_peer) != len(peer_refs) or len(selected_method) != len(method_refs):
            raise FrozenProjectionError("approved 04 ref is missing from the same fixture knowledge base")

        analysis_by_ref = {
            item["reference_ref"]: item for item in analysis.get("reference_analyses", [])
        }
        mechanism_selections = selection.get("reference_mechanisms")
        if not isinstance(mechanism_selections, list):
            raise FrozenProjectionError("reference_mechanisms must be a list")
        if {item.get("reference_ref") for item in mechanism_selections} != set(
            frozen["reference_refs"]
        ):
            raise FrozenProjectionError("reference mechanism refs must match approved references exactly")
        selected_mechanisms = []
        for item in mechanism_selections:
            ref = item["reference_ref"]
            analyzed = analysis_by_ref.get(ref)
            if analyzed is None:
                raise FrozenProjectionError("reference mechanism has no matching P2 analysis")
            transferable = _string_list(
                item.get("transferable_mechanisms"), "transferable_mechanisms"
            )
            forbidden = _string_list(item.get("forbidden_transfers"), "forbidden_transfers")
            if not transferable or not forbidden:
                raise FrozenProjectionError("reference mechanisms and forbidden boundaries are required")
            if not set(transferable).issubset(set(analyzed["transferable_mechanisms"])):
                raise FrozenProjectionError("selected mechanism was not present in P2 analysis")
            if not set(forbidden).issubset(set(analyzed["forbidden_transfers"])):
                raise FrozenProjectionError("forbidden boundary was not present in P2 analysis")
            selected_mechanisms.append(
                {
                    "reference_ref": ref,
                    "transferable_mechanisms": transferable,
                    "forbidden_transfers": forbidden,
                }
            )

        missing_evidence = _string_list(selection.get("missing_evidence"), "missing_evidence")
        preview = selection.get("save_target_preview")
        manifest_preview = knowledge_base.get("save_target")
        if isinstance(manifest_preview, dict):
            if preview is not None and preview != manifest_preview:
                raise FrozenProjectionError("save target differs from the frozen Manifest")
            preview = manifest_preview
        if not isinstance(preview, dict):
            raise FrozenProjectionError("save_target_preview must be an object")
        if preview.get("backend") != run["knowledge_base_identity"]["backend"]:
            raise FrozenProjectionError("save preview backend must match current knowledge base")
        if preview.get("status") != "preview_only_not_writable":
            raise FrozenProjectionError("P3 save target must remain a non-writable preview")
        target_ref = preview.get("target_ref")
        if not isinstance(target_ref, str) or not target_ref.strip():
            raise FrozenProjectionError("P3 save preview target_ref is invalid")
        if not isinstance(manifest_preview, dict) and not target_ref.startswith("fixture://"):
            raise FrozenProjectionError("P3 fixture save preview must use fixture://")

        excluded_business = []
        for ref in frozen["business_candidate_refs"]:
            if ref in selected_03:
                continue
            asset = business_assets.get(ref)
            excluded_business.append(
                {
                    "ref": ref,
                    "title": asset.get("title") if asset else None,
                    "reason": "not selected for final business context",
                    "fact_status": asset.get("fact_status") if asset else "unknown",
                }
            )

        return {
            "selected_05_profile_context": profile_context,
            "selected_03_business_context": business_context,
            "selected_04_content_assets": selected_peer,
            "selected_04_method_assets": selected_method,
            "selected_reference_mechanisms": selected_mechanisms,
            "excluded_business_candidates": excluded_business,
            "missing_evidence": missing_evidence,
            "save_target_preview": preview,
        }
