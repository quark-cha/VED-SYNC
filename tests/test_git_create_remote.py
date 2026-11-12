"""Creación autorizada para el proyecto de Víctor Estrada Díaz; GitHub simulado.

Autoría y condiciones: https://estradad.es/licencia.php.
"""
import contextlib
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import git_control as control
from tests import test_git_control


class GithubCreationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('/tmp/PROYECTO')
        self.owner = 'usuario-prueba'
        self.token = 'gh' + 'p_' + 'A' * 36
        self.record = 'protocol=https\nhost=github.com\nusername=usuario-prueba\npassword=' + self.token + '\n\n'
        self.repo = SimpleNamespace(confirm=False, env={}, executable='/fake/git',
                                    run=Mock(return_value=SimpleNamespace(
                                        stdout='https://github.com/usuario-prueba/PROYECTO.git')))
        for target, value in [('ROOT', self.root), ('secure_access', []), ('check_publication', None)]:
            patcher = patch.object(control, target, value if target == 'ROOT' else Mock(return_value=value))
            started = patcher.start()
            self.addCleanup(patcher.stop)
            if target == 'check_publication':
                self.review = started
        self.credential = patch.object(control, 'git_credential', return_value=self.record).start()
        self.addCleanup(patch.stopall)
        self.out = io.StringIO()

    def api(self, method, path, token, payload=None):
        self.assertEqual(token, self.token)
        if (method, path) == ('GET', '/user'):
            return 200, {'login': self.owner}
        if (method, path) == ('GET', '/repos/usuario-prueba/PROYECTO'):
            return 404, {}
        if (method, path) == ('POST', '/user/repos'):
            return 201, {'full_name': self.owner + '/PROYECTO', 'private': payload['private']}
        self.fail('Petición inesperada')

    def choose(self, value, api=None):
        with patch.object(control, 'github_request', side_effect=api or self.api) as request, \
             patch('builtins.input', return_value=value) as question, contextlib.redirect_stdout(self.out):
            result = control.offer_github_creation(self.repo, 'origin')
        self.assertNotIn(self.token, self.out.getvalue())
        return result, request, question

    def test_private_choice_creates_only_an_empty_private_repository(self):
        result, request, question = self.choose('1')
        self.assertTrue(result)
        question.assert_called_once()
        self.assertIn('1 Privado | 2 Público | 0 No crear', question.call_args.args[0])
        post = request.call_args_list[-1]
        self.assertEqual(post.args, ('POST', '/user/repos', self.token,
                                     {'name': 'PROYECTO', 'private': True, 'auto_init': False}))
        self.review.assert_any_call(self.repo)
        self.review.assert_any_call(self.repo, history=True)

    def test_public_creation_requires_the_public_choice(self):
        result, request, _ = self.choose('2')
        self.assertTrue(result)
        self.assertIs(request.call_args_list[-1].args[3]['private'], False)
        self.assertIn('(público)', self.out.getvalue())

    def test_no_or_empty_never_creates_a_repository(self):
        for value in ('', '0', 'no'):
            with self.subTest(value=value):
                result, request, _ = self.choose(value)
                self.assertFalse(result)
                self.assertTrue(all(c.args[0] == 'GET' for c in request.call_args_list))

    def test_closed_input_cancels_without_creating(self):
        with patch.object(control, 'github_request', side_effect=self.api) as request, \
             patch('builtins.input', side_effect=EOFError), contextlib.redirect_stdout(self.out):
            self.assertFalse(control.offer_github_creation(self.repo, 'origin'))
        self.assertFalse(any(c.args[0] == 'POST' for c in request.call_args_list))

    def test_another_account_cannot_create_in_the_authors_account(self):
        self.owner = 'otra-cuenta'
        with self.assertRaises(control.GitError), \
             patch.object(control, 'github_request', side_effect=self.api) as request, \
             patch('builtins.input') as question, contextlib.redirect_stdout(self.out):
            control.offer_github_creation(self.repo, 'origin')
        self.assertEqual(request.call_count, 1)
        question.assert_not_called()

    def test_forbidden_response_is_not_claimed_to_be_a_missing_repository(self):
        def forbidden(method, path, token, payload=None):
            return (200, {'login': self.owner}) if path == '/user' else (403, {})
        with self.assertRaises(control.GitError), \
             patch.object(control, 'github_request', side_effect=forbidden) as request, \
             patch('builtins.input') as question, contextlib.redirect_stdout(self.out):
            control.offer_github_creation(self.repo, 'origin')
        question.assert_not_called()
        self.assertFalse(any(c.args[0] == 'POST' for c in request.call_args_list))

    def test_secret_detection_blocks_even_the_creation_lookup(self):
        self.review.side_effect = control.GitError('Secreto ficticio detectado')
        with self.assertRaises(control.GitError), patch.object(control, 'github_request') as request:
            control.offer_github_creation(self.repo, 'origin')
        self.credential.assert_not_called()
        request.assert_not_called()

    def test_existing_repository_is_reused_without_changing_visibility(self):
        def exists(method, path, token, payload=None):
            return (200, {'login': self.owner}) if path == '/user' else (200, {'private': True})
        result, request, question = self.choose('', exists)
        self.assertTrue(result)
        question.assert_not_called()
        self.assertFalse(any(c.args[0] == 'POST' for c in request.call_args_list))

    def test_visibility_mismatch_stops_before_retrying_push(self):
        def mismatch(method, path, token, payload=None):
            if method == 'POST':
                return 201, {'full_name': self.owner + '/PROYECTO', 'private': False}
            return self.api(method, path, token, payload)
        with self.assertRaises(control.GitError):
            self.choose('1', mismatch)

    def test_creation_error_does_not_leak_the_token(self):
        def denied(method, path, token, payload=None):
            return (422, {}) if method == 'POST' else self.api(method, path, token, payload)
        with self.assertRaises(control.GitError) as failure:
            self.choose('1', denied)
        self.assertNotIn(self.token, str(failure.exception) + self.out.getvalue())


