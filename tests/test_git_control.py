"""Non-destructive script tests: Git writes/network are simulated, never executed."""
import hashlib
import json
import re
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from ved_sync.engine import PROJECT


def isolated_git_environment():
    """Do not inherit Git directories, trace files or configuration overrides."""
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull, GIT_OPTIONAL_LOCKS='0',
               GIT_TERMINAL_PROMPT='0', GIT_ALLOW_PROTOCOL='')
    return env


FAKE_GIT = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
root = Path.cwd()
args = sys.argv[1:]
raw = list(args)
while args:
    if args[0] == '--no-pager':
        args.pop(0)
    elif args[0] in ('-C', '-c'):
        args = args[2:]
    else:
        break
cfg = json.loads((root / 'fake-config.json').read_text())
with (root / 'fake-git.jsonl').open('a') as out:
    out.write(json.dumps({'args': args, 'raw': raw, 'cwd': str(root),
                          'git_dir': os.environ.get('GIT_DIR'),
                          'git_index': os.environ.get('GIT_INDEX_FILE')}) + '\n')
if args[0] in cfg.get('fail', {}):
    raise SystemExit(cfg['fail'][args[0]])
if args[0] == 'commit':
    cfg['no_commits'] = False
    cfg['commit_hash'] = 'def5678901234567890'
    (root / 'fake-config.json').write_text(json.dumps(cfg))
if args[:2] == ['rev-parse', '--show-toplevel']:
    print(cfg.get('top', str(root)))
elif args[0] == 'symbolic-ref':
    if cfg.get('detached'):
        raise SystemExit(1)
    print(cfg.get('branch', 'main'))
elif args[:2] == ['rev-parse', '--short']:
    print('abc1234')
elif args[:3] == ['rev-parse', '--verify', 'HEAD']:
    if cfg.get('no_commits'):
        raise SystemExit(1)
    print(cfg.get('commit_hash', 'abc1234'))
elif args[0] == 'rev-parse':
    if cfg.get('no_upstream'):
        raise SystemExit(1)
    print('origin/main')
elif args[0] == 'status':
    if '--porcelain' in args:
        if cfg.get('dirty'):
            print(' M README.md')
    else:
        print('## main...origin/main')
        if cfg.get('dirty'):
            print(' M README.md')
elif args[0] == 'diff':
    if '--quiet' in args:
        raise SystemExit(0 if cfg.get('no_changes') else 1)
    print('README.md | 1 +')
elif args[0] == 'ls-files':
    sys.stdout.write(''.join(p + '\0' for p in cfg.get('ignored', [])))
elif args[:2] == ['remote', 'get-url']:
    default = 'https://github.com/ficticio/' + root.name + '.git'
    print(cfg.get('push_url', cfg.get('url', default)) if '--push' in args else cfg.get('url', default))
elif args == ['remote']:
    for name in cfg.get('remotes', ['origin']):
        print(name)
elif args[0] == 'config':
    if args[-1] in ('user.name', 'user.email'):
        if cfg.get('missing_identity'):
            raise SystemExit(1)
        print('Prueba local' if args[-1] == 'user.name' else 'prueba@example.invalid')
        raise SystemExit(0)
    if cfg.get('no_upstream'):
        raise SystemExit(1)
    print('origin' if args[-1].endswith('.remote') else 'refs/heads/main')
elif args[0] == 'var':
    if cfg.get('missing_identity'):
        raise SystemExit(128)
    print('Prueba local <prueba@example.invalid> 1 +0000')
