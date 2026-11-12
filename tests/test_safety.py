import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_engine
from ved_sync.engine import PROJECT
from tools.check_tests import check

class SafetyTests(unittest.TestCase):
    def test_audit_guard_rejects_external_writes_before_io(self):
        for path in (PROJECT.parent / 'OTHER/file', Path('/mnt/windows/file')):
            with self.assertRaises(PermissionError):
                check(path)
        check(PROJECT / '.test-runs/fictitious')

    def test_unreadable_repository_is_grey(self):
        f = test_engine.SyncTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        e = f.engine()
        scan = e.scan
        def inaccessible(root):
            if root == f.repos[0]:
                raise PermissionError('fictitious unreadable repository')
            return scan(root)
        with patch.object(e, 'scan', side_effect=inaccessible):
            result = e.run_once()
        self.assertEqual(result['status']['a'], 'gris')
        self.assertNotIn('verde', result['status'].values())

    def test_final_verification_failure_prevents_green(self):
        f = test_engine.SyncTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        e = f.engine()
        scan = e.scan
        calls = 0
        def late_failure(root):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise PermissionError('lost access during final verification')
            return scan(root)
        with patch.object(e, 'scan', side_effect=late_failure):
            result = e.run_once()
        self.assertEqual(result['status']['a'], 'gris')
        self.assertNotIn('verde', result['status'].values())

    def test_discovery_never_uses_control_directory_as_repository(self):
        from ved_sync.identity import IDENTITY_FILE, read_identity
        f = test_engine.SyncTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.seed()
        identity = read_identity(f.repos[0])
        nested = f.root / 'nested'
        nested.mkdir()
        f.repos[0].rename(nested / 'unavailable')
        (f.root / 'state' / IDENTITY_FILE).write_text(identity)
        f.cfg['repositories'][0]['search_roots'] = ['.']
        f.configure()
        report = f.engine().run_once()
        self.assertEqual(report['status']['a'], 'rojo')
        self.assertTrue(any(e.get('code') == 'ControlDirectoryOverlap' for e in report['events']))
        self.assertFalse((f.repos[1] / 'operaciones.jsonl').exists())
        self.assertFalse((f.repos[1] / 'state.json').exists())

    def test_log_and_timing_symlinks_rejected_without_writing_target(self):
        f = test_engine.SyncTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        directory = f.root / 'state'
        directory.mkdir()
        sentinel = f.root / 'sentinel'
        sentinel.write_text('unchanged')
        for filename in ('tiempo.csv', 'operaciones.jsonl'):
            with self.subTest(filename=filename):
                link = directory / filename
                link.symlink_to(sentinel)
                try:
                    with self.assertRaises(ValueError):
                        f.engine().run_once()
                    self.assertEqual(sentinel.read_text(), 'unchanged')
                    self.assertFalse((directory / 'run.lock').exists())
                finally:
                    link.unlink()
