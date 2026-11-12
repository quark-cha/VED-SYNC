"""Interrupted cycles retain verified cache and completed file history."""
import json
import time
import unittest
from unittest.mock import patch

from tests import test_engine


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.f = test_engine.SyncTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.put(0, 'uno')
        (self.f.repos[0] / 'g').write_text('dos')

    def test_interrupted_scan_saves_only_completed_hashes(self):
        engine = self.f.engine()
        original = engine.inspect_file
        def interrupt(path, *args, **kwargs):
            if path.name == 'g':
                raise KeyboardInterrupt
            return original(path, *args, **kwargs)
        def ordered_scan(root):
            return {p.name: engine.cached_inspect(p) for p in sorted(root.iterdir()) if p.name in ('f', 'g')}
        with patch.object(engine, 'inspect_file', side_effect=interrupt), \
             patch.object(engine, 'scan', side_effect=ordered_scan):
            with self.assertRaises(KeyboardInterrupt):
                engine.run_once()
        state = json.loads(engine.state_file.read_text())
        self.assertIn(str(self.f.repos[0] / 'f'), state['hash_cache'])
        self.assertNotIn(str(self.f.repos[0] / 'g'), state['hash_cache'])
        resumed = self.f.engine()
        with patch.object(resumed, 'inspect_file', side_effect=AssertionError('Hash repetido')):
            resumed.cached_inspect(self.f.repos[0] / 'f')
        self.assertFalse((engine.state_dir / 'run.lock').exists())

    def test_completed_files_are_not_copied_again_after_interruption(self):
        engine = self.f.engine()
        copy = engine.copy
        def interrupt(source, target, *args):
            if target.name == 'g':
                raise KeyboardInterrupt
            return copy(source, target, *args)
        with patch.object(engine, 'copy', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.run_once()
        state = json.loads(engine.state_file.read_text())
        self.assertIn('f', state['files'])
        self.assertNotIn('g', state['files'])
        resumed = self.f.engine()
        with patch.object(resumed, 'copy', wraps=resumed.copy) as copies:
            report = resumed.run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertTrue(all(call.args[1].name == 'g' for call in copies.call_args_list))

    def test_periodic_scan_checkpoint_occurs_before_final_save(self):
        engine = self.f.engine()
        def action():
            engine._checkpoint_last = time.monotonic() - 31
            engine.cached_inspect(self.f.repos[0] / 'f')
            self.assertTrue(engine.state_file.exists())
            self.assertIn(str(self.f.repos[0] / 'f'), json.loads(engine.state_file.read_text())['hash_cache'])
            return {'status': {'a': 'gris'}, 'events': []}
        engine._project_bytes = 0
        engine._run(action)

    def test_simulated_interruption_does_not_save_cache(self):
        engine = self.f.engine(apply=False)
        with patch.object(engine, 'scan', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.run_once()
        self.assertFalse(engine.state_file.exists())

    def test_checkpoint_failure_does_not_hide_interrupt_or_leave_lock(self):
        engine = self.f.engine()
        with patch.object(engine, 'scan', side_effect=KeyboardInterrupt), \
             patch.object(engine, 'save', side_effect=OSError('Sin espacio ficticio')):
            with self.assertRaises(KeyboardInterrupt):
                engine.run_once()
        self.assertFalse((engine.state_dir / 'run.lock').exists())
        log = (engine.state_dir / 'operaciones.jsonl').read_text()
        self.assertIn('checkpoint_failed', log)
