from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from runtime.approved_direction import ApprovedDirectionError, materialize_approved_direction
from runtime.artifact_store import ArtifactStore
from runtime.context_contract import CONTEXT_ROOT_FIELDS
from runtime.contracts import validate_task_input
from runtime.fixture_adapter import FixtureAdapter
from runtime.frozen_projection import FrozenProjectionError
from runtime.p2_pipeline import P2Pipeline
from runtime.p3_pipeline import P3Pipeline
from runtime.run_store import RunStore, RunStoreError


FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = FIXTURES / "p2_catalog.json"


def read_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class P3RuntimeTests(unittest.TestCase):
    def _p2_run(self, root: str, *, approve: bool) -> tuple[str, RunStore]:
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
        if approve:
            store.approve_gate(run["run_id"], "A", "确认方向")
        return run["run_id"], store

    def test_p3_rejects_unapproved_gate_a(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, _ = self._p2_run(temporary, approve=False)
            with self.assertRaisesRegex(RunStoreError, "direction_approved"):
                P3Pipeline(temporary, CATALOG).run(
                    run_id, FIXTURES / "p3_selection.json"
                )

    def test_p3_creates_one_context_and_stops_context_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._p2_run(temporary, approve=True)
            result = P3Pipeline(temporary, CATALOG).run(
                run_id, FIXTURES / "p3_selection.json"
            )
            run = store.load(run_id)
            names = {
                path.name
                for path in (Path(temporary) / "runs" / run_id).iterdir()
                if path.is_file()
            }

        self.assertEqual(run["status"], "context_ready")
        self.assertFalse(result["resumed"])
        self.assertIn("approved_direction.json", names)
        self.assertIn("article_context_v1.json", names)
        self.assertEqual(len([name for name in names if name.startswith("article_context")]), 1)
        self.assertFalse(any("source_pack" in name or "writing_packet" in name for name in names))
        self.assertFalse(any(name.endswith(".md") for name in names))

    def test_context_has_only_spec_fields_and_role_budgets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, _ = self._p2_run(temporary, approve=True)
            context = P3Pipeline(temporary, CATALOG).run(
                run_id, FIXTURES / "p3_selection.json"
            )["context"]

        self.assertEqual(set(context), CONTEXT_ROOT_FIELDS)
        self.assertEqual(context["writer_mode"], "ganhuo")
        self.assertLessEqual(len(context["selected_05_profile_context"]["confirmed_fragments"]), 3)
        self.assertLessEqual(len(context["selected_03_business_context"]), 5)
        self.assertLessEqual(len(context["selected_04_content_assets"]), 3)
        self.assertLessEqual(len(context["selected_04_method_assets"]), 2)
        self.assertEqual(context["ip_identity_and_status"]["requested_name"], "示例甲")

    def test_receipt_marks_final_selection_but_stays_operational_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, _ = self._p2_run(temporary, approve=True)
            result = P3Pipeline(temporary, CATALOG).run(
                run_id, FIXTURES / "p3_selection.json"
            )

        receipt = result["retrieval_receipt"]
        self.assertEqual(receipt["totals"]["context_packs"], 1)
        self.assertTrue(any(item["final_selection_status"] == "selected" for item in receipt["entries"]))
        self.assertTrue(any(item["final_selection_status"] == "not_selected" for item in receipt["entries"]))
        reference_entry = next(item for item in receipt["entries"] if item["role"] == "reference")
        self.assertTrue(reference_entry["in_context_pack"])
        self.assertIn("full frozen source", reference_entry["selected_use"])
        self.assertNotEqual(set(receipt), CONTEXT_ROOT_FIELDS)

    def test_context_preserves_full_reference_separately_from_author_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, _ = self._p2_run(temporary, approve=True)
            context = P3Pipeline(temporary, CATALOG).run(
                run_id, FIXTURES / "p3_selection.json"
            )["context"]
            snapshot = ArtifactStore(temporary).read_json(run_id, "reference_snapshot_v1.json")
        source = context["selected_reference_mechanisms"][0]["source_snapshot"]
        self.assertEqual(source["content"], snapshot["references"][0]["content"])
        self.assertIn("负责人连续收到投诉的虚构场景提出疑问", source["content"])
        self.assertNotIn("负责人连续收到投诉", json.dumps(context["selected_05_profile_context"], ensure_ascii=False))
        self.assertIn("not instructions", source["usage_boundary"])
        self.assertEqual(context["selected_reference_mechanisms"][0]["forbidden_transfers"], read_json("p3_selection.json")["reference_mechanisms"][0]["forbidden_transfers"])

    def test_p3_rejects_modified_reference_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, _ = self._p2_run(temporary, approve=True)
            path = Path(temporary) / "runs" / run_id / "reference_snapshot_v1.json"
            snapshot = json.loads(path.read_text())
            snapshot["references"][0]["content"] = "Changed after analysis"
            path.write_text(json.dumps(snapshot))
            with self.assertRaisesRegex(RunStoreError, "reference snapshot differs"):
                P3Pipeline(temporary, CATALOG).run(run_id, FIXTURES / "p3_selection.json")

    def test_post_gate_selection_cannot_replace_04_or_expand_03(self) -> None:
        bad_04 = read_json("p3_selection.json")
        bad_04["selected_04_method_refs"] = ["fixture://obsidian/kb-alpha/04/m2"]
        bad_03 = read_json("p3_selection.json")
        bad_03["selected_03_refs"].append("fixture://obsidian/kb-alpha/03/b4")

        for selection, message in ((bad_04, "reused exactly"), (bad_03, "approved Gate A")):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                run_id, _ = self._p2_run(temporary, approve=True)
                selection_path = Path(temporary) / "selection.json"
                selection_path.write_text(json.dumps(selection, ensure_ascii=False), encoding="utf-8")
                with self.assertRaisesRegex(FrozenProjectionError, message):
                    P3Pipeline(temporary, CATALOG).run(run_id, selection_path)

    def test_p3_cannot_read_a_fragment_from_another_ip(self) -> None:
        selection = read_json("p3_selection.json")
        selection["selected_05_fragment_ids"] = ["ip-limited-boundary"]
        with tempfile.TemporaryDirectory() as temporary:
            run_id, _ = self._p2_run(temporary, approve=True)
            selection_path = Path(temporary) / "selection.json"
            selection_path.write_text(json.dumps(selection, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(FrozenProjectionError, "same IP"):
                P3Pipeline(temporary, CATALOG).run(run_id, selection_path)

    def test_create_only_retry_resumes_same_and_rejects_different_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, _ = self._p2_run(temporary, approve=True)
            pipeline = P3Pipeline(temporary, CATALOG)
            first = pipeline.run(run_id, FIXTURES / "p3_selection.json")
            second = pipeline.run(run_id, FIXTURES / "p3_selection.json")

            changed = read_json("p3_selection.json")
            changed["missing_evidence"].append("另一条不同缺口")
            changed_path = Path(temporary) / "changed-selection.json"
            changed_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "different P3 selection"):
                pipeline.run(run_id, changed_path)

        self.assertFalse(first["resumed"])
        self.assertTrue(second["resumed"])
        self.assertEqual(first["context"], second["context"])

    def test_approved_direction_binds_run_and_rejects_unbound_multiple_options(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id, store = self._p2_run(temporary, approve=True)
            artifacts = ArtifactStore(temporary)
            run = store.load(run_id)
            direction = artifacts.read_json(run_id, "direction_v1.json")
            receipt = artifacts.read_json(run_id, "retrieval_receipt.json")
            approved = materialize_approved_direction(run, direction, receipt)
            self.assertEqual(approved["run_id"], run_id)
            self.assertEqual(approved["gate_receipt"]["decision"], "确认方向")

            multiple = copy.deepcopy(direction)
            multiple["mode"] = "options"
            multiple["options"].append(copy.deepcopy(multiple["options"][0]))
            multiple["options"][1]["option_id"] = "direction-2"
            with self.assertRaisesRegex(ApprovedDirectionError, "refusing to guess"):
                materialize_approved_direction(run, multiple, receipt)


if __name__ == "__main__":
    unittest.main()
