from __future__ import annotations

import copy
import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.artifact_store import ArtifactStore
from runtime.save_contract import SaveContractError, validate_target_preview


ROOT = Path(__file__).resolve().parents[1]


def _load_verify_module():
    spec = importlib.util.spec_from_file_location("content_gzh_verify", ROOT / "tools" / "verify.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsCompatibilityTests(unittest.TestCase):
    def test_verify_success_message_is_ascii_console_safe(self) -> None:
        source = (ROOT / "tools" / "verify.py").read_text(encoding="utf-8")
        success_line = next(line for line in source.splitlines() if line.strip().startswith("print(f\"PASS:"))
        self.assertTrue(success_line.isascii())

    def test_verify_subprocesses_request_utf8_text_decoding(self) -> None:
        verify = _load_verify_module()
        completed = subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
        with mock.patch.object(verify.subprocess, "run", return_value=completed) as run:
            result = verify._run_utf8([sys.executable, "-c", "print('中文')"])

        self.assertEqual(result.returncode, 0)
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "strict")

    def test_artifact_text_hash_is_calculated_from_persisted_utf8_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = ArtifactStore(temporary)
            run_id = "run_" + "a" * 24
            run_dir = Path(temporary) / "runs" / run_id
            run_dir.mkdir(parents=True)
            artifacts.write_text_once_or_verify(run_id, "draft_v1.md", "第一行\n第二行")
            persisted = (run_dir / "draft_v1.md").read_bytes()

        self.assertEqual(persisted, "第一行\n第二行\n".encode("utf-8"))
        self.assertEqual(hashlib.sha256(persisted).hexdigest(), hashlib.sha256("第一行\n第二行\n".encode("utf-8")).hexdigest())

    def test_save_target_rejects_all_host_absolute_and_escape_forms(self) -> None:
        base = {
            "knowledge_base_identity": {"backend": "obsidian"},
            "save_target_preview": {
                "backend": "obsidian",
                "target_ref": "fixture://obsidian/kb/articles",
                "status": "preview_only_not_writable",
            },
        }
        for target_ref in (
            "/absolute/articles",
            "C:\\absolute\\articles",
            "C:/absolute/articles",
            "\\\\server\\share\\articles",
            "\\\\?\\C:\\absolute\\articles",
            "fixture://obsidian/kb/..\\articles",
            "fixture://obsidian/kb\\05-IP-Profile\\articles",
            "fixture://obsidian/kb/03-业务知识库/articles",
            "safe\x00name",
        ):
            with self.subTest(target_ref=target_ref):
                context = copy.deepcopy(base)
                context["save_target_preview"]["target_ref"] = target_ref
                with self.assertRaises(SaveContractError):
                    validate_target_preview(context, "obsidian")

    def test_activation_falls_back_to_copy_and_rolls_back_partial_new_entries(self) -> None:
        spec = importlib.util.spec_from_file_location("content_gzh_install", ROOT / "install.py")
        assert spec and spec.loader
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skills_root = root / "skills"
            skills_root.mkdir()
            package = root / "package"
            wanted = package / ".agents" / "skills"
            for name in installer.SKILLS:
                (wanted / name).mkdir(parents=True, exist_ok=True)
                (wanted / name / "SKILL.md").write_bytes(name.encode("utf-8"))
            original_copy = installer._copy
            calls = 0

            def fail_second_copy(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated copy failure")
                original_copy(source, destination)

            with mock.patch.object(installer, "_activation_mode", return_value="copy"), mock.patch.object(installer, "_copy", side_effect=fail_second_copy):
                with self.assertRaisesRegex(OSError, "simulated copy failure"):
                    installer._activate(skills_root, package)

            self.assertFalse(any((skills_root / name).exists() or (skills_root / name).is_symlink() for name in installer.SKILLS))


if __name__ == "__main__":
    unittest.main()
