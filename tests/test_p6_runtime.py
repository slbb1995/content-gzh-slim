from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from runtime.approved_direction import ApprovedDirectionError, materialize_approved_direction
from runtime.artifact_store import ArtifactStore
from runtime.contracts import validate_task_input
from runtime.distribution_contract import DistributionContractError
from runtime.distribution_service import DistributionService
from runtime.fixture_adapter import FixtureAdapter, FixtureResolutionError
from runtime.obsidian_adapter import ObsidianAdapter
from runtime.p2_pipeline import P2Pipeline
from runtime.p3_pipeline import P3Pipeline
from runtime.p4_pipeline import P4Pipeline
from runtime.retrieval_search import ControlledFixtureRetriever
from runtime.run_store import RunStore, RunStoreError
from runtime.save_service import SaveService


FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = FIXTURES / "p2_catalog.json"


def read_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class P6RuntimeTests(unittest.TestCase):
    def _saved_run(self, root: str) -> tuple[str, RunStore]:
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
        P4Pipeline(root).run_initial(
            run["run_id"],
            (FIXTURES / "p4_draft.md").read_text(encoding="utf-8"),
            read_json("p4_headline.json"),
        )
        store.approve_gate(run["run_id"], "B", "确认正文和标题")
        context = ArtifactStore(root).read_json(run["run_id"], "article_context_v1.json")
        adapter = ObsidianAdapter(
            Path(root) / "isolated-obsidian",
            {context["save_target_preview"]["target_ref"]: "articles"},
        )
        SaveService(root, {"obsidian": adapter}).save(run["run_id"])
        return run["run_id"], store

    def _three_option_run(
        self, root: str, *, ip_name: str = "示例甲"
    ) -> tuple[str, RunStore, ArtifactStore]:
        raw_task = read_json("p2_task.json")
        raw_task.update(
            {"ip": ip_name, "topic": "", "user_thoughts": "", "references": []}
        )
        task = validate_task_input(raw_task)
        knowledge_base, ip = FixtureAdapter(CATALOG).resolve(
            task["knowledge_base"], task["ip"]
        )
        store = RunStore(root)
        run = store.create_or_resume(task, knowledge_base, ip).run
        base = copy.deepcopy(read_json("p2_direction.json")["options"][0])
        base["selected_sources"]["reference_refs"] = []
        if ip_name == "none":
            base["selected_sources"]["business_refs"] = []
            base["selected_sources"]["peer_refs"] = []
            base["selected_sources"]["method_refs"] = []
        options = []
        for index in range(3):
            option = copy.deepcopy(base)
            option["option_id"] = f"option-{index + 1}"
            option["title"] = f"虚构方向 {index + 1}"
            options.append(option)
        analysis_path = Path(root) / "empty-analysis.json"
        direction_path = Path(root) / "three-directions.json"
        analysis_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "reference_analyses": [],
                    "multi_reference_synthesis": None,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        direction_path.write_text(
            json.dumps(
                {"schema_version": 1, "mode": "options", "options": options},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        P2Pipeline(root, CATALOG).run(run["run_id"], analysis_path, direction_path)
        return run["run_id"], store, ArtifactStore(root)

    def test_distribution_is_optional_and_requires_exact_request_after_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._saved_run(temporary)
            service = DistributionService(temporary)
            with self.assertRaisesRegex(DistributionContractError, "exact explicit request"):
                service.generate(
                    run_id,
                    explicit_request="",
                    candidate=read_json("p6_distribution.json"),
                )
            names = {path.name for path in (Path(temporary) / "runs" / run_id).iterdir()}
            status = store.load(run_id)["status"]

        self.assertEqual(status, "saved")
        self.assertFalse(any(name.startswith("distribution_v") for name in names))

        with tempfile.TemporaryDirectory() as temporary:
            task = validate_task_input(
                {
                    "knowledge_base": "fixture-kb-alpha",
                    "ip": "none",
                    "topic": "尚未保存的虚构任务",
                    "references": [],
                }
            )
            knowledge_base, ip = FixtureAdapter(CATALOG).resolve(
                task["knowledge_base"], task["ip"]
            )
            run = RunStore(temporary).create_or_resume(task, knowledge_base, ip).run
            with self.assertRaisesRegex(RunStoreError, "requires saved"):
                DistributionService(temporary).generate(
                    run["run_id"],
                    explicit_request="生成分发包",
                    candidate=read_json("p6_distribution.json"),
                )

    def test_distribution_is_bound_create_only_versioned_and_nonmutating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._saved_run(temporary)
            artifacts = ArtifactStore(temporary)
            approved_before = artifacts.read_json(run_id, "approved_final.json")
            body_before = approved_before["draft"]["body"]
            title_before = approved_before["headline"]["final_title"]
            service = DistributionService(temporary)
            first = service.generate(
                run_id,
                explicit_request="生成分发包",
                candidate=read_json("p6_distribution.json"),
            )
            retry = service.generate(
                run_id,
                explicit_request="生成分发包",
                candidate=read_json("p6_distribution.json"),
            )
            revised = read_json("p6_distribution.json")
            revised["moments"]["copy"] += " 欢迎转给正在排查流程的朋友。"
            second = service.generate(
                run_id, explicit_request="生成分发包", candidate=revised
            )
            approved_after = artifacts.read_json(run_id, "approved_final.json")
            names = {path.name for path in (Path(temporary) / "runs" / run_id).iterdir()}
            status = store.load(run_id)["status"]

        self.assertEqual(first["distribution"]["distribution_version"], 1)
        self.assertTrue(retry["resumed"])
        self.assertEqual(second["distribution"]["distribution_version"], 2)
        self.assertEqual(approved_after["draft"]["body"], body_before)
        self.assertEqual(approved_after["headline"]["final_title"], title_before)
        self.assertEqual(status, "distribution_optional")
        self.assertEqual(
            {name for name in names if name.startswith("distribution_v")},
            {"distribution_v1.json", "distribution_v2.json"},
        )
        self.assertFalse(first["distribution"]["semantics"]["published"])

    def test_distribution_rejects_main_title_body_or_intro_contract_changes(self) -> None:
        candidates = []
        changed_title = read_json("p6_distribution.json")
        changed_title["wechat_final_title"] = "静默换掉公众号主标题"
        candidates.append(changed_title)
        body_added = read_json("p6_distribution.json")
        body_added["article_body"] = "越权改正文"
        candidates.append(body_added)
        short_intro = read_json("p6_distribution.json")
        short_intro["douyin"]["intro"] = "太短"
        candidates.append(short_intro)

        for candidate in candidates:
            with self.subTest(candidate=candidate), tempfile.TemporaryDirectory() as temporary:
                run_id, _ = self._saved_run(temporary)
                with self.assertRaises(DistributionContractError):
                    DistributionService(temporary).generate(
                        run_id, explicit_request="生成分发包", candidate=candidate
                    )

        forbidden_candidates = []
        xhs_title = read_json("p6_distribution.json")
        xhs_title["xiaohongshu"]["title"] = "未经验证的增长数字"
        forbidden_candidates.append(xhs_title)
        channels_intro = read_json("p6_distribution.json")
        channels_intro["wechat_channels"]["intro"] += " 不写未经验证的增长数字。"
        forbidden_candidates.append(channels_intro)
        douyin_tag = read_json("p6_distribution.json")
        douyin_tag["douyin"]["tags"].append("未经验证的增长数字")
        forbidden_candidates.append(douyin_tag)
        moments_copy = read_json("p6_distribution.json")
        moments_copy["moments"]["copy"] += " 未经验证的增长数字。"
        forbidden_candidates.append(moments_copy)
        for candidate in forbidden_candidates:
            with self.subTest(forbidden=candidate), tempfile.TemporaryDirectory() as temporary:
                run_id, _ = self._saved_run(temporary)
                with self.assertRaisesRegex(DistributionContractError, "must_avoid"):
                    DistributionService(temporary).generate(
                        run_id, explicit_request="生成分发包", candidate=candidate
                    )

    def test_distribution_rejects_any_save_receipt_misbinding(self) -> None:
        mutations = {
            "title": lambda receipt: receipt.update({"title": "错绑标题"}),
            "body_digest": lambda receipt: receipt.update({"body_digest": "0" * 64}),
            "context_digest": lambda receipt: receipt.update({"context_digest": "0" * 64}),
            "version": lambda receipt: receipt.update({"version": 99}),
            "published": lambda receipt: receipt["semantics"].update({"published": True}),
        }
        for field, mutate in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                run_id, _ = self._saved_run(temporary)
                receipt_path = Path(temporary) / "runs" / run_id / "save_receipt.json"
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                mutate(receipt)
                receipt_path.write_text(
                    json.dumps(receipt, ensure_ascii=False), encoding="utf-8"
                )
                with self.assertRaisesRegex(DistributionContractError, "save receipt"):
                    DistributionService(temporary).generate(
                        run_id,
                        explicit_request="生成分发包",
                        candidate=read_json("p6_distribution.json"),
                    )
                self.assertFalse(
                    any(
                        (Path(temporary) / "runs" / run_id).glob(
                            "distribution_v*.json"
                        )
                    )
                )

    def test_three_option_gate_a_binds_selected_option_before_exact_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store, artifacts = self._three_option_run(temporary)
            store.select_gate_a_option(run_id, "option-2")
            with self.assertRaisesRegex(RunStoreError, "cannot be replaced"):
                store.select_gate_a_option(run_id, "option-1")
            store.approve_gate(run_id, "A", "确认方向")
            selection = read_json("p3_selection.json")
            selection["reference_mechanisms"] = []
            selection_path = Path(temporary) / "selection.json"
            selection_path.write_text(
                json.dumps(selection, ensure_ascii=False), encoding="utf-8"
            )
            result = P3Pipeline(temporary, CATALOG).run(run_id, selection_path)
            run = store.load(run_id)

        self.assertEqual(run["gate_a_selection"]["option_id"], "option-2")
        self.assertEqual(run["gate_approvals"][0]["decision"], "确认方向")
        self.assertEqual(result["context"]["approved_direction"]["option_id"], "option-2")
        self.assertNotEqual(result["context"]["approved_direction"]["option_id"], "option-1")

        with tempfile.TemporaryDirectory() as temporary:
            no_ip_run_id, no_ip_store, _ = self._three_option_run(
                temporary, ip_name="none"
            )
            no_ip_store.select_gate_a_option(no_ip_run_id, "option-3")
            no_ip_store.approve_gate(no_ip_run_id, "A", "确认方向")
            no_ip_selection = read_json("p3_selection.json")
            no_ip_selection["selected_05_fragment_ids"] = []
            no_ip_selection["selected_03_refs"] = []
            no_ip_selection["selected_04_peer_refs"] = []
            no_ip_selection["selected_04_method_refs"] = []
            no_ip_selection["reference_mechanisms"] = []
            no_ip_selection_path = Path(temporary) / "selection.json"
            no_ip_selection_path.write_text(
                json.dumps(no_ip_selection, ensure_ascii=False), encoding="utf-8"
            )
            no_ip_result = P3Pipeline(temporary, CATALOG).run(
                no_ip_run_id, no_ip_selection_path
            )

        self.assertEqual(no_ip_result["context"]["ip_identity_and_status"]["status"], "none")
        self.assertEqual(no_ip_result["context"]["approved_direction"]["option_id"], "option-3")

    def test_three_option_gate_a_never_defaults_to_first_option(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store, artifacts = self._three_option_run(temporary)
            store.approve_gate(run_id, "A", "确认方向")
            direction = artifacts.read_json(run_id, "direction_v1.json")
            receipt = artifacts.read_json(run_id, "retrieval_receipt.json")
            with self.assertRaisesRegex(ApprovedDirectionError, "refusing to guess"):
                materialize_approved_direction(store.load(run_id), direction, receipt)

    def test_core_scenario_matrix_uses_controlled_fixture_roles_and_ip_status(self) -> None:
        base = read_json("p2_task.json")
        scenarios = {
            "ip_topic_reference": {},
            "ip_no_reference_thought": {"references": [], "topic": "", "user_thoughts": "一个明确想法"},
            "ip_no_direction": {"references": [], "topic": "", "user_thoughts": ""},
            "no_ip_topic": {"ip": "none", "references": []},
            "no_ip_no_direction": {"ip": "none", "references": [], "topic": "", "user_thoughts": ""},
            "limited_ip": {"ip": "有限示例", "references": []},
        }
        adapter = FixtureAdapter(CATALOG)
        retriever = ControlledFixtureRetriever(CATALOG)
        observed = {}
        for name, changes in scenarios.items():
            raw = {**base, **changes}
            task = validate_task_input(raw)
            knowledge_base, ip = adapter.resolve(task["knowledge_base"], task["ip"])
            retrieval = retriever.prepare(task, knowledge_base, ip)
            observed[name] = {
                "ip_status": retrieval["ip_status"],
                "roles": [item["role"] for item in retrieval["access_log"]],
                "business": len(retrieval["business_candidates"]),
                "peer": len(retrieval["peer_candidates"]),
                "method": len(retrieval["method_candidates"]),
            }

        self.assertEqual(observed["no_ip_topic"]["ip_status"], "none")
        self.assertEqual(observed["limited_ip"]["ip_status"], "limited")
        self.assertTrue(all(value["roles"] == ["05", "03", "04"] for value in observed.values()))
        self.assertTrue(all(value["business"] <= 5 for value in observed.values()))
        self.assertTrue(all(value["peer"] <= 3 for value in observed.values()))
        self.assertTrue(all(value["method"] <= 2 for value in observed.values()))

    def test_run_isolation_for_same_kb_two_ips_and_two_kbs_same_ip(self) -> None:
        adapter = FixtureAdapter(FIXTURES / "knowledge_bases.json")
        base = {
            "knowledge_base": "fixture-kb-alpha",
            "ip": "示例甲",
            "topic": "虚构隔离测试",
            "references": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            store = RunStore(temporary)
            runs = []
            for raw in (
                base,
                {**base, "ip": "示例乙"},
                {**base, "knowledge_base": "fixture-kb-beta"},
            ):
                task = validate_task_input(raw)
                knowledge_base, ip = adapter.resolve(task["knowledge_base"], task["ip"])
                runs.append(store.create_or_resume(task, knowledge_base, ip).run)

        self.assertEqual(len({run["run_id"] for run in runs}), 3)
        self.assertNotEqual(runs[0]["ip_identity"], runs[1]["ip_identity"])
        self.assertNotEqual(runs[0]["knowledge_base_identity"], runs[2]["knowledge_base_identity"])

    def test_same_name_resolution_conflict_is_fail_closed(self) -> None:
        duplicate = read_json("knowledge_bases.json")
        duplicate["knowledge_bases"].append(copy.deepcopy(duplicate["knowledge_bases"][0]))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text(json.dumps(duplicate, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(FixtureResolutionError, "uniquely"):
                FixtureAdapter(path).resolve("fixture-kb-alpha", "示例甲")

    def test_anti_bloat_budget_and_artifact_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._saved_run(temporary)
            result = DistributionService(temporary).generate(
                run_id,
                explicit_request="生成分发包",
                candidate=read_json("p6_distribution.json"),
            )
            run_dir = Path(temporary) / "runs" / run_id
            names = {path.name for path in run_dir.iterdir() if path.is_file()}
            context = ArtifactStore(temporary).read_json(run_id, "article_context_v1.json")
            receipt = ArtifactStore(temporary).read_json(run_id, "retrieval_receipt.json")
            run = store.load(run_id)

        skills = list((Path(__file__).parents[1] / "skills").glob("*/SKILL.md"))
        self.assertEqual(len(skills), 7)
        self.assertEqual(len([path for path in skills if path.parent.name != "content-gzh-slim"]), 6)
        self.assertEqual(len([name for name in names if name.startswith("article_context")]), 1)
        self.assertEqual(len(run["gate_approvals"]), 2)
        self.assertEqual(receipt["totals"]["context_packs"], 1)
        self.assertLessEqual(len(context["task_input"]["references"]), 5)
        self.assertLessEqual(len(context["selected_03_business_context"]), 5)
        self.assertLessEqual(len(context["selected_04_content_assets"]), 3)
        self.assertLessEqual(len(context["selected_04_method_assets"]), 2)
        self.assertIn(context["ip_identity_and_status"]["status"], {"full", "limited", "unused", "none"})
        self.assertFalse(any(any(token in name for token in ("review", "quality", "source_pack", "writing_packet", "image", "audio")) for name in names))
        self.assertFalse(result["distribution"]["semantics"]["draftbox"])
        self.assertFalse(result["distribution"]["semantics"]["published"])


if __name__ == "__main__":
    unittest.main()
