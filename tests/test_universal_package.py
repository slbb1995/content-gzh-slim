from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def _load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UniversalPackageTests(unittest.TestCase):
    def test_installer_resolves_codex_and_workbuddy_homes(self) -> None:
        installer = _load("install.py", "content_gzh_installer_hosts")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            installer.Path, "home", return_value=Path("/users/customer")
        ):
            self.assertEqual(installer._default_agent_home("codex"), Path("/users/customer/.codex"))
            self.assertEqual(
                installer._default_agent_home("workbuddy"), Path("/users/customer/.workbuddy")
            )

        with mock.patch.dict(
            os.environ,
            {"CODEX_HOME": "/agents/codex", "WORKBUDDY_HOME": "/agents/workbuddy"},
            clear=True,
        ):
            self.assertEqual(installer._default_agent_home("codex"), Path("/agents/codex"))
            self.assertEqual(
                installer._default_agent_home("workbuddy"), Path("/agents/workbuddy")
            )

    def test_workbuddy_skill_frontmatter_matches_release_version(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        skill = (ROOT / "workbuddy" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\n"))
        self.assertIn("name: content-gzh-slim", skill)
        self.assertIn(f"version: {version}", skill)
        self.assertIn("description:", skill)
        self.assertIn("scripts/content-gzh-slim", skill)
        self.assertIn("skills/content-gzh-analyzer/SKILL.md", skill)

    def test_universal_zip_contains_both_host_surfaces_and_verified_manifest(self) -> None:
        builder = ROOT / "tools" / "build_universal_package.py"
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary) / "content-gzh-slim.zip"
            completed = subprocess.run(
                [sys.executable, "-B", str(builder), "--output", str(output), "--allow-dirty"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertTrue(output.is_file())
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertIn("SKILL.md", names)
                self.assertIn("workbuddy.json", names)
                self.assertIn("workbuddy/SKILL.md", names)
                self.assertIn("workbuddy/workbuddy.json", names)
                self.assertIn(".gitattributes", names)
                self.assertIn("install.py", names)
                self.assertIn("scripts/content-gzh-slim", names)
                self.assertIn("runtime/host_cli.py", names)
                self.assertIn(".github/workflows/universal-package.yml", names)
                for name in (
                    "content-gzh-slim",
                    "content-gzh-analyzer",
                    "content-gzh-context-retriever",
                    "content-gzh-writer",
                    "content-gzh-headline",
                    "content-gzh-distribution-pack",
                ):
                    self.assertIn(f"skills/{name}/SKILL.md", names)
                self.assertFalse(any(name.startswith(".git/") for name in names))
                self.assertFalse(any("phase-receipts/" in name for name in names))
                manifest = json.loads(archive.read("UNIVERSAL-PACKAGE-MANIFEST.json"))
                self.assertEqual(manifest["version"], (ROOT / "VERSION").read_text().strip())
                self.assertEqual(manifest["hosts"], ["codex", "workbuddy"])
                self.assertEqual(manifest["operating_systems"], ["macos", "windows"])
                git_revision = subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, check=False,
                    capture_output=True, text=True, encoding="utf-8"
                )
                expected_revision = (
                    git_revision.stdout.strip()
                    if git_revision.returncode == 0
                    else json.loads((ROOT / "UNIVERSAL-PACKAGE-MANIFEST.json").read_text(encoding="utf-8"))["source_revision"]
                )
                self.assertEqual(manifest["source_revision"], expected_revision)
                for relative, expected in manifest["files"].items():
                    import hashlib

                    self.assertEqual(hashlib.sha256(archive.read(relative)).hexdigest(), expected)
                extracted = Path(temporary) / "extracted"
                archive.extractall(extracted)
            probe = subprocess.run(
                [sys.executable, "-B", str(extracted / "scripts" / "content-gzh-slim"), "probe"],
                cwd=extracted,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
            )
            self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
            self.assertEqual(json.loads(probe.stdout)["status"], "ready")

    def test_workbuddy_activation_is_self_contained_and_probes_without_git(self) -> None:
        installer = _load("install.py", "content_gzh_installer_workbuddy")
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            root = Path(temporary)
            package = root / "package"
            package.mkdir()
            installer._build(package)
            skills_root = root / ".workbuddy" / "skills"
            with mock.patch.object(installer, "_activation_mode", return_value="copy"):
                mode = installer._activate(skills_root, package, host="workbuddy")
            public = skills_root / "content-gzh-slim"
            probe = subprocess.run(
                [sys.executable, "-B", str(public / "scripts" / "content-gzh-slim"), "probe"],
                cwd=public,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
            )
            installed = {path.name for path in skills_root.iterdir() if path.is_dir()}

        self.assertEqual(mode, "copy")
        self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
        self.assertEqual(json.loads(probe.stdout)["status"], "ready")
        self.assertEqual(installed, {
            "content-gzh-slim", "content-gzh-analyzer", "content-gzh-context-retriever",
            "content-gzh-writer", "content-gzh-headline", "content-gzh-distribution-pack",
        })

    def test_copy_activation_stages_each_skill_directly_under_skills_root(self) -> None:
        installer = _load("install.py", "content_gzh_installer_short_staging")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skills_root = root / "skills"
            wanted_root = root / "package" / ".agents" / "skills"
            for name in installer.SKILLS:
                (wanted_root / name).mkdir(parents=True, exist_ok=True)
            staged: list[Path] = []

            def fake_copy(_source: Path, destination: Path) -> None:
                staged.append(destination)
                destination.mkdir()

            with mock.patch.object(installer, "_activation_mode", return_value="copy"), mock.patch.object(
                installer, "_copy", side_effect=fake_copy
            ):
                installer._activate(skills_root, root / "package")

        self.assertEqual(len(staged), len(installer.SKILLS))
        self.assertTrue(all(path.parent == skills_root for path in staged))

    def test_package_candidate_uses_one_short_leaf_under_packages(self) -> None:
        installer = _load("install.py", "content_gzh_installer_short_package_staging")
        packages = Path("/customer/.workbuddy/skills/.packages")
        candidate = installer._package_staging_path(packages)

        self.assertEqual(candidate.parent, packages)
        self.assertLessEqual(len(candidate.name), 12)

    def test_release_manifest_covers_host_adapters_and_builder(self) -> None:
        manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
        paths = {item["path"] for item in manifest["runtime"]["files"]}
        self.assertIn("workbuddy/SKILL.md", paths)
        self.assertIn("workbuddy/workbuddy.json", paths)
        self.assertIn("install.py", paths)
        self.assertIn("tools/build_universal_package.py", paths)

    def test_universal_builder_rejects_embedded_credentials(self) -> None:
        builder = _load("tools/build_universal_package.py", "content_gzh_universal_builder")
        payload = b'{"access_' + b'token": "real-secret-value"}'
        failures = builder._privacy_failures({"bad.json": payload})
        self.assertEqual(len(failures), 1)

    def test_extracted_package_revision_fallback_does_not_invoke_git(self) -> None:
        revision = "a" * 40
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            extracted = Path(temporary)
            (extracted / "UNIVERSAL-PACKAGE-MANIFEST.json").write_text(
                json.dumps({"source_revision": revision}), encoding="utf-8"
            )
            builder = _load("tools/build_universal_package.py", "content_gzh_builder_no_git")
            installer = _load("install.py", "content_gzh_installer_no_git")
            with mock.patch.object(builder, "ROOT", extracted), mock.patch.object(
                builder, "_git", side_effect=AssertionError("git must not run")
            ):
                self.assertEqual(builder._source_revision(), revision)
            with mock.patch.object(installer, "ROOT", extracted), mock.patch.object(
                installer.subprocess, "run", side_effect=AssertionError("git must not run")
            ):
                self.assertEqual(installer._source_revision(), revision)

    def test_ci_runs_universal_package_on_windows_and_macos(self) -> None:
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "universal-package.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("* text=auto eol=lf", attributes)
        self.assertIn("windows-latest", workflow)
        self.assertIn("macos-latest", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("branches: [main]", workflow)
        self.assertIn("test_universal_package", workflow)
        self.assertIn("build_universal_package.py", workflow)


if __name__ == "__main__":
    unittest.main()
