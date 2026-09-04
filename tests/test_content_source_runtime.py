from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from runtime.content_source import (
    ContentSourceError,
    LarkContentSourceClient,
    _feishu_documents,
    apply_configuration,
    plan_configuration,
    resolve_real_source,
    verify_source_snapshot,
)
from runtime.artifact_store import ArtifactStore
from runtime.host_cli import _derived_adapter
from runtime.p2_pipeline import P2Pipeline
from runtime.p3_pipeline import P3Pipeline
from runtime.p4_pipeline import P4Pipeline
from runtime.run_store import RunStore
from runtime.save_service import SaveService


def canonical(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


class ContentSourceRuntimeTests(unittest.TestCase):
    def test_lark_client_drops_only_known_dead_local_proxy(self) -> None:
        completed = mock.Mock(returncode=0, stdout='{"data": {}}', stderr='')
        with mock.patch.dict(
            "runtime.content_source.os.environ",
            {
                "ALL_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://localhost:9",
                "HTTP_PROXY": "http://proxy.example:8080",
            },
            clear=True,
        ), mock.patch("runtime.content_source.subprocess.run", return_value=completed) as run:
            LarkContentSourceClient(binary="lark-cli")._call(["wiki", "nodes", "list"])

        environment = run.call_args.kwargs["env"]
        self.assertNotIn("ALL_PROXY", environment)
        self.assertNotIn("HTTPS_PROXY", environment)
        self.assertEqual(environment["HTTP_PROXY"], "http://proxy.example:8080")

    def temporary_root(self):
        parent = Path("/private/tmp") if Path("/private/tmp").is_dir() else None
        return tempfile.TemporaryDirectory(prefix="content-gzh-source-", dir=parent)

    def make_vault(self, root: Path, *, two_profiles: bool = True) -> tuple[Path, Path, str, str]:
        vault = root / "公众号知识库"
        vault.mkdir()
        for name in ("03-业务知识库", "04-内容方法库", "05-IP-Profile", "06-Agent与Workflow", "07-生产与反馈"):
            (vault / name).mkdir()
        client_id = "CLT-1234567890ABCD"
        knowledge_base_id = "KB-1234567890ABCDEF"
        profiles = []
        for index, (name, primary) in enumerate((("甲", True), ("乙", False)) if two_profiles else (("甲", False),), 1):
            profile_id = f"PRF-{index:016X}"
            text = (
                "---\n"
                "status: active\n"
                f"is_primary: {'true' if primary else 'false'}\n"
                f"profile_id: {profile_id}\n"
                "profile_schema: zsk-profile-v2\n"
                f"display_name: \"{name}\"\n"
                f"aliases: [\"{name}老师\"]\n"
                "---\n\n"
                f"# {name} Profile\n\n## 确认事实\n\n- {name}只讲可核验的业务事实。\n- {name}面向企业负责人。\n- {name}不承诺未经验证的结果。\n"
                f"\n## 表达方式\n\n- {name}说话亲切、明确、不端着。\n"
                f"\n## 专业判断\n\n- {name}认为流程断点比工具参数更值得优先检查。\n"
                f"\n## 读者连接\n\n- {name}理解负责人买了工具却看不到结果的焦虑。\n"
                f"\n## 业务边界\n\n- {name}不会把未经核验的结果写成承诺。\n"
            )
            path = vault / "05-IP-Profile" / f"{name}.md"
            payload = text.encode("utf-8")
            path.write_bytes(payload)
            profiles.append({"profile_id": profile_id, "display_name": name, "aliases": [f"{name}老师"], "object_ref": path.relative_to(vault).as_posix(), "status": "active", "is_primary": primary, "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        (vault / "03-业务知识库" / "业务.md").write_text(
            "---\nasset_id: KNO-1\ntype: business_knowledge_asset\nstatus: confirmed\nkeywords:\n  - 企业服务\napplicable_workflows:\n  - content-gzh-slim\n---\n\n# 企业服务事实\n\n已确认先做需求诊断。\n",
            encoding="utf-8",
        )
        (vault / "04-内容方法库" / "方法.md").write_text(
            "---\nasset_id: MET-1\ntype: content_method_asset\nstatus: active\naudience_scope: both\nkeywords:\n  - 企业服务\nuse_when:\n  - 需要解释流程\napplicable_workflows:\n  - content-gzh-slim\n---\n\n# 流程方法\n\n先讲问题，再讲行动。\n",
            encoding="utf-8",
        )
        manifest = {
            "contract_version": "content-source-v1",
            "knowledge_base_id": knowledge_base_id,
            "client_id": client_id,
            "knowledge_base_name": "公众号知识库",
            "backend": "obsidian",
            "locator": str(vault),
            "asset_roots": {"knowledge": "03-业务知识库", "content": "04-内容方法库", "profiles": "05-IP-Profile", "workflow": "06-Agent与Workflow", "output": "07-生产与反馈"},
            "profile_index_ref": "06-Agent与Workflow/content-profile-index.json",
            "workflow_outputs": {"content-koubo-slim": "content-koubo-slim/{profile_id}/weekly", "content-gzh-slim": "content-gzh-slim/{profile_id}/articles"},
            "supported_workflows": ["content-gzh-slim", "content-koubo-slim"],
            "revision": 1,
        }
        profile_index = {"contract_version": "content-source-v1", "knowledge_base_id": knowledge_base_id, "profiles": profiles, "revision": 1}
        manifest_path = vault / "06-Agent与Workflow" / "content-source-manifest.json"
        index_path = vault / "06-Agent与Workflow" / "content-profile-index.json"
        manifest_path.write_text(canonical(manifest), encoding="utf-8")
        index_path.write_text(canonical(profile_index), encoding="utf-8")
        return vault, index_path, client_id, profiles[0]["profile_id"]

    def test_default_binding_resolves_primary_and_reads_real_obsidian(self) -> None:
        with self.temporary_root() as directory:
            root = Path(directory)
            vault, _index_path, client_id, primary_id = self.make_vault(root)
            registry = root / "host" / ".content-workflows" / "knowledge-base-registry.json"
            preview = plan_configuration(vault, registry_path=registry)
            self.assertFalse(registry.exists())
            result = apply_configuration(vault, registry_path=registry, confirmation=preview["confirmation"])
            self.assertEqual(result["readback"], "verified")
            task, kb, ip, catalog, snapshot = resolve_real_source(
                {"topic": "企业服务怎么做", "references": [], "must_keep": [], "must_avoid": []},
                registry_path=registry,
            )
            self.assertEqual(task["knowledge_base"], "KB-1234567890ABCDEF")
            self.assertEqual(ip["profile_id"], primary_id)
            self.assertEqual(ip["requested_name"], "甲")
            self.assertEqual(kb["backend"], "obsidian")
            entry = catalog["knowledge_bases"][0]
            self.assertEqual(len(entry["profiles"]), 1)
            self.assertEqual(len(entry["business_assets"]), 1)
            self.assertEqual(len(entry["content_method_assets"]), 1)
            profile = entry["profiles"][0]
            fragment_types = {item["fragment_type"] for item in profile["confirmed_fragments"]}
            self.assertIn("identity_fact", fragment_types)
            self.assertIn("expression_style", fragment_types)
            self.assertIn("professional_judgment", fragment_types)
            self.assertIn("reader_empathy", fragment_types)
            self.assertIn("business_boundary", fragment_types)
            self.assertEqual(
                profile["anchors"]["expression_style"],
                "甲说话亲切、明确、不端着。",
            )
            verify_source_snapshot(snapshot)

    def test_feishu_content_root_recurses_two_levels_but_not_three(self) -> None:
        class FakeClient:
            tree = {
                "root": [
                    {"node_token": "folder-1", "has_child": True, "obj_type": "docx", "obj_token": "folder-doc", "title": "公众号对标"},
                ],
                "folder-1": [
                    {"node_token": "article-1", "has_child": False, "obj_type": "docx", "obj_token": "article-doc", "title": "江景房判断方法"},
                    {"node_token": "folder-2", "has_child": True, "obj_type": "docx", "obj_token": "folder-2-doc", "title": "更深目录"},
                ],
                "folder-2": [
                    {"node_token": "too-deep", "has_child": False, "obj_type": "docx", "obj_token": "too-deep-doc", "title": "江景房深层文章"},
                ],
            }

            def list_children(self, *, space_id, parent_node_token):
                return self.tree.get(parent_node_token, [])

            def fetch_markdown(self, token):
                return f"# {token}\n\n内容"

        documents = _feishu_documents(
            FakeClient(), space_id="1", parent_ref="root", query="江景房", limit=5
        )

        self.assertEqual([item[0] for item in documents], ["article-doc"])

    def test_ganhuo_guide_requires_persona_judgment_and_executable_verification(self) -> None:
        guide = (
            Path(__file__).parents[1]
            / "skills"
            / "content-gzh-writer"
            / "references"
            / "ganhuo.md"
        ).read_text(encoding="utf-8")
        self.assertIn("读者真实处境", guide)
        self.assertIn("IP 的明确判断", guide)
        self.assertIn("用户可执行的核验动作", guide)
        self.assertIn("不要求每个自然段机械重复", guide)

    def test_explicit_second_ip_creates_distinct_identity(self) -> None:
        with self.temporary_root() as directory:
            root = Path(directory)
            vault, _index_path, _client_id, primary_id = self.make_vault(root)
            task_a, _kb_a, ip_a, _catalog_a, _snapshot_a = resolve_real_source({"knowledge_base": str(vault), "ip": "甲", "topic": "企业服务", "references": []})
            task_b, _kb_b, ip_b, _catalog_b, _snapshot_b = resolve_real_source({"knowledge_base": str(vault), "ip": "乙老师", "topic": "企业服务", "references": []})
            self.assertEqual(ip_a["profile_id"], primary_id)
            self.assertNotEqual(ip_a["profile_id"], ip_b["profile_id"])
            self.assertNotEqual(task_a["ip"], task_b["ip"])

    def test_source_mutation_is_detected_after_freeze(self) -> None:
        with self.temporary_root() as directory:
            root = Path(directory)
            vault, _index_path, _client_id, _primary_id = self.make_vault(root)
            _task, _kb, _ip, _catalog, snapshot = resolve_real_source({"knowledge_base": str(vault), "ip": "甲", "topic": "企业服务", "references": []})
            (vault / "03-业务知识库" / "业务.md").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ContentSourceError, "frozen source changed"):
                verify_source_snapshot(snapshot)

    def test_registry_manifest_and_profile_index_drift_are_each_blocked(self) -> None:
        for target, expected in (
            ("registry", "Registry changed"),
            ("manifest", "manifest changed"),
            ("profile_index", "profile_index changed"),
        ):
            with self.subTest(target=target), self.temporary_root() as directory:
                root = Path(directory)
                vault, index_path, _client_id, _primary_id = self.make_vault(root)
                registry = root / "registry.json"
                preview = plan_configuration(vault, registry_path=registry)
                apply_configuration(vault, registry_path=registry, confirmation=preview["confirmation"])
                _task, _kb, _ip, _catalog, snapshot = resolve_real_source(
                    {"topic": "企业服务", "references": []},
                    registry_path=registry,
                )
                path = {
                    "registry": registry,
                    "manifest": vault / "06-Agent与Workflow" / "content-source-manifest.json",
                    "profile_index": index_path,
                }[target]
                value = json.loads(path.read_text(encoding="utf-8"))
                value["revision"] += 1
                path.write_text(canonical(value), encoding="utf-8")
                with self.assertRaisesRegex(ContentSourceError, expected):
                    verify_source_snapshot(snapshot)

    def test_no_ip_must_be_explicit_or_confirmed_configuration(self) -> None:
        with self.temporary_root() as directory:
            root = Path(directory)
            vault, _index_path, _client_id, _primary_id = self.make_vault(root)
            registry = root / "registry.json"
            plan = plan_configuration(vault, registry_path=registry, default_no_ip=True)
            apply_configuration(vault, registry_path=registry, default_no_ip=True, confirmation=plan["confirmation"])
            _task, _kb, ip, _catalog, _snapshot = resolve_real_source({"topic": "企业服务", "references": []}, registry_path=registry)
            self.assertEqual(ip["status"], "none")

    def test_no_primary_multiple_profiles_requires_selection(self) -> None:
        with self.temporary_root() as directory:
            root = Path(directory)
            vault, index_path, _client_id, _primary_id = self.make_vault(root)
            index = json.loads(index_path.read_text(encoding="utf-8"))
            for item in index["profiles"]:
                item["is_primary"] = False
            index_path.write_text(canonical(index), encoding="utf-8")
            with self.assertRaisesRegex(ContentSourceError, "explicit selection"):
                resolve_real_source({"knowledge_base": str(vault), "topic": "企业服务", "references": []})

    def test_real_obsidian_chain_uses_manifest_target_and_readback(self) -> None:
        with self.temporary_root() as directory:
            root = Path(directory)
            vault, _index_path, _client_id, primary_id = self.make_vault(root)
            task, kb, ip, catalog, snapshot = resolve_real_source({"knowledge_base": str(vault), "ip": "甲", "topic": "企业服务怎么做", "references": []})
            store_root = root / "runs"
            store = RunStore(store_root)
            run = store.create_or_resume(task, kb, ip).run
            artifacts = ArtifactStore(store_root)
            artifacts.write_json_once_or_verify(run["run_id"], "source_catalog.json", catalog)
            artifacts.write_json_once_or_verify(run["run_id"], "source_snapshot.json", snapshot)
            entry = catalog["knowledge_bases"][0]
            business_ref = entry["business_assets"][0]["ref"]
            method_ref = entry["content_method_assets"][0]["ref"]
            analysis_path = root / "analysis.json"
            direction_path = root / "direction.json"
            selection_path = root / "selection.json"
            analysis_path.write_text(json.dumps({"schema_version": 1, "reference_analyses": [], "multi_reference_synthesis": None}), encoding="utf-8")
            direction = {
                "schema_version": 1,
                "mode": "single",
                "options": [{
                    "option_id": "real-direction-1",
                    "title": "企业服务先做需求诊断",
                    "speaker": "甲",
                    "target_audience": "需要梳理企业服务流程的负责人",
                    "core_judgment": "先确认问题和再提供方案。",
                    "promise": "给出一个可核验的诊断顺序。",
                    "why_now": "流程不清会让工具投入失去方向。",
                    "writer_mode": "ganhuo",
                    "writer_mode_reason": "适合用步骤解释。",
                    "voice_mode": "用甲的专业判断解释，不虚构个人经历。",
                    "professional_judgments": ["先诊断，再给方案。"],
                    "reader_situations": ["负责人面对流程不清的问题。"],
                    "verification_actions": ["核对问题、责任人和下一步。"],
                    "structure": [{"section": "先诊断", "purpose": "确认真实问题。"}, {"section": "再行动", "purpose": "给出最小下一步。"}],
                    "selected_sources": {"business_refs": [business_ref], "peer_refs": [], "method_refs": [method_ref], "reference_refs": []},
                    "benchmark_transfer": [],
                    "forbidden_transfer": ["不补造案例"],
                    "knowledge_materials": ["需求诊断事实"],
                    "business_connection": "连接到可验证的企业服务流程。",
                    "fact_boundaries": ["只使用已确认事实"],
                    "first_person_claims": [],
                    "must_keep": [],
                    "must_avoid": [],
                }],
            }
            direction_path.write_text(json.dumps(direction, ensure_ascii=False), encoding="utf-8")
            P2Pipeline(store_root, artifacts.boundary.child("runs", run["run_id"], "source_catalog.json")).run(run["run_id"], analysis_path, direction_path)
            store.approve_gate(run["run_id"], "A", "确认方向")
            selection = {
                "schema_version": 1,
                "selected_05_fragment_ids": [item["fragment_id"] for item in entry["profiles"][0]["confirmed_fragments"][:3]],
                "selected_03_refs": [business_ref],
                "selected_04_peer_refs": [],
                "selected_04_method_refs": [method_ref],
                "reference_mechanisms": [],
                "missing_evidence": [],
            }
            selection_path.write_text(json.dumps(selection, ensure_ascii=False), encoding="utf-8")
            P3Pipeline(store_root, artifacts.boundary.child("runs", run["run_id"], "source_catalog.json")).run(run["run_id"], selection_path)
            headline = {"diagnosis": {"target_audience": "企业负责人", "core_judgment": "先诊断再行动", "click_tension": "工具投入与结果之间的落差"}, "top3": [{"title": "企业服务，先别急着给方案", "reason": "突出诊断"}, {"title": "为什么先问清这件事", "reason": "制造行动感"}, {"title": "一套不跑偏的需求诊断顺序", "reason": "强调方法"}], "recommended": "企业服务，先别急着给方案"}
            P4Pipeline(store_root).run_initial(run["run_id"], "很多方案没有效果，不一定是工具不够好。先把真实问题、责任人和下一步问清楚，再决定需要什么方案。这样每一步都有资料可以回查，也不会把未经确认的判断写成事实。", headline)
            store.approve_gate(run["run_id"], "B", "确认正文和标题")
            result = SaveService(store_root, _derived_adapter(store_root, run["run_id"], identity="user")).save(run["run_id"])
            target = Path(result["save_receipt"]["target"]["object_ref"])
            self.assertTrue(target.is_file())
            self.assertIn(primary_id, target.parts)
            self.assertEqual(result["save_receipt"]["readback_status"], "verified")
            self.assertFalse(result["save_receipt"]["semantics"]["published"])


if __name__ == "__main__":
    unittest.main()
