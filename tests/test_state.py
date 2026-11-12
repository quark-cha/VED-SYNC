"""Large checkpoint loading and malformed input regressions."""
import json
from pathlib import Path
import tempfile
import unittest
from ved_sync.engine import PROJECT
from ved_sync.state import load_state
from ved_sync.state import DiskStore, DiskMap, dump_state
from unittest.mock import patch
from tests import test_engine


class StateTests(unittest.TestCase):
    def setUp(self):
        parent = PROJECT / '.test-runs'
        parent.mkdir(exist_ok=True)
        tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'state.json'

    def test_legacy_sections_unicode_and_chunk_boundaries(self):
        state = {'files': {f'carpeta/á{i}': {'head': 'a' * 64, 'history': [],
                 'seen': {'windows': 'b' * 64}} for i in range(1700)},
                 'hash_cache': {'/ruta': {'stat': [1, 2, 3], 'verified_ns': 123}},
                 'repository_ids': {'windows': 'id'}, 'other': [False, None, 123]}
        self.path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        self.assertEqual(load_state(self.path), state)

    def test_absent_file_and_empty_sections(self):
        self.assertEqual(load_state(self.path), {'files': {}})
        self.path.write_text('{"files": {}, "hash_cache": {}}')
        self.assertEqual(load_state(self.path), {'files': {}, 'hash_cache': {}})

    def test_truncated_or_trailing_input_is_rejected(self):
        for text in ['{"files":{"x":', '{"files":{},}', '{"files":{}}garbage',
                     '{"files":{1: {}}}', '{"hash_cache":{"a":{"x":true']:
            with self.subTest(text=text):
                self.path.write_text(text)
                with self.assertRaises(ValueError):
                    load_state(self.path)

    def test_disk_sections_round_trip_without_changing_checkpoint(self):
        state = {'files': {'á.lean': {'head': 'a' * 64, 'seen': {'uno': 'a' * 64}}},
                 'hash_cache': {'/á.lean': {'stat': [1, 2], 'sha256': 'a' * 64}},
                 'repository_ids': {'uno': 'identidad'}}
        original = json.dumps(state, ensure_ascii=False, indent=2)
        self.path.write_text(original)
        store = DiskStore(self.path.with_suffix('.sqlite'))
        self.addCleanup(store.close)
        loaded = load_state(self.path, store)
        self.assertIsInstance(loaded['files'], DiskMap)
        self.assertEqual(dict(loaded['files'].items()), state['files'])
        loaded['files']['otro'] = {'seen': {}, 'head': None}
        self.assertIn('otro', loaded['files'])
        output = self.path.with_suffix('.out')
        with output.open('w') as stream:
            dump_state(loaded, stream)
        expected = {**state, 'files': {**state['files'], 'otro': {'seen': {}, 'head': None}}}
        self.assertEqual(json.loads(output.read_text()), expected)
        self.assertEqual(self.path.read_text(), original)
        store.close()
        self.assertFalse(store.path.exists())

    def test_disk_mode_restarts_and_reuses_hashes(self):
        fixture = test_engine.SyncTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.seed()
        with patch('ved_sync.engine.DISK_STATE_BYTES', 0):
            engine = fixture.engine()
            with patch('ved_sync.engine.inspect', side_effect=AssertionError('Hash repetido')):
                self.assertEqual(set(engine.run_once()['status'].values()), {'verde'})
                self.assertTrue(engine._state_deferred)
                self.assertIsNone(engine._disk_store)
                saved = json.loads(engine.state_file.read_text())
                self.assertIn('f', saved['files'])
                self.assertTrue(saved['hash_cache'])
                self.assertEqual(set(engine.run_once()['status'].values()), {'verde'})
            engine.close()
        self.assertFalse((engine.state_dir / '.runtime-state.sqlite').exists())

    def test_deferred_state_cannot_overwrite_saved_history(self):
        fixture = test_engine.SyncTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.seed()
        path = fixture.engine().state_file
        original = path.read_bytes()
        with patch('ved_sync.engine.DISK_STATE_BYTES', 0):
            engine = fixture.engine()
            with self.assertRaises(RuntimeError):
                engine.save()
        self.assertEqual(path.read_bytes(), original)

    def test_missing_checkpoint_uses_disk_sections(self):
        store = DiskStore(self.path.with_suffix('.sqlite'))
        self.addCleanup(store.close)
        loaded = load_state(self.path, store)
        self.assertIsInstance(loaded['files'], DiskMap)
        self.assertIsInstance(loaded['hash_cache'], DiskMap)

    def test_disk_mode_saves_interrupted_copy_and_resumes(self):
        fixture = test_engine.SyncTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.seed()
        fixture.put(0, 'modificado')
        with patch('ved_sync.engine.DISK_STATE_BYTES', 0):
            engine = fixture.engine()
            real_copy = engine.copy
            count = 0
            def interrupt(*args):
                nonlocal count
                count += 1
                if count == 2:
                    raise KeyboardInterrupt
                return real_copy(*args)
            with patch.object(engine, 'copy', side_effect=interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    engine.run_once()
            self.assertIsInstance(json.loads(engine.state_file.read_text())['files'], dict)
            self.assertFalse((engine.state_dir / 'run.lock').exists())
            self.assertEqual(set(engine.run_once()['status'].values()), {'verde'})
            self.assertEqual(fixture.contents(), ['modificado'] * 3)
            engine.close()
