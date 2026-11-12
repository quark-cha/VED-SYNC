"""Pure rendering tests: no synchronizer, repositories or Git are started."""
import io
import re
import unittest
from unittest.mock import patch

from ved_sync.telemetry import Console


class Tty(io.StringIO):
    def isatty(self):
        return True


class Clock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        return self.now


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.out = Tty()
        self.console = Console(self.out, clock=self.clock, ansi=True, width=100)

    def send(self, kind, **fields):
        self.clock.now += 1
        self.console({'type': kind, **fields})

    @staticmethod
    def screen(data):
        """Interpret the cursor moves we emit, so newlines cannot hide scrolling."""
        rows, row, column = {}, 0, 0
        cursor = 0
        while cursor < len(data):
            if data[cursor] == '\x1b':
                match = re.match(r'\x1b\[(\d*)([AKm])', data[cursor:])
                if match is None:
                    raise AssertionError('Secuencia de terminal inesperada')
                number, command = match.groups()
                if command == 'A':
                    row = max(0, row - int(number or '1'))
                elif command == 'K':
                    rows[row] = {}
                cursor += len(match.group())
                continue
            char = data[cursor]
            if char == '\r':
                column = 0
            elif char == '\n':
                row += 1
            else:
                rows.setdefault(row, {})[column] = char
                column += Console._cells(char)
            cursor += 1
        return {r: ''.join(c for _, c in sorted(cells.items())) for r, cells in rows.items() if cells}

    def test_state_and_bar_stay_on_same_three_rows_across_updates_and_cycles(self):
        for _ in range(2):
            self.send('cycle_started', simulation=False, display_project='VED-SYNC', display_location='/USB/PRUEBA')
            for n in range(10):
                self.send('project_progress', phase='synchronization', percent=n * 9.,
                          processed=n, total=10, files_done=n, files_total=10)
            self.send('project_progress', phase='confirmed', percent=100., processed=10, total=10,
                      files_done=10, files_total=10, finished=True)
        screen = self.screen(self.out.getvalue())
        self.assertEqual(set(screen), {0, 1, 2})
        self.assertIn('[VERDE] /USB/PRUEBA ✓ VED-SYNC 10/10', screen[1])
        self.assertIn('100.0%', screen[2])
        self.assertIn('Finalizado correctamente', screen[2])
        self.console.close()
        self.assertEqual(set(self.screen(self.out.getvalue())), {0, 1, 2})

    def test_running_icon_and_unknown_counts_are_explicit(self):
        self.send('cycle_started', simulation=True, display_project='DEMO', display_location='/SSD')
        line, bar = self.console.lines()
        self.assertIn('⌛', line)
        self.assertIn('[SIM]', line)
        self.assertTrue(line.endswith('0/?'))
        self.assertIn('indeterminado', bar)

    def test_direction_changes_in_same_first_row_without_scrolling(self):
        self.send('cycle_started')
        self.send('transfer_direction', direction_source='Windows', direction_target='Ubuntu')
        self.assertEqual(self.screen(self.out.getvalue())[0], 'Windows → Ubuntu')
        self.send('transfer_direction', direction_source='Ubuntu', direction_target='Windows')
        screen = self.screen(self.out.getvalue())
        self.assertEqual(set(screen), {0, 1, 2})
        self.assertEqual(screen[0], 'Ubuntu → Windows')
        self.send('cycle_started')
        self.assertIn('comparando', self.screen(self.out.getvalue())[0])

    def test_direction_permissions_are_shown_before_copying_and_stay_on_first_row(self):
        self.send('cycle_started')
        self.console({'type': 'transfer_policy', 'transfers': [
            {'source': 'windows', 'target': 'ubuntu', 'source_label': 'Windows',
             'target_label': 'Ubuntu', 'allowed': True, 'reason': None},
            {'source': 'ubuntu', 'target': 'windows', 'source_label': 'Ubuntu',
             'target_label': 'Windows', 'allowed': False, 'reason': 'solo lectura'}]})
        expected = 'Windows → Ubuntu | permitido; Ubuntu → Windows: bloqueado (solo lectura)'
        self.assertEqual(self.screen(self.out.getvalue())[0], expected)
        self.send('preserved', display_path='solo-en-ubuntu.txt')
        self.assertNotEqual(self.console.light, 'rojo')
        self.send('project_progress', phase='confirmed', percent=100, finished=True)
        screen = self.screen(self.out.getvalue())
        self.assertEqual(set(screen), {0, 1, 2})
        self.assertEqual(screen[0], expected)
        self.assertIn('[VERDE]', screen[1])
        self.send('cycle_started')
        self.assertEqual(self.screen(self.out.getvalue())[0], 'Dirección: comparando repositorios')

    def test_bidirectional_permissions_remain_visible_when_direction_changes(self):
        self.send('transfer_policy', transfers=[
            {'source': 'a', 'target': 'b', 'source_label': 'Ubuntu',
             'target_label': 'USB', 'allowed': True, 'reason': None},
            {'source': 'b', 'target': 'a', 'source_label': 'USB',
             'target_label': 'Ubuntu', 'allowed': True, 'reason': None}])
        for source, target in [('Ubuntu', 'USB'), ('USB', 'Ubuntu')]:
            self.send('transfer_direction', direction_source=source, direction_target=target)
            self.assertEqual(self.screen(self.out.getvalue())[0],
                             f'{source} → {target} | permitido; {target} → {source}: permitido')

    def test_direction_is_clipped_and_control_characters_are_removed(self):
        self.console.width = 30
        self.send('transfer_direction', direction_source='Windows\n\x1b[2J' * 20,
                  direction_target='Ubuntu')
        screen = self.screen(self.out.getvalue())
        self.assertEqual(set(screen), {0, 1, 2})
        self.assertLessEqual(Console._cells(screen[0]), 29)

    def test_conflict_stays_red_and_never_reports_success(self):
        self.send('cycle_started')
        self.send('conflict')
        self.send('project_progress', phase='pending', percent=98., files_done=1, files_total=2, finished=True)
        line, bar = self.console.lines()
        self.assertIn('[ROJO]', line)
        self.assertIn('!', line)
        self.assertNotIn('✓', line)
        self.assertNotIn('100.0%', bar)
        self.assertIn('Finalizado con pendientes', bar)
        self.assertTrue(line.endswith('1/2'))

    def test_closing_without_confirmation_cannot_leave_a_running_icon(self):
        self.send('cycle_started')
        self.send('project_progress', phase='verification', percent=98,
                  processed=10, total=10, files_done=1, files_total=1)
        self.console.close()
        screen = self.screen(self.out.getvalue())
        self.assertIn('!', screen[1])
        self.assertNotIn('⌛', screen[1])
        self.assertIn('Finalizado con errores', screen[2])
        self.assertNotIn('100.0%', screen[2])

    def test_confirmation_phase_explains_why_it_is_still_at_98_percent(self):
        self.send('project_progress', phase='confirmation', percent=98)
        self.assertIn('Guardando y cerrando', self.console.lines()[1])
        self.assertIn('⌛', self.console.lines()[0])
        self.assertNotIn('Finalizado', self.console.lines()[1])

    def test_unavailable_is_grey(self):
        self.send('status', status='gris', display_repository='usb')
        self.send('project_progress', phase='pending', percent=98., finished=True)
        self.assertIn('[GRIS]', self.console.lines()[0])

    def test_read_error_keeps_code_and_filename_in_final_display(self):
        self.send('cycle_started')
        self.send('error', code='FileNotFoundError', display_path='temporal.txt')
        self.send('project_progress', phase='pending', percent=98, finished=True)
        self.assertIn('FileNotFoundError: temporal.txt', self.console.lines()[1])

    def test_long_unicode_paths_do_not_wrap_or_inject_control_sequences(self):
        self.console.width = 60
        self.send('cycle_started', display_project='PROYECTO', display_location='/USB/' + '資料' * 80 + '\n\x1b[2J')
        for line in self.console.lines():
            self.assertLessEqual(Console._cells(line), 59)
            self.assertNotIn('\n', line)
            self.assertNotIn('\x1b', line)
        self.assertEqual(set(self.screen(self.out.getvalue())), {0, 1, 2})

    def test_redirected_output_has_one_final_snapshot_without_ansi(self):
        out = io.StringIO()
        console = Console(out)
        for n in range(50):
            console({'type': 'project_progress', 'percent': n, 'phase': 'comparison'})
        self.assertEqual(out.getvalue(), '')
        console({'type': 'project_progress', 'phase': 'confirmed', 'percent': 100., 'finished': True})
        self.assertEqual(len(out.getvalue().splitlines()), 3)
        self.assertNotIn('\x1b', out.getvalue())

    def test_idle_interrupt_does_not_turn_verified_completion_into_error(self):
        self.send('project_progress', phase='confirmed', percent=100., finished=True)
        before = self.out.getvalue()
        self.console.fail('KeyboardInterrupt', interrupted=True)
        self.assertEqual(self.out.getvalue(), before)
        self.assertTrue(self.console.success)

    def test_ascii_terminal_uses_safe_icon_fallback(self):
        class AsciiTty(Tty):
            @property
            def encoding(self):
                return 'ascii'
        console = Console(AsciiTty(), ansi=True, width=80)
        console({'type': 'cycle_started'})
        self.assertIn(' > ', console.lines()[0])
        console({'type': 'project_progress', 'phase': 'confirmed', 'percent': 100., 'finished': True})
        self.assertIn(' + ', console.lines()[0])

    def test_terminal_mode_is_restored_when_closing(self):
        from unittest.mock import Mock
        kernel = Mock()
        self.console._restore_mode = (kernel, 123, 7)
        self.console.close()
        kernel.SetConsoleMode.assert_called_once_with(123, 7)


