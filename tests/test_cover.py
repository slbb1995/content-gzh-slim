"""Isolated fixtures verify behavior; generated PNG bytes are not real imagegen evidence."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

import test_p6_runtime as p6
from runtime.artifact_store import ArtifactStore
from runtime.cover import CoverService, atomic_write, png_size
from runtime.distribution_service import DistributionService
from runtime.obsidian_adapter import ObsidianAdapter, split_cover
from runtime.save_service import SaveService


def fixture_png(width=940, height=400):
    def chunk(kind, value):
        return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value))
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress((b'\x00' + bytes(width * 3)) * height)) + chunk(b'IEND', b'')


class CoverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_id, self.store = p6.P6RuntimeTests()._saved_run(str(self.root))
        self.artifacts = ArtifactStore(self.root)
        context = self.artifacts.read_json(self.run_id, 'article_context_v1.json')
        self.adapter = ObsidianAdapter(self.root/'isolated-obsidian', {context['save_target_preview']['target_ref']: 'articles'})
        self.service = CoverService(self.root, self.adapter)
        self.receipt = self.artifacts.read_json(self.run_id, 'save_receipt.json')
        self.article = Path(self.receipt['target']['object_ref'])
        self.original = self.article.read_bytes()
        self.image = self.root/'fixture.png'
        self.image.write_bytes(fixture_png())

    def candidate(self, style='consulting', **updates):
        context = self.service.context(self.run_id, style)
        value = {key: context[key] for key in ('approved_final_digest', 'article_digest', 'style', 'layout_version')}
        value.update(cover_title=context['title'], prompt='fixture prompt, not real generation', image_path=str(self.image), generator='fixture-only', visual_checked=True)
        value.update(updates)
        return value

    def test_single_cover_preserves_body_gates_save_and_distribution(self):
        before_run = self.store.load(self.run_id)
        before_approved = self.artifacts.read_json(self.run_id, 'approved_final.json')
        candidate = self.candidate()
        result = self.service.save(self.run_id, candidate)
        self.assertTrue(result['cover']['applied'])
        self.assertEqual(split_cover(self.article.read_text())[0].encode(), self.original)
        self.assertEqual(self.article.read_text().count('<!-- content-gzh:cover -->'), 1)
        self.assertEqual(self.store.load(self.run_id), before_run)
        self.assertEqual(self.artifacts.read_json(self.run_id, 'approved_final.json'), before_approved)
        self.assertEqual(self.artifacts.read_json(self.run_id, 'save_receipt.json'), self.receipt)
        self.assertTrue(SaveService(self.root, {'obsidian': self.adapter}).save(self.run_id)['resumed'])
        self.assertTrue(self.service.save(self.run_id, candidate)['resumed'])
        self.assertEqual(len(self.service.context(self.run_id, 'consulting')['existing']), 1)
        DistributionService(self.root).generate(self.run_id, explicit_request='生成分发包', candidate=p6.read_json('p6_distribution.json'))
        self.assertEqual(self.store.load(self.run_id)['status'], 'distribution_optional')
        self.service.context(self.run_id, 'retro-ink')

    def test_preview_three_independent_single_styles_does_not_write_article(self):
        for style in ('consulting', 'retro-ink', 'raster-tech'):
            self.service.save(self.run_id, self.candidate(style, apply=False))
        folder = self.root/'runs'/self.run_id
        self.assertEqual(len(list(folder.glob('cover-*.png'))), 3)
        self.assertEqual(len(list(folder.glob('cover-*.json'))), 3)
        self.assertEqual(self.article.read_bytes(), self.original)

    def test_changed_article_after_prompt_is_not_overwritten(self):
        candidate = self.candidate()
        self.article.write_bytes(self.original + b'\nmanual change')
        changed = self.article.read_bytes()
        with self.assertRaises((ValueError, RuntimeError)):
            self.service.save(self.run_id, candidate)
        self.assertEqual(self.article.read_bytes(), changed)

    def test_cross_run_binding_and_multiple_styles_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'another approved'):
            self.service.save(self.run_id, self.candidate(approved_final_digest='0'*64))
        with self.assertRaises((ValueError, TypeError)):
            self.service.save(self.run_id, self.candidate(style='consulting,retro-ink'))

    def test_unsaved_run_cannot_generate(self):
        path = self.root/'runs'/self.run_id/'run.json'
        value = json.loads(path.read_text()); value['status'] = 'waiting_final'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'saved article'):
            self.service.context(self.run_id, 'consulting')

    def test_unchecked_damaged_wrong_aspect_and_missing_images_rejected(self):
        with self.assertRaisesRegex(ValueError, 'visual check'):
            self.service.save(self.run_id, self.candidate(visual_checked=False))
        with self.assertRaises((ValueError, OSError)):
            self.service.save(self.run_id, self.candidate(image_path=str(self.root/'missing.png')))
        for data in (b'not an image', b'\x89PNG\r\n\x1a\n', fixture_png(1000,1000), self.image.read_bytes()[:-8]):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                png_size(data)

    def test_asset_path_escape_and_protected_source_root_rejected(self):
        for path in (self.root, self.adapter.boundary.root/'03-business'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'boundaries'):
                self.service.save(self.run_id, self.candidate(asset_directory=str(path)))
        self.assertEqual(self.article.read_bytes(), self.original)

    def test_declared_vault_attachment_directory_is_used(self):
        assets = self.adapter.boundary.root/'A.系统'/'附件'
        assets.mkdir(parents=True)
        value = self.service.save(self.run_id, self.candidate())['cover']
        self.assertTrue(Path(value['image_path']).is_relative_to(assets))

    def test_unembeddable_attachment_paths_stop_before_any_write(self):
        for name in ('attachments [shared]', 'assets|alias', 'assets<draft>'):
            target = self.adapter.boundary.root/name
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'managed cover path'):
                self.service.save(self.run_id, self.candidate(asset_directory=str(target)))
            self.assertEqual(self.article.read_bytes(), self.original)
            self.assertFalse(target.exists())
            self.assertEqual(list((self.root/'runs'/self.run_id).glob('cover-*.json')), [])
            self.service.context(self.run_id, 'consulting')

    def test_context_recovers_image_when_final_record_write_fails(self):
        candidate = self.candidate()
        def fail_final_record(path, data):
            if path.name.startswith('cover-') and path.suffix == '.json' and json.loads(data).get('applied'):
                raise OSError('interrupted final record')
            atomic_write(path, data)
        with patch('runtime.cover.atomic_write', side_effect=fail_final_record):
            with self.assertRaisesRegex(OSError, 'interrupted final'):
                self.service.save(self.run_id, candidate)
        context = self.service.context(self.run_id, 'consulting')
        self.assertEqual(len(context['existing']), 1)
        cached = context['existing'][0]
        self.assertTrue(cached['currently_applied'])
        self.assertFalse(cached['applied'])
        result = self.service.save(self.run_id, self.candidate(image_path=cached['image_path']))
        self.assertTrue(result['resumed'])
        self.assertTrue(result['cover']['applied'])
        self.assertEqual(self.article.read_text().count('<!-- content-gzh:cover -->'), 1)
        self.assertEqual(split_cover(self.article.read_text())[0].encode(), self.original)

    def test_context_recovers_image_when_article_write_fails(self):
        candidate = self.candidate()
        def fail_article(path, data):
            if path == self.article:
                raise OSError('interrupted article')
            atomic_write(path, data)
        with patch('runtime.cover.atomic_write', side_effect=fail_article):
            with self.assertRaisesRegex(OSError, 'interrupted article'):
                self.service.save(self.run_id, candidate)
        self.assertEqual(self.article.read_bytes(), self.original)
        context = self.service.context(self.run_id, 'consulting')
        self.assertEqual(len(context['existing']), 1)
        cached = context['existing'][0]
        self.assertFalse(cached['currently_applied'])
        result = self.service.save(self.run_id, self.candidate(image_path=cached['image_path']))
        self.assertTrue(result['cover']['applied'])
        self.assertEqual(len(list((self.root/'runs'/self.run_id).glob('cover-*.json'))), 1)
        self.assertEqual(self.article.read_text().count('<!-- content-gzh:cover -->'), 1)

    def test_interrupted_final_record_can_resume_without_duplicate_insert(self):
        candidate = self.candidate()
        self.service.save(self.run_id, candidate)
        record_path = next((self.root/'runs'/self.run_id).glob('cover-*.json'))
        record = json.loads(record_path.read_text()); record['applied'] = False
        record_path.write_text(json.dumps(record))
        result = self.service.save(self.run_id, candidate)
        self.assertTrue(result['resumed'])
        self.assertTrue(result['cover']['applied'])
        self.assertEqual(self.article.read_text().count('<!-- content-gzh:cover -->'), 1)

    def test_old_layout_not_reused_and_square_crop_is_recorded(self):
        candidate = self.candidate()
        result = self.service.save(self.run_id, candidate)['cover']
        self.assertEqual(result['square_crop'], [0, 0, 400, 400])
        path = next((self.root/'runs'/self.run_id).glob('cover-*.json'))
        for old_layout in (None, 'square-title-left-v1'):
            record = json.loads(path.read_text())
            candidate['layout_version'] = old_layout
            record['layout_version'] = old_layout
            if old_layout is None:
                record.pop('layout_version')
                candidate.pop('layout_version')
            path.write_text(json.dumps(record))
            with self.subTest(old_layout=old_layout):
                self.assertEqual(self.service.context(self.run_id, 'consulting')['existing'], [])
                with self.assertRaisesRegex(ValueError, 'square-title'):
                    self.service.save(self.run_id, candidate)

    def test_reusing_prior_style_applies_existing_image_without_new_version(self):
        first = self.service.save(self.run_id, self.candidate())['cover']
        self.service.save(self.run_id, self.candidate('retro-ink'))
        cached = self.service.context(self.run_id, 'consulting')['existing'][0]
        self.assertFalse(cached['currently_applied'])
        result = self.service.save(self.run_id, self.candidate(image_path=first['image_path']))
        self.assertTrue(result['cover']['applied'])
        self.assertTrue(self.service.context(self.run_id, 'consulting')['existing'][0]['currently_applied'])
        self.assertEqual(len(list((self.root/'runs'/self.run_id).glob('cover-*.json'))), 2)

    def test_saved_cover_adapter_does_not_retrieve_source_library(self):
        from runtime.host_cli import _derived_adapter
        from runtime.cover import digest
        snapshot = {"backend": "obsidian", "save_target_ref": self.receipt["target"]["target_ref"],
                    "output_template": "articles", "output_locator": ".",
                    "knowledge_base_locator": str(self.adapter.boundary.root)}
        directory = self.root/'runs'/self.run_id
        (directory/'source_snapshot.json').write_text(json.dumps(snapshot))
        run = self.store.load(self.run_id)
        raw = (json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode()
        run['knowledge_base_identity']['source_snapshot_sha256'] = 'sha256:'+digest(raw)
        (directory/'run.json').write_text(json.dumps(run))
        with patch('runtime.host_cli.verify_source_snapshot', side_effect=AssertionError('unexpected retrieval')):
            adapters = _derived_adapter(self.root, self.run_id, identity='user', verify_sources=False)
        self.assertEqual(adapters['obsidian'].boundary.root, self.adapter.boundary.root)

    def test_managed_block_cannot_hide_body_changes_or_corrupted_image(self):
        result = self.service.save(self.run_id, self.candidate())
        text = self.article.read_text()
        self.article.write_text(text + '\nsecret edit')
        with self.assertRaises((ValueError, RuntimeError)):
            self.service.context(self.run_id, 'consulting')
        self.article.write_text(text)
        Path(result['cover']['image_path']).write_bytes(b'changed')
        with self.assertRaises((ValueError, RuntimeError)):
            self.service.context(self.run_id, 'consulting')


if __name__ == '__main__':
    unittest.main()
