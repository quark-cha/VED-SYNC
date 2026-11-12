import json
import uuid
import unittest
from unittest.mock import patch
from tests import test_engine
from ved_sync.identity import IDENTITY_FILE, read_identity, repository_identity

class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.f = test_engine.SyncTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def ids(self):
        return [read_identity(p) for p in self.f.repos]

    def test_unique_creation_persistence_no_content_changes(self):
        self.assertEqual(self.f.engine().run_once()['events'], [])
        ids = self.ids()
        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(all(uuid.UUID(i).version == 4 for i in ids))
        self.assertEqual(self.f.engine().run_once()['events'], [])
        self.assertEqual(self.ids(), ids)
        self.assertEqual(json.loads((self.f.root / 'state/state.json').read_text())['files'], {})

    def test_absence_disabled_and_simulation(self):
        self.f.put(0, 'data')
        self.f.engine(False).run_once()
        self.assertEqual(self.ids(), [None] * 3)
        self.f.cfg['persistent_ids'] = False
        self.f.configure()
        self.f.engine().run_once()
        self.assertEqual(self.f.contents(), ['data'] * 3)
        self.assertEqual(self.ids(), [None] * 3)

    def test_readonly_continues(self):
        with patch('ved_sync.identity.tempfile.mkstemp', side_effect=PermissionError('read only')):
            self.assertEqual(set(self.f.engine().run_once()["status"].values()), {"verde"})
        self.assertEqual(self.ids(), [None] * 3)

    def test_duplicates_block_without_merging(self):
        value = str(uuid.uuid4())
        for p in self.f.repos[:2]:
            (p / IDENTITY_FILE).write_text(value)
        self.f.put(0, 'left')
        self.f.put(1, 'right')
        result = self.f.engine().run_once()
        self.assertEqual(result['status']['a'], 'rojo')
        self.assertEqual(result['status']['b'], 'rojo')
        self.assertFalse((self.f.repos[2] / 'f').exists())
        self.assertEqual((self.f.repos[0] / 'f').read_text(), 'left')

    def test_move_recognized_by_uuid(self):
        self.f.seed()
        old = self.ids()[0]
        moved = self.f.root / 'new-mount'
        self.f.repos[0].rename(moved)
        self.f.repos[0].mkdir()
        self.f.cfg['repositories'][0] = {'id': 'a', 'paths': ['a', 'new-mount']}
        self.f.configure()
        (moved / 'f').write_text('moved')
        self.assertEqual(set(self.f.engine().run_once()['status'].values()), {'verde'})
        self.assertEqual(read_identity(moved), old)
        self.assertEqual((self.f.repos[1] / 'f').read_text(), 'moved')

    def test_new_computer_explicit_uuid(self):
        self.f.engine().run_once()
        self.f.cfg['state_dir'] = 'new-state'
        self.f.cfg['repositories'][0]['uuid'] = self.ids()[0]
        self.f.configure()
        self.assertEqual(set(self.f.engine().run_once()['status'].values()), {'verde'})

    def test_removed_id_regenerated_without_copies(self):
        self.f.seed()
        old = self.ids()[0]
        (self.f.repos[0] / IDENTITY_FILE).unlink()
        self.assertEqual(self.f.engine().run_once()['events'], [])
        self.assertNotEqual(self.ids()[0], old)

    def test_exclusion_from_scan_copy_and_versions(self):
        self.f.seed()
        ids = self.ids()
        sub = self.f.repos[0] / 'sub'
        sub.mkdir()
        (sub / IDENTITY_FILE).write_text('private')
        e = self.f.engine()
        e.state['files'][IDENTITY_FILE] = {'seen': {}, 'head': None}
        e.save()
        self.assertEqual(self.f.engine().run_once()['events'], [])
        self.assertEqual(self.ids(), ids)
        self.assertFalse((self.f.repos[1] / 'sub' / IDENTITY_FILE).exists())
        self.assertFalse((e.state_dir / 'versions').exists())
        self.assertNotIn(IDENTITY_FILE, e.scan(self.f.repos[0]))

    def test_atomic_race_preserves_winner(self):
        import ved_sync.identity as module
        link = module.os.link
        winner = str(uuid.uuid4())
        def concurrent(source, target):
            target.write_text(winner)
            return link(source, target)
        with patch('ved_sync.identity.os.link', side_effect=concurrent):
            self.assertEqual(repository_identity(self.f.repos[0], True), winner)
        self.assertEqual([p.name for p in self.f.repos[0].iterdir()], [IDENTITY_FILE])

    def test_atomic_failure_no_partial_file(self):
        with patch('ved_sync.identity.os.link', side_effect=OSError('unsupported')):
            self.assertIsNone(repository_identity(self.f.repos[0], True))
        self.assertEqual(list(self.f.repos[0].iterdir()), [])

    def test_invalid_uuid_preserved(self):
        p = self.f.repos[0] / IDENTITY_FILE
        p.write_text('invalid')
        self.assertEqual(self.f.engine().run_once()['status']['a'], 'rojo')
        self.assertEqual(p.read_text(), 'invalid')

    def test_bounded_discovery_after_mount_change(self):
        self.f.seed()
        mount = self.f.root / 'mounts'
        mount.mkdir()
        moved = mount / 'usb'
        self.f.repos[0].rename(moved)
        self.f.cfg['repositories'][0]['search_roots'] = ['mounts']
        self.f.configure()
        (moved / 'f').write_text('rediscovered')
        self.assertEqual(set(self.f.engine().run_once()['status'].values()), {'verde'})
        self.assertEqual((self.f.repos[2] / 'f').read_text(), 'rediscovered')

    def test_git_ignore_rule(self):
        from ved_sync.engine import PROJECT
        self.assertIn(IDENTITY_FILE, (PROJECT / '.gitignore').read_text().splitlines())

    def test_readonly_directory_no_metadata(self):
        import os
        if os.name != 'posix' or os.geteuid() == 0:
            self.skipTest('Requiere permisos POSIX sin root')
        p = self.f.repos[0]
        p.chmod(0o555)
        try:
            self.assertIsNone(repository_identity(p, True))
            self.assertEqual(list(p.iterdir()), [])
        finally:
            p.chmod(0o755)

    def test_discovery_duplicate_uuid_blocks_sync(self):
        import shutil
        self.f.seed()
        mounts = self.f.root / 'mounts'
        mounts.mkdir()
        shutil.copytree(self.f.repos[0], mounts / 'clone')
        self.f.cfg['repositories'][0]['search_roots'] = ['mounts']
        self.f.configure()
        self.assertEqual(self.f.engine().run_once()['status']['a'], 'rojo')

    def test_missing_id_with_creation_disabled_keeps_history(self):
        self.f.seed()
        (self.f.repos[1] / IDENTITY_FILE).unlink()
        self.f.cfg['persistent_ids'] = False
        self.f.configure()
        self.f.put(1, 'edit without UUID')
        self.assertEqual(set(self.f.engine().run_once()['status'].values()), {'verde'})
        self.assertEqual(self.f.contents(), ['edit without UUID'] * 3)
        self.assertIsNone(read_identity(self.f.repos[1]))
