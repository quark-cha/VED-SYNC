"""Project-directory Git entries for Víctor Estrada Díaz's VED-SYNC."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from tests import test_git_control
from ved_sync.engine import PROJECT


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Prueba Bash en POSIX')
class ProjectScriptsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_git_control.GitControlTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.scripts = self.fixture.project / 'proyecto'
        self.scripts.mkdir()
        for name in ('git.sh', 'git.bat'):
            shutil.copyfile(PROJECT / 'proyecto' / name, self.scripts / name)

    def run_script(self, *args):
        return subprocess.run(['bash', str(self.scripts / 'git.sh'), *args],
                              cwd=self.fixture.root, env=self.fixture.env,
                              capture_output=True, text=True, timeout=15)

    def test_launch_from_another_directory_uses_the_application_git_root(self):
        result = self.run_script('status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.fixture.calls())
        self.assertTrue(all(c['cwd'] == str(self.fixture.project) for c in self.fixture.calls()))
        self.assertEqual(self.fixture.writes(), [])
        self.assertEqual((self.fixture.parent / 'NO_MODIFICAR').read_text(), 'padre intacto')

    def test_neither_src_ved_nor_the_tooling_directory_git_can_be_used_as_fallback(self):
        (self.fixture.project / '.git').rmdir()
        (self.scripts / '.git').mkdir()
        result = self.run_script('status')
        self.assertEqual(result.returncode, 1)
        self.assertIn('No hay repositorio Git propio', result.stderr)
        self.assertEqual(self.fixture.calls(), [])

    def test_authorization_and_arguments_with_spaces_reach_the_shared_controller(self):
        result = self.run_script('add', 'ruta con espacios.txt')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.fixture.writes(), [])
        (self.fixture.project / 'ruta con espacios.txt').write_text('contenido de prueba')
        result = self.run_script('add', '--autorizar', 'ruta con espacios.txt')
        self.assertEqual(result.returncode, 0, result.stderr)
        adds = [c['args'] for c in self.fixture.writes() if c['args'][0] == 'add']
        self.assertEqual(adds, [['add', '--', 'ruta con espacios.txt']])

    def test_help_and_both_windows_launchers_use_the_shared_application_controller(self):
        result = self.run_script('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fixture.calls(), [])
        bat = (self.scripts / 'git.bat').read_text()
        self.assertIn('py -3 "%~dp0..\\git_control.py" %*', bat)
        self.assertIn('python "%~dp0..\\git_control.py" %*', bat)
        self.assertEqual(bat.count('exit /b %errorlevel%'), 2)
