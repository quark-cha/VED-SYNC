"""Discovery only: fictitious folders, mocked mounts; never run a sync cycle."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from ved_sync.engine import Engine, PROJECT


class USBDiscoveryTests(unittest.TestCase):
    def setUp(self):
        parent = PROJECT / '.test-runs'
        parent.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mounts = self.root / 'media'
        self.mounts.mkdir()
        self.identity = str(uuid.uuid4())
        self.usb = {'id': '3', 'paths': [], 'device_type': 'usb',
                    'search_roots': [str(self.mounts)],
                    'mounted_subdirectory': 'SRC-VED', 'uuid': self.identity}

    def engine(self):
        config = self.root / 'config.json'
        config.write_text(json.dumps({'state_dir': str(self.root / 'control'),
            'repositories': [{'id': '1', 'path': str(self.root / 'one')},
                             {'id': '2', 'path': str(self.root / 'two')}, self.usb]}))
        return Engine(config)

    def volume(self, name, identity=None):
        mount = self.mounts / name
        repo = mount / 'SRC-VED'
        repo.mkdir(parents=True)
        if identity:
            (repo / '.ved-sync-id').write_text(identity + '\n')
        return mount, repo

    def test_no_uuid_never_selects_any_usb(self):
        self.usb['uuid'] = None
        self.volume('USB', self.identity)
        with patch('ved_sync.engine.os.path.ismount', return_value=True):
            engine = self.engine()
            self.assertNotIn('3', engine.available())
            self.assertEqual(engine.status['3'], 'gris')

    def test_unmounted_matching_folder_stays_gray(self):
        self.volume('USB', self.identity)
        with patch('ved_sync.engine.os.path.ismount', return_value=False):
            engine = self.engine()
            self.assertNotIn('3', engine.available())
            self.assertEqual(engine.status['3'], 'gris')

    def test_reconnect_and_mount_rename_preserve_identity(self):
        mount, repo = self.volume('ANTES', self.identity)
        with patch('ved_sync.engine.os.path.ismount', side_effect=lambda p: p.parent == self.mounts):
            engine = self.engine()
            self.assertEqual(engine.available()['3'], repo)
            moved = self.mounts / 'DESPUES'
            mount.rename(moved)
            self.assertEqual(engine.available()['3'], moved / 'SRC-VED')
            with patch('ved_sync.engine.os.path.ismount', return_value=False):
                self.assertNotIn('3', engine.available())
            self.assertEqual(engine.available()['3'], moved / 'SRC-VED')

    def test_wrong_or_absent_identity_never_enrolls(self):
        self.volume('AJENO', str(uuid.uuid4()))
        _, empty = self.volume('VACIO')
        with patch('ved_sync.engine.os.path.ismount', return_value=True):
            engine = self.engine()
            self.assertNotIn('3', engine.available())
        self.assertFalse((empty / '.ved-sync-id').exists())

    def test_duplicate_identity_blocks_selection(self):
        self.volume('A', self.identity)
        self.volume('B', self.identity)
        with patch('ved_sync.engine.os.path.ismount', return_value=True):
            engine = self.engine()
            self.assertNotIn('3', engine.available())
            self.assertEqual(engine.status['3'], 'rojo')

    def test_symlink_mount_not_followed(self):
        mount, _ = self.volume('REAL', self.identity)
        link = self.mounts / 'ENLACE'
        link.symlink_to(mount, target_is_directory=True)
        with patch('ved_sync.engine.os.path.ismount', side_effect=lambda p: p == link):
            self.assertNotIn('3', self.engine().available())

    def test_reject_parent_traversal(self):
        self.usb['mounted_subdirectory'] = '../SRC-VED'
        with self.assertRaises(ValueError):
            self.engine()
