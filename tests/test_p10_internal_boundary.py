from __future__ import annotations

import unittest
from pathlib import Path

from runtime.contracts import ContractError, validate_task_input
from runtime.draft_contract import DraftContractError, validate_draft_body


ROOT = Path(__file__).resolve().parents[1]


def minimal_context() -> dict:
    return {
        "must_keep": [],
        "must_avoid": [],
        "fact_and_candidate_boundaries": {
            "excluded_business_candidates": [],
            "missing_evidence": [],
        },
    }


class P10InternalBoundaryTests(unittest.TestCase):
    def test_private_production_requirement_cannot_enter_must_keep(self) -> None:
        with self.assertRaisesRegex(ContractError, "must_keep is reader-visible"):
            validate_task_input(
                {
                    "knowledge_base": "fixture-kb-alpha",
                    "ip": "示例甲",
                    "topic": "示例选题",
                    "must_keep": ["这里不讲客户故事，只看已经入库的项目资料。"],
                }
            )

        task = validate_task_input(
            {
                "knowledge_base": "fixture-kb-alpha",
                "ip": "示例甲",
                "topic": "示例选题",
                "must_keep": ["本文不构成投资建议。"],
            }
        )
        self.assertEqual(task["must_keep"], ["本文不构成投资建议。"])

    def test_draft_rejects_internal_requirements_exposed_to_readers(self) -> None:
        leaked_bodies = (
            "这里不讲客户故事，只看已经入库的项目资料。",
            "最后把写作要求和素材边界说清楚。",
            "因为知识库没有客户案例，所以本文改用项目资料来写。",
        )
        for body in leaked_bodies:
            with self.subTest(body=body), self.assertRaisesRegex(
                DraftContractError, "internal production requirement"
            ):
                validate_draft_body(body, minimal_context())

    def test_draft_allows_reader_facing_discussion_of_property_records(self) -> None:
        body = "判断一套老别墅值不值得买，需要先核对产权资料和历年维修记录。"
        self.assertEqual(validate_draft_body(body, minimal_context()), body)

    def test_analyzer_and_writer_contracts_keep_controls_private(self) -> None:
        analyzer = (
            ROOT / "skills" / "content-gzh-analyzer" / "references" / "analysis-contract.md"
        ).read_text(encoding="utf-8")
        writer = (ROOT / "skills" / "content-gzh-writer" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("reader-visible exact content", analyzer)
        self.assertIn("private production controls", writer)
        self.assertIn("must not be quoted or paraphrased to the reader", writer)


if __name__ == "__main__":
    unittest.main()
