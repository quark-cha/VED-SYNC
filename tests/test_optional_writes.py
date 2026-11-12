"""Optional remote writes never block other fictitious repository targets."""
import errno
import unittest
from unittest.mock import patch

from tests import test_engine


class OptionalWritesTests(unittest.TestCase):
    def setUp(self):
        self.f = test_engine.SyncTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.cfg['repositories'][1]['write_policy'] = 'if_possible'
        self.f.configure()
        self.f.put(0, 'actualización')

    def test_permission_or_read_only_remote_does_not_block_local_copy(self):
        for code in (errno.EACCES, errno.EPERM, errno.EROFS):
            with self.subTest(code=code):
                engine = self.f.engine()
                copy = engine.copy
                def denied(source, target, *args):
                    if target.parent == self.f.repos[1]:
                        raise OSError(code, 'Destino no escribible ficticio')
                    return copy(source, target, *args)
                with patch.object(engine, 'copy', side_effect=denied):
                    report = engine.run_once()
                self.assertEqual((self.f.repos[2] / 'f').read_text(), 'actualización')
                self.assertFalse((self.f.repos[1] / 'f').exists())
                self.assertTrue(any(e['type'] == 'write_unavailable' for e in report['events']))
                self.assertFalse(any(e['type'] == 'error' for e in report['events']))
                self.assertNotEqual(report['status']['b'], 'verde')

    def test_remote_receives_changes_when_writable(self):
        report = self.f.engine().run_once()
        self.assertEqual(self.f.contents(), ['actualización'] * 3)
        self.assertEqual(set(report['status'].values()), {'verde'})

    def test_integrity_failure_remains_error(self):
        engine = self.f.engine()
        copy = engine.copy
        def corrupt(source, target, *args):
            if target.parent == self.f.repos[1]:
                raise OSError('SHA-256 incorrecto ficticio')
            return copy(source, target, *args)
        with patch.object(engine, 'copy', side_effect=corrupt):
            report = engine.run_once()
        self.assertTrue(any(e['type'] == 'error' for e in report['events']))
        self.assertFalse(any(e['type'] == 'write_unavailable' for e in report['events']))

    def test_unknown_policy_rejected(self):
        self.f.cfg['repositories'][1]['write_policy'] = 'ignorar_todo'
        self.f.configure()
        with self.assertRaises(ValueError):
            self.f.engine()
