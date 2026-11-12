"""Explicit content exclusions in three fictitious repositories."""
import unittest
from unittest.mock import patch

from tests import test_engine


class ExclusionTests(unittest.TestCase):
    def setUp(self):
        self.f = test_engine.SyncTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.cfg['exclude_patterns'] = ['*.zip', 'hashes*.json', '__pycache__', '.venv']
        self.f.configure()
        self.f.put(0, 'contenido')

    def test_excluded_files_are_not_hashed_copied_or_reported_as_conflicts(self):
        for index, repo in enumerate(self.f.repos):
            for name in ('hashes.json', 'HASHES-v2.JSON', 'copia.ZIP'):
                (repo / name).write_text(str(index))
            (repo / '__pycache__').mkdir()
            (repo / '__pycache__/temporal.pyc').write_text(str(index))
        engine = self.f.engine()
        inspect = engine.cached_inspect
        with patch.object(engine, 'cached_inspect', wraps=inspect) as reads:
            report = engine.run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertTrue(all(call.args[0].name == 'f' for call in reads.call_args_list))
        self.assertEqual(set(engine.state['files']), {'f'})
        for index, repo in enumerate(self.f.repos):
            self.assertEqual((repo / 'hashes.json').read_text(), str(index))
        self.assertNotIn('conflict', [e['type'] for e in report['events']])

    def test_already_known_excluded_file_does_not_trigger_recovery(self):
        self.f.seed()
        engine = self.f.engine()
        engine.state['files']['hashes.json'] = {'head': '0' * 64, 'seen': {}}
        engine.state['files']['.test-runs/ficticio.txt'] = {'head': '0' * 64, 'seen': {}}
        engine.save()
        report = self.f.engine().run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertFalse(any(e.get('path') == 'hashes.json' for e in report['events']))
        self.assertFalse(any(e.get('path', '').startswith('.test-runs/') for e in report['events']))

    def test_explicit_copy_and_recovery_of_excluded_files_rejected(self):
        engine = self.f.engine()
        with self.assertRaises(ValueError):
            engine.copy(self.f.root / 'missing', self.f.repos[0] / 'a.zip', None, None, self.f.repos[0])
        with self.assertRaises(ValueError):
            engine.recover('a', 'hashes.json', '0' * 64)

    def test_relative_patterns_are_scoped_and_plain_json_is_kept(self):
        engine = self.f.engine()
        engine.exclude_patterns = ['CLASES/cache/*']
        self.assertTrue(engine.excluded('CLASES/cache/a.dat'))
        self.assertFalse(engine.excluded('OTRO/cache/a.dat'))
        self.assertFalse(engine.excluded('datos.json'))

    def test_root_marker_is_allowed_but_all_dot_prefixed_components_are_excluded(self):
        engine = self.f.engine()
        engine.exclude_patterns = []
        for relative in ('.gitignore', './.env', '.venv-comparacion/paquete.py',
                         'DEMUESTRA/.venv-comparacion/Lib/pip.py',
                         './carpeta/.oculto.txt', 'carpeta/.directorio/visible.txt'):
            with self.subTest(relative=relative):
                self.assertTrue(engine.excluded(relative))
        for relative in ('.', './', './archivo.py', './carpeta/archivo.py',
                         'carpeta/archivo.con.puntos.py'):
            with self.subTest(relative=relative):
                self.assertFalse(engine.excluded(relative))

    def test_hidden_files_and_directories_are_never_hashed_or_synchronized(self):
        hidden = ('.gitignore', '.oculto.txt', '.venv-comparacion/paquete.py',
                  'visible/.directorio/datos.txt', 'visible/.config')
        for index, repo in enumerate(self.f.repos):
            for relative in hidden:
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(index))
        engine = self.f.engine()
        with patch.object(engine, 'cached_inspect', wraps=engine.cached_inspect) as reads:
            report = engine.run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertTrue(all(call.args[0].name == 'f' for call in reads.call_args_list))
        self.assertEqual(set(engine.state['files']), {'f'})
        for index, repo in enumerate(self.f.repos):
            for relative in hidden:
                self.assertEqual((repo / relative).read_text(), str(index))

    def test_invalid_patterns_rejected(self):
        for value in ('*.zip', ['/absoluta'], ['../fuera'], [None], ['']):
            self.f.cfg['exclude_patterns'] = value
            self.f.configure()
            with self.assertRaises(ValueError):
                self.f.engine()
