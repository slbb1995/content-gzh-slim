from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from runtime.analysis_contract import AnalysisContractError, validate_analysis
from runtime.contracts import validate_task_input
from runtime.fixture_adapter import FixtureAdapter
from runtime.gate_a import DirectionContractError, build_direction, classify_gate_a_decision
from runtime.p2_pipeline import P2Pipeline
from runtime.reference_prep import FixtureReferencePreparer, ReferencePrepError
from runtime.retrieval_search import ControlledFixtureRetriever
from runtime.run_store import RunStore


FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = FIXTURES / "p2_catalog.json"


def read_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class P2RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_task = read_json("p2_task.json")
        self.task = validate_task_input(self.raw_task)
        self.adapter = FixtureAdapter(CATALOG)
        self.knowledge_base, self.ip = self.adapter.resolve(
            self.task["knowledge_base"], self.task["ip"]
        )

    def _create_run(self, root: str, task=None, knowledge_base=None, ip=None):
        return RunStore(root).create_or_resume(
            task or self.task,
            knowledge_base or self.knowledge_base,
            ip or self.ip,
        ).run

    def test_retrieval_reads_05_first_and_enforces_all_budgets(self) -> None:
        result = ControlledFixtureRetriever(CATALOG).prepare(
            self.task, self.knowledge_base, self.ip
        )

        self.assertEqual([item["role"] for item in result["access_log"]], ["05", "03", "04"])
        self.assertEqual(result["access_log"][0]["operation"], "read_requested_ip_anchor")
        self.assertEqual(len(result["business_candidates"]), 5)
        self.assertEqual(len(result["peer_candidates"]), 3)
        self.assertEqual(len(result["method_candidates"]), 2)
        self.assertEqual(result["access_log"][1]["full_document_count"], 0)
        self.assertEqual(result["access_log"][2]["full_document_count"], 0)
        self.assertNotIn(
            "fixture://obsidian/kb-alpha/03/b6",
            {item["ref"] for item in result["business_candidates"]},
        )

    def test_limited_and_unused_ip_warn_but_continue(self) -> None:
        retriever = ControlledFixtureRetriever(CATALOG)

        limited_task = validate_task_input({**self.raw_task, "ip": "有限示例", "references": []})
        limited_kb, limited_ip = self.adapter.resolve(
            limited_task["knowledge_base"], limited_task["ip"]
        )
        limited = retriever.prepare(limited_task, limited_kb, limited_ip)
        self.assertEqual(limited["ip_status"], "limited")
        self.assertTrue(limited["warnings"])
        self.assertIsNotNone(limited["ip_anchor"])

        unused_task = validate_task_input({**self.raw_task, "ip": "不存在示例", "references": []})
        unused_kb, unused_ip = self.adapter.resolve(
            unused_task["knowledge_base"], unused_task["ip"]
        )
        unused = retriever.prepare(unused_task, unused_kb, unused_ip)
        self.assertEqual(unused["ip_status"], "unused")
        self.assertTrue(unused["warnings"])
        self.assertIsNone(unused["ip_anchor"])
        self.assertLessEqual(len(unused["business_candidates"]), 5)

    def test_reference_prep_rejects_summary_as_full_article(self) -> None:
        preparer = FixtureReferencePreparer(CATALOG)
        with self.assertRaisesRegex(ReferencePrepError, "not a complete body"):
            preparer.prepare(["fixture://reference/summary-only"])

    def test_analysis_contract_rejects_shallow_output(self) -> None:
        snapshots = FixtureReferencePreparer(CATALOG).prepare(self.task["references"])
        shallow = read_json("p2_analysis.json")
        del shallow["reference_analyses"][0]["argument_and_evidence"]
        with self.assertRaisesRegex(AnalysisContractError, "missing deep fields"):
            validate_analysis(shallow, snapshots)

    def test_multi_reference_analysis_requires_comparison_and_conflict_resolution(self) -> None:
        snapshots = FixtureReferencePreparer(CATALOG).prepare(
            ["fixture://reference/one", "fixture://reference/two"]
        )
        payload = read_json("p2_analysis.json")
        second = copy.deepcopy(payload["reference_analyses"][0])
        second["reference_ref"] = "fixture://reference/two"
        second["title_mechanism"] = "用停止换模型的动作指令制造紧迫感。"
        payload["reference_analyses"].append(second)
        payload["multi_reference_synthesis"] = {
            "common_mechanisms": ["都把问题从模型能力转向协作流程"],
            "differences": ["第一篇用结果反差，第二篇用停止动作"],
            "conflict_resolution": "当前任务保留结果反差作为开头，清单结构用于正文推进。",
        }
        validated = validate_analysis(payload, snapshots)
        self.assertEqual(len(validated["reference_analyses"]), 2)

        payload["multi_reference_synthesis"] = None
        with self.assertRaisesRegex(AnalysisContractError, "complete synthesis"):
            validate_analysis(payload, snapshots)

    def test_pipeline_stops_at_gate_a_and_creates_only_p2_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = self._create_run(temporary)
            pipeline = P2Pipeline(temporary, CATALOG)
            result = pipeline.run(
                run["run_id"],
                FIXTURES / "p2_analysis.json",
                FIXTURES / "p2_direction.json",
            )
            stored_run = RunStore(temporary).load(run["run_id"])
            names = {
                path.name
                for path in (Path(temporary) / "runs" / run["run_id"]).iterdir()
                if path.is_file()
            }

            resumed = pipeline.run(
                run["run_id"],
                Path(temporary) / "missing-analysis.json",
                Path(temporary) / "missing-direction.json",
            )

        self.assertEqual(stored_run["status"], "waiting_direction")
        self.assertEqual(
            names,
            {
                "run.json",
                "reference_snapshot_v1.json",
                "analysis_v1.json",
                "direction_v1.json",
                "retrieval_receipt.json",
            },
        )
        self.assertFalse(result["resumed"])
        self.assertTrue(resumed["resumed"])
        self.assertEqual(result["retrieval_receipt"]["totals"]["context_packs"], 0)
        self.assertNotIn("article_context_v1.json", names)
        self.assertIn("# Gate A：方向确认", result["gate_a"])
        self.assertIn("03 业务素材", result["gate_a"])
        self.assertIn("其他模糊回复不会批准", result["gate_a"])

    def test_gate_a_marks_candidates_as_proposed_not_final(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = self._create_run(temporary)
            result = P2Pipeline(temporary, CATALOG).run(
                run["run_id"],
                FIXTURES / "p2_analysis.json",
                FIXTURES / "p2_direction.json",
            )

        entries = result["retrieval_receipt"]["entries"]
        self.assertTrue(any(item["gate_a_status"] == "proposed" for item in entries))
        self.assertTrue(all(item["final_selection_status"] == "pending_gate_a" for item in entries))
        self.assertTrue(all(item["in_context_pack"] is False for item in entries))

    def test_ambiguous_gate_reply_does_not_approve(self) -> None:
        self.assertEqual(classify_gate_a_decision("确认方向"), "approve")
        self.assertEqual(classify_gate_a_decision("需要修改：换一个开头"), "revise")
        self.assertEqual(classify_gate_a_decision("不采用"), "reject")
        self.assertEqual(classify_gate_a_decision("可以"), "ambiguous")
        self.assertEqual(classify_gate_a_decision("继续"), "ambiguous")

    def test_no_direction_requires_exactly_three_options(self) -> None:
        no_direction = validate_task_input(
            {
                "knowledge_base": "fixture-kb-alpha",
                "ip": "示例甲",
                "topic": "",
                "user_thoughts": "",
                "references": [],
            }
        )
        kb, ip = self.adapter.resolve(no_direction["knowledge_base"], no_direction["ip"])
        retrieval = ControlledFixtureRetriever(CATALOG).prepare(no_direction, kb, ip)
        analysis = validate_analysis(
            {"schema_version": 1, "reference_analyses": [], "multi_reference_synthesis": None},
            {"schema_version": 1, "references": []},
        )
        with tempfile.TemporaryDirectory() as temporary:
            run = self._create_run(temporary, no_direction, kb, ip)

        base = copy.deepcopy(read_json("p2_direction.json")["options"][0])
        base["selected_sources"]["reference_refs"] = []
        base["must_keep"] = no_direction["must_keep"]
        base["must_avoid"] = no_direction["must_avoid"]
        options = []
        for index in range(3):
            option = copy.deepcopy(base)
            option["option_id"] = f"option-{index + 1}"
            option["title"] = f"虚构候选方向 {index + 1}"
            options.append(option)
        direction = build_direction(
            {"schema_version": 1, "mode": "options", "options": options},
            run,
            retrieval,
            analysis,
        )
        self.assertEqual(direction["mode"], "options")
        self.assertEqual(len(direction["options"]), 3)

    def test_limited_ip_cannot_add_unsupported_first_person_claim(self) -> None:
        limited_task = validate_task_input({**self.raw_task, "ip": "有限示例"})
        kb, ip = self.adapter.resolve(limited_task["knowledge_base"], limited_task["ip"])
        retrieval = ControlledFixtureRetriever(CATALOG).prepare(limited_task, kb, ip)
        snapshots = FixtureReferencePreparer(CATALOG).prepare(limited_task["references"])
        analysis = validate_analysis(read_json("p2_analysis.json"), snapshots)
        with tempfile.TemporaryDirectory() as temporary:
            run = self._create_run(temporary, limited_task, kb, ip)
        template = read_json("p2_direction.json")
        template["options"][0]["first_person_claims"] = ["我曾帮助客户获得三倍增长"]
        with self.assertRaisesRegex(DirectionContractError, "unsupported first-person"):
            build_direction(template, run, retrieval, analysis)

    def test_fixture_data_contains_no_real_paths_or_tokens(self) -> None:
        fixture_text = CATALOG.read_text(encoding="utf-8")
        self.assertNotIn("/Users/", fixture_text)
        self.assertNotIn("tenant_access_token", fixture_text.casefold())
        self.assertNotIn("app_secret", fixture_text.casefold())


if __name__ == "__main__":
    unittest.main()