'''


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Prueba Bash con Git simulado en POSIX')
class GitControlTests(unittest.TestCase):
    def setUp(self):
        parent = PROJECT / '.test-runs'
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root / 'SRC VED ficticio'
        self.parent.mkdir()
        self.project = self.parent / 'VED-SYNC con espacios'
        self.project.mkdir()
        (self.parent / '.git').mkdir()
        (self.parent / 'NO_MODIFICAR').write_text('padre intacto')
        (self.project / '.git').mkdir()
        for name in ('git.sh', 'git.bat', 'git_control.py', '.gitignore'):
            shutil.copyfile(PROJECT / name, self.project / name)
        binary = self.root / 'bin'
        binary.mkdir()
        fake = binary / 'git'
        fake.write_text(FAKE_GIT)
        fake.chmod(0o755)
        self.env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ.get('PATH', ''))
        self.config = {}
        self.configure()

    def configure(self):
        (self.project / 'fake-config.json').write_text(json.dumps(self.config))

    def run_script(self, *args):
        return subprocess.run(['bash', str(self.project / 'git.sh'), *args], cwd=self.root,
                              env=self.env, text=True, capture_output=True)

    def calls(self):
        log = self.project / 'fake-git.jsonl'
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def writes(self):
        return [c for c in self.calls() if c['args'][0] in ('init', 'fetch', 'pull', 'add', 'commit', 'push')
                or c['args'][0] == 'remote' and len(c['args']) > 1
                and c['args'][1] not in ('show', 'get-url')]

    def test_default_checks_branch_changes_and_no_writes(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Rama actual: main', result.stdout)
        self.assertIn('cambios pendientes', result.stdout)
        self.assertIn('preparado', result.stdout)
        self.assertEqual(self.writes(), [])
        self.assertTrue(all(c['cwd'] == str(self.project) for c in self.calls()))
        self.assertEqual((self.parent / 'NO_MODIFICAR').read_text(), 'padre intacto')

    def test_parent_repository_is_never_used(self):
        (self.project / '.git').rmdir()
        result = self.run_script('status')
        self.assertEqual(result.returncode, 1)
        self.assertIn('No hay repositorio Git propio', result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual((self.parent / 'NO_MODIFICAR').read_text(), 'padre intacto')

    def test_root_mismatch_is_rejected(self):
        self.config['top'] = str(self.parent)
        self.configure()
        result = self.run_script('add', '--autorizar', '.')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.writes(), [])

    def test_every_mutation_requires_explicit_authorization(self):
        for action in ('init', 'fetch', 'pull', 'add', 'commit', 'push', 'remote'):
            with self.subTest(action=action):
                self.assertEqual(self.run_script(action).returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_add_previews_before_staging_and_uses_safe_path_separator(self):
        result = self.run_script('add', '--autorizar', 'ruta con espacios.txt')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.writes()[-1]['args'], ['add', '--', 'ruta con espacios.txt'])
        commands = [c['args'] for c in self.calls()]
        self.assertLess(commands.index(['status', '--short', '--branch']), commands.index(self.writes()[-1]['args']))
        self.assertTrue(any(c[:3] == ['diff', '--cached', '--stat'] for c in commands))

    def test_add_forcing_metadata_or_paths_outside_project_is_rejected(self):
        for args in (('-f', '.env'), ('../NO_MODIFICAR',), ('.git',)):
            with self.subTest(args=args):
                self.assertEqual(self.run_script('add', '--autorizar', *args).returncode, 2)
        self.assertEqual(self.writes(), [])

    def test_tracked_ignored_files_block_commit_and_push(self):
        self.config['ignored'] = ['.ved-sync-id', 'state/tiempo.csv']
        self.configure()
        for args in (('commit', '--autorizar', '-m', 'Mensaje'), ('push', '--autorizar')):
            self.assertNotEqual(self.run_script(*args).returncode, 0)
        self.assertEqual(self.writes(), [])

    def test_commit_is_only_explicit_and_does_not_stage_or_push(self):
        result = self.run_script('commit', '--autorizar', '-m', 'Mensaje con espacios')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c['args'] for c in self.writes()], [['commit', '-m', 'Mensaje con espacios']])
        self.assertEqual(self.run_script('commit', '--autorizar', '-am', 'No').returncode, 2)

    def test_pull_requires_clean_tree_and_only_fast_forward(self):
        result = self.run_script('pull', '--autorizar')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.writes()[-1]['args'], ['pull', '--ff-only'])
        self.config['dirty'] = True
        self.configure()
        before = len(self.writes())
        self.assertNotEqual(self.run_script('pull', '--autorizar').returncode, 0)
        self.assertEqual(len(self.writes()), before)

    def test_missing_remote_or_upstream_blocks_network_actions(self):
        self.config['remotes'] = []
        self.configure()
        self.assertNotEqual(self.run_script('fetch', '--autorizar').returncode, 0)
        self.config = {'no_upstream': True}
        self.configure()
        self.assertNotEqual(self.run_script('pull', '--autorizar').returncode, 0)
        self.assertNotEqual(self.run_script('push', '--autorizar').returncode, 0)
        self.assertEqual(self.writes(), [])

    def test_push_is_single_current_branch_no_implicit_other_refs(self):
        result = self.run_script('push', '--autorizar')
        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.writes()[-1]
        self.assertEqual(call['args'], ['push', '--', 'origin', 'HEAD:refs/heads/main'])
        self.assertIn('remote.origin.mirror=false', call['raw'])
        self.assertEqual([c['args'][0] for c in self.writes()], ['push'])

    def test_push_upstream_is_explicit_and_force_delete_or_other_branch_rejected(self):
        self.assertEqual(self.run_script('push', '--autorizar', '-u', 'origin', 'main').returncode, 0)
        self.assertIn('--set-upstream', self.writes()[-1]['args'])
        before = len(self.writes())
        for args in (('--force',), ('--delete', 'main'), ('-u',), ('origin', 'otra'), ('https://example.test/repo', 'main')):
            with self.subTest(args=args):
                self.assertNotEqual(self.run_script('push', '--autorizar', *args).returncode, 0)
        self.assertEqual(len(self.writes()), before)

    def test_detached_head_blocks_commit_pull_and_push(self):
        self.config['detached'] = True
        self.configure()
        for args in (('commit', '--autorizar', '-m', 'Mensaje'), ('pull', '--autorizar'), ('push', '--autorizar')):
            self.assertNotEqual(self.run_script(*args).returncode, 0)
        self.assertEqual(self.writes(), [])

    def test_git_failure_stops_sequence_and_preserves_exit_code(self):
        self.config['fail'] = {'diff': 7}
        self.configure()
        self.assertEqual(self.run_script('add', '--autorizar', '.').returncode, 7)
        self.assertEqual(self.writes(), [])

    def test_environment_cannot_redirect_git_to_parent_or_external_index(self):
        self.env['GIT_DIR'] = str(self.parent / '.git')
        self.env['GIT_INDEX_FILE'] = str(self.root / 'forbidden-index')
        self.assertEqual(self.run_script('status').returncode, 0)
        self.assertTrue(all(c['git_dir'] is None and c['git_index'] is None for c in self.calls()))
        self.assertFalse((self.root / 'forbidden-index').exists())

    def test_read_operations_and_remote_show_do_not_trigger_network(self):
        for action in ('diff', 'log'):
            self.assertEqual(self.run_script(action).returncode, 0)
        self.assertEqual(self.run_script('remote', '--autorizar', 'show', 'origin').returncode, 0)
        self.assertIn(['remote', 'show', '-n', 'origin'], [c['args'] for c in self.calls()])

    def test_both_entry_points_use_same_controller_and_bat_preserves_arguments(self):
        bat = (self.project / 'git.bat').read_text()
        shell = (self.project / 'git.sh').read_text()
        self.assertIn('%~dp0git_control.py', bat)
        self.assertIn('%*', bat)
        self.assertIn('exit /b %errorlevel%', bat)
        self.assertIn('$script_dir/git_control.py', shell)
        self.assertIn('"$@"', shell)
        self.assertEqual(subprocess.run(['bash', '-n', str(self.project / 'git.sh')], capture_output=True).returncode, 0)


    def test_menu_can_exit_without_mutation(self):
        result = subprocess.run(['bash', str(self.project / 'git.sh'), 'avanzado'], cwd=self.root,
                                env=self.env, input='0\n', text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Git de este proyecto exclusivamente', result.stdout)
        self.assertEqual(self.writes(), [])

    def test_menu_cancellation_never_stages_changes(self):
        result = subprocess.run(['bash', str(self.project / 'git.sh'), 'avanzado'], cwd=self.root,
                                env=self.env, input='5\n.\nNO\n0\n', text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Operación cancelada', result.stderr)
        self.assertEqual(self.writes(), [])

    def test_menu_requires_review_then_confirmation_for_one_commit_only(self):
        result = subprocess.run(['bash', str(self.project / 'git.sh'), 'avanzado'], cwd=self.root,
                                env=self.env, input='6\nMensaje probado\nAUTORIZAR\n0\n', text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c['args'] for c in self.writes()], [['commit', '-m', 'Mensaje probado']])
        self.assertLess(result.stdout.rfind('Resumen preparado'), result.stdout.index('Escriba AUTORIZAR'))

    def test_eof_in_menu_never_writes(self):
        result = subprocess.run(['bash', str(self.project / 'git.sh'), 'avanzado'], cwd=self.root,
                                env=self.env, input='', text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.writes(), [])


    def test_help_explains_scope_steps_and_limits_without_running_git(self):
        result = self.run_script('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        for text in ('No crea repositorios en GitHub', 'init inicializa únicamente Git local',
                     'Cómo preparar el primer envío', 'no activan suscripciones',
                     './git.sh diff', 'NOMBRE_RAMA', 'no se encadenan'):
            self.assertIn(text.lower(), result.stdout.lower())
        self.assertEqual(self.calls(), [])

    def test_help_needs_no_repository_and_ignores_write_examples(self):
        (self.project / '.git').rmdir()
        result = self.run_script('--help', 'push', '--autorizar')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('push --autorizar', result.stdout)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.project / '.git').exists())


class GitIgnoreTests(unittest.TestCase):
    def test_private_runtime_patterns_are_explicit(self):
        rules = (PROJECT / '.gitignore').read_text().splitlines()
        for pattern in ('.ved-sync-id', '.ved-sync-*', 'operaciones.jsonl', 'tiempo.csv',
                        '*.original', '*.log', '*.tmp', '.ved-sync/', '.test-runs/', '**/state.json', '**/run.lock', '**/versions/'):
            self.assertIn(pattern, rules)

    @unittest.skipUnless(shutil.which('git'), 'Git no está instalado: comprobación real de check-ignore pendiente')
    def test_git_check_ignore_in_disposable_repository(self):
        parent = PROJECT / '.test-runs'
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            shutil.copyfile(PROJECT / '.gitignore', root / '.gitignore')
            env = isolated_git_environment()
            subprocess.run(['git', 'init', '--template=', str(root)], cwd=root, env=env,
                           check=True, capture_output=True)
            names = ['.ved-sync-id', 'nested/.ved-sync-id', 'operaciones.jsonl', 'state/tiempo.csv',
                     'sub/a.original', '.ved-sync-stage', 'a.log', 'a.tmp', '.ved-sync/state.json',
                     'state/state.json', 'state/run.lock', 'state/versions/hash']
            result = subprocess.run(['git', '-C', str(root), 'check-ignore', '-z', '--stdin'],
                                    input='\0'.join(names) + '\0', cwd=root, env=env,
                                    text=True, capture_output=True, check=True)
            self.assertEqual(set(result.stdout.strip('\0').split('\0')), set(names))


@unittest.skipUnless(os.name == 'posix' and shutil.which('bash') and shutil.which('git'),
                     'Requiere Git real y Bash; solo se crean repositorios ficticios')
class RealGitScriptTests(unittest.TestCase):
    def setUp(self):
        parent = PROJECT / '.test-runs'
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root / 'SRC VED ficticio'
        self.project = self.parent / 'VED-SYNC con espacios'
        self.project.mkdir(parents=True)
        self.env = isolated_git_environment()
        # Real Git metadata belongs only to the disposable test tree.
        for directory in (self.parent, self.project):
            self.git(directory, 'init', '--template=', '.')
        self.git(self.project, 'symbolic-ref', 'HEAD', 'refs/heads/pruebas')
        for name in ('git.sh', 'git.bat', 'git_control.py', '.gitignore'):
            shutil.copyfile(PROJECT / name, self.project / name)
        (self.parent / 'NO_MODIFICAR').write_text('padre ficticio intacto')
        (self.project / 'datos.txt').write_text('contenido ficticio')
        self.parent_before = self.snapshot(self.parent / '.git')

    def git(self, root, *args):
        self.assertTrue(root == self.root or self.root in root.parents)
        self.assertNotIn(args[0], ('commit', 'push', 'pull', 'fetch'))
        result = subprocess.run(['git', '-C', str(root), *args], cwd=self.root, env=self.env,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    @staticmethod
    def snapshot(root):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file()}

    def run_entry(self, *args, controller=False, input=None):
        entry = [sys.executable, str(self.project / 'git_control.py')] if controller else [
            'bash', str(self.project / 'git.sh')]
        return subprocess.run([*entry, *args], cwd=self.root, env=self.env, input=input,
                              text=True, capture_output=True, timeout=15)

    def tearDown(self):
        self.assertEqual(self.snapshot(self.parent / '.git'), self.parent_before)
        self.assertEqual((self.parent / 'NO_MODIFICAR').read_text(), 'padre ficticio intacto')

    def test_real_status_and_diff_keep_metadata_unchanged_from_other_directory(self):
        before = self.snapshot(self.project / '.git')
        status = self.run_entry('status')
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn('Rama actual: pruebas', status.stdout)
        self.assertIn('datos.txt', status.stdout)
        self.assertEqual(self.run_entry('diff').returncode, 0)
        self.assertEqual(self.snapshot(self.project / '.git'), before)

    def test_real_add_respects_all_internal_exclusions_without_commit(self):
        internal = ['.ved-sync-id', 'nested/.ved-sync-id', 'operaciones.jsonl', 'state/tiempo.csv',
                    'sub/a.original', '.ved-sync-stage', 'a.log', 'a.tmp', '.ved-sync/state.json',
                    'state/state.json', 'state/run.lock', 'state/versions/hash']
        for name in internal:
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('dato privado ficticio')
        result = self.run_entry('add', '--autorizar', '.')
        self.assertEqual(result.returncode, 0, result.stderr)
        tracked = set(self.git(self.project, 'ls-files', '-z').strip('\0').split('\0'))
        self.assertIn('datos.txt', tracked)
        self.assertIn('.gitignore', tracked)
        self.assertTrue(tracked.isdisjoint(internal))
        self.assertFalse(any((self.project / '.git/refs/heads').iterdir()))
        self.assertFalse((self.project / '.git/logs/HEAD').exists())

    def test_real_parent_repository_is_rejected_if_project_git_is_absent(self):
        shutil.rmtree(self.project / '.git')  # Only metadata created by this fixture.
        result = self.run_entry('status')
        self.assertEqual(result.returncode, 1)
        self.assertIn('No hay repositorio Git propio', result.stderr)
        self.assertFalse((self.project / '.git').exists())

    def test_real_commands_without_authorization_leave_index_config_and_head_unchanged(self):
        before = self.snapshot(self.project / '.git')
        for action in ('init', 'fetch', 'pull', 'add', 'commit', 'push', 'remote'):
            with self.subTest(action=action):
                result = self.run_entry(action)
                self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.snapshot(self.project / '.git'), before)

    def test_real_menu_cancellation_does_not_stage_or_create_commits(self):
        before = self.snapshot(self.project / '.git')
        result = self.run_entry('avanzado', input='5\n.\nNO\n0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Operación cancelada', result.stderr)
        self.assertEqual(self.snapshot(self.project / '.git'), before)

    def test_bash_and_bat_share_controller_and_same_local_remote_configuration(self):
        # Configure an invalid test URL locally; there is no fetch or push.
        url = 'https://example.invalid/ved-sync-ficticio.git'
        self.git(self.project, 'config', '--local', 'remote.origin.url', url)
        before = self.snapshot(self.project / '.git')
        bat = (self.project / 'git.bat').read_text()
        targets = re.findall(r'^(?:py -3|python) "%~dp0([^"]+)" %\*$', bat, re.MULTILINE)
        self.assertEqual(targets, ['git_control.py', 'git_control.py'])
        for args in (('status',), ('remote', '--autorizar', 'get-url', 'origin')):
            with self.subTest(args=args):
                shell = self.run_entry(*args)
                common = self.run_entry(*args, controller=True)
                self.assertEqual(shell.returncode, 0, shell.stderr)
                self.assertEqual((shell.returncode, shell.stdout, shell.stderr),
                                 (common.returncode, common.stdout, common.stderr))
        self.assertIn(url, shell.stdout)
        self.assertEqual(self.snapshot(self.project / '.git'), before)
