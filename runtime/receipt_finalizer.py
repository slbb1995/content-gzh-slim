"""Finalize P2 retrieval evidence after the single Context Pack is created."""

from __future__ import annotations

from typing import Any


class ReceiptFinalizationError(ValueError):
    """Raised when receipt identities or selected refs do not match the Context Pack."""


def finalize_retrieval_receipt(
    receipt: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    if receipt.get("run_id") != context["run_identity"]["run_id"]:
        raise ReceiptFinalizationError("receipt Run does not match Context Pack")
    selected = {
        "05": {
            context["selected_05_profile_context"].get("ip_ref")
        }
        if context["selected_05_profile_context"].get("confirmed_fragments") or context["selected_05_profile_context"].get("profile_documents")
        else set(),
        "03": {item["ref"] for item in context["selected_03_business_context"]},
        "04": {
            item["ref"]
            for item in (
                context["selected_04_content_assets"] + context["selected_04_method_assets"]
            )
        },
        "reference": {
            item["reference_ref"] for item in context["selected_reference_mechanisms"]
        },
    }
    updated_entries = []
    for entry in receipt.get("entries", []):
        role = entry.get("role")
        if role not in selected:
            raise ReceiptFinalizationError("receipt contains an unknown source role")
        is_selected = entry.get("source_ref") in selected[role]
        updated = dict(entry)
        updated["final_selection_status"] = "selected" if is_selected else "not_selected"
        updated["in_context_pack"] = is_selected
        if is_selected:
            if role == "reference":
                has_source = any(item.get("source_snapshot") for item in context["selected_reference_mechanisms"] if item["reference_ref"] == entry["source_ref"])
                updated["selected_use"] = "mechanisms and attributed full frozen source" if has_source else "benchmark mechanisms only; full body excluded"
            elif role == "05":
                updated["selected_use"] = "same-IP profile documents and selected confirmed fragments"
            updated["not_selected_reason"] = None
        elif updated.get("not_selected_reason") is None:
            updated["not_selected_reason"] = "not selected for final Article Context"
        updated_entries.append(updated)

    result = dict(receipt)
    result["entries"] = updated_entries
    totals = dict(receipt.get("totals", {}))
    totals["context_packs"] = 1
    result["totals"] = totals
    return result
