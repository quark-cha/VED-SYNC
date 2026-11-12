"""Remote/project identity and guided setup for Víctor Estrada Díaz's projects."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from tests import test_git_control
from ved_sync.engine import PROJECT


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Git simulado en POSIX')
class GitProjectRemoteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_git_control.GitControlTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        original = self.fixture.project
        self.fixture.project = original.with_name('VED-SYNC')
        original.rename(self.fixture.project)

    def menu(self, answer):
        return subprocess.run(['bash', str(self.fixture.project / 'git.sh'), 'avanzado'],
                              input=answer, cwd=self.fixture.root, env=self.fixture.env,
                              capture_output=True, text=True, timeout=15)

    def test_unborn_branch_explains_the_commit_step_before_attempting_push(self):
        self.fixture.config['no_commits'] = True
        self.fixture.configure()
        result = self.fixture.run_script('push', '--autorizar')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('primer commit', result.stderr)
        self.assertIn('6', result.stderr)
        self.assertEqual(self.fixture.writes(), [])

    def test_menu_does_not_publish_staged_files_without_a_commit(self):
        self.fixture.config['no_commits'] = True
        self.fixture.configure()
        result = self.menu('7\n0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('primer commit', result.stdout)
        self.assertEqual(self.fixture.writes(), [])

    def test_other_project_urls_block_push_fetch_and_pull(self):
        self.fixture.config['url'] = 'https://github.com/cuenta/OTRO-PROYECTO.git'
        self.fixture.configure()
        for action in ('push', 'fetch', 'pull'):
            with self.subTest(action=action):
                result = self.fixture.run_script(action, '--autorizar')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("debe corresponder a 'VED-SYNC'", result.stderr)
        self.assertEqual(self.fixture.writes(), [])

    def test_a_different_push_url_cannot_publish_to_another_project(self):
        self.fixture.config['url'] = 'https://github.com/cuenta/VED-SYNC.git'
        self.fixture.config['push_url'] = 'git@github.com:cuenta/OTRO.git'
        self.fixture.configure()
        result = self.fixture.run_script('push', '--autorizar')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("debe corresponder a 'VED-SYNC'", result.stderr)
        self.assertEqual(self.fixture.writes(), [])

    def test_ssh_and_case_insensitive_repository_names_match_the_project(self):
        self.fixture.config['url'] = 'git@github.com:cuenta/ved-sync.git'
        self.fixture.configure()
        result = self.fixture.run_script('fetch', '--autorizar')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c['args'] for c in self.fixture.writes()], [['fetch', 'origin']])

    def test_menu_builds_origin_from_account_and_the_parent_directory_name(self):
        self.fixture.config['remotes'] = []
        self.fixture.configure()
        result = self.menu('10\ncuenta-autorizada\nAUTORIZAR\n0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c['args'] for c in self.fixture.writes()],
                         [['remote', 'add', 'origin', 'https://github.com/cuenta-autorizada/VED-SYNC.git']])
        self.assertTrue(all(c['cwd'] == str(self.fixture.project) for c in self.fixture.calls()))

    def test_remote_setup_cancelled_or_pointing_elsewhere_does_not_write(self):
        for answer in ('10\n\n0\n', '10\nhttps://github.com/cuenta/OTRO.git\n0\n',
                       '10\ncuenta\n\n0\n'):
            with self.subTest(answer=answer):
                result = self.menu(answer)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.fixture.writes(), [])

    def test_cli_remote_add_cannot_save_another_projects_url(self):
        result = self.fixture.run_script('remote', '--autorizar', 'add', 'origin',
                                         'https://github.com/cuenta/OTRO.git')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.fixture.writes(), [])

    def test_remote_setup_rejects_embedded_credentials(self):
        result = self.fixture.run_script('remote', '--autorizar', 'add', 'origin',
                                         'https://TOKEN_PRIVADO@github.com/cuenta/VED-SYNC.git')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('TOKEN_PRIVADO', result.stderr)
        self.assertEqual(self.fixture.writes(), [])

    def test_first_menu_push_sets_tracking_for_the_current_branch(self):
        self.fixture.config.update(no_upstream=True, branch='master')
        self.fixture.configure()
        result = self.menu('7\nAUTORIZAR\n0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c['args'] for c in self.fixture.writes()],
                         [['push', '--set-upstream', '--', 'origin', 'HEAD:refs/heads/master']])

    def test_missing_origin_can_be_configured_without_chaining_a_push(self):
        self.fixture.config['remotes'] = []
        self.fixture.configure()
        result = self.menu('7\ns\ncuenta\nAUTORIZAR\n0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c['args'] for c in self.fixture.writes()],
                         [['remote', 'add', 'origin', 'https://github.com/cuenta/VED-SYNC.git']])

    def test_controller_inside_proyecto_still_uses_its_parent_project_root(self):
        scripts = self.fixture.project / 'proyecto'
        scripts.mkdir()
        shutil.copyfile(PROJECT / 'git_control.py', scripts / 'git_control.py')
        result = subprocess.run([sys.executable, str(scripts / 'git_control.py'), 'status'],
                                cwd=self.fixture.root, env=self.fixture.env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Nombre del repositorio: VED-SYNC', result.stdout)
        self.assertTrue(all(c['cwd'] == str(self.fixture.project) for c in self.fixture.calls()))
