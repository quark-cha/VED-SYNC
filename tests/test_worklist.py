"""Small real SIGKILL regressions for Víctor Estrada Díaz's recovery FIFO."""
from contextlib import closing
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tests import test_restore_projects
from ved_sync.engine import inspect
from ved_sync.worklist import WorkList
from ved_sync.restore import fingerprint, copy_pending, verify_pending


class WorkListTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_restore_projects.RestoreProjectsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.control = self.fixture.project / '.ved-sync/control'

    def prepare(self):
        self.fixture.put(self.fixture.windows, 'a', 'primero')
        self.fixture.put(self.fixture.windows, 'b', 'segundo')

    def kill(self, stage='copy'):
        self.prepare()
        code = '''
import os, signal, sys
from pathlib import Path
from ved_sync import engine
engine.PROJECT = Path(sys.argv[1])
e = engine.Engine(Path(sys.argv[2]), apply=True, restore_projects=True)
if sys.argv[3] == 'copy':
    original = e.copy
    def copy(source, target, *args):
        if target.name == 'b':
            os.kill(os.getpid(), signal.SIGKILL)
        return original(source, target, *args)
    e.copy = copy
elif sys.argv[3] == 'transaction':
    from ved_sync.worklist import WorkList
    original = WorkList.flush
    def flush(self):
        row = self.connection.execute("SELECT status FROM inventory WHERE path='a'").fetchone()
        if row and row[0] == 'done':
            os.kill(os.getpid(), signal.SIGKILL)
        return original(self)
    WorkList.flush = flush
else:
    original = e.inspect_file
    def check(path, *args, **kwargs):
        if (e.monitor.project_progress['phase'] == 'verification'
                and path == engine.PROJECT.parent / 'b'):
            os.kill(os.getpid(), signal.SIGKILL)
        return original(path, *args, **kwargs)
    e.inspect_file = check
e.run_once()
'''
        completed = subprocess.run([sys.executable, '-c', code, str(self.fixture.project),
                                    str(self.fixture.config), stage], capture_output=True, text=True)
        self.assertEqual(completed.returncode, -signal.SIGKILL, completed.stderr)
        # The following invocation must acquire the OS lock without manual removal.
        self.assertEqual(json.loads((self.control / 'run.lock').read_text())['protocol'], 'flock-v1')

    def pending(self, table):
        with closing(sqlite3.connect(self.control / '.ved-sync-fifo.sqlite')) as db:
            db.execute('ATTACH DATABASE ? AS history', (str(self.control / 'VED-Sync.historial'),))
            return [r[0] for r in db.execute(f'SELECT i.path FROM {table} p JOIN inventory i '
                                             'ON i.id=p.job_id ORDER BY p.sequence')]

    @unittest.skipUnless(os.name == 'posix', 'SIGKILL is a POSIX regression')
    def test_sigkill_resumes_pending_before_review_without_recopying_confirmed(self):
        self.kill()
        self.assertFalse((self.control / 'state.json').exists())
        self.assertEqual(self.pending('pending_copy'), ['b'])
        self.assertEqual((self.control / 'VED-Sync.cola').read_text(), '2;1;b\n')
        self.assertEqual(self.pending('pending_review'), ['a'])
        engine = self.fixture.engine()
        checked = []
        original = engine.inspect_file
        def check(path, *args, **kwargs):
            checked.append(path.name)
            return original(path, *args, **kwargs)
        with patch.object(engine, 'inspect_file', side_effect=check), \
             patch.object(engine, 'copy', wraps=engine.copy) as copies:
            report = engine.run_once()
        self.assertEqual(checked[0], 'b')
        self.assertEqual([call.args[1].name for call in copies.call_args_list], ['b'])
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertEqual(self.pending('pending_copy'), [])
        self.assertEqual(self.pending('pending_review'), [])
        self.assertFalse((self.control / '.runtime-state.sqlite').exists())
        self.assertEqual(set(json.loads((self.control / 'state.json').read_text())['files']), {'a', 'b'})
        events = [json.loads(line) for line in (self.control / 'VED-Sync.cola.log').read_text().splitlines()]
        self.assertEqual(events[0]['event'], 'cycle_started')
        self.assertEqual([e['path'] for e in events if e['event'] == 'copy_confirmed'], ['b'])

    @unittest.skipUnless(os.name == 'posix', 'SIGKILL is a POSIX regression')
    def test_sigkill_during_review_does_not_repeat_verified_files(self):
        self.kill('verify')
        self.assertEqual(self.pending('pending_copy'), [])
        self.assertEqual(self.pending('pending_review'), ['b'])
        engine = self.fixture.engine()
        with patch.object(engine, 'inspect_file', wraps=engine.inspect_file) as checks:
            report = engine.run_once()
        self.assertNotIn('a', [c.args[0].name for c in checks.call_args_list])
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertEqual(self.pending('pending_review'), [])

    @unittest.skipUnless(os.name == 'posix', 'SIGKILL is a POSIX regression')
    def test_final_review_discovers_added_file(self):
        self.kill()
        self.fixture.put(self.fixture.windows, 'c', 'nuevo durante la interrupción')
        engine = self.fixture.engine()
        with patch.object(engine, 'copy', wraps=engine.copy) as copies:
            report = engine.run_once()
        self.assertEqual([c.args[1].name for c in copies.call_args_list], ['b', 'c'])
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertEqual((self.fixture.ubuntu / 'c').read_text(), 'nuevo durante la interrupción')

    @unittest.skipUnless(os.name == 'posix', 'SIGKILL is a POSIX regression')
    def test_final_review_detects_destination_edit_and_preserves_backup(self):
        self.kill()
        target = self.fixture.ubuntu / 'a'
        target.write_text('edición posterior')
        digest = inspect(target).digest
        report = self.fixture.engine().run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertEqual(target.read_text(), 'primero')
        self.assertEqual((self.control / 'versions' / (digest + '.original')).read_text(), 'edición posterior')

    @unittest.skipUnless(os.name == 'posix', 'SIGKILL is a POSIX regression')
    def test_corrupt_backup_keeps_work_pending(self):
        self.kill()
        digest = inspect(self.fixture.windows / 'b').digest
        (self.control / 'versions' / (digest + '.original')).write_text('corrupto')
        report = self.fixture.engine().run_once()
        self.assertIn('rojo', report['status'].values())
        self.assertEqual(self.pending('pending_copy'), ['b'])
        self.assertFalse((self.fixture.ubuntu / 'b').exists())

    @unittest.skipUnless(os.name == 'posix', 'SIGKILL is a POSIX regression')
    def test_kill_before_receipt_commit_rechecks_published_file(self):
        self.kill('transaction')
        self.assertEqual((self.fixture.ubuntu / 'a').read_text(), 'primero')
        self.assertEqual(self.pending('pending_copy'), ['a', 'b'])
        engine = self.fixture.engine()
        with patch.object(engine, 'copy', wraps=engine.copy) as copies:
            report = engine.run_once()
        self.assertEqual([c.args[1].name for c in copies.call_args_list], ['b'])
        self.assertEqual(set(report['status'].values()), {'verde'})

    def test_local_queue_and_history_never_propagate(self):
        names = ['VED-Sync.cola', 'VED-Sync.cola-journal', 'VED-Sync.cola.log',
                 'VED-Sync.cola.log.1', 'VED-Sync.cola-mj123', 'VED-Sync.historial',
                 'VED-Sync.historial-journal', 'VED-SYNC.COLA', 'operaciones.jsonl',
                 'operaciones.json', 'tiempo.csv', '.ved-sync-fifo.sqlite']
        for name in names:
            self.fixture.put(self.fixture.windows, 'folder/' + name, 'solo local')
        self.fixture.put(self.fixture.windows, 'VED-Sync.colaborador.txt', 'conservar fuente')
        report = self.fixture.engine().run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        for name in names:
            self.assertFalse((self.fixture.ubuntu / 'folder' / name).exists())
        self.assertEqual((self.fixture.ubuntu / 'VED-Sync.colaborador.txt').read_text(), 'conservar fuente')

    def test_text_log_is_bounded_separate_from_pending_work(self):
        self.control.mkdir(parents=True)
        queue = WorkList(self.control / 'VED-Sync.cola', 'scope')
        self.addCleanup(queue.close)
        with patch.object(WorkList, 'LOG_LIMIT', 64):
            for i in range(5):
                queue.trace('test', number=i)
        self.assertEqual(len(list(self.control.glob('VED-Sync.cola.log*'))), 2)
        self.assertEqual(json.loads(queue.log_path.read_text())['number'], 4)
        self.assertEqual(queue.progress()['total'], 0)

    def test_bootstrap_from_legacy_checkpoint_starts_with_pending_file(self):
        self.prepare()
        target = self.fixture.put(self.fixture.ubuntu, 'a', 'primero')
        entries = {name: inspect(self.fixture.windows / name) for name in ('a', 'b')}
        current = inspect(target)
        record = {'head': current.digest, 'seen': {'windows': current.digest, 'ubuntu': current.digest},
                  'history': [{'sha256': current.digest, 'time_ns': 1}], 'observations': {
                      'windows': {'sha256': entries['a'].digest, 'size': entries['a'].size,
                                  'mtime_ns': entries['a'].mtime_ns},
                      'ubuntu': {'sha256': current.digest, 'size': current.size, 'mtime_ns': current.mtime_ns}}}
        cache = {str(self.fixture.windows / name): {'sha256': entry.digest,
                  'stat': fingerprint(self.fixture.windows / name), 'verified_ns': 1}
                 for name, entry in entries.items()}
        self.control.mkdir(parents=True)
        (self.control / 'state.json').write_text(json.dumps({'files': {'a': record}, 'hash_cache': cache}))
        engine = self.fixture.engine()
        with patch.object(engine, 'inspect_file', wraps=engine.inspect_file) as checks:
            report = engine.run_once()
        self.assertEqual(checks.call_args_list[0].args[0].name, 'b')
        self.assertEqual(set(report['status'].values()), {'verde'})

    def test_save_failure_resumes_finished_review_without_rehashing(self):
        self.prepare()
        engine = self.fixture.engine()
        with patch.object(engine, 'save', side_effect=OSError('guardado interrumpido')):
            with self.assertRaises(OSError):
                engine.run_once()
        self.assertEqual(self.pending('pending_copy'), [])
        self.assertEqual(self.pending('pending_review'), [])
        engine = self.fixture.engine()
        with patch.object(engine, 'inspect_file', side_effect=AssertionError('Repite revisión confirmada')):
            report = engine.run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})

    def test_two_stalled_attempts_trigger_rebuild_but_progress_resets_counter(self):
        self.control.mkdir(parents=True)
        queue = WorkList(self.control / 'VED-Sync.cola', 'scope')
        self.addCleanup(queue.close)
        queue.add('a', ('a' * 64, 1, 1))
        queue.flush()
        self.assertFalse(queue.attempt())
        self.assertFalse(queue.attempt())
        self.assertTrue(queue.attempt())
        job = next(queue.jobs(('pending',)))
        queue.update(job, 'done')
        self.assertFalse(queue.attempt())
        self.assertEqual(queue.meta('stalled_attempts'), 0)

    def test_full_disk_keeps_fifo_and_waits_for_space_before_rebuild(self):
        self.prepare()
        with patch('ved_sync.restore.shutil.disk_usage', return_value=SimpleNamespace(free=0)):
            for _ in range(2):
                report = self.fixture.engine().run_once()
                self.assertIn('rojo', report['status'].values())
            with self.assertRaises(OSError) as error:
                self.fixture.engine().run_once()
            self.assertEqual(error.exception.errno, 28)
        self.assertEqual(self.pending('pending_copy'), ['a', 'b'])
        self.assertFalse((self.control / 'queue-backups').exists())
        report = self.fixture.engine().run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertEqual(len(list((self.control / 'queue-backups').iterdir())), 1)

    def test_manual_reset_backs_up_plan_without_recopying_equal_files(self):
        self.prepare()
        self.fixture.engine().run_once()
        engine = self.fixture.engine()
        engine.reset_queue = True
        with patch.object(engine, 'copy', side_effect=AssertionError('Recopia archivo igual')):
            report = engine.run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        backups = list((self.control / 'queue-backups').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual({p.name for p in backups[0].iterdir()},
                         {'VED-Sync.cola', 'VED-Sync.historial', '.ved-sync-fifo.sqlite'})

    @unittest.skipUnless(os.name == 'posix', 'flock is a POSIX regression')
    def test_simultaneous_recovery_is_rejected_and_dead_owner_marker_is_reusable(self):
        self.prepare()
        self.control.mkdir(parents=True)
        owner = self.fixture.engine()
        fd, advisory = owner._acquire_lock(self.control / 'run.lock')
        self.assertTrue(advisory)
        try:
            with self.assertRaises(RuntimeError):
                self.fixture.engine().run_once()
        finally:
            os.close(fd)
        report = self.fixture.engine().run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertEqual((self.control / 'run.lock').read_bytes(), b'')

    def test_recovery_creates_no_operation_or_timing_log(self):
        self.prepare()
        self.fixture.engine().run_once()
        self.assertFalse((self.control / 'operaciones.jsonl').exists())
        self.assertFalse((self.control / 'tiempo.csv').exists())
        events = [json.loads(line) for line in (self.control / 'VED-Sync.cola.log').read_text().splitlines()]
        self.assertEqual(events[-1]['event'], 'cycle_finished')
        self.assertEqual(events[-1]['result'], 'ok')
        self.assertTrue(events[-1]['completed'])
        self.assertEqual(events[-1]['files_done'], 2)
        self.assertEqual(events[-1]['files_total'], 2)

    def test_new_recovery_cleans_previous_logs_without_recopying_confirmed_files(self):
        self.prepare()
        self.fixture.engine().run_once()
        log = self.control / 'VED-Sync.cola.log'
        log.write_text('actividad de la ejecución anterior\n')
        inode = log.stat().st_ino
        (self.control / 'VED-Sync.cola.log.1').write_text('rotación anterior')
        (self.control / 'operaciones.jsonl').write_text('registro del modo antiguo')
        engine = self.fixture.engine()
        with patch.object(engine, 'copy', side_effect=AssertionError('Repite una copia confirmada')):
            report = engine.run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertEqual(log.stat().st_ino, inode)
        self.assertFalse((self.control / 'VED-Sync.cola.log.1').exists())
        self.assertFalse((self.control / 'operaciones.jsonl').exists())
        events = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(sum(e['event'] == 'cycle_started' for e in events), 1)
        self.assertEqual(events[-1]['event'], 'cycle_finished')
        self.assertTrue(events[-1]['completed'])
        self.assertTrue((self.control / 'state.json').is_file())
        self.assertTrue((self.control / 'VED-Sync.historial').is_file())

    def test_rejected_second_execution_cannot_clear_the_active_log(self):
        self.control.mkdir(parents=True)
        owner = self.fixture.engine()
        fd, _ = owner._acquire_lock(self.control / 'run.lock')
        owner.monitor.start(False)
        try:
            log = self.control / 'VED-Sync.cola.log'
            previous = log.read_bytes()
            with self.assertRaises(RuntimeError):
                self.fixture.engine().run_once()
            self.assertEqual(log.read_bytes(), previous)
        finally:
            owner.monitor.close('test_finished')
            os.close(fd)

    def test_text_queue_quotes_relative_names_and_removes_confirmed_entries(self):
        import csv
        self.control.mkdir(parents=True)
        queue = WorkList(self.control / 'VED-Sync.cola', 'scope')
        self.addCleanup(queue.close)
        queue.add('UNIHOLOG/run.sh', ('a' * 64, 1, 1))
        queue.add('carpeta/con;separador.py', ('b' * 64, 1, 1))
        queue.flush()
        queue.export_pending()
        with queue.path.open(newline='') as stream:
            self.assertEqual(list(csv.reader(stream, delimiter=';')),
                             [['1', '2', 'UNIHOLOG/run.sh'], ['1', '2', 'carpeta/con;separador.py']])
        first = next(queue.jobs(('pending',)))
        queue.update(first, 'done')
        self.assertNotIn('UNIHOLOG/run.sh', queue.path.read_text())

    def test_binary_queue_converts_to_text_without_losing_pending_work(self):
        self.control.mkdir(parents=True)
        path = self.control / 'VED-Sync.cola'
        queue = WorkList(path, 'scope')
        queue.add('UNIHOLOG/run.sh', ('a' * 64, 1, 1))
        queue.flush()
        index = queue.index_path
        queue.close()
        path.unlink()
        index.replace(path)  # Earlier format stored its SQLite index at .cola.
        queue = WorkList(path, 'scope')
        self.addCleanup(queue.close)
        self.assertEqual(path.read_text(), '1;2;UNIHOLOG/run.sh\n')
        self.assertEqual([j['path'] for j in queue.jobs(('pending',))], ['UNIHOLOG/run.sh'])
        saved = self.control / 'queue-backups/text-format/VED-Sync.cola'
        self.assertEqual(saved.read_bytes()[:16], b'SQLite format 3\x00')

    def test_old_queued_audit_file_is_retired_without_copying_or_blocking_finish(self):
        self.prepare()
        self.fixture.engine().run_once()
        with closing(sqlite3.connect(self.control / '.ved-sync-fifo.sqlite')) as db:
            signature = json.loads(db.execute("SELECT value FROM metadata WHERE key='signature'").fetchone()[0])
        queue = WorkList(self.control / 'VED-Sync.cola', signature, routes=(2, 1))
        queue.add('folder/operaciones.jsonl', ('a' * 64, 1, 1))
        queue.add('folder/.test-runs/ficticio.txt', ('b' * 64, 1, 1))
        queue.add('DEMUESTRA/.venv-comparacion/paquete.py', ('c' * 64, 1, 1))
        queue.add('folder/.oculto.txt', ('d' * 64, 1, 1), done=True)
        queue.set_meta('complete', False)
        queue.flush()
        queue.close()
        report = self.fixture.engine().run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertEqual(self.pending('pending_copy'), [])
        self.assertEqual(self.pending('pending_review'), [])
        self.assertFalse((self.fixture.ubuntu / 'folder/operaciones.jsonl').exists())
        self.assertFalse((self.fixture.ubuntu / 'folder/.test-runs').exists())
        self.assertFalse((self.fixture.ubuntu / 'DEMUESTRA/.venv-comparacion').exists())
        self.assertFalse((self.fixture.ubuntu / 'folder/.oculto.txt').exists())
        events = [json.loads(line) for line in (self.control / 'VED-Sync.cola.log').read_text().splitlines()]
        self.assertEqual([e['total'] for e in events if e['event'] == 'exclusions_applied'], [4])

    def test_old_hidden_jobs_are_skipped_before_copy_or_verification(self):
        self.control.mkdir(parents=True)
        queue = WorkList(self.control / 'VED-Sync.cola', 'scope')
        self.addCleanup(queue.close)
        hidden = ('DEMUESTRA/.venv-comparacion/paquete.py', './visible/.oculto.txt')
        queue.add(hidden[0], ('a' * 64, 1, 1))
        queue.add(hidden[1], ('b' * 64, 1, 1), done=True)
        queue.flush()
        engine = self.fixture.engine()
        engine.monitor.start(False)
        self.addCleanup(lambda: engine.monitor.close('test_finished'))
        with patch.object(engine, 'inspect_file', side_effect=AssertionError('Lee un archivo oculto')):
            self.assertEqual(copy_pending(engine, queue, self.fixture.windows, self.fixture.ubuntu,
                                          'windows', 'ubuntu'), 0)
            self.assertEqual(verify_pending(engine, queue, self.fixture.windows, self.fixture.ubuntu), 0)
        self.assertEqual(queue.progress()['total'], 0)
        self.assertTrue(all(queue.get(path)['status'] == 'absent' for path in hidden))
        events = [json.loads(line) for line in queue.log_path.read_text().splitlines()]
        self.assertFalse(any(e['event'] in ('checking_pending', 'checking_final',
                                          'copy_confirmed', 'verification_confirmed') for e in events))

    def test_fifo_contains_only_unconfirmed_work_and_survives_reopen(self):
        self.control.mkdir(parents=True)
        path = self.control / 'queue.sqlite'
        queue = WorkList(path, 'scope')
        queue.add('a', ('a' * 64, 1, 1))
        queue.add('b', ('b' * 64, 2, 1))
        queue.flush()
        first = next(queue.jobs(('pending',)))
        self.assertEqual(first['path'], 'a')
        queue.update(first, 'done')
        progress = queue.progress()
        queue.close()
        queue = WorkList(path, 'scope')
        self.addCleanup(queue.close)
        self.assertEqual([j['path'] for j in queue.jobs(('pending',))], ['b'])
        self.assertEqual([j['path'] for j in queue.jobs(('done',))], ['a'])
        self.assertEqual(queue.progress(), progress)
        first = next(queue.jobs(('done',)))
        queue.update(first, 'verified')
        self.assertEqual(list(queue.jobs(('done',))), [])
        self.assertEqual(queue.progress()['verified'], 1)
