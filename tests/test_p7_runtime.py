from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from runtime.lark_cli_client import LarkCliFeishuClient


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class StubLarkClient(LarkCliFeishuClient):
    def __init__(self, state_path: Path) -> None:
        super().__init__(state_path, binary=sys.executable)
        self.created_content = ""

    def _call(self, arguments):
        if "+create" in arguments:
            self.created_content = arguments[arguments.index("--content") + 1]
            return {
                "ok": True,
                "data": {"document": {"url": "https://example.feishu.cn/docx/test-doc"}},
            }
        return {
            "ok": True,
            "data": {"document": {"content": self.created_content}},
        }


class P7RuntimeTests(unittest.TestCase):
    @staticmethod
    def _utf8_run(arguments, **kwargs):
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment.update(kwargs.pop("env", {}))
        return subprocess.run(
            arguments,
            text=True,
            encoding="utf-8",
            errors="strict",
            env=environment,
            **kwargs,
        )

    def _build(self, temporary: str) -> tuple[Path, Path]:
        candidate = Path(temporary) / "candidate"
        project = Path(temporary) / "project"
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "build_p7_candidate.py"),
                "--output",
                str(candidate),
                "--install-project",
                str(project),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            env=environment,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return candidate, project

    def test_candidate_is_self_contained_private_and_project_installed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate, project = self._build(temporary)
            manifest = json.loads(
                (candidate / "PACKAGE-MANIFEST.json").read_text(encoding="utf-8")
            )
            probe = self._utf8_run(
                [sys.executable, "-B", str(candidate / "bin" / "content-gzh-slim"), "probe"],
                check=False,
                capture_output=True,
            )
            installed = project / ".agents" / "skills"
            installed_is_symlink = installed.is_symlink()
            installed_is_directory = installed.is_dir()

        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertTrue(installed_is_symlink or installed_is_directory)
        self.assertEqual(len(manifest["skills"]), 6)
        self.assertFalse(manifest["credentials_included"])
        self.assertFalse(manifest["customer_data_included"])
        self.assertFalse(any(path.startswith("tests/") for path in manifest["files"]))

    def test_internal_skills_are_explicit_only(self) -> None:
        public = ROOT / "skills" / "content-gzh-slim" / "SKILL.md"
        self.assertTrue(public.is_file())
        for name in (
            "content-gzh-analyzer",
            "content-gzh-context-retriever",
            "content-gzh-writer",
            "content-gzh-headline",
            "content-gzh-distribution-pack",
        ):
            policy = (ROOT / "skills" / name / "agents" / "openai.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn("allow_implicit_invocation: false", policy)

    def test_real_feishu_client_keeps_credentials_out_of_state_and_reads_remote_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "client-state.json"
            client = StubLarkClient(state)
            metadata = {
                "version": 1,
                "body_digest": "a" * 64,
                "context_digest": "b" * 64,
            }
            reference = client.create_document_once(
                "my_library", "测试标题", "第一段。\n\n第二段。", metadata
            )
            readback = client.read_document(reference)
            state_text = state.read_text(encoding="utf-8")

        self.assertEqual(readback["title"], "测试标题")
        self.assertEqual(readback["body"], "第一段。\n\n第二段。")
        self.assertEqual(readback["metadata"], metadata)
        self.assertNotIn("access_token", state_text.casefold())
        self.assertNotIn("refresh_token", state_text.casefold())

    def test_bundled_launcher_smokes_full_fixture_chain_to_isolated_obsidian(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate, _ = self._build(temporary)
            launcher = candidate / "bin" / "content-gzh-slim"
            store = Path(temporary) / "runs"
            task = FIXTURES / "p2_task.json"
            catalog = FIXTURES / "p2_catalog.json"

            start = self._utf8_run(
                [sys.executable, "-B", str(launcher), "start", "--input", str(task), "--catalog", str(catalog), "--store", str(store)],
                check=True,
                capture_output=True,
            )
            run_id = json.loads(start.stdout)["run_id"]
            self._utf8_run(
                [sys.executable, "-B", str(launcher), "prepare-gate-a", "--input", str(task), "--catalog", str(catalog), "--analysis", str(FIXTURES / "p2_analysis.json"), "--direction", str(FIXTURES / "p2_direction.json"), "--store", str(store)],
                check=True,
                capture_output=True,
            )
            self._utf8_run(
                [sys.executable, "-B", str(launcher), "approve-gate-a", "--run-id", run_id, "--store", str(store), "--option-id", "direction-1", "--decision", "确认方向"],
                check=True,
                capture_output=True,
            )
            self._utf8_run(
                [sys.executable, "-B", str(launcher), "build-context", "--run-id", run_id, "--catalog", str(catalog), "--selection", str(FIXTURES / "p3_selection.json"), "--store", str(store)],
                check=True,
                capture_output=True,
            )
            self._utf8_run(
                [sys.executable, "-B", str(launcher), "prepare-gate-b", "--run-id", run_id, "--draft-output", str(FIXTURES / "p4_draft.md"), "--headline-output", str(FIXTURES / "p4_headline.json"), "--store", str(store)],
                check=True,
                capture_output=True,
            )
            self._utf8_run(
                [sys.executable, "-B", str(launcher), "approve-gate-b", "--run-id", run_id, "--store", str(store), "--decision", "确认正文和标题"],
                check=True,
                capture_output=True,
            )
            context = json.loads(
                (store / "runs" / run_id / "article_context_v1.json").read_text(encoding="utf-8")
            )
            target_ref = context["save_target_preview"]["target_ref"]
            saved = self._utf8_run(
                [sys.executable, "-B", str(launcher), "save-obsidian", "--run-id", run_id, "--store", str(store), "--isolated-root", str(Path(temporary) / "obsidian"), "--target-ref", target_ref, "--relative-dir", "articles"],
                check=False,
                capture_output=True,
            )

        self.assertEqual(saved.returncode, 0, saved.stderr)
        receipt = json.loads(saved.stdout)
        self.assertEqual(receipt["readback_status"], "verified")
        self.assertFalse(receipt["semantics"]["published"])


if __name__ == "__main__":
    unittest.main()
