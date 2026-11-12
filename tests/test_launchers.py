"""Start scripts are tested only against temporary fictitious repositories."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from ved_sync.engine import PROJECT
from tests import test_engine


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Requiere Bash para probar el lanzador Ubuntu')
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.f = test_engine.SyncTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def run_launcher(self, *args):
        return subprocess.run(['bash', str(PROJECT / 'run.sh'), *args], cwd=self.f.root,
                              capture_output=True, text=True, timeout=15)

    def test_default_simulation_once_from_another_directory(self):
        self.f.put(0, 'demo')
        result = self.run_launcher('--once', '--config', str(self.f.config), '--quiet')
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['simulation'])
        self.assertFalse((self.f.repos[1] / 'f').exists())
        self.assertFalse((self.f.repos[0] / '.ved-sync-id').exists())

    def test_explicit_apply_only_on_fixture_repositories(self):
        self.f.put(2, 'demo')
        result = self.run_launcher('--once', '--config', str(self.f.config), '--apply', '--quiet')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.f.contents(), ['demo'] * 3)
        self.assertEqual(set(json.loads(result.stdout)['status'].values()), {'verde'})

    def test_argument_forwarding_and_script_location_with_spaces(self):
        project = self.f.root / 'VED SYNC de prueba'
        project.mkdir()
        shutil.copyfile(PROJECT / 'run.sh', project / 'run.sh')
        binary = self.f.root / 'bin'
        binary.mkdir()
        python = binary / 'python3'
        python.write_text('#!' + sys.executable + '\nimport json, os, sys\nprint(json.dumps({"cwd": os.getcwd(), "args": sys.argv[1:]}))\n')
        python.chmod(0o755)
        env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ.get('PATH', ''))
        result = subprocess.run(['bash', str(project / 'run.sh'), '--config', 'config con espacios.json', '--once'],
                                cwd=self.f.root, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['cwd'], str(project))
        self.assertEqual(data['args'], ['-m', 'ved_sync', '--watch', '--config', 'config con espacios.json', '--once'])

    def test_help_does_not_start_synchronization(self):
        before = list(self.f.root.iterdir())
        result = self.run_launcher('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--once', result.stdout)
        for text in ('Uso:', 'Qué hace', 'Cómo ejecutar', 'Qué modifica',
                     './run.sh --once --apply', 'repositorios ficticios',
                     'simulation: false', 'no publica código'):
            self.assertIn(text, result.stdout)
        self.assertEqual(before, list(self.f.root.iterdir()))

    def test_windows_and_ubuntu_select_same_module_and_safe_defaults(self):
        bat = (PROJECT / 'run.bat').read_text()
        shell = (PROJECT / 'run.sh').read_text()
        self.assertIn('cd /d "%~dp0"', bat)
        self.assertIn('py -3 -m ved_sync --watch %*', bat)
        self.assertIn('python -m ved_sync --watch %*', bat)
        self.assertIn('exit /b %errorlevel%', bat)
        self.assertIn('cd -- "$script_dir"', shell)
        self.assertIn('exec python3 -m ved_sync --watch "$@"', shell)
        # Examples in comments must not be confused with the actual default command.
        bat_commands = '\n'.join(line for line in bat.splitlines()
                                 if not line.lstrip().lower().startswith('rem '))
        shell_commands = '\n'.join(line for line in shell.splitlines()
                                   if not line.lstrip().startswith('#'))
        self.assertNotIn('--apply', bat_commands)
        self.assertNotIn('--apply', shell_commands)
        for name in ('run.sh', 'git.sh'):
            self.assertEqual(subprocess.run(['bash', '-n', str(PROJECT / name)], capture_output=True).returncode, 0)

    def test_help_with_apply_flag_does_not_create_ids_state_or_copies(self):
        self.f.put(0, 'contenido ficticio')
        result = self.run_launcher('--config', str(self.f.config), '--apply', '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('simulación', result.stdout)
        self.assertFalse((self.f.root / 'state').exists())
        self.assertFalse((self.f.repos[1] / 'f').exists())
        self.assertTrue(all(not (root / '.ved-sync-id').exists() for root in self.f.repos))
