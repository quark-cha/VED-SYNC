"""Protección local del proyecto de Víctor Estrada Díaz; sin credenciales reales.

Autoría y licencia: https://estradad.es/licencia.php.
"""
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import git_control
from tests import test_git_control


class PrivacyConfigurationTests(unittest.TestCase):
    def test_trace_variables_cannot_write_secrets_into_debug_logs(self):
        values = {'GIT_TRACE': 'trace.log', 'GIT_TRACE_CURL': 'curl.log',
                  'GIT_CURL_VERBOSE': '1', 'GCM_TRACE_SECRETS': '1', 'GH_DEBUG': 'api'}
        with patch.dict(os.environ, values):
            environment = git_control.environment()
        self.assertFalse(set(values) & set(environment))

    def test_manager_uses_the_protected_store_and_clears_other_helpers(self):
        repo = SimpleNamespace(env={'GCM_CREDENTIAL_STORE': 'plaintext'},
                               run=lambda *a, **kw: SimpleNamespace(stdout=''))
        with patch('git_control.shutil.which', return_value='/bin/git-credential-manager'):
            options = git_control.secure_access(repo)
        self.assertIn('credential.helper=', options)
        self.assertIn('credential.helper=manager', options)
        self.assertNotEqual(repo.env['GCM_CREDENTIAL_STORE'], 'plaintext')
        self.assertNotIn('credential.helper=store', options)
        self.assertIn('http.followRedirects=false', options)

    @unittest.skipUnless(os.name == 'posix', 'Caché de memoria de Git en POSIX')
    def test_missing_wallet_uses_memory_and_never_plaintext_storage(self):
        repo = SimpleNamespace(env={}, run=lambda *a, **kw: SimpleNamespace(stdout=''))
        with patch('git_control.shutil.which', return_value=None):
            options = git_control.secure_access(repo)
        self.assertIn('credential.helper=', options)
        self.assertIn('credential.helper=cache --timeout=900', options)
        self.assertNotIn('credential.helper=store', options)

    @unittest.skipUnless(os.name == 'posix', 'Caché de memoria de Git en POSIX')
    def test_oauth_opens_browser_after_checking_the_memory_cache(self):
        repo = SimpleNamespace(env={}, run=lambda *a, **kw: SimpleNamespace(stdout=''))
        def executable(name):
            return '/usr/bin/git-credential-oauth' if name == 'git-credential-oauth' else None
        with patch('git_control.shutil.which', side_effect=executable):
            options = git_control.secure_access(repo)
        self.assertLess(options.index('credential.helper=cache --timeout=900'),
                        options.index('credential.helper=oauth'))
        self.assertEqual(repo.env['GIT_TERMINAL_PROMPT'], '0')
        self.assertNotIn('credential.helper=store', options)

    def test_manager_does_not_chain_a_second_oauth_login(self):
        repo = SimpleNamespace(env={}, run=lambda *a, **kw: SimpleNamespace(stdout=''))
        with patch('git_control.shutil.which', return_value='/usr/bin/helper'):
            options = git_control.secure_access(repo)
        self.assertIn('credential.helper=manager', options)
        self.assertNotIn('credential.helper=oauth', options)

    def test_private_filename_policy_is_independent_of_gitignore(self):
        for name in ['.env', 'nested/.env.local', '.git-credentials', '.gitconfig',
                     '.ssh/id_ed25519', '.aws/credentials', 'config/credentials.json', 'private.pem']:
            with self.subTest(name=name):
                self.assertTrue(git_control.private_path(name))
        self.assertFalse(git_control.private_path('.env.example'))
        self.assertFalse(git_control.private_path('config/example.json'))

    def test_known_secret_formats_are_detected_without_echoing_the_value(self):
        values = [('gh' + 'p_' + 'A' * 36).encode(),
                  ('github_' + 'pat_' + 'B' * 50).encode(),
                  ('-----BEGIN ' + 'OPENSSH PRIVATE KEY-----').encode(),
                  ('https://' + 'someone:secret@example.invalid/repo.git').encode()]
        for value in values:
            with self.subTest(format=value[:3]):
                with self.assertRaises(git_control.GitError) as error:
                    git_control.check_secret(value)
                self.assertNotIn(value.decode(), str(error.exception))

    def test_source_has_no_default_login_or_default_commit_author(self):
        source = Path(git_control.__file__).read_text()
        self.assertNotIn('DEFAULT_ACCOUNT', source)
        self.assertNotIn('/mnt/windows', source)
        self.assertNotIn('Nombre del autor [', source)


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash') and shutil.which('git'),
                     'Git y Bash; sólo repositorios locales desechables')
class RealGitPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_git_control.RealGitScriptTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.env['GIT_ALLOW_PROTOCOL'] = 'file'
        self.token = 'gh' + 'p_' + 'A' * 36
        self.raw_git('config', '--local', 'user.name', 'Prueba local')
        self.raw_git('config', '--local', 'user.email', 'prueba@example.invalid')

    def raw_git(self, *args):
        result = subprocess.run(['git', '-C', str(self.fixture.project), *args],
                                env=self.fixture.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def assert_not_disclosed(self, result):
        self.assertNotIn(self.token, result.stdout + result.stderr)
        self.assertNotIn('[SUBIDA COMPLETADA]', result.stdout)

    def test_ordinary_add_leaves_credential_files_outside_the_index(self):
        for name in ['.env', '.git-credentials', 'private.key', 'credentials.json']:
            (self.fixture.project / name).write_text(self.token)
        result = self.fixture.run_entry('add', '--autorizar', '.')
        self.assertEqual(result.returncode, 0, result.stderr)
        names = self.raw_git('ls-files').splitlines()
        self.assertFalse(any(git_control.private_path(name) for name in names))
        self.assert_not_disclosed(result)

    def test_token_in_an_unrelated_file_is_blocked_before_staging(self):
        (self.fixture.project / 'notas.txt').write_text(self.token)
        before = self.fixture.snapshot(self.fixture.project / '.git')
        result = self.fixture.run_entry('add', '--autorizar', '.')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.fixture.snapshot(self.fixture.project / '.git'), before)
        self.assert_not_disclosed(result)

    def test_secret_already_staged_cannot_be_committed(self):
        (self.fixture.project / 'notas.txt').write_text(self.token)
        self.raw_git('add', 'notas.txt')
        result = self.fixture.run_entry('commit', '--autorizar', '-m', 'Prueba')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assert_not_disclosed(result)

    def test_secret_in_a_commit_message_is_blocked(self):
        self.raw_git('add', 'datos.txt')
        result = self.fixture.run_entry('commit', '--autorizar', '-m', self.token)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assert_not_disclosed(result)

    def test_deleting_a_secret_does_not_allow_its_history_to_be_pushed(self):
        path = self.fixture.project / 'notas.txt'
        path.write_text(self.token)
        self.raw_git('add', 'notas.txt')
        self.raw_git('commit', '-m', 'Commit desechable con dato ficticio')
        path.write_text('Contenido ya limpio')
        self.raw_git('add', 'notas.txt')
        self.raw_git('commit', '-m', 'Dato retirado del archivo actual')
        self.assert_history_push_blocked()

    def test_private_file_in_old_history_is_blocked_even_without_a_known_token(self):
        path = self.fixture.project / '.env'
        path.write_text('VARIABLE=valor-ficticio')
        self.raw_git('add', '-f', '.env')
        self.raw_git('commit', '-m', 'Archivo privado ficticio')
        path.unlink()
        self.raw_git('add', '-u')
        self.raw_git('commit', '-m', 'Archivo retirado')
        self.assert_history_push_blocked()

    def assert_history_push_blocked(self):
        remote = self.fixture.root / 'remote' / (self.fixture.project.name + '.git')
        remote.parent.mkdir()
        self.fixture.git(remote.parent, 'init', '--bare', '--template=', str(remote))
        self.raw_git('remote', 'add', 'origin', str(remote))
        result = self.fixture.run_entry('push', '--autorizar', '-u', 'origin', 'pruebas')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assert_not_disclosed(result)
        refs = subprocess.run(['git', '--git-dir', str(remote), 'show-ref'],
                              env=self.fixture.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(refs.returncode, 1, refs.stderr)
        self.assertEqual(refs.stdout, '')

    def tearDown(self):
        self.assertEqual(self.fixture.snapshot(self.fixture.parent / '.git'), self.fixture.parent_before)
