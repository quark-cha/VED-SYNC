import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ved_sync.engine import PROJECT
from ved_sync.telemetry import Console, Monitor, TimingHistory


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        parent = PROJECT / '.test-runs'
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = FakeClock()

    def monitor(self):
        m = Monitor(self.root, 'fictitious', clock=self.clock)
        m.start(False)
        self.current_monitor = m
        self.addCleanup(lambda: m.close('test_finished'))
        return m

    def events(self):
        if self.current_monitor.stream:
            self.current_monitor.stream.flush()
        return [json.loads(line) for line in (self.root / 'operaciones.jsonl').read_text().splitlines()]

    def test_no_eta_without_reliable_history(self):
        m = self.monitor()
        with m.operation('write', 100) as operation:
            operation.advance(50)
            self.clock.now = 0.3
            operation.advance(50)
            event = self.events()[-1]
            self.assertIsNone(event['eta_seconds'])
            self.assertLess(event['percent'], 100)
        self.assertEqual(self.events()[-1]['percent'], 100)
        self.assertTrue(self.events()[-1]['finished'])

    def test_cold_start_observed_rate_requires_real_window(self):
        m = self.monitor()
        with m.operation('write', 1024 * 1024) as operation:
            self.clock.now = 0.3
            operation.advance(256 * 1024)
            self.assertIsNone(self.events()[-1]['eta_seconds'])
            self.clock.now = 1.0
            operation.advance(256 * 1024)
            self.assertAlmostEqual(self.events()[-1]['eta_seconds'], 1.0)

    def test_history_estimates_and_adapts_to_observed_speed(self):
        m = self.monitor()
        for _ in range(3):
            m.history.record('write', 65536, 1, 'usb', 'ok')
        with m.operation('write', 1024 * 1024, 'usb') as operation:
            first_eta = self.events()[-1]['eta_seconds']
            self.assertAlmostEqual(first_eta, 16)
            self.clock.now = 1
            operation.advance(262144)
            self.assertLess(self.events()[-1]['eta_seconds'], first_eta - 4)

    def test_failed_and_outlier_samples_do_not_bias_estimation(self):
        h = TimingHistory(self.root / 'tiempo.csv')
        for _ in range(4):
            h.record('write', 65536, 1, 'usb', 'ok')
        h.record('write', 10**12, 1, 'usb', 'ok')
        h.record('write', 65536, 10000, 'usb', 'failed')
        h.record('write', 65536, 10000, 'usb', 'interrupted')
        self.assertEqual(h.speed('write', 'usb'), 65536)
        self.assertIsNone(h.speed('write', 'network'))
        self.assertIsNone(h.speed('sha256', 'usb'))
        self.assertEqual(TimingHistory(h.path).speed('write', 'usb'), 65536)

    def test_history_is_bounded_and_csv_remains_readable(self):
        h = TimingHistory(self.root / 'tiempo.csv', limit=10)
        for i in range(35):
            h.record('sha256', 65536 + i, 1, 'local', 'ok')
        with h.path.open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertLessEqual(len(rows), 10)
        self.assertEqual(int(rows[-1]['bytes']), 65570)
        self.assertEqual(set(rows[-1]), set(TimingHistory.FIELDS))
        self.assertTrue(rows[-1]['executed_at'])
        self.assertLessEqual(len(TimingHistory(h.path, 10).rows), 10)

    def test_incomplete_or_invalid_samples_are_ignored(self):
        p = self.root / 'tiempo.csv'
        p.write_text(','.join(TimingHistory.FIELDS) + '\nwrite,1,nan,inf,usb,ok,date\nbroken\n')
        self.assertIsNone(TimingHistory(p).speed('write', 'usb'))

    def test_log_is_visible_before_close_and_omits_untrusted_details(self):
        m = self.monitor()
        m.emit('pending', path='https://' + 'user:password@host/password=SECRET',
               detail='password=SECRET', credentials='SECRET', code='OSError')
        raw = (self.root / 'operaciones.jsonl').read_text()
        self.assertNotIn('SECRET', raw)
        self.assertNotIn('password', raw)
        self.assertNotIn('https://', raw)
        self.assertEqual(self.events()[-1]['code'], 'OSError')
        self.assertIn('path_ref', self.events()[-1])

    def test_error_event_retains_local_diagnostics(self):
        from ved_sync.telemetry import EventList
        m = self.monitor()
        path = '/ubuntu/pruebas/archivo ausente.lean'
        detail = f"[Errno 2] No such file or directory: '{path}'"
        EventList(m).append({'type': 'error', 'repository': 'recuperados',
                             'path': path, 'detail': detail, 'code': 'FileNotFoundError',
                             'credentials': 'SECRET'})
        event = self.events()[-1]
        self.assertEqual(event['repository'], 'recuperados')
        self.assertEqual(event['path'], path)
        self.assertEqual(event['detail'], detail)
        self.assertEqual(event['code'], 'FileNotFoundError')
        self.assertIn('path_ref', event)
        self.assertIn('repository_ref', event)
        self.assertNotIn('credentials', event)

    def test_new_run_starts_a_fresh_log_with_a_distinct_run_id(self):
        m = self.monitor()
        first = self.events()[0]['run']
        m.close('ok')
        log = self.root / 'operaciones.jsonl'
        inode = log.stat().st_ino
        (self.root / 'operaciones.jsonl.1').write_text('registro antiguo')
        m.start(True)
        self.assertNotEqual(self.events()[-1]['run'], first)
        self.assertEqual(self.events()[0]['run'], m.run_id)
        self.assertEqual(sum(e['type'] == 'cycle_started' for e in self.events()), 1)
        self.assertEqual(log.stat().st_ino, inode)
        self.assertFalse((self.root / 'operaciones.jsonl.1').exists())

    def test_recovery_records_durable_completion_before_displaying_success(self):
        out = io.StringIO()
        console = Console(out)
        m = Monitor(self.root, 'fictitious', console=console, clock=self.clock, audit=False)
        m.start(False)
        m.plan_files(['a'])
        m.finish_file('a')
        m.project_update('confirmation', 98)
        m.close('ok', completed=True)
        console.close()
        events = [json.loads(line) for line in (self.root / 'VED-Sync.cola.log').read_text().splitlines()]
        self.assertTrue(events[-1]['completed'])
        self.assertEqual(events[-1]['files_done'], 1)
        self.assertIn('Finalizado correctamente', out.getvalue())
        self.assertIn('100.0%', out.getvalue())

    def test_recovery_summary_failure_prevents_success_and_leaves_no_hourglass(self):
        from ved_sync.worklist import append_trace
        out = io.StringIO()
        console = Console(out)
        m = Monitor(self.root, 'fictitious', console=console, clock=self.clock, audit=False)
        m.start(False)
        m.project_update('confirmation', 98)
        def fail_summary(path, event, **fields):
            if event == 'cycle_finished':
                raise OSError('Error de cierre ficticio')
            return append_trace(path, event, **fields)
        with patch('ved_sync.worklist.append_trace', side_effect=fail_summary):
            with self.assertRaises(OSError):
                m.close('ok', completed=True)
        console.close()
        self.assertNotIn('100.0%', out.getvalue())
        self.assertNotIn('⌛', out.getvalue())
        self.assertIn('Finalizado con errores', out.getvalue())

    def test_interruption_never_publishes_success_or_100(self):
        m = self.monitor()
        with self.assertRaises(KeyboardInterrupt):
            with m.operation('file', 100) as operation:
                self.clock.now = 1
                operation.advance(99)
                raise KeyboardInterrupt
        self.assertFalse(any(e.get('percent') == 100 for e in self.events()))
        self.assertEqual(list(m.history.rows)[-1]['result'], 'interrupted')

    def test_console_throttles_and_reuses_tty_line(self):
        class Tty(io.StringIO):
            def isatty(self):
                return True
        out = Tty()
        console = Console(out, clock=self.clock, ansi=True, width=120)
        event = dict(type='project_progress', phase='comparison', percent=50.0,
                     processed=50, total=100, eta_seconds=None, finished=False)
        for _ in range(100):
            console(event)
        self.assertEqual(out.getvalue().count('\x1b[2K'), 3)
        self.clock.now = 1
        console({**event, 'percent': 90.0})
        self.assertIn('\x1b[2A', out.getvalue())
        self.assertIn('indeterminado', out.getvalue())

    def test_console_does_not_show_child_100_as_file_completion(self):
        class Tty(io.StringIO):
            def isatty(self):
                return True
        out = Tty()
        console = Console(out, clock=self.clock, ansi=True, width=120)
        file = dict(type='progress', operation='file', percent=80., processed=80,
                    total=100, elapsed=2, finished=False, transaction='test')
        console(file)
        self.clock.now = 2
        console({**file, 'operation': 'write', 'percent': 100., 'finished': True})
        self.assertNotIn('100.0%', out.getvalue())
        self.clock.now = 3
        console({**file, 'percent': 100., 'finished': True})
        self.assertIn('100.0%', out.getvalue())

    def test_global_estimate_requires_project_history(self):
        m = self.monitor()
        m.set_work(500000, 100000)
        self.assertIsNone(m.project_progress['eta_seconds'])
        for _ in range(3):
            m.history.record('project', 100000, 10, 'mixed', 'ok')
        m.set_work(500000, 100000)
        self.assertGreater(m.project_progress['eta_seconds'], 0)
        self.assertLess(m.project_progress['percent'], 100)

    def test_progress_updates_are_bounded_per_operation_and_project(self):
        m = self.monitor()
        with m.operation('write', 1000) as operation:
            for _ in range(1000):
                operation.advance(1)
                m.project_update('comparison', 20)
        progress = [e for e in self.events() if e['type'] == 'progress']
        self.assertEqual(len(progress), 2)
        global_progress = [e for e in self.events() if e['type'] == 'project_progress']
        self.assertEqual(len(global_progress), 2)

    def test_console_names_are_human_readable_but_log_keeps_only_references(self):
        class Tty(io.StringIO):
            def isatty(self):
                return True
        out = Tty()
        m = Monitor(self.root, 'fictitious',
                    console=Console(out, clock=self.clock, ansi=True, width=160), clock=self.clock)
        m.start(False)
        self.addCleanup(lambda: m.close('done'))
        self.clock.now = 1
        m.emit('status', repository='USB_PRUEBAS', status='amarillo', location='/demo/USB_PRUEBAS')
        self.clock.now = 2
        m.emit('progress', operation='file', percent=30., processed=3, total=10,
               path='fotos/imagen_prueba.jpg')
        m.stream.flush()
        self.assertIn('USB_PRUEBAS', out.getvalue())
        self.assertIn('imagen_prueba.jpg', out.getvalue())
        raw = (self.root / 'operaciones.jsonl').read_text()
        self.assertNotIn('USB_PRUEBAS', raw)
        self.assertNotIn('imagen_prueba.jpg', raw)

    def test_file_counter_counts_unique_files_and_reconciles_verification(self):
        m = self.monitor()
        m.plan_files(['a', 'b'])
        m.finish_file('a')
        m.finish_file('a')
        self.assertEqual(len(m.finished_files), 1)
        self.assertEqual(self.events()[-1]['files_done'], 1)
        self.assertEqual(self.events()[-1]['files_total'], 2)
        m.reconcile_files([])
        self.assertEqual(self.events()[-1]['files_done'], 0)

    def test_new_cycle_resets_file_count_without_persisting_display_location(self):
        m = self.monitor()
        m.plan_files(['a'])
        m.finish_file('a')
        m.close('ok')
        m.start(True)
        self.assertIsNone(m.files_total)
        self.assertEqual(m.finished_files, set())
