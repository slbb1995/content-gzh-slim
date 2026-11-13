from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path

from runtime.artifact_store import ArtifactStoreError
from runtime.contracts import validate_task_input
from runtime.draft_contract import DraftContractError
from runtime.fixture_adapter import FixtureAdapter
from runtime.gate_b import classify_gate_b_decision
from runtime.headline_contract import HeadlineContractError
from runtime.p2_pipeline import P2Pipeline
from runtime.p3_pipeline import P3Pipeline
from runtime.p4_pipeline import P4Pipeline
from runtime.run_store import RunStore


FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = FIXTURES / "p2_catalog.json"


def read_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class P4RuntimeTests(unittest.TestCase):
    def _context_ready_run(self, root: str) -> tuple[str, RunStore]:
        task = validate_task_input(read_json("p2_task.json"))
        knowledge_base, ip = FixtureAdapter(CATALOG).resolve(
            task["knowledge_base"], task["ip"]
        )
        store = RunStore(root)
        run = store.create_or_resume(task, knowledge_base, ip).run
        P2Pipeline(root, CATALOG).run(
            run["run_id"],
            FIXTURES / "p2_analysis.json",
            FIXTURES / "p2_direction.json",
        )
        store.approve_gate(run["run_id"], "A", "确认方向")
        P3Pipeline(root, CATALOG).run(
            run["run_id"], FIXTURES / "p3_selection.json"
        )
        return run["run_id"], store

    @staticmethod
    def _draft() -> str:
        return (FIXTURES / "p4_draft.md").read_text(encoding="utf-8")

    @staticmethod
    def _headlines():
        return read_json("p4_headline.json")

    def test_writer_has_one_context_file_and_no_source_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, _ = self._context_ready_run(temporary)
            pipeline = P4Pipeline(temporary)
            invocation = pipeline.writer_input(run_id)

        self.assertEqual(invocation["formal_input_files"], ["article_context_v1.json"])
        self.assertEqual(invocation["formal_input_file_count"], 1)
        self.assertEqual(invocation["writer_mode"], "ganhuo")
        self.assertEqual(invocation["source_access"], "none")
        self.assertEqual(list(inspect.signature(P4Pipeline).parameters), ["store_root"])
        serialized = json.dumps(invocation).casefold()
        self.assertNotIn("vault", serialized)
        self.assertNotIn("feishu", serialized)
        self.assertNotIn("retriever", serialized)

    def test_p4_creates_body_top3_and_gate_b_then_stops_waiting_final(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._context_ready_run(temporary)
            result = P4Pipeline(temporary).run_initial(
                run_id, self._draft(), self._headlines()
            )
            names = {
                path.name
                for path in (Path(temporary) / "runs" / run_id).iterdir()
                if path.is_file()
            }
            run = store.load(run_id)

        self.assertEqual(run["status"], "waiting_final")
        self.assertEqual(len(result["headline"]["top3"]), 3)
        self.assertIn(result["headline"]["recommended"], [item["title"] for item in result["headline"]["top3"]])
        self.assertIn("## 完整正文", result["gate_b"])
        self.assertIn("## 保存目标预览", result["gate_b"])
        self.assertIn("## 事实缺口", result["gate_b"])
        self.assertIn("draft_v1.md", names)
        self.assertIn("headline_v1.json", names)
        self.assertFalse(any("save" in name or "review" in name or "quality" in name for name in names))
        self.assertNotIn("approved_final.json", names)

    def test_p4_rejects_context_identity_and_gate_digest_mismatch(self) -> None:
        mutations = (
            ("knowledge base", lambda value: value["knowledge_base_identity"].update({"ref": "fixture://other"})),
            ("IP", lambda value: value["ip_identity_and_status"].update({"requested_name": "另一个IP"})),
            ("direction digest", lambda value: value["run_identity"]["gate_a"].update({"direction_digest": "0" * 64})),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                run_id, _ = self._context_ready_run(temporary)
                path = Path(temporary) / "runs" / run_id / "article_context_v1.json"
                context = json.loads(path.read_text(encoding="utf-8"))
                mutate(context)
                path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(DraftContractError):
                    P4Pipeline(temporary).writer_input(run_id)

    def test_draft_enforces_body_only_must_keep_avoid_and_fact_gap(self) -> None:
        invalid_bodies = [
            self._draft().replace("工具上线不等于业务结果。", "工具买完就行。"),
            self._draft() + "\n未经验证的增长数字",
            self._draft() + "\n上线以后转化提升300%。",
            "标题：智能客服为什么没结果\n\n" + self._draft(),
        ]
        for body in invalid_bodies:
            with self.subTest(body=body[-30:]), tempfile.TemporaryDirectory() as temporary:
                run_id, _ = self._context_ready_run(temporary)
                with self.assertRaises(DraftContractError):
                    P4Pipeline(temporary).run_initial(run_id, body, self._headlines())

    def test_draft_allows_status_colon_inside_normal_prose(self) -> None:
        body = "读者需要回答：它现在是什么状态：仍要回到记录核对。\n\n" + self._draft()
        with tempfile.TemporaryDirectory() as temporary:
            run_id, _ = self._context_ready_run(temporary)
            result = P4Pipeline(temporary).run_initial(
                run_id, body, self._headlines()
            )

        self.assertEqual(result["draft"], body.strip())

    def test_headline_contract_requires_bounded_candidates_and_recommended_member(self) -> None:
        invalid_candidates = []
        two = self._headlines()
        two["top3"] = two["top3"][:0]
        invalid_candidates.append(two)
        off_list = self._headlines()
        off_list["recommended"] = "第四个标题"
        invalid_candidates.append(off_list)
        with_body = self._headlines()
        with_body["body"] = "越权改正文"
        invalid_candidates.append(with_body)

        for candidate in invalid_candidates:
            with self.subTest(candidate=candidate), tempfile.TemporaryDirectory() as temporary:
                run_id, _ = self._context_ready_run(temporary)
                with self.assertRaises(HeadlineContractError):
                    P4Pipeline(temporary).run_initial(run_id, self._draft(), candidate)

    def test_existing_title_can_be_the_only_candidate_and_still_waits_for_approval(self) -> None:
        candidate = self._headlines()
        candidate["top3"] = candidate["top3"][:1]
        candidate["recommended"] = candidate["top3"][0]["title"]
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._context_ready_run(temporary)
            result = P4Pipeline(temporary).run_initial(run_id, self._draft(), candidate)
            self.assertEqual(len(result["headline"]["top3"]), 1)
            self.assertEqual(result["headline"]["recommended"], candidate["recommended"])
            self.assertEqual(store.load(run_id)["status"], "waiting_final")
            self.assertFalse((Path(temporary) / "runs" / run_id / "approved_final.json").exists())

    def test_gate_b_decision_is_fail_closed(self) -> None:
        self.assertEqual(classify_gate_b_decision("确认正文和标题"), "approve")
        self.assertEqual(
            classify_gate_b_decision("需要修改正文：开头更直接"), "revise_body"
        )
        self.assertEqual(
            classify_gate_b_decision("只修改标题：第二个更具体"), "revise_headline"
        )
        self.assertEqual(
            classify_gate_b_decision("使用标题：智能客服上线了，转化为什么没有跟着来？"),
            "select_headline",
        )
        self.assertEqual(classify_gate_b_decision("不采用"), "reject")
        self.assertEqual(classify_gate_b_decision("需要修改正文："), "ambiguous")
        self.assertEqual(classify_gate_b_decision("只修改标题："), "ambiguous")
        self.assertEqual(classify_gate_b_decision("使用标题："), "ambiguous")
        self.assertEqual(classify_gate_b_decision("需要修改："), "ambiguous")
        self.assertEqual(classify_gate_b_decision("需要修改：开头更直接"), "ambiguous")
        self.assertEqual(classify_gate_b_decision("可以"), "ambiguous")
        self.assertEqual(classify_gate_b_decision("继续"), "ambiguous")

    def test_draft_revision_versions_without_overwriting_prior_body(self) -> None:
        revised = self._draft().replace(
            "本周先选一个真实会话",
            "如果你只做一件事，本周先选一个真实会话",
        )
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._context_ready_run(temporary)
            pipeline = P4Pipeline(temporary)
            pipeline.run_initial(run_id, self._draft(), self._headlines())
            result = pipeline.revise(
                run_id,
                base_version=1,
                feedback="把结尾动作写得更直接",
                body=revised,
                headline_candidate=self._headlines(),
            )
            original = (Path(temporary) / "runs" / run_id / "draft_v1.md").read_text(encoding="utf-8")
            updated = (Path(temporary) / "runs" / run_id / "draft_v2.md").read_text(encoding="utf-8")
            run = store.load(run_id)

        self.assertNotEqual(original, updated)
        self.assertEqual(result["writer_invocation"]["user_feedback_count"], 1)
        self.assertEqual(result["writer_invocation"]["current_draft_file"], "draft_v1.md")
        self.assertEqual(run["status"], "waiting_final")

    def test_create_only_retry_resumes_identical_and_rejects_changed_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, _ = self._context_ready_run(temporary)
            pipeline = P4Pipeline(temporary)
            first = pipeline.run_initial(run_id, self._draft(), self._headlines())
            second = pipeline.run_initial(run_id, self._draft(), self._headlines())
            with self.assertRaises(ArtifactStoreError):
                pipeline.run_initial(
                    run_id,
                    self._draft() + "\n\n这是不同内容。",
                    self._headlines(),
                )

        self.assertFalse(first["resumed"])
        self.assertTrue(second["resumed"])

    def test_gate_b_is_not_approval_save_or_quality_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._context_ready_run(temporary)
            P4Pipeline(temporary).run_initial(run_id, self._draft(), self._headlines())
            run_dir = Path(temporary) / "runs" / run_id
            names = {path.name for path in run_dir.iterdir()}
            run = store.load(run_id)

        self.assertEqual(run["status"], "waiting_final")
        self.assertEqual([item["gate"] for item in run["gate_approvals"]], ["A"])
        self.assertFalse(any(name.startswith("save_") for name in names))
        self.assertFalse(any("review" in name or "ai_check" in name for name in names))
        self.assertFalse(any(name.startswith("distribution_") for name in names))


if __name__ == "__main__":
    unittest.main()
