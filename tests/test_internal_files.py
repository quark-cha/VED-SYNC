"""Read-only scans of fictitious trees; no synchronizer or Git is started."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ved_sync.engine import Engine, PROJECT, inspect
from ved_sync.identity import IDENTITY_FILE, INTERNAL_FILES, LOCAL_CONFIG_FILE, is_internal


class LocalFilesTests(unittest.TestCase):
    def setUp(self):
        parent = PROJECT / '.test-runs'
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_three_fictitious_repositories_keep_private_config_and_git_out_of_scan(self):
        for index in range(3):
            with self.subTest(repository=index):
                root = self.root / str(index)
                root.mkdir()
                (root / 'datos.txt').write_text('contenido normal')
                (root / LOCAL_CONFIG_FILE).write_text(json.dumps({'local': index}))
                (root / IDENTITY_FILE).write_text('identidad privada')
                if index == 1:
                    (root / '.git').write_text('gitdir: ruta-local')
                else:
                    (root / '.git').mkdir()
                    (root / '.git/HEAD').write_text('ref: refs/heads/pruebas')
                nested = root / 'sub'
                nested.mkdir()
                (nested / LOCAL_CONFIG_FILE).write_text('configuración anidada')
                (nested / 'normal.txt').write_text('otro contenido')
                for base in (root / '.test-runs', nested / '.TEST-RUNS'):
                    base.mkdir()
                    (base / 'ficticio.txt').write_text('dato de prueba que no se sincroniza')
                engine = Engine.__new__(Engine)
                engine.restore_projects = False
                engine.monitor = SimpleNamespace(active=False, emit=Mock())
                engine.cached_inspect = Mock(wraps=inspect)
                scanned = engine.scan(root)  # Read only; __init__ and run_once are never called.
                self.assertEqual(set(scanned), {'datos.txt', 'sub/normal.txt'})
                self.assertEqual(engine.cached_inspect.call_count, 2)
                self.assertEqual(json.loads((root / LOCAL_CONFIG_FILE).read_text()), {'local': index})

    def test_copy_guard_rejects_private_config_and_git_before_any_io(self):
        root = self.root / 'repo'
        root.mkdir()
        engine = Engine.__new__(Engine)
        engine.check_write = Mock(side_effect=AssertionError('No debe alcanzarse la escritura'))
        for relative in (LOCAL_CONFIG_FILE, 'sub/' + LOCAL_CONFIG_FILE, '.git/HEAD', '.git',
                         '.test-runs/ficticio.txt', 'sub/.TEST-RUNS/ficticio.txt'):
            with self.subTest(path=relative), self.assertRaises(ValueError):
                engine.copy(self.root / 'inexistente', root / relative, None, None, root)
        engine.check_write.assert_not_called()
        self.assertEqual(list(root.iterdir()), [])

    def test_private_name_is_explicitly_excluded_from_git_and_sync(self):
        self.assertIn(LOCAL_CONFIG_FILE, INTERNAL_FILES)
        self.assertTrue(is_internal(LOCAL_CONFIG_FILE))
        self.assertTrue(is_internal('.git'))
        self.assertIn(LOCAL_CONFIG_FILE, (PROJECT / '.gitignore').read_text().splitlines())
        self.assertFalse(is_internal('config.json'))  # Other portable configuration remains ordinary content.
