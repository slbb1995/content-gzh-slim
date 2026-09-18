"""Isolated regression coverage for installation and system-path compatibility."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv

from runtime.path_boundary import PathBoundary, PathBoundaryError

ROOT = Path(__file__).resolve().parents[1]


class ReviewRegressions(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'macOS system aliases')
    def test_macos_system_aliases_work_but_nested_links_do_not(self):
        for alias in ('/tmp', '/var/folders'):
            self.assertEqual(PathBoundary(alias).root, Path(alias).resolve())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'real').mkdir()
            (root / 'link').symlink_to(root / 'real', target_is_directory=True)
            with self.assertRaises(PathBoundaryError):
                PathBoundary(root / 'link')
            with self.assertRaises(PathBoundaryError):
                PathBoundary(root).child('link', 'output.png')

    def test_manifest_generator_rejects_crlf(self):
        spec = importlib.util.spec_from_file_location('release_builder', ROOT / 'tools/build_release_manifest.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.py'
            path.write_bytes(b'line\r\n')
            with self.assertRaisesRegex(ValueError, 'must use LF'):
                module.sha256(path)
            path.write_bytes(b'line\n')
            self.assertEqual(len(module.sha256(path)), 64)

    def test_clean_python_fails_before_build_writes_and_probe_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = root / 'venv'
            venv.create(environment, with_pip=False)
            python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            target = root / 'package'
            result = subprocess.run([str(python), '-B', str(ROOT / 'install.py'), '--build-output', str(target)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Pillow>=10 is required', result.stderr)
            self.assertFalse(target.exists())
            probe = subprocess.run([str(python), '-B', str(ROOT / 'scripts/content-gzh-slim'), 'probe'], capture_output=True, text=True)
            self.assertNotEqual(probe.returncode, 0)
            self.assertIn('Pillow>=10 is required', probe.stderr)
            self.assertNotIn('"status": "ready"', probe.stdout)
