"""First-run consent for Víctor Estrada Díaz's VED-SYNC, with simulated Git."""
import os
import shutil
import subprocess
import sys
import unittest

from tests import test_git_control


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Prueba con Git simulado en POSIX')
class GitFirstRunTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_git_control.GitControlTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        (self.fixture.project / '.git').rmdir()
        binary = self.fixture.root / 'bin/git'
        source = binary.read_text()
        marker = "if args[:2] == ['rev-parse', '--show-toplevel']:"
        source = source.replace(marker, "if args[0] == 'init':\n    (root / '.git').mkdir()\n" + marker)
        binary.write_text(source)

    def interactive(self, answer, *operation):
        code = '''
import runpy, sys
target = sys.argv[1]
sys.argv = sys.argv[1:]
sys.stdin.isatty = lambda: True
runpy.run_path(target, run_name='__main__')
'''
        return subprocess.run([sys.executable, '-c', code,
                               str(self.fixture.project / 'git_control.py'), *operation],
                              input=answer, cwd=self.fixture.root, env=self.fixture.env,
                              capture_output=True, text=True, timeout=15)

    def test_no_or_empty_answer_does_not_initialize_any_repository(self):
        for answer in ('n\n', '\n'):
            with self.subTest(answer=answer):
                result = self.interactive(answer, 'status')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('¿Quieres crear el repositorio Git', result.stdout)
                self.assertFalse((self.fixture.project / '.git').exists())
                self.assertEqual(self.fixture.calls(), [])
                self.assertEqual((self.fixture.parent / 'NO_MODIFICAR').read_text(), 'padre intacto')

    def test_yes_initializes_only_the_application_after_one_question(self):
        result = self.interactive('s\n', 'status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('¿Quieres crear el repositorio Git'), 1)
        self.assertTrue((self.fixture.project / '.git').is_dir())
        self.assertEqual([c['args'] for c in self.fixture.writes()], [['init', '.']])
        self.assertTrue(all(c['cwd'] == str(self.fixture.project) for c in self.fixture.calls()))
        self.assertEqual((self.fixture.parent / 'NO_MODIFICAR').read_text(), 'padre intacto')

    def test_closed_input_does_not_create_git(self):
        result = self.interactive('', 'status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.fixture.project / '.git').exists())
        self.assertEqual(self.fixture.calls(), [])

    def test_noninteractive_status_never_initializes_or_waits_for_input(self):
        result = self.fixture.run_script('status')
        self.assertEqual(result.returncode, 1)
        self.assertIn('menu', result.stderr)
        self.assertFalse((self.fixture.project / '.git').exists())
        self.assertEqual(self.fixture.calls(), [])

    def test_existing_repository_is_not_offered_creation_again(self):
        (self.fixture.project / '.git').mkdir()
        result = self.interactive('', 'status')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('¿Quieres crear el repositorio Git', result.stdout)
        self.assertEqual(self.fixture.writes(), [])

    def test_default_interactive_menu_asks_once_before_showing_operations(self):
        result = self.interactive('s\n0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('¿Quieres crear el repositorio Git'), 1)
        self.assertIn('Elija una operación', result.stdout)
        self.assertEqual([c['args'] for c in self.fixture.writes()], [['init', '.']])

    def test_initialization_failure_does_not_continue_with_git_operations(self):
        self.fixture.config['fail'] = {'init': 7}
        self.fixture.configure()
        result = self.interactive('s\n', 'status')
        self.assertEqual(result.returncode, 7)
        self.assertFalse((self.fixture.project / '.git').exists())
        self.assertEqual([c['args'] for c in self.fixture.calls()], [['init', '.']])
