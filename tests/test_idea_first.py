from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_content_source_runtime as source_tests
from runtime.content_source import ContentSourceError, _asset_catalog, _feishu_documents, _feishu_inventory, preview_real_source, resolve_real_source, verify_source_snapshot
from runtime.contracts import ContractError, validate_task_input
from runtime.draft_contract import DraftContractError, validate_draft_body
from runtime.gate_a import DirectionContractError, build_direction, render_gate_a
from runtime.retrieval_search import ControlledFixtureRetriever


class IdeaFirstTests(unittest.TestCase):
    def vault(self, root):
        return source_tests.ContentSourceRuntimeTests().make_vault(root)[0]

    def asset(self, vault, name, kind="peer_content_asset", extra="", body=None):
        path = vault / "04-内容方法库" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'---\ntype: {kind}\nstatus: active\napplicable_workflows: ["content-gzh-slim"]\nkeywords: ["企业服务"]\n{extra}---\n\n' + (body or "# 同行内容\n为什么这个问题值得讲；用具体场景展开理由。"), encoding="utf-8")
        return path.relative_to(vault).as_posix()

    def plan(self, **changes):
        return {"knowledge_base_id": "KB-1234567890ABCDEF", "business_refs": [], "peer_refs": [], "method_refs": [], "rationale": "根据受众的问题选择可用观点和组织方式，不按标题关键词猜测。", **changes}

    def resolve_plan(self, request, plan):
        preview = preview_real_source(request, retrieval_plan=plan)
        return resolve_real_source(request, retrieval_plan=preview["retrieval_plan"])

    def test_semantic_plan_keeps_no_keyword_match_and_complete_peer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = self.vault(root)
            ending = "## 七、如何用于相似问题\n先明确日常取舍，再解释服务承诺的适用条件。"
            peer = self.asset(vault, "同行/服务价值.md", body="# 服务价值\n" + "背景材料。" * 350 + ending)
            method = self.asset(vault, "方法/比较.md", "content_method_asset", "method_kind: structure\ncontent_purposes: [\"比较与判断\"]\n", "# 比较结构\n## 展开\n按读者的生活条件比较。\n## 收束\n说明不同情况下的选择。")
            request = {"knowledge_base": str(vault), "ip": "none", "user_thoughts": "我想谈一下签约之后持续陪伴的意义"}
            discovery = resolve_real_source(request, discover_only=True)
            self.assertEqual(discovery["status"], "discovery_only_no_run")
            self.assertIn(peer, [item["object_ref"] for item in discovery["inventory"]["04"]])
            task, kb, ip, catalog, snapshot = self.resolve_plan(request, self.plan(peer_refs=[peer], method_refs=[method]))
            entry = catalog["knowledge_bases"][0]
            self.assertTrue(entry["peer_content_assets"][0]["excerpt"].endswith(ending))
            catalog_path = root / "catalog.json"
            catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
            result = ControlledFixtureRetriever(catalog_path).prepare(task, kb, ip)
            self.assertEqual(len(result["peer_candidates"]), 1)
            self.assertEqual(result["method_candidates"][0]["source_metadata"]["method_kind"], "structure")
            self.assertEqual(result["peer_candidates"][0]["score"], 0)
            verify_source_snapshot(snapshot)
            (vault / peer).write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ContentSourceError, "frozen source changed"):
                verify_source_snapshot(snapshot)

    def test_role_budgets_apply_after_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = self.vault(Path(directory))
            for i in range(8):
                self.asset(vault, f"peer-{i}.md")
            self.asset(vault, "method-b.md", "content_method_asset")
            *_, catalog, _snapshot = resolve_real_source({"knowledge_base": str(vault), "ip": "none", "topic": "企业服务"})
            entry = catalog["knowledge_bases"][0]
            self.assertEqual(len(entry["peer_content_assets"]), 3)
            self.assertEqual(len(entry["content_method_assets"]), 2)

    def test_wrong_library_role_and_oral_only_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = self.vault(Path(directory))
            peer = self.asset(vault, "peer.md")
            oral = self.asset(vault, "oral.md", "oral_method_asset")
            request = {"knowledge_base": str(vault), "ip": "none", "topic": "一句想法"}
            for plan in (self.plan(method_refs=[peer]), self.plan(method_refs=[oral]), self.plan(peer_refs=["../outside.md"])):
                with self.subTest(plan=plan), self.assertRaises(ContentSourceError):
                    preview_real_source(request, retrieval_plan=plan)

    def test_scope_and_status_boundaries_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = self.vault(Path(directory))
            disabled = self.asset(vault, "disabled.md", extra="status: disabled\n")
            oral_scope = self.asset(vault, "oral-scope.md", extra='applicable_workflows: ["content-koubo-slim"]\n')
            experiment = self.asset(vault, "experiment.md", "content_method_asset", "status: experimental\nusage_boundary: 仅用于已明确表达探索意图的任务\n")
            request = {"knowledge_base": str(vault), "ip": "none", "topic": "探索一种讲法"}
            for ref in (disabled, oral_scope):
                with self.assertRaises(ContentSourceError):
                    preview_real_source(request, retrieval_plan=self.plan(peer_refs=[ref]))
            *_, catalog, _snapshot = self.resolve_plan(request, self.plan(method_refs=[experiment]))
            metadata = catalog["knowledge_bases"][0]["content_method_assets"][0]["source_metadata"]
            self.assertEqual(metadata["status"], "experimental")
            self.assertIn("探索", metadata["usage_boundary"])

    def test_all_source_restrictions_survive_projection_and_explicit_bans_stop(self):
        restrictions = {"audience_scope": "internal_sales_training", "usage_scope": "internal_reference",
                        "maturity": "experimental_reference", "source_verification": "unverified", "claim_scope": "source_only"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = self.vault(root)
            extra = "".join(f"{key}: {value}\n" for key, value in restrictions.items())
            peer = self.asset(vault, "restricted.md", extra=extra)
            request = {"knowledge_base": str(vault), "ip": "none", "topic": "内部培训"}
            task, kb, ip, catalog, _snapshot = self.resolve_plan(request, self.plan(peer_refs=[peer]))
            asset = catalog["knowledge_bases"][0]["peer_content_assets"][0]
            for key, value in restrictions.items():
                self.assertEqual(asset["source_metadata"][key], value)
            path = root / "catalog.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            candidate = ControlledFixtureRetriever(path).prepare(task, kb, ip)["peer_candidates"][0]
            self.assertEqual(candidate["source_metadata"], asset["source_metadata"])
            for field, value in (("status", "blocked"), ("usage_scope", "do_not_use"), ("usage_scope", "forbidden")):
                banned = self.asset(vault, "banned.md", extra=f"{field}: {value}\n")
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ContentSourceError, "prohibits use"):
                    preview_real_source(request, retrieval_plan=self.plan(peer_refs=[banned]))
                text = (vault / banned).read_text(encoding="utf-8")
                self.assertEqual(_asset_catalog([(banned, text, "a" * 64)], backend="obsidian", role="04")[1], [])

    def test_active_03_reference_metadata_is_not_confirmed_fact(self):
        signals = {"usage_scope": "reference_with_fact_check", "maturity": "requires_current_fact_check",
                   "source_verification": "local_original_hash_verified", "claim_scope": "source_only", "fact_status": "candidate"}
        cases = [{key: value} for key, value in signals.items()] + [signals, {"usage_scope": "reference_only"}, {"maturity": "experimental_reference"}, {"source_verification": "unverified"}]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                text = "---\ntype: business_knowledge_asset\nstatus: active\n" + "".join(f"{key}: {value}\n" for key, value in metadata.items()) + "---\n# 服务说明\n一段来自原件的业务描述。"
                business, _peer, _methods, _objects = _asset_catalog([("03/business.md", text, "b" * 64)], backend="obsidian", role="03")
                self.assertEqual(business[0]["fact_status"], "candidate")
                for key, value in metadata.items():
                    self.assertEqual(business[0]["source_metadata"][key], value)
                candidate = ControlledFixtureRetriever._bounded_candidates(business, "不相关的词", 5, "03", "business_asset", preselected=True)[0]
                self.assertEqual(candidate["fact_status"], "candidate")
                template = json.loads((Path(__file__).parent / "fixtures/p2_direction.json").read_text(encoding="utf-8"))
                option = template["options"][0]
                option["selected_sources"] = {"business_refs": [candidate["ref"]], "peer_refs": [], "method_refs": [], "reference_refs": []}
                option["must_keep"], option["must_avoid"] = [], []
                run = {"run_id": "metadata-test", "task_input": validate_task_input({"knowledge_base": "kb", "ip": "none", "topic": "服务价值"}), "knowledge_base_identity": {}, "ip_identity": {"status": "none"}}
                retrieval = {"business_candidates": [candidate], "peer_candidates": [], "method_candidates": [], "warnings": []}
                with self.assertRaisesRegex(DirectionContractError, "unconfirmed business candidate"):
                    build_direction(template, run, retrieval, {"reference_analyses": []})

    def test_03_missing_metadata_compatibility_does_not_scan_body_for_status(self):
        for metadata in ("", "status: active\n", "status: confirmed\n"):
            text = "---\ntype: business_knowledge_asset\n" + metadata + "---\n# 核验指南\n词语 reference_only 或 candidate 出现在说明正文不代表元数据状态。"
            business, *_ = _asset_catalog([("03/legacy.md", text, "c" * 64)], backend="obsidian", role="03")
            self.assertEqual(business[0]["fact_status"], "confirmed")

    def test_preview_plan_pins_material_task_manifest_and_profile(self):
        for target in ("peer", "method", "business", "manifest", "profile_index", "profile", "task", "chosen_ip", "reference"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                vault = self.vault(root)
                peer = self.asset(vault, "peer.md")
                method = self.asset(vault, "method.md", "content_method_asset")
                reference = root / "reference.md"
                reference.write_text("# 独立对标\n完整对标正文。", encoding="utf-8")
                request = {"knowledge_base": str(vault), "ip": "甲", "user_thoughts": "签约之后的服务价值", "references": [str(reference)]}
                plan = self.plan(business_refs=["03-业务知识库/业务.md"], peer_refs=[peer], method_refs=[method])
                with self.assertRaisesRegex(ContentSourceError, "selection_snapshot"):
                    resolve_real_source(request, retrieval_plan=plan)
                preview = preview_real_source(request, retrieval_plan=plan)
                pinned = preview["retrieval_plan"]
                snapshot = pinned["selection_snapshot"]
                self.assertEqual(snapshot["knowledge_base_id"], plan["knowledge_base_id"])
                self.assertTrue(snapshot["manifest_sha256"] and snapshot["profile_index_sha256"])
                self.assertIsNotNone(snapshot["ip_identity"]["profile_id"])
                self.assertEqual(len(snapshot["objects"]), 5)
                _task, kb, _ip, _catalog, _snapshot = resolve_real_source(request, retrieval_plan=pinned)
                self.assertEqual(kb, preview["knowledge_base_identity"])
                paths = {"peer": vault / peer, "method": vault / method, "business": vault / "03-业务知识库/业务.md",
                         "profile": vault / "05-IP-Profile/甲.md", "reference": reference}
                if target in paths:
                    path = paths[target]
                    path.write_text(path.read_text(encoding="utf-8") + "\n新增内容。", encoding="utf-8")
                elif target in {"manifest", "profile_index"}:
                    filename = "content-source-manifest.json" if target == "manifest" else "content-profile-index.json"
                    path = vault / "06-Agent与Workflow" / filename
                    value = json.loads(path.read_text(encoding="utf-8"))
                    value["revision"] += 1
                    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                elif target == "task":
                    request["user_thoughts"] = "完全不同的表达任务"
                else:
                    request["ip"] = "乙"
                with self.assertRaises(ContentSourceError):
                    resolve_real_source(request, retrieval_plan=pinned)

    def test_cli_rejects_drift_before_start_or_gate_a_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = self.vault(root)
            peer = self.asset(vault, "peer.md")
            request = {"knowledge_base": str(vault), "ip": "none", "user_thoughts": "持续服务的价值"}
            input_path, raw_path, pinned_path = root / "input.json", root / "raw-plan.json", root / "pinned-plan.json"
            input_path.write_text(json.dumps(request), encoding="utf-8")
            raw_path.write_text(json.dumps(self.plan(peer_refs=[peer])), encoding="utf-8")
            script = str(Path(__file__).resolve().parents[1] / "scripts/content-gzh-slim")
            command = [sys.executable, "-B", script]
            preview = subprocess.run(command + ["preview-sources", "--input", str(input_path), "--retrieval-plan", str(raw_path)], capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            pinned_path.write_text(json.dumps(json.loads(preview.stdout)["retrieval_plan"]), encoding="utf-8")
            common = ["--input", str(input_path), "--retrieval-plan", str(pinned_path), "--store", str(root / "store")]
            start = subprocess.run(command + ["start", *common], capture_output=True, text=True)
            self.assertEqual(start.returncode, 0, start.stderr)
            original = {path.relative_to(root / "store").as_posix(): path.read_bytes() for path in (root / "store").rglob("*") if path.is_file()}
            (vault / peer).write_text((vault / peer).read_text(encoding="utf-8") + "\n不同来源版本", encoding="utf-8")
            for args in (["start", *common], ["prepare-gate-a", *common, "--analysis", str(root / "not-read.json"), "--direction", str(root / "not-read-direction.json")]):
                result = subprocess.run(command + args, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("selection preview changed", result.stderr + result.stdout)
            after = {path.relative_to(root / "store").as_posix(): path.read_bytes() for path in (root / "store").rglob("*") if path.is_file()}
            self.assertEqual(original, after)

    def test_feishu_classifies_before_spending_peer_method_budget(self):
        class Client:
            def list_children(self, **kwargs):
                return [{"node_token": str(i), "obj_token": str(i), "obj_type": "docx", "title": f"topic {i}", "has_child": False} for i in range(6)]
            def fetch_markdown(self, token):
                kind = "peer_content_asset" if int(token) < 5 else "content_method_asset"
                return f'---\ntype: {kind}\napplicable_workflows: ["content-gzh-slim"]\n---\n# 方法或同行\n完整内容。'
        read_stats = {}
        documents = _feishu_documents(Client(), space_id="123", parent_ref="root", query="topic", limit=5, content=True, read_stats=read_stats)
        _business, peers, methods, _objects = _asset_catalog(documents, backend="feishu", role="04")
        self.assertEqual(len(peers), 3)
        self.assertEqual(len(methods), 1)
        self.assertEqual(read_stats["full_documents"], 6)

    def test_feishu_nested_selection_does_not_require_title_keyword(self):
        class Client:
            def list_children(self, *, space_id, parent_node_token):
                return {"root": [{"node_token": "folder", "obj_token": "index", "obj_type": "docx", "title": "目录", "has_child": True}],
                        "folder": [{"node_token": "leaf", "obj_token": "peer", "obj_type": "docx", "title": "一种日常观察", "has_child": False}]}[parent_node_token]
            def fetch_markdown(self, token):
                self.assert_token = token
                return '---\ntype: peer_content_asset\napplicable_workflows: ["content-gzh-slim"]\n---\n# 具体素材\n场景与推理。'
        client = Client()
        documents = _feishu_documents(client, space_id="123", parent_ref="root", query="毫不相同的字词", limit=5, content=True, selected=["peer"])
        self.assertEqual([item[0] for item in documents], ["peer"])
        with self.assertRaisesRegex(ContentSourceError, "outside"):
            _feishu_documents(client, space_id="123", parent_ref="root", query="", limit=5, content=True, selected=["other-space-object"])

    def test_discovery_limit_is_visible(self):
        class Client:
            def list_children(self, **kwargs):
                return [{"node_token": str(i)} for i in range(201)]
        with self.assertRaisesRegex(ContentSourceError, "200"):
            _feishu_inventory(Client(), space_id="123", parent_ref="root")

    def test_oversize_selected_content_never_silently_truncates(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = self.vault(Path(directory))
            peer = self.asset(vault, "long.md", body="有价值的内容" * 5000)
            with self.assertRaisesRegex(ContentSourceError, "24000"):
                preview_real_source({"knowledge_base": str(vault), "ip": "none", "topic": "想法"}, retrieval_plan=self.plan(peer_refs=[peer]))

    def test_editorial_requirements_are_not_required_prose(self):
        raw = {"knowledge_base": "kb", "ip": "none", "user_thoughts": "专业判断应该说明依据", "must_keep": ["选择需要有依据"], "writing_requirements": ["请突出我的专业判断但不要生硬推销"]}
        task = validate_task_input(raw)
        context = {"task_input": task, "must_keep": task["must_keep"], "must_avoid": []}
        self.assertEqual(validate_draft_body("选择需要有依据，也需要说明适用条件。", context), "选择需要有依据，也需要说明适用条件。")
        with self.assertRaisesRegex(DraftContractError, "internal writing requirement"):
            validate_draft_body("选择需要有依据。请突出我的专业判断但不要生硬推销", context)
        with self.assertRaisesRegex(ContractError, "cannot also be must_keep"):
            validate_task_input({**raw, "must_keep": raw["writing_requirements"]})
        self.assertNotIn("writing_requirements", validate_task_input({"knowledge_base": "kb", "ip": "none"}))

    def test_empty_library_direction_discloses_actual_basis(self):
        fixture = Path(__file__).parent / "fixtures" / "p2_direction.json"
        template = json.loads(fixture.read_text(encoding="utf-8"))
        option = template["options"][0]
        option["selected_sources"] = {key: [] for key in ("business_refs", "peer_refs", "method_refs", "reference_refs")}
        option["must_keep"], option["must_avoid"] = [], []
        run = {"run_id": "test", "task_input": validate_task_input({"knowledge_base": "kb", "ip": "none", "user_thoughts": "想讲一个问题"}), "knowledge_base_identity": {}, "ip_identity": {"status": "none", "requested_name": "none", "resolved_ref": None}}
        retrieval = {"business_candidates": [], "peer_candidates": [], "method_candidates": [], "warnings": []}
        result = build_direction(template, run, retrieval, {"reference_analyses": []})
        self.assertIn("不能声称", render_gate_a(result))
        wrong = copy.deepcopy(template)
        wrong["options"][0]["must_keep"] = ["擅自加入的内部写作要求"]
        with self.assertRaisesRegex(DirectionContractError, "frozen user input"):
            build_direction(wrong, run, retrieval, {"reference_analyses": []})


if __name__ == "__main__":
    unittest.main()