class OutputRoutingTests(unittest.TestCase):
    """Exercise only argument/output routing, replacing Engine with a harmless stub."""
    def invoke(self, *options):
        import sys
        from types import SimpleNamespace
        from ved_sync.__main__ import main
        out, err = Tty(), Tty()
        def factory(*args, **kwargs):
            console = kwargs['console']
            def run_once():
                if console is not None:
                    console({'type': 'cycle_started', 'simulation': True,
                             'display_project': 'DEMO', 'display_location': '/USB/demo'})
                    console({'type': 'project_progress', 'phase': 'confirmed', 'percent': 100.,
                             'finished': True, 'files_done': 1, 'files_total': 1})
                return {'simulation': True, 'status': {'a': 'verde'}, 'events': []}
            return SimpleNamespace(run_once=run_once, interval=1)
        with patch('ved_sync.__main__.Engine', side_effect=factory), \
             patch.object(sys, 'argv', ['ved-sync', '--once', *options]), \
             patch.object(sys, 'stdout', out), patch.object(sys, 'stderr', err), \
             patch.dict('os.environ', {'TERM': 'xterm-256color'}):
            code = main()
        return code, out.getvalue(), err.getvalue()

    def test_interactive_terminal_has_no_json_block_and_only_three_display_rows(self):
        code, out, err = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(out, '')
        screen = ConsoleTests.screen(err)
        self.assertEqual(set(screen), {0, 1, 2})
        self.assertIn('DEMO', screen[1])
        self.assertTrue(screen[1].endswith('1/1'))

    def test_explicit_json_keeps_report_and_disables_fixed_display(self):
        import json
        code, out, err = self.invoke('--json')
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)['simulation'])
        self.assertEqual(err, '')

    def test_quiet_keeps_previous_json_behavior(self):
        import json
        code, out, err = self.invoke('--quiet')
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)['simulation'])
        self.assertEqual(err, '')
