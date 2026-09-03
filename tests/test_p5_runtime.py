from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from runtime.approved_direction import canonical_digest
from runtime.artifact_store import ArtifactStore
from runtime.contracts import validate_task_input
from runtime.feishu_adapter import FeishuAdapter
from runtime.fixture_adapter import FixtureAdapter
from runtime.obsidian_adapter import ObsidianAdapter, SaveAdapterError, _slug
from runtime.p2_pipeline import P2Pipeline
from runtime.p3_pipeline import P3Pipeline
from runtime.p4_pipeline import P4Pipeline
from runtime.run_store import RunStore, RunStoreError
from runtime.save_contract import SaveContractError, validate_target_preview
from runtime.save_service import SaveService


FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = FIXTURES / "p2_catalog.json"


def read_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeFeishuClient:
    def __init__(self, *, corrupt_readback: bool = False) -> None:
        self.documents: dict[str, dict] = {}
        self.names: dict[tuple[str, str], str] = {}
        self.corrupt_readback = corrupt_readback

    def create_document_once(self, parent_ref, title, body, metadata):
        key = (parent_ref, title)
        existing_ref = self.names.get(key)
        candidate = {"title": title, "body": body, "metadata": copy.deepcopy(metadata)}
        if existing_ref is not None:
            if self.documents[existing_ref] != candidate:
                raise SaveAdapterError("Feishu article name conflict")
            return existing_ref
        object_ref = f"fake-doc-{len(self.documents) + 1}"
        self.names[key] = object_ref
        self.documents[object_ref] = candidate
        return object_ref

    def read_document(self, object_ref):
        value = copy.deepcopy(self.documents[object_ref])
        if self.corrupt_readback:
            value["body"] += "被篡改"
        return value


class CorruptingObsidianAdapter(ObsidianAdapter):
    def read_back(self, target):
        value = super().read_back(target)
        value["title"] += "不一致"
        return value


