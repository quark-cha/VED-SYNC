"""One-operation Git workflow for Víctor Estrada Díaz, tested without GitHub."""
import os
import shutil
import subprocess
import unittest

from tests import test_git_control


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Bash y Git simulado')
class GitUploadTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_git_control.GitControlTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def menu(self, answer):
        return subprocess.run(['bash', str(self.fixture.project / 'git.sh'), 'menu'],
                              input=answer, cwd=self.fixture.root, env=self.fixture.env,
                              capture_output=True, text=True, timeout=15)

    def test_blank_input_exits_instead_of_repeating_invalid_option(self):
        result = self.menu('\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('Elija una operación'), 1)
        self.assertEqual(self.fixture.writes(), [])

    def test_option_two_prepares_creates_commit_and_pushes_in_order(self):
        self.fixture.config['no_commits'] = True
        self.fixture.configure()
        result = self.menu('2\nPrimer commit\ns\n5\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c['args'][0] for c in self.fixture.writes()], ['add', 'commit', 'push'])
        self.assertIn('[COMMIT CREADO] def567890123', result.stdout)
        self.assertIn('[SUBIDA COMPLETADA]', result.stdout)
        self.assertTrue(all(c['cwd'] == str(self.fixture.project) for c in self.fixture.calls()))

    def test_missing_origin_asks_for_the_current_users_account_and_project_name(self):
        self.fixture.config.update(no_commits=True, remotes=[])
        self.fixture.configure()
        result = self.menu('2\ncuenta-ficticia\nPrimer commit\ns\n5\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        writes = self.fixture.writes()
        self.assertEqual([c['args'][0] for c in writes], ['remote', 'add', 'commit', 'push'])
        self.assertIn('https://github.com/cuenta-ficticia/', writes[0]['args'][-1])
        self.assertIn('[SUBIDA COMPLETADA]', result.stdout)

    def test_declining_cancels_the_entire_operation_before_any_write(self):
        result = self.menu('2\nPrueba\nn\n5\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fixture.writes(), [])
        self.assertNotIn('[COMMIT CREADO]', result.stdout)

    def test_commit_failure_stops_before_push_and_reports_no_commit(self):
        self.fixture.config.update(no_commits=True, fail={'commit': 7})
        self.fixture.configure()
        result = self.menu('2\nPrueba\ns\n5\n')
        self.assertEqual([c['args'][0] for c in self.fixture.writes()], ['add', 'commit'])
        self.assertIn('[NO SE HA CREADO NINGÚN COMMIT]', result.stdout)
        self.assertNotIn('[SUBIDA COMPLETADA]', result.stdout)

    def test_push_failure_reports_the_created_commit_as_local_not_uploaded(self):
        self.fixture.config.update(no_commits=True, fail={'push': 9})
        self.fixture.configure()
        result = self.menu('2\nPrueba\ns\n5\n')
        self.assertIn('[COMMIT CREADO Y CONSERVADO LOCALMENTE]', result.stdout)
        self.assertIn('[SUBIDA NO COMPLETADA]', result.stderr)
        self.assertNotIn('[SUBIDA COMPLETADA]', result.stdout)

    def test_no_new_changes_retries_push_without_creating_an_empty_commit(self):
        self.fixture.config['no_changes'] = True
        self.fixture.configure()
        result = self.menu('2\nPrueba\ns\n5\n')
        self.assertEqual([c['args'][0] for c in self.fixture.writes()], ['add', 'push'])
        self.assertIn('[SIN CAMBIOS NUEVOS]', result.stdout)
        self.assertIn('[SUBIDA COMPLETADA]', result.stdout)

    def test_other_project_remote_is_rejected_before_staging_or_committing(self):
        self.fixture.config['url'] = 'https://github.com/cuenta-ficticia/OTRO.git'
        self.fixture.configure()
        result = self.menu('2\n5\n')
        self.assertEqual(self.fixture.writes(), [])
        self.assertIn('[SUBIDA NO COMPLETADA]', result.stderr)

    def test_missing_identity_is_requested_and_configured_only_in_the_project(self):
        self.fixture.config['missing_identity'] = True
        self.fixture.configure()
        result = self.menu('2\nPrueba local\nprueba@example.invalid\ns\nPrimer commit\ns\n5\n')
        calls = [c['args'] for c in self.fixture.calls()]
        self.assertIn(['config', '--local', 'user.name', 'Prueba local'], calls)
        self.assertIn(['config', '--local', 'user.email', 'prueba@example.invalid'], calls)
        self.assertFalse(any('--global' in c for c in calls))
        self.assertIn('[SUBIDA COMPLETADA]', result.stdout)
        self.assertIn('Identidad guardada', result.stdout)
        self.assertIn('identifican al autor de cada commit', result.stdout)
        self.assertIn('no es una contraseña', result.stdout)

    def test_declining_does_not_save_the_requested_identity(self):
        self.fixture.config['missing_identity'] = True
        self.fixture.configure()
        result = self.menu('2\nPrueba local\nprueba@example.invalid\ns\nPrimer commit\nn\n5\n')
        self.assertIn('Operación cancelada', result.stdout)
        calls = [c['args'] for c in self.fixture.calls()]
        self.assertFalse(any(c[:2] == ['config', '--local'] for c in calls))
        self.assertEqual(self.fixture.writes(), [])

    def test_configured_identity_is_reused_and_its_purpose_explained(self):
        result = self.menu('2\nPrueba\ns\n5\n')
        self.assertIn('Se reutilizará la identidad configurada en Git', result.stdout)
        self.assertIn('identifican al autor de cada commit', result.stdout)
        self.assertNotIn('¿Guardar y reutilizar', result.stdout)
        self.assertNotIn('Correo para los commits de este proyecto:', result.stdout)


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash') and shutil.which('git'),
                     'Requiere Git y Bash; sólo usa repositorios locales desechables')
class RealGitUploadTests(unittest.TestCase):
    def test_first_commit_and_push_reach_the_local_remote_with_identical_content(self):
        fixture = test_git_control.RealGitScriptTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.env['GIT_ALLOW_PROTOCOL'] = 'file'
        remote = fixture.root / 'remote' / (fixture.project.name + '.git')
        remote.parent.mkdir()
        fixture.git(remote.parent, 'init', '--bare', '--template=', str(remote))
        fixture.git(fixture.project, 'remote', 'add', 'origin', str(remote))

        result = fixture.run_entry('menu', input='2\nPrueba local\nprueba@example.invalid\ns\nPrimer commit de prueba\ns\n5\n')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('[COMMIT CREADO]', result.stdout)
        self.assertIn('[SUBIDA COMPLETADA]', result.stdout)
        local_head = fixture.git(fixture.project, 'rev-parse', 'HEAD').strip()
        remote_head = fixture.git(remote, 'rev-parse', 'refs/heads/pruebas').strip()
        self.assertEqual(local_head, remote_head)
        self.assertEqual(fixture.git(fixture.project, 'config', '--local', '--get', 'user.name').strip(),
                         'Prueba local')
        self.assertEqual(fixture.git(fixture.project, 'config', '--local', '--get', 'user.email').strip(),
                         'prueba@example.invalid')
        remote_content = fixture.git(remote, 'show', 'refs/heads/pruebas:datos.txt')
        self.assertEqual(remote_content, 'contenido ficticio')
        self.assertEqual(fixture.git(fixture.project, 'status', '--porcelain'), '')
        self.assertEqual(fixture.snapshot(fixture.parent / '.git'), fixture.parent_before)

        repeated = fixture.run_entry('menu', input='2\nReintento\ns\n5\n')
        self.assertIn('Se reutilizará la identidad configurada en Git', repeated.stdout)
        self.assertNotIn('Correo para los commits de este proyecto:', repeated.stdout)
        self.assertIn('[SUBIDA COMPLETADA]', repeated.stdout)
        self.assertEqual(fixture.git(fixture.project, 'rev-parse', 'HEAD').strip(), local_head)

    def test_one_time_identity_creates_and_pushes_without_saving_configuration(self):
        fixture = test_git_control.RealGitScriptTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.env['GIT_ALLOW_PROTOCOL'] = 'file'
        remote = fixture.root / 'remote' / (fixture.project.name + '.git')
        remote.parent.mkdir()
        fixture.git(remote.parent, 'init', '--bare', '--template=', str(remote))
        fixture.git(fixture.project, 'remote', 'add', 'origin', str(remote))

        result = fixture.run_entry('menu', input='2\nPrueba temporal\ntemporal@example.invalid\nn\nCommit temporal\ns\n5\n')

        self.assertIn('[SUBIDA COMPLETADA]', result.stdout, result.stderr)
        self.assertIn('Identidad sólo para esta ejecución', result.stdout)
        author = fixture.git(fixture.project, 'log', '-1', '--format=%an <%ae>').strip()
        self.assertEqual(author, 'Prueba temporal <temporal@example.invalid>')
        for key in ('user.name', 'user.email'):
            configuration = subprocess.run(['git', '-C', str(fixture.project), 'config', '--local', '--get', key],
                                           env=fixture.env, capture_output=True, text=True)
            self.assertEqual(configuration.returncode, 1, configuration.stderr)
        self.assertEqual(fixture.snapshot(fixture.parent / '.git'), fixture.parent_before)
