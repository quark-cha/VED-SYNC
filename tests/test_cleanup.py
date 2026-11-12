"""Isolated cleanup regressions for Víctor Estrada Díaz's VED-SYNC."""
from contextlib import redirect_stdout, redirect_stderr
import errno
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ved_sync import cleanup
from ved_sync.engine import PROJECT
from ved_sync.worklist import WorkList


@unittest.skipUnless(os.name == 'posix', 'limpieza.sh requiere Ubuntu/Linux')
class CleanupTests(unittest.TestCase):
    def setUp(self):
        parent = PROJECT / '.test-runs'
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'VED-SYNC'
        self.control = self.root / '.ved-sync/control'
        self.control.mkdir(parents=True)
        (self.root / '.ved-sync-config.json').write_text(json.dumps({'state_dir': '.ved-sync/control'}))
        (self.control / 'state.json').write_text('{"files":{}}')
        self.log = self.control / 'VED-Sync.cola.log'
        self.log.write_text('registro prescindible\n')

    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cleanup.main(list(args), project=self.root)
        return code, out.getvalue(), err.getvalue()

    def queue(self, completed):
        queue = WorkList(self.control / 'VED-Sync.cola', 'scope')
        queue.add('visible.txt', ('a' * 64, 4, 1))
        if completed:
            queue.update(queue.get('visible.txt'), 'verified')
        queue.set_meta('complete', completed)
        queue.set_meta('ready', True)
        queue.flush()
        queue.close()
        return {p: p.read_bytes() for p in self.control.iterdir() if cleanup.QUEUE.fullmatch(p.name)}

    def test_default_cleans_generated_files_and_preserves_pending_queue_sources_and_backups(self):
        pending = self.queue(False)
        cache = self.root / 'ved_sync/__pycache__/modulo.cpython-314.pyc'
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b'cache')
        temporary = self.control / ('state-' + 'a' * 32 + '.tmp')
        temporary.write_text('temporal')
        original = self.control / 'versions' / ('a' * 64 + '.original')
        original.parent.mkdir()
        original.write_text('respaldo necesario')
        source = self.root / 'ved_sync/modulo.py'
        source.write_text('fuente original')
        secret = self.root / '.env'
        secret.write_text('conservar')
        sentinel = self.control / 'state-importante.tmp'
        sentinel.write_text('no es un temporal del motor')
        before = {p: p.read_bytes() for p in (original, source, secret, sentinel,
                                             self.control / 'state.json', self.root / '.ved-sync-config.json')}
        code, out, err = self.invoke()
        self.assertEqual(code, 0, err)
        self.assertFalse(self.log.exists())
        self.assertFalse(cache.exists())
        self.assertFalse(temporary.exists())
        self.assertIn('Cola pendiente', out)
        for path, contents in {**before, **pending}.items():
            self.assertEqual(path.read_bytes(), contents)

    def test_completed_queue_is_archived_and_removed_as_a_consistent_set(self):
        previous = self.queue(True)
        code, out, err = self.invoke()
        self.assertEqual(code, 0, err)
        self.assertIn('Respaldo verificado', out)
        backup = next((self.root / '.ved-sync/backups').iterdir())
        manifest = json.loads((backup / 'sha256.json').read_text())
        self.assertEqual(set(manifest), {str(p.relative_to(self.root)) for p in previous})
        for path, contents in previous.items():
            self.assertFalse(path.exists())
            archived = backup / path.relative_to(self.root)
            self.assertEqual(archived.read_bytes(), contents)
            self.assertEqual(cleanup.digest(archived), manifest[str(path.relative_to(self.root))])
        self.assertTrue((self.control / 'state.json').exists())

    def test_pending_queue_is_only_retired_with_explicit_reset(self):
        previous = self.queue(False)
        code, _, err = self.invoke('--reiniciar-colas')
        self.assertEqual(code, 0, err)
        backup = next((self.root / '.ved-sync/backups').iterdir())
        for path, contents in previous.items():
            self.assertFalse(path.exists())
            self.assertEqual((backup / path.relative_to(self.root)).read_bytes(), contents)
        self.assertTrue((self.control / 'state.json').exists())

    def test_unbound_history_is_not_treated_as_a_completed_queue(self):
        self.queue(True)
        db = sqlite3.connect(self.control / 'VED-Sync.historial')
        try:
            db.execute('DELETE FROM binding')
            db.commit()
        finally:
            db.close()
        code, out, err = self.invoke()
        self.assertEqual(code, 0, err)
        self.assertIn('sin cierre confirmado', out)
        self.assertTrue((self.control / 'VED-Sync.historial').exists())
        self.assertTrue((self.control / '.ved-sync-fifo.sqlite').exists())

    def test_interrupted_retirement_cannot_reuse_verified_history_with_a_fresh_index(self):
        previous = self.queue(True)
        remove = cleanup.Artifact.remove
        def interrupted(artifact, project):
            remove(artifact, project)
            if artifact.path.name == 'VED-Sync.historial':
                raise KeyboardInterrupt
        with patch.object(cleanup.Artifact, 'remove', interrupted):
            code, _, err = self.invoke()
        self.assertEqual(code, 130)
        self.assertIn('interrumpida', err)
        backup = next((self.root / '.ved-sync/backups').iterdir())
        for path, contents in previous.items():
            self.assertEqual((backup / path.relative_to(self.root)).read_bytes(), contents)
        self.assertTrue((self.control / '.ved-sync-fifo.sqlite').exists())
        with self.assertRaisesRegex(ValueError, 'Falta el historial'):
            WorkList(self.control / 'VED-Sync.cola', 'scope')

    def test_preview_does_not_write_remove_or_create_a_lock(self):
        self.queue(True)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        code, out, err = self.invoke('--simular')
        self.assertEqual(code, 0, err)
        self.assertIn('Simulación', out)
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)
        self.assertFalse((self.root / '.ved-sync/backups').exists())
        self.assertFalse((self.control / 'run.lock').exists())

    def test_automatic_log_reset_preserves_queue_state_timings_and_other_controls(self):
        queue = self.queue(False)
        timing = self.control / 'tiempo.csv'
        timing.write_text('estadística de tiempos, no actividad de la ejecución\n')
        (self.control / 'VED-Sync.cola.log.1').write_text('rotación antigua')
        (self.control / 'operaciones.jsonl').write_text('actividad antigua')
        other = self.root / '.ved-sync/otro'
        other.mkdir()
        other_log = other / 'VED-Sync.cola.log'
        other_log.write_text('otro conjunto')
        before = {p: p.read_bytes() for p in (*queue, timing, self.control / 'state.json', other_log)}
        with self.log.open('rb') as viewer:
            cleanup.reset_activity_logs(self.control, 'VED-Sync.cola.log', project=self.root)
            viewer.seek(0)
            self.assertEqual(viewer.read(), b'')
        self.assertEqual(self.log.read_bytes(), b'')
        self.assertFalse((self.control / 'VED-Sync.cola.log.1').exists())
        self.assertFalse((self.control / 'operaciones.jsonl').exists())
        for path, contents in before.items():
            self.assertEqual(path.read_bytes(), contents)

    def test_automatic_reset_rejects_a_rotated_symlink_before_truncating_current_log(self):
        source = self.base / 'fuente.txt'
        source.write_text('intacto')
        (self.control / 'VED-Sync.cola.log.1').symlink_to(source)
        before = self.log.read_bytes()
        with self.assertRaises(ValueError):
            cleanup.reset_activity_logs(self.control, 'VED-Sync.cola.log', project=self.root)
        self.assertEqual(self.log.read_bytes(), before)
        self.assertEqual(source.read_text(), 'intacto')

    def test_active_advisory_lock_blocks_all_cleanup_before_any_removal(self):
        other = self.root / '.ved-sync/aaa'
        other.mkdir()
        other_log = other / 'operaciones.jsonl'
        other_log.write_text('conservar también')
        lock = self.control / 'run.lock'
        with lock.open('w+') as owner:
            owner.write(json.dumps({'protocol': 'flock-v1', 'pid': os.getpid()}))
            owner.flush()
            cleanup.fcntl.flock(owner.fileno(), cleanup.fcntl.LOCK_EX | cleanup.fcntl.LOCK_NB)
            for args in ((), ('--simular',), ('--reiniciar-colas',)):
                code, _, err = self.invoke(*args)
                self.assertEqual(code, 2)
                self.assertIn('ejecución activa', err)
                self.assertTrue(self.log.exists())
                self.assertTrue(other_log.exists())
            self.assertFalse((other / 'run.lock').exists())

    def test_active_legacy_pid_blocks_cleanup(self):
        lock = self.control / 'run.lock'
        lock.write_text(str(os.getpid()))
        code, _, err = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn('ejecución activa', err)
        self.assertEqual(lock.read_text(), str(os.getpid()))
        self.assertTrue(self.log.exists())

    def test_stale_legacy_lock_is_retired_but_empty_advisory_lock_is_preserved(self):
        lock = self.control / 'run.lock'
        lock.write_text('12345')
        with patch.object(cleanup, 'pid_alive', return_value=False):
            code, _, err = self.invoke()
        self.assertEqual(code, 0, err)
        self.assertFalse(lock.exists())
        lock.write_text('')
        code, _, err = self.invoke()
        self.assertEqual(code, 0, err)
        self.assertEqual(lock.read_bytes(), b'')

    def test_symlink_file_aborts_before_other_logs_are_removed(self):
        outside = self.base / 'fuente.txt'
        outside.write_text('intacto')
        link = self.control / 'operaciones.jsonl'
        link.symlink_to(outside)
        code, _, err = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn('enlaces', err)
        self.assertTrue(self.log.exists())
        self.assertTrue(link.is_symlink())
        self.assertEqual(outside.read_text(), 'intacto')

    def test_configuration_cannot_redirect_cleanup_outside_project(self):
        outside = self.base / 'externo'
        outside.mkdir()
        sentinel = outside / 'operaciones.jsonl'
        sentinel.write_text('intacto')
        (self.root / '.ved-sync-config.json').write_text(json.dumps({'state_dir': str(outside)}))
        code, _, err = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn('fuera de VED-SYNC', err)
        self.assertEqual(sentinel.read_text(), 'intacto')
        self.assertTrue(self.log.exists())

    def test_symlink_control_directory_cannot_redirect_cleanup(self):
        outside = self.base / 'externo'
        outside.mkdir()
        (outside / 'operaciones.jsonl').write_text('intacto')
        (self.root / '.ved-sync/otro').symlink_to(outside, target_is_directory=True)
        code, _, err = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn('enlaces', err)
        self.assertEqual((outside / 'operaciones.jsonl').read_text(), 'intacto')
        self.assertTrue(self.log.exists())

    def test_failed_or_corrupt_archive_prevents_all_selected_removals(self):
        previous = self.queue(True)
        for failure in (OSError(errno.ENOSPC, 'sin espacio'), None):
            with self.subTest(failure=failure):
                def corrupt(source, destination):
                    Path(destination).write_text('copia corrupta')
                with patch.object(cleanup.shutil, 'copy2', side_effect=failure or corrupt):
                    code, _, err = self.invoke()
                self.assertEqual(code, 2)
                self.assertTrue(err)
                self.assertTrue(self.log.exists())
                for path, contents in previous.items():
                    self.assertEqual(path.read_bytes(), contents)

    def test_changed_file_is_not_removed(self):
        artifact = cleanup.Artifact.inspect(self.root, self.log)
        self.log.write_text('modificado después del inventario')
        with self.assertRaises(RuntimeError):
            artifact.remove(self.root)
        self.assertTrue(self.log.exists())

    def test_selected_config_does_not_clean_other_control_directories(self):
        other = self.root / '.ved-sync/otro'
        other.mkdir()
        sentinel = other / 'operaciones.jsonl'
        sentinel.write_text('otro registro')
        code, _, err = self.invoke('--config', '.ved-sync-config.json')
        self.assertEqual(code, 0, err)
        self.assertFalse(self.log.exists())
        self.assertEqual(sentinel.read_text(), 'otro registro')

    def test_launcher_uses_its_own_project_from_another_working_directory(self):
        helper = self.root / 'ved_sync/cleanup.py'
        helper.parent.mkdir()
        shutil.copy2(PROJECT / 'ved_sync/cleanup.py', helper)
        shutil.copy2(PROJECT / 'limpieza.sh', self.root / 'limpieza.sh')
        result = subprocess.run(['bash', str(self.root / 'limpieza.sh')], cwd=self.base,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Limpieza terminada', result.stdout)
        self.assertFalse(self.log.exists())
        self.assertTrue(helper.exists())
