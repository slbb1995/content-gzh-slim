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

    def test_reader_visible_sources_and_business_requirements_are_not_private_controls(self) -> None:
        texts = (
            "本文只使用公开资料核对产权，不采信销售口头承诺。",
            "客户的生产要求必须在合同中写清楚。",
            "本文只看项目资料中的产权证号与维修记录，帮助购房人做核对。",
            "销售人员不得虚构客户案例或夸大成果。",
            "公开资料尚不能证明这项服务已经上线。",
        )
        for text in texts:
            with self.subTest(text=text):
                task = validate_task_input({"knowledge_base": "synthetic", "ip": "none", "must_keep": [text]})
                self.assertEqual(task["must_keep"], [text])
                self.assertEqual(validate_draft_body(text, {**minimal_context(), "must_keep": [text]}), text)

    def test_private_controls_use_existing_writing_requirements_and_do_not_leak(self) -> None:
        requirement = "写作要求：不要生造客户案例。"
        task = validate_task_input({"knowledge_base": "synthetic", "ip": "none", "writing_requirements": [requirement]})
        self.assertEqual(task["writing_requirements"], [requirement])
        self.assertEqual(task["must_keep"], [])
        with self.assertRaises(ContractError):
            validate_task_input({**task, "must_keep": [requirement]})
        with self.assertRaises(DraftContractError):
            validate_draft_body(requirement, {**minimal_context(), "task_input": task})
        with self.assertRaises(DraftContractError):
            validate_draft_body("最后把写作要求和素材边界说清楚。", {**minimal_context(), "task_input": task})

    def test_unrelated_evidence_checks_and_legacy_task_shape_remain(self) -> None:
        task = validate_task_input({"knowledge_base": "synthetic", "ip": "none"})
        self.assertNotIn("writing_requirements", task)
        with self.assertRaises(DraftContractError):
            validate_draft_body("这个方法让效果提升50%。", {**minimal_context(), "fact_and_candidate_boundaries": {"missing_evidence": ["缺少增长数字"]}})

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
