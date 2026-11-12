"""Real copies exclusively between fictitious trees inside VED-SYNC."""
import json
import unittest
from unittest.mock import patch

from tests import test_engine
from ved_sync.engine import inspect


class ReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.f = test_engine.SyncTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        cfg = json.loads(self.f.config.read_text())
        cfg['repositories'][0]['read_only'] = True
        self.f.config.write_text(json.dumps(cfg))

    def test_import_verifies_original_and_never_creates_source_id(self):
        self.f.put(0, 'Windows ficticio')
        digest = inspect(self.f.repos[0] / 'f').digest
        engine = self.f.engine()
        report = engine.run_once()
        self.assertEqual(self.f.contents(), ['Windows ficticio'] * 3)
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertFalse((self.f.repos[0] / '.ved-sync-id').exists())
        self.assertEqual(inspect(self.f.root / 'state/versions' / (digest + '.original')).digest, digest)
        events = [json.loads(line) for line in (self.f.root / 'state/operaciones.jsonl').read_text().splitlines()]
        self.assertLess(next(i for i,e in enumerate(events) if e['type']=='recovery_verified'),
                        next(i for i,e in enumerate(events) if e['type']=='transaction_started'))

    def test_destination_file_never_propagates_to_source(self):
        self.f.put(1, 'solo Ubuntu')
        report = self.f.engine().run_once()
        self.assertFalse((self.f.repos[0] / 'f').exists())
        self.assertEqual(report['status']['a'], 'rojo')

    def test_explicit_recovery_to_source_rejected(self):
        with self.assertRaises(ValueError):
            self.f.engine().recover('a', 'f', '0' * 64)

    def test_corrupt_original_prevents_import(self):
        self.f.put(0, 'Windows ficticio')
        digest = inspect(self.f.repos[0] / 'f').digest
        folder = self.f.root / 'state/versions'
        folder.mkdir(parents=True)
        (folder / (digest + '.original')).write_text('corrupto')
        report = self.f.engine().run_once()
        self.assertFalse((self.f.repos[1] / 'f').exists())
        self.assertEqual(report['status']['b'], 'rojo')

    def test_source_read_only_skips_write_guard_but_destination_does_not(self):
        from ved_sync.engine import Engine
        with patch.object(Engine, 'check_write') as guard:
            self.f.engine()
        self.assertNotIn(self.f.repos[0], [call.args[0] for call in guard.call_args_list])
        self.assertIn(self.f.repos[1], [call.args[0] for call in guard.call_args_list])
