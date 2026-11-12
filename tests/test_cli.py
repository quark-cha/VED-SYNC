import json
import contextlib
import io
import subprocess
import sys
import unittest
from unittest.mock import patch
from ved_sync.__main__ import main
from ved_sync.engine import PROJECT
from tests import test_engine


class CliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_engine.SyncTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_default_cli_simulates_and_returns_pending(self):
        f = self.fixture
        f.put(0, 'demo')
        result = subprocess.run([sys.executable, '-m', 'ved_sync', '--config', str(f.config)],
                                cwd=PROJECT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['simulation'])
        self.assertFalse((f.repos[1] / 'f').exists())

    def test_cli_apply_verified(self):
        f = self.fixture
        f.put(2, 'demo')
        result = subprocess.run([sys.executable, '-m', 'ved_sync', '--config', str(f.config), '--apply'],
                                cwd=PROJECT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(json.loads(result.stdout)['status'].values()), {'verde'})
        self.assertEqual(f.contents(), ['demo'] * 3)

    def test_watch_stops_on_interrupt(self):
        with patch('sys.argv', ['ved-sync', '--watch', '--config', str(self.fixture.config)]), \
             patch('threading.Event.wait', side_effect=KeyboardInterrupt), patch('builtins.print'):
            self.assertEqual(main(), 0)

    def test_git_script_refuses_parent_repository(self):
        import shutil
        parent = self.fixture.root
        (parent / '.git').mkdir()
        project = parent / 'proyecto sin Git'
        project.mkdir()
        for name in ('git.sh', 'git_control.py'):
            shutil.copyfile(PROJECT / name, project / name)
        result = subprocess.run(['bash', str(project / 'git.sh'), 'status'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('No hay repositorio Git propio', result.stderr)

    def test_stale_staging_file_not_synchronized(self):
        f = self.fixture
        (f.repos[0] / '.ved-sync-aborted').write_text('partial')
        f.engine().run_once()
        self.assertFalse((f.repos[1] / '.ved-sync-aborted').exists())



    def test_missing_tkinter_reports_dependency(self):
        error = io.StringIO()
        with patch('sys.argv', ['ved-sync', '--gui', '--config', str(self.fixture.config)]), \
             patch.dict('sys.modules', {'tkinter': None}), contextlib.redirect_stderr(error):
            with self.assertRaises(SystemExit) as caught:
                main()
        self.assertEqual(caught.exception.code, 2)
        self.assertIn('requiere Tkinter', error.getvalue())

    def test_live_console_keeps_stdout_json_and_quiet_preserves_logs(self):
        f = self.fixture
        f.put(0, 'demo')
        result = subprocess.run([sys.executable, '-m', 'ved_sync', '--config', str(f.config)],
                                cwd=PROJECT, capture_output=True, text=True)
        self.assertTrue(json.loads(result.stdout)['simulation'])
        self.assertEqual(len(result.stderr.splitlines()), 3)
        self.assertIn('[ROJO]', result.stderr)
        self.assertIn('0/1', result.stderr)
        self.assertNotIn('\x1b', result.stderr)
        self.assertTrue((f.root / 'state/operaciones.jsonl').exists())
        quiet = subprocess.run([sys.executable, '-m', 'ved_sync', '--config', str(f.config), '--quiet'],
                               cwd=PROJECT, capture_output=True, text=True)
        self.assertTrue(json.loads(quiet.stdout)['simulation'])
        self.assertEqual(quiet.stderr, '')
        self.assertTrue((f.root / 'state/tiempo.csv').exists())
