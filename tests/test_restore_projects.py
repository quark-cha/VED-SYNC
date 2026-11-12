"""Authoritative recovery in an isolated SRC-VED tree, never real projects."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ved_sync.engine import Engine, PROJECT, inspect


class RestoreProjectsTests(unittest.TestCase):
    def setUp(self):
        parent = PROJECT / '.test-runs'
        parent.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.ubuntu = self.base / 'SRC-VED'
        self.project = self.ubuntu / 'VED-SYNC'
        self.project.mkdir(parents=True)
        self.windows = self.base / 'windows'
        self.windows.mkdir()
        (self.project / 'motor.py').write_text('motor Ubuntu actual')
        self.config = self.project / '.ved-sync-config.json'
        self.config.write_text(json.dumps({'state_dir': str(self.project / '.ved-sync/control'),
            'persistent_ids': False, 'authoritative_source': 'windows', 'repositories': [
                {'id': 'windows', 'label': 'Windows', 'path': str(self.windows), 'read_only': True},
                {'id': 'ubuntu', 'label': 'Ubuntu', 'path': str(self.ubuntu)}]}))
        self.patch = patch('ved_sync.engine.PROJECT', self.project)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def engine(self, apply=True, restore=True):
        return Engine(self.config, apply=apply, restore_projects=restore)

    def put(self, root, name, content):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_windows_wins_even_when_ubuntu_was_changed_and_engine_is_preserved(self):
        self.put(self.windows, 'CLASES/a.txt', 'correcto Windows')
        target = self.put(self.ubuntu, 'CLASES/a.txt', 'distinto Ubuntu')
        old = inspect(target).digest
        self.put(self.windows, 'VED-SYNC/motor.py', 'no importar')
        report = self.engine().run_once()
        self.assertEqual(target.read_text(), 'correcto Windows')
        self.assertEqual((self.project / 'motor.py').read_text(), 'motor Ubuntu actual')
        backup = self.project / '.ved-sync/control/versions' / (old + '.original')
        self.assertEqual(backup.read_text(), 'distinto Ubuntu')
        self.assertEqual(set(report['status'].values()), {'verde'})
        target.write_text('edición posterior Ubuntu')
        self.engine().run_once()
        self.assertEqual(target.read_text(), 'correcto Windows')
        self.assertFalse((self.windows / '.ved-sync-id').exists())

    def test_ubuntu_only_files_are_preserved_without_error_in_apply_and_simulation(self):
        path = self.put(self.ubuntu, 'LOCAL/solo.txt', 'conservar')
        for apply in (False, True):
            with self.subTest(apply=apply):
                engine = self.engine(apply=apply)
                report = engine.run_once()
                self.assertEqual(set(report['status'].values()), {'verde'})
                self.assertTrue(any(e['type'] == 'preserved' for e in report['events']))
                self.assertFalse(any(e['type'] in ('pending', 'error') for e in report['events']))
                self.assertEqual(engine.monitor.files_total, 0)
        self.assertEqual(path.read_text(), 'conservar')
        self.assertFalse((self.windows / 'LOCAL').exists())

    def test_source_copies_are_verified_while_destination_extras_are_preserved(self):
        self.put(self.windows, 'comun.txt', 'Windows')
        extra = self.put(self.ubuntu, 'LOCAL/solo.txt', 'conservar')
        for apply in (True, False, True):
            engine = self.engine(apply=apply)
            report = engine.run_once()
            self.assertEqual(set(report['status'].values()), {'verde'})
            self.assertEqual(engine.monitor.files_total, 1)
            self.assertEqual(engine.monitor.finished_files, {'comun.txt'})
            self.assertEqual((self.ubuntu / 'comun.txt').read_text(), 'Windows')
            self.assertEqual(extra.read_text(), 'conservar')
            self.assertFalse((self.windows / 'LOCAL').exists())

    def test_disappeared_source_does_not_request_a_forbidden_reverse_copy(self):
        source = self.put(self.windows, 'comun.txt', 'conservar')
        self.engine().run_once()
        source.unlink()
        report = self.engine().run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertEqual((self.ubuntu / 'comun.txt').read_text(), 'conservar')
        self.assertFalse(source.exists())
        self.assertFalse(any(e['type'] in ('pending', 'error') for e in report['events']))

    def test_permissions_are_announced_before_the_first_hash(self):
        self.put(self.windows, 'comun.txt', 'Windows')
        engine = self.engine()
        events = []
        engine.monitor.console = events.append
        inspect_file = engine.inspect_file
        def check(path, *args, **kwargs):
            policy = next(e['transfers'] for e in events if e['type'] == 'transfer_policy')
            directions = {(t['source'], t['target']): t['allowed'] for t in policy}
            self.assertEqual(directions, {('windows', 'ubuntu'): True, ('ubuntu', 'windows'): False})
            self.assertTrue(any(e['type'] == 'transfer_direction' for e in events))
            return inspect_file(path, *args, **kwargs)
        with patch.object(engine, 'inspect_file', side_effect=check):
            report = engine.run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertFalse((self.windows / '.ved-sync-id').exists())

    def test_read_only_destination_blocks_recovery_before_content_reads(self):
        self.put(self.windows, 'comun.txt', 'Windows')
        cfg = json.loads(self.config.read_text())
        cfg['repositories'][1]['read_only'] = True
        self.config.write_text(json.dumps(cfg))
        engine = self.engine()
        with patch.object(engine, 'inspect_file', side_effect=AssertionError('Dirección bloqueada')):
            report = engine.run_once()
        self.assertFalse((self.ubuntu / 'comun.txt').exists())
        self.assertIn('rojo', report['status'].values())
        self.assertTrue(any(e.get('code') == 'TransferNotAllowed' for e in report['events']))

    def test_destination_without_write_permission_blocks_recovery_before_content_reads(self):
        self.put(self.windows, 'comun.txt', 'Windows')
        engine = self.engine()
        with patch('ved_sync.engine.os.access', return_value=False), \
             patch.object(engine, 'inspect_file', side_effect=AssertionError('Destino no escribible')):
            report = engine.run_once()
        self.assertFalse((self.ubuntu / 'comun.txt').exists())
        self.assertEqual(engine.transfer_permissions[('windows', 'ubuntu')]['reason'],
                         'sin permiso de escritura')
        self.assertIn('rojo', report['status'].values())

    def test_final_verification_failure_remains_an_error(self):
        self.put(self.windows, 'comun.txt', 'Windows')
        extra = self.put(self.ubuntu, 'LOCAL/solo.txt', 'conservar')
        engine = self.engine()
        inspect_file = engine.inspect_file
        def check(path, *args, **kwargs):
            if engine.monitor.project_progress['phase'] == 'verification':
                raise OSError('Error de lectura ficticio')
            return inspect_file(path, *args, **kwargs)
        with patch.object(engine, 'inspect_file', side_effect=check):
            report = engine.run_once()
        self.assertIn('rojo', report['status'].values())
        self.assertTrue(any(e['type'] == 'error' for e in report['events']))
        self.assertEqual(extra.read_text(), 'conservar')

    def test_missing_source_performs_no_recovery(self):
        self.put(self.ubuntu, 'CLASES/a.txt', 'conservar')
        self.windows.rmdir()
        report = self.engine().run_once()
        self.assertEqual((self.ubuntu / 'CLASES/a.txt').read_text(), 'conservar')
        self.assertEqual(report['status']['windows'], 'gris')

    def test_explicit_flag_required_for_parent_destination(self):
        with self.assertRaises(ValueError):
            self.engine(restore=False)

    def test_simulation_does_not_change_destination(self):
        self.put(self.windows, 'CLASES/a.txt', 'Windows')
        target = self.put(self.ubuntu, 'CLASES/a.txt', 'Ubuntu')
        self.engine(apply=False).run_once()
        self.assertEqual(target.read_text(), 'Ubuntu')