class P5RuntimeTests(unittest.TestCase):
    def _waiting_final_run(self, root: str) -> tuple[str, RunStore]:
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
        return run["run_id"], store

    def _final_approved_run(
        self, root: str, decision: str = "确认正文和标题"
    ) -> tuple[str, RunStore]:
        run_id, store = self._waiting_final_run(root)
        store.approve_gate(run_id, "B", decision)
        return run_id, store

    def _obsidian_adapter(self, root: str, run_id: str, *, corrupt=False):
        context = ArtifactStore(root).read_json(run_id, "article_context_v1.json")
        adapter_class = CorruptingObsidianAdapter if corrupt else ObsidianAdapter
        return adapter_class(
            Path(root) / "isolated-obsidian",
            {context["save_target_preview"]["target_ref"]: "articles"},
        )

    def _feishu_final_run(self, root: str) -> tuple[str, RunStore, str]:
        template_run_id, _ = self._waiting_final_run(root)
        artifacts = ArtifactStore(root)
        template_context = artifacts.read_json(template_run_id, "article_context_v1.json")
        template_approved = artifacts.read_json(template_run_id, "approved_direction.json")

        raw_task = read_json("p2_task.json")
        raw_task["knowledge_base"] = "fixture-kb-beta"
        raw_task["ip"] = "none"
        task = validate_task_input(raw_task)
        knowledge_base = {
            "backend": "feishu",
            "ref": "fixture://feishu/kb-beta",
            "manifest_revision": "fixture-beta-r1",
        }
        ip = {"requested_name": "none", "resolved_ref": None, "status": "none"}
        store = RunStore(root)
        run = store.create_or_resume(task, knowledge_base, ip).run
        store.advance(run["run_id"], "direction_working")
        store.advance(run["run_id"], "waiting_direction")
        store.approve_gate(run["run_id"], "A", "确认方向")
        run = store.load(run["run_id"])
        gate_a = run["gate_approvals"][0]

        approved = copy.deepcopy(template_approved)
        approved.update(
            {
                "run_id": run["run_id"],
                "input_digest": run["input_digest"],
                "knowledge_base_identity": knowledge_base,
                "ip_identity": ip,
                "task_input": task,
                "gate_receipt": gate_a,
                "direction_digest": "f" * 64,
            }
        )
        context = copy.deepcopy(template_context)
        context["run_identity"].update(
            {"run_id": run["run_id"], "input_digest": run["input_digest"]}
        )
        context["run_identity"]["gate_a"].update(
            {
                "decision": "确认方向",
                "approved_at": gate_a["at"],
                "direction_digest": approved["direction_digest"],
            }
        )
        context["knowledge_base_identity"] = knowledge_base
        context["ip_identity_and_status"] = ip
        context["task_input"] = task
        context["selected_05_profile_context"] = {
            "ip_ref": None,
            "status": "none",
            "core_anchors": {},
            "confirmed_fragments": [],
        }
        target_ref = "fixture://feishu/kb-beta/articles"
        context["save_target_preview"] = {
            "backend": "feishu",
            "target_ref": target_ref,
            "status": "preview_only_not_writable",
        }
        artifacts.write_json_once_or_verify(run["run_id"], "approved_direction.json", approved)
        artifacts.write_json_once_or_verify(run["run_id"], "article_context_v1.json", context)
        store.advance(run["run_id"], "context_ready")
        P4Pipeline(root).run_initial(
            run["run_id"],
            (FIXTURES / "p4_draft.md").read_text(encoding="utf-8"),
            read_json("p4_headline.json"),
        )
        store.approve_gate(run["run_id"], "B", "确认正文和标题")
        return run["run_id"], store, target_ref

    def test_save_rejects_missing_or_nonfinal_gate_b(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._waiting_final_run(temporary)
            adapter = self._obsidian_adapter(temporary, run_id)
            with self.assertRaisesRegex(RunStoreError, "final_approved"):
                SaveService(temporary, {"obsidian": adapter}).save(run_id)

            run_path = Path(temporary) / "runs" / run_id / "run.json"
            run = store.load(run_id)
            run["status"] = "final_approved"
            run["gate_approvals"].append(
                {"gate": "B", "decision": "需要修改正文：继续改", "at": "fixture-time"}
            )
            run_path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(SaveContractError, "not an explicit final approval"):
                SaveService(temporary, {"obsidian": adapter}).save(run_id)

    def test_obsidian_save_is_create_only_and_readback_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._final_approved_run(temporary)
            adapter = self._obsidian_adapter(temporary, run_id)
            service = SaveService(temporary, {"obsidian": adapter})
            first = service.save(run_id)
            second = service.save(run_id)
            receipt = first["save_receipt"]
            saved_path = Path(receipt["target"]["object_ref"])
            status = store.load(run_id)["status"]

        self.assertEqual(status, "saved")
        self.assertTrue(
            saved_path.resolve().is_relative_to(
                (Path(temporary) / "isolated-obsidian").resolve()
            )
        )
        self.assertEqual(receipt["readback_status"], "verified")
        self.assertFalse(first["resumed"])
        self.assertTrue(second["resumed"])

    def test_feishu_adapter_uses_injected_fake_client_and_readback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store, target_ref = self._feishu_final_run(temporary)
            client = FakeFeishuClient()
            adapter = FeishuAdapter(client, {target_ref: "fake-parent-beta"})
            service = SaveService(temporary, {"feishu": adapter})
            result = service.save(run_id)
            resumed = service.save(run_id)
            status = store.load(run_id)["status"]
            for protected_parent in ("05 IP", "03-业务库", "04_内容方法"):
                protected = FeishuAdapter(client, {target_ref: protected_parent})
                with self.assertRaisesRegex(SaveAdapterError, "01-05"):
                    protected.write_create_only(result["approved_final"])
            safe_client = FakeFeishuClient()
            safe = FeishuAdapter(safe_client, {target_ref: "051资料"})
            safe.write_create_only(result["approved_final"])

        self.assertEqual(status, "saved")
        self.assertEqual(result["save_receipt"]["backend"], "feishu")
        self.assertEqual(len(client.documents), 1)
        self.assertTrue(resumed["resumed"])

    def test_final_title_must_be_top3_or_explicit_gate_b_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._final_approved_run(temporary)
            adapter = self._obsidian_adapter(temporary, run_id)
            alternate_top3_title = read_json("p4_headline.json")["top3"][0]["title"]
            with self.assertRaisesRegex(SaveContractError, "recommended title"):
                SaveService(temporary, {"obsidian": adapter}).save(
                    run_id, final_title=alternate_top3_title
                )
            self.assertEqual(store.load(run_id)["status"], "final_approved")
            confirmed = SaveService(temporary, {"obsidian": adapter}).save(run_id)
            self.assertEqual(
                confirmed["approved_final"]["headline"]["final_title"],
                read_json("p4_headline.json")["recommended"],
            )

        with tempfile.TemporaryDirectory() as temporary:
            explicit = "用户现场明确输入的新标题"
            run_id, _ = self._final_approved_run(temporary, f"使用标题：{explicit}")
            adapter = self._obsidian_adapter(temporary, run_id)
            result = SaveService(temporary, {"obsidian": adapter}).save(run_id)
            self.assertEqual(result["approved_final"]["headline"]["final_title"], explicit)
            self.assertEqual(
                result["approved_final"]["headline"]["title_source"],
                "explicit_gate_b_input",
            )

    def test_version_and_digests_are_bound_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._final_approved_run(temporary)
            artifacts = ArtifactStore(temporary)
            headline = artifacts.read_json(run_id, "headline_v1.json")
            headline["draft_digest"] = "0" * 64
            path = Path(temporary) / "runs" / run_id / "headline_v1.json"
            path.write_text(json.dumps(headline, ensure_ascii=False), encoding="utf-8")
            adapter = self._obsidian_adapter(temporary, run_id)
            with self.assertRaisesRegex(SaveContractError, "draft digest mismatch"):
                SaveService(temporary, {"obsidian": adapter}).save(run_id)
            self.assertEqual(store.load(run_id)["status"], "final_approved")

    def test_target_rejects_absolute_parent_protected_and_mapping_escape(self) -> None:
        base = {
            "knowledge_base_identity": {"backend": "obsidian"},
            "save_target_preview": {
                "backend": "obsidian",
                "target_ref": "fixture://obsidian/kb/articles",
                "status": "preview_only_not_writable",
            },
        }
        bad_refs = [
            "/absolute/articles",
            "fixture://obsidian/kb/../articles",
            "fixture://obsidian/kb/05 IP/articles",
            "fixture://obsidian/kb/03-业务库/articles",
            "fixture://obsidian/kb/04_内容方法/articles",
        ]
        for target_ref in bad_refs:
            with self.subTest(target_ref=target_ref):
                context = copy.deepcopy(base)
                context["save_target_preview"]["target_ref"] = target_ref
                with self.assertRaises(SaveContractError):
                    validate_target_preview(context, "obsidian")
        safe_numbered = copy.deepcopy(base)
        safe_numbered["save_target_preview"]["target_ref"] = (
            "fixture://obsidian/kb/051资料/articles"
        )
        self.assertEqual(
            validate_target_preview(safe_numbered, "obsidian")["backend"], "obsidian"
        )
        backend_mismatch = copy.deepcopy(base)
        backend_mismatch["save_target_preview"]["backend"] = "feishu"
        with self.assertRaisesRegex(SaveContractError, "frozen knowledge base"):
            validate_target_preview(backend_mismatch, "feishu")

        with tempfile.TemporaryDirectory() as temporary:
            run_id, _ = self._final_approved_run(temporary)
            context = ArtifactStore(temporary).read_json(run_id, "article_context_v1.json")
            adapter = ObsidianAdapter(
                Path(temporary) / "isolated",
                {context["save_target_preview"]["target_ref"]: "../outside"},
            )
            with self.assertRaisesRegex(SaveAdapterError, "escapes"):
                SaveService(temporary, {"obsidian": adapter}).save(run_id)

            target_ref = context["save_target_preview"]["target_ref"]
            for protected_relative in ("05 IP/articles", "03-业务库", "04_内容方法"):
                protected = ObsidianAdapter(
                    Path(temporary) / "isolated", {target_ref: protected_relative}
                )
                with self.assertRaisesRegex(SaveAdapterError, "01-05"):
                    protected._directory(target_ref)
            safe = ObsidianAdapter(
                Path(temporary) / "isolated", {target_ref: "051资料/articles"}
            )
            self.assertEqual(safe._directory(target_ref).parts[-2:], ("051资料", "articles"))

    def test_placeholder_or_fixture_residue_blocks_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._final_approved_run(temporary)
            run_dir = Path(temporary) / "runs" / run_id
            body = (run_dir / "draft_v1.md").read_text(encoding="utf-8").rstrip()
            body += "\n\n[TODO] 补一段"
            (run_dir / "draft_v1.md").write_text(body + "\n", encoding="utf-8")
            headline = json.loads((run_dir / "headline_v1.json").read_text(encoding="utf-8"))
            headline["draft_digest"] = canonical_digest(body)
            (run_dir / "headline_v1.json").write_text(
                json.dumps(headline, ensure_ascii=False), encoding="utf-8"
            )
            adapter = self._obsidian_adapter(temporary, run_id)
            with self.assertRaisesRegex(SaveContractError, "placeholder"):
                SaveService(temporary, {"obsidian": adapter}).save(run_id)
            self.assertEqual(store.load(run_id)["status"], "final_approved")

    def test_readback_mismatch_never_reports_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._final_approved_run(temporary)
            adapter = self._obsidian_adapter(temporary, run_id, corrupt=True)
            with self.assertRaisesRegex(SaveAdapterError, "readback"):
                SaveService(temporary, {"obsidian": adapter}).save(run_id)
            run_dir = Path(temporary) / "runs" / run_id
            status = store.load(run_id)["status"]
            receipt_exists = (run_dir / "save_receipt.json").exists()

        self.assertEqual(status, "saving")
        self.assertFalse(receipt_exists)

    def test_same_name_conflict_preserves_saving_error_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._final_approved_run(temporary)
            adapter = self._obsidian_adapter(temporary, run_id)
            headline = ArtifactStore(temporary).read_json(run_id, "headline_v1.json")
            target_dir = Path(temporary) / "isolated-obsidian" / "articles"
            target_dir.mkdir(parents=True)
            (target_dir / _slug(headline["recommended"])).write_text(
                "different content", encoding="utf-8"
            )
            with self.assertRaisesRegex(SaveAdapterError, "conflicts"):
                SaveService(temporary, {"obsidian": adapter}).save(run_id)
            status = store.load(run_id)["status"]

        self.assertEqual(status, "saving")

    def test_saved_semantics_and_artifact_budget_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._final_approved_run(temporary)
            adapter = self._obsidian_adapter(temporary, run_id)
            result = SaveService(temporary, {"obsidian": adapter}).save(run_id)
            names = {
                path.name
                for path in (Path(temporary) / "runs" / run_id).iterdir()
                if path.is_file()
            }
            status = store.load(run_id)["status"]

        semantics = result["save_receipt"]["semantics"]
        self.assertEqual(status, "saved")
        self.assertEqual(
            semantics,
            {
                "saved": True,
                "draftbox": False,
                "published": False,
                "distribution_generated": False,
            },
        )
        p5_artifacts = {name for name in names if name in {"approved_final.json", "save_receipt.json"}}
        self.assertEqual(p5_artifacts, {"approved_final.json", "save_receipt.json"})
        self.assertFalse(any("review" in name or "quality" in name for name in names))


if __name__ == "__main__":
    unittest.main()