class PushCreationTests(unittest.TestCase):
    def test_confirmed_creation_retries_the_same_push_once(self):
        repo = SimpleNamespace(confirm=True, run=Mock(side_effect=[control.RemoteNotFound('Ausente'), None]))
        with patch.object(control, 'offer_github_creation', return_value=True) as create, \
             contextlib.redirect_stdout(io.StringIO()):
            control.push_branch(repo, 'origin', 'refs/heads/master', set_upstream=True)
        create.assert_called_once_with(repo, 'origin')
        self.assertEqual(repo.run.call_count, 2)
        self.assertEqual(repo.run.call_args_list[0], repo.run.call_args_list[1])
        self.assertTrue(repo.confirm)

    def test_declining_creation_does_not_retry_or_change_anything(self):
        repo = SimpleNamespace(confirm=False, run=Mock(side_effect=control.RemoteNotFound('Ausente')))
        with patch.object(control, 'offer_github_creation', return_value=False), self.assertRaises(control.GitError):
            control.push_branch(repo, 'origin', 'refs/heads/master')
        self.assertEqual(repo.run.call_count, 1)

    def test_other_git_failures_do_not_offer_creation(self):
        repo = SimpleNamespace(confirm=False, run=Mock(side_effect=control.GitError('Error de red')))
        with patch.object(control, 'offer_github_creation') as create, self.assertRaises(control.GitError):
            control.push_branch(repo, 'origin', 'refs/heads/master')
        create.assert_not_called()

    def test_failed_retry_does_not_loop_or_repeat_the_question(self):
        repo = SimpleNamespace(confirm=False, run=Mock(side_effect=control.RemoteNotFound('Ausente')))
        with patch.object(control, 'offer_github_creation', return_value=True) as create, \
             self.assertRaises(control.RemoteNotFound), contextlib.redirect_stdout(io.StringIO()):
            control.push_branch(repo, 'origin', 'refs/heads/master')
        self.assertEqual(repo.run.call_count, 2)
        create.assert_called_once()


class CredentialTransportTests(unittest.TestCase):
    def test_credentials_are_captured_and_sent_to_git_only_over_stdin(self):
        repo = SimpleNamespace(executable='/fake/git', env={})
        token = 'gh' + 'p_' + 'B' * 36
        record = 'protocol=https\nhost=github.com\npassword=' + token + '\n\n'
        with patch.object(control.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='')) as run:
            control.git_credential(repo, [], 'approve', record)
        self.assertEqual(run.call_args.kwargs['input'], record)
        self.assertIs(run.call_args.kwargs['stdout'], subprocess.PIPE)
        self.assertNotIn(token, str(run.call_args.args))

    def test_api_token_is_only_in_the_header_and_redirects_are_refused(self):
        token = 'gh' + 'p_' + 'B' * 36
        response = Mock(status=201)
        response.read.return_value = json.dumps({'private': True}).encode()
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch.object(control, 'build_opener', return_value=opener):
            control.github_request('POST', '/user/repos', token,
                                   {'name': 'PROYECTO', 'private': True, 'auto_init': False})
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.github.com/user/repos')
        self.assertNotIn(token, request.full_url)
        self.assertNotIn(token.encode(), request.data)
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + token)
        self.assertIsNone(control.NoCredentialRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid'))


class PushDiagnosticTests(unittest.TestCase):
    def test_push_keeps_browser_instructions_visible_and_detects_repository_not_found(self):
        fixture = test_git_control.GitControlTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.config.update(fail={'push': 128})
        fixture.configure()
        executable = fixture.root / 'bin/git'
        executable.write_text(executable.read_text().replace(
            "if args[0] in cfg.get('fail', {}):",
            "if args[0] in cfg.get('fail', {}):\n    print('remote: Repository not found.', file=sys.stderr)"))
        with patch.object(control, 'ROOT', fixture.project), \
             patch.object(control, 'secure_access', return_value=[]), \
             patch.object(control, 'check_publication'), \
             contextlib.redirect_stderr(io.StringIO()) as output:
            repo = control.Repository()
            repo.executable = str(executable)
            repo.env = fixture.env
            with self.assertRaises(control.RemoteNotFound):
                repo.run('push', '--', 'origin', 'HEAD:refs/heads/main')
        self.assertIn('Repository not found', output.getvalue())
