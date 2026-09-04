"""Assemble and validate the only Writer-readable Article Context Pack."""

from __future__ import annotations

from typing import Any

from .approved_direction import canonical_digest


class ContextContractError(ValueError):
    """Raised when projected roles are mixed or the Context root exceeds SPEC 11.2."""


CONTEXT_ROOT_FIELDS = {
    "schema_version",
    "run_identity",
    "knowledge_base_identity",
    "ip_identity_and_status",
    "task_input",
    "approved_direction",
    "writer_mode",
    "voice_and_viewpoint",
    "selected_05_profile_context",
    "selected_03_business_context",
    "selected_04_content_assets",
    "selected_04_method_assets",
    "selected_reference_mechanisms",
    "must_keep",
    "must_avoid",
    "fact_and_candidate_boundaries",
    "business_link",
    "save_target_preview",
}


def build_article_context(
    run: dict[str, Any],
    approved_direction: dict[str, Any],
    projection: dict[str, Any],
    selection: dict[str, Any],
) -> dict[str, Any]:
    option = approved_direction["approved_option"]
    task = run["task_input"]
    if set(option.get("must_keep", [])) != set(task.get("must_keep", [])):
        raise ContextContractError("approved direction must_keep does not match frozen task input")
    if set(option.get("must_avoid", [])) != set(task.get("must_avoid", [])):
        raise ContextContractError("approved direction must_avoid does not match frozen task input")
    if option.get("writer_mode") not in {"ganhuo", "huati"}:
        raise ContextContractError("approved writer_mode is invalid")
    if len(projection["selected_03_business_context"]) > 5:
        raise ContextContractError("03 context exceeds five fragments")
    if len(projection["selected_04_content_assets"]) > 3:
        raise ContextContractError("04 peer context exceeds three fragments")
    if len(projection["selected_04_method_assets"]) > 2:
        raise ContextContractError("04 method context exceeds two fragments")

    boundaries = {
        "approved_fact_boundaries": option["fact_boundaries"],
        "confirmed_fact_policy": "Only selected 03 fragments marked confirmed may support business facts.",
        "candidate_material_policy": "Excluded candidates are not facts and must not appear as confirmed claims.",
        "excluded_business_candidates": projection["excluded_business_candidates"],
        "missing_evidence": projection["missing_evidence"],
        "reference_policy": (
            "References supply mechanisms and forbidden-transfer boundaries only; source bodies, author facts, "
            "cases, screenshots, data, and recognizable wording are excluded."
        ),
    }
    context = {
        "schema_version": 1,
        "run_identity": {
            "run_id": run["run_id"],
            "input_digest": run["input_digest"],
            "context_version": 1,
            "selection_digest": canonical_digest(selection),
            "gate_a": {
                "decision": approved_direction["gate_receipt"]["decision"],
                "approved_at": approved_direction["gate_receipt"]["at"],
                "approved_option_id": option["option_id"],
                "direction_digest": approved_direction["direction_digest"],
            },
        },
        "knowledge_base_identity": run["knowledge_base_identity"],
        "ip_identity_and_status": run["ip_identity"],
        "task_input": task,
        "approved_direction": option,
        "writer_mode": option["writer_mode"],
        "voice_and_viewpoint": {
            "voice_mode": option["voice_mode"],
            "professional_judgments": option["professional_judgments"],
            "reader_situations": option["reader_situations"],
            "verification_actions": option["verification_actions"],
            "profile_anchors": {
                key: value
                for key, value in projection["selected_05_profile_context"].get(
                    "core_anchors", {}
                ).items()
                if key
                in {
                    "expression_style",
                    "professional_judgments",
                    "reader_empathy",
                    "business_boundary",
                }
            },
            "opinion_policy": (
                "Professional judgments may use the IP voice; first-person experiences require an explicitly "
                "selected confirmed fragment."
            ),
        },
        "selected_05_profile_context": projection["selected_05_profile_context"],
        "selected_03_business_context": projection["selected_03_business_context"],
        "selected_04_content_assets": projection["selected_04_content_assets"],
        "selected_04_method_assets": projection["selected_04_method_assets"],
        "selected_reference_mechanisms": projection["selected_reference_mechanisms"],
        "must_keep": task["must_keep"],
        "must_avoid": task["must_avoid"],
        "fact_and_candidate_boundaries": boundaries,
        "business_link": option["business_connection"],
        "save_target_preview": projection["save_target_preview"],
    }
    if set(context) != CONTEXT_ROOT_FIELDS:
        raise ContextContractError("Article Context root differs from Master SPEC 11.2")
    return context


def verify_writer_input(context: dict[str, Any], run_id: str, selection: dict[str, Any]) -> None:
    if set(context) != CONTEXT_ROOT_FIELDS:
        raise ContextContractError("stored Article Context has unexpected root fields")
    if context.get("run_identity", {}).get("run_id") != run_id:
        raise ContextContractError("stored Article Context belongs to a different Run")
    if context["run_identity"].get("selection_digest") != canonical_digest(selection):
        raise ContextContractError("different P3 selection cannot replace or resume this Context Pack")
