from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from runtime.artifact_store import ArtifactStore
from runtime.content_source import (
    ContentSourceError, apply_configuration, plan_configuration,
    resolve_real_source, verify_source_snapshot,
)
from runtime.host_cli import _derived_adapter, _verify_real_run
from runtime.run_store import RunStore
from tests import test_content_source_runtime as source_tests

canonical = source_tests.canonical


class DirectoryProfileTests(unittest.TestCase):
    def make_vault(self, root):
        vault, index_path, _, _ = source_tests.ContentSourceRuntimeTests().make_vault(root, two_profiles=False)
        profile_root = vault / "author" / "alpha"
        profile_root.mkdir(parents=True)
        for role, body in {
            "persona": "This author advises teams. This is a paragraph, not a bullet list.",
            "style": "Preserve how a judgment develops. Do not impose a fixed ending.",
            "business": "Confirmed scope: consulting. The new offer and price remain unconfirmed.",
        }.items():
            (profile_root / f"{role}.md").write_text(f"---\nprofile: alpha\nstatus: confirmed\n---\n\n{body}\n")
        index = json.loads(index_path.read_text())
        profile = index["profiles"][0]
        profile.pop("content_sha256")
        profile.update({"object_ref": "author/alpha", "source_kind": "profile_directory_v1",
                        "aliases": ["alpha"], "profile_files": {role: f"{role}.md" for role in ("persona", "style", "business")}})
        index_path.write_text(canonical(index))
        return vault, index_path, profile_root

    def test_prose_is_preserved_and_new_run_reads_edits_without_index_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            vault, index, profile = self.make_vault(Path(directory))
            before = index.read_bytes()
            request = {"knowledge_base": str(vault), "ip": "alpha", "topic": "A bounded task"}
            _, _, identity, catalog, frozen = resolve_real_source(request)
            docs = catalog["knowledge_bases"][0]["profiles"][0]["profile_documents"]
            self.assertEqual(identity["status"], "full")
            self.assertIn("not a bullet list", next(x["text"] for x in docs if x["role"] == "persona"))
            self.assertIn("unconfirmed", next(x["text"] for x in docs if x["role"] == "business"))
            path = profile / "style.md"
            path.write_text(path.read_text() + "\nA newly approved paragraph.\n")
            with self.assertRaisesRegex(ContentSourceError, "frozen source changed"):
                verify_source_snapshot(frozen)
            _, _, new_identity, updated, _ = resolve_real_source(request)
            self.assertNotEqual(identity["resolved_ref"], new_identity["resolved_ref"])
            self.assertIn("newly approved", json.dumps(updated))
            self.assertEqual(index.read_bytes(), before)

    def test_cross_ip_and_unapproved_document_are_rejected(self):
        for replacement in ("profile: beta", "status: draft"):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                vault, _, profile = self.make_vault(Path(directory))
                path = profile / "style.md"
                old = "profile: alpha" if replacement.startswith("profile") else "status: confirmed"
                path.write_text(path.read_text().replace(old, replacement))
                with self.assertRaises(ContentSourceError):
                    resolve_real_source({"knowledge_base": str(vault), "ip": "alpha", "topic": "task"})

    def test_member_path_cannot_escape_its_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            vault, index, _ = self.make_vault(Path(directory))
            data = json.loads(index.read_text())
            data["profiles"][0]["profile_files"]["style"] = "../another.md"
            index.write_text(canonical(data))
            with self.assertRaisesRegex(ContentSourceError, "escapes"):
                resolve_real_source({"knowledge_base": str(vault), "ip": "alpha", "topic": "task"})

    def test_configuration_reroutes_existing_vault_without_copying_prose(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault, index, profile = self.make_vault(root)
            old = vault / "06-Agent与Workflow" / "content-source-manifest.json"
            manifest = json.loads(old.read_text())
            manifest["workflow_outputs"]["content-gzh-slim"] = "articles/{year}-{month}-week-{week}"
            metadata = vault / "system" / "content"
            metadata.mkdir(parents=True)
            new = metadata / "manifest.json"
            new.write_text(canonical(manifest))
            registry = root / "registry.json"
            relative = new.relative_to(vault).as_posix()
            plan = plan_configuration(vault, registry_path=registry, manifest_ref=relative, timezone="Asia/Shanghai", default_profile="alpha")
            apply_configuration(vault, registry_path=registry, manifest_ref=relative, timezone="Asia/Shanghai", default_profile="alpha", confirmation=plan["confirmation"])
            task, kb, ip, catalog, snapshot = resolve_real_source({"topic": "task"}, registry_path=registry)
            self.assertEqual(snapshot["output_timezone"], "Asia/Shanghai")
            store = root / "store"
            run = RunStore(store).create_or_resume(task, kb, ip).run
            artifacts = ArtifactStore(store)
            artifacts.write_json_once_or_verify(run["run_id"], "source_catalog.json", catalog)
            artifacts.write_json_once_or_verify(run["run_id"], "source_snapshot.json", snapshot)
            adapter = _derived_adapter(store, run["run_id"], identity="user")["obsidian"]
            self.assertNotIn("{", str(adapter._directory(snapshot["save_target_ref"])))
            self.assertEqual(len(list(profile.glob("*.md"))), 3)

    def test_same_vault_bindings_select_exact_ip_and_keep_outputs_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault, index_path, _ = self.make_vault(root)
            manifest_path = vault / "06-Agent与Workflow" / "content-source-manifest.json"
            manifest = json.loads(manifest_path.read_text())
            registry = root / "registry.json"
            plan = plan_configuration(vault, registry_path=registry, default_profile="alpha")
            apply_configuration(vault, registry_path=registry, default_profile="alpha", confirmation=plan["confirmation"])
            beta = vault / "author" / "beta"
            beta.mkdir()
            for role in ("persona", "style"):
                (beta / f"{role}.md").write_text(f"---\nprofile: beta\nstatus: confirmed\n---\nBeta {role}, no Alpha facts.\n")
            index = json.loads(index_path.read_text())
            index["knowledge_base_id"] = "KB-2222222222222222"
            profile = index["profiles"][0]
            profile.update({"profile_id": "PRF-2222222222222222", "display_name": "Beta", "aliases": ["beta"], "object_ref": "author/beta", "profile_files": {r: f"{r}.md" for r in ("persona", "style")}})
            beta_index = index_path.parent / "beta-index.json"
            beta_index.write_text(canonical(index))
            manifest.update({"client_id": "client-beta", "knowledge_base_id": index["knowledge_base_id"], "profile_index_ref": beta_index.relative_to(vault).as_posix()})
            manifest["asset_roots"]["output"] = "beta-output"
            beta_manifest = index_path.parent / "beta-manifest.json"
            beta_manifest.write_text(canonical(manifest))
            relative = beta_manifest.relative_to(vault).as_posix()
            plan = plan_configuration(vault, registry_path=registry, default_profile="beta", manifest_ref=relative)
            apply_configuration(vault, registry_path=registry, default_profile="beta", manifest_ref=relative, confirmation=plan["confirmation"])
            for requested in ({"knowledge_base": str(vault), "ip": "beta", "topic": "task"}, {"ip": "beta", "topic": "task"}):
                _, kb, ip, catalog, snapshot = resolve_real_source(requested, registry_path=registry)
                self.assertEqual(kb["knowledge_base_id"], index["knowledge_base_id"])
                self.assertEqual(ip["requested_name"], "Beta")
                self.assertEqual(snapshot["output_locator"], "beta-output")
                self.assertNotIn("author/alpha", json.dumps(catalog))
            with self.assertRaisesRegex(ContentSourceError, "one content-gzh-slim binding"):
                resolve_real_source({"knowledge_base": str(vault), "ip": "unknown", "topic": "task"}, registry_path=registry)
            for requested_ip, expected_status in ((None, "full"), ("none", "none")):
                _, kb, ip, _, _ = resolve_real_source({"knowledge_base": str(vault), "ip": requested_ip, "topic": "task"}, registry_path=registry)
                self.assertEqual(kb["knowledge_base_id"], "KB-1234567890ABCDEF")
                self.assertEqual(ip["status"], expected_status)

    def test_modified_catalog_cannot_replace_frozen_profile_prose(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault, _, _ = self.make_vault(root)
            task, kb, ip, catalog, snapshot = resolve_real_source({"knowledge_base": str(vault), "topic": "task"})
            store = root / "store"
            run = RunStore(store).create_or_resume(task, kb, ip).run
            artifacts = ArtifactStore(store)
            artifacts.write_json_once_or_verify(run["run_id"], "source_snapshot.json", snapshot)
            catalog["knowledge_bases"][0]["profiles"][0]["profile_documents"][0]["text"] = "Unapproved replacement"
            artifacts.write_json_once_or_verify(run["run_id"], "source_catalog.json", catalog)
            with self.assertRaisesRegex(ContentSourceError, "catalog does not match"):
                _verify_real_run(store, run["run_id"], identity="user")


if __name__ == "__main__":
    unittest.main()
