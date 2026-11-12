import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ved_sync.engine import Engine, PROJECT, inspect


class SyncTests(unittest.TestCase):
    def setUp(self):
        parent = PROJECT / '.test-runs'
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repos = [self.root / n for n in ('a', 'b', 'c')]
        for p in self.repos:
            p.mkdir()
        self.config = self.root / 'config.json'
        self.cfg = {'interval_seconds': 1, 'state_dir': 'state', 'repositories': [
            {'id': p.name, 'path': p.name} for p in self.repos]}
        self.configure()

    def configure(self):
        self.config.write_text(json.dumps(self.cfg), encoding='utf-8')

    def engine(self, apply=True):
        return Engine(self.config, apply=apply)

    def put(self, index, value):
        (self.repos[index] / 'f').write_text(value)

    def contents(self):
        return [(p / 'f').read_text() for p in self.repos]

    def seed(self):
        self.put(0, 'original')
        self.assertEqual(set(self.engine().run_once()['status'].values()), {'verde'})

    def test_default_simulation(self):
        self.put(0, 'one')
        report = Engine(self.config).run_once()
        self.assertTrue(report['simulation'])
        self.assertFalse((self.repos[1] / 'f').exists())
        self.assertFalse((self.root / 'state/state.json').exists())
        self.assertIn('would_copy', [e['type'] for e in report['events']])

    def test_three_way_bidirectional_and_new_nested_binary(self):
        self.seed()
        for i in (1, 2, 0):
            self.put(i, f'edit-{i}')
            self.assertEqual(set(self.engine().run_once()['status'].values()), {'verde'})
            self.assertEqual(self.contents(), [f'edit-{i}'] * 3)
        (self.repos[2] / 'sub').mkdir()
        data = bytes(range(256))
        (self.repos[2] / 'sub/photo.bin').write_bytes(data)
        self.engine().run_once()
        self.assertEqual((self.repos[0] / 'sub/photo.bin').read_bytes(), data)

    def test_hash_detects_same_size_and_date(self):
        self.seed()
        p = self.repos[1] / 'f'
        before = p.stat()
        self.put(1, 'modified')
        os.utime(p, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.engine().run_once()
        self.assertEqual(self.contents(), ['modified'] * 3)

    def test_conflicts_survive_restart(self):
        self.seed()
        self.put(0, 'left')
        self.put(1, 'right')
        for _ in range(2):
            report = self.engine().run_once()
            self.assertIn('conflict', [e['type'] for e in report['events']])
            self.assertEqual(self.contents(), ['left', 'right', 'original'])
            self.assertEqual(set(report['status'].values()), {'rojo'})

    def test_initial_conflict_manual_resolution(self):
        for i in range(3):
            self.put(i, str(i))
        self.assertEqual(self.engine().run_once()['events'][0]['type'], 'conflict')
        for i in range(3):
            self.put(i, 'resolved')
        self.assertEqual(set(self.engine().run_once()['status'].values()), {'verde'})

    def test_version_archive(self):
        self.seed()
        digest = inspect(self.repos[0] / 'f').digest
        self.put(1, 'changed')
        self.engine().run_once()
        self.assertEqual((self.root / 'state/versions' / digest).read_text(), 'original')

    def test_no_deletion_propagation(self):
        self.seed()
        (self.repos[1] / 'f').unlink()
        self.engine().run_once()
        self.assertEqual(self.contents(), ['original'] * 3)

    def test_offline_reconnect(self):
        self.seed()
        off = self.root / 'off'
        self.repos[2].rename(off)
        self.put(0, 'new')
        report = self.engine().run_once()
        self.assertEqual(report['status']['c'], 'gris')
        self.assertEqual(report['status']['a'], 'rojo')
        off.rename(self.repos[2])
        self.engine().run_once()
        self.assertEqual(self.contents(), ['new'] * 3)

    def test_offline_independent_edit_conflicts(self):
        self.seed()
        off = self.root / 'off'
        self.repos[2].rename(off)
        self.put(0, 'new')
        self.engine().run_once()
        (off / 'f').write_text('independent')
        off.rename(self.repos[2])
        result = self.engine().run_once()
        self.assertIn('conflict', [e['type'] for e in result['events']])
        self.assertEqual(self.contents(), ['new', 'new', 'independent'])

    def test_head_offline_never_reverted(self):
        self.seed()
        off_b, off_c = self.root / 'off-b', self.root / 'off-c'
        self.repos[1].rename(off_b)
        self.repos[2].rename(off_c)
        self.put(0, 'new')
        self.engine().run_once()
        off_a = self.root / 'off-a'
        self.repos[0].rename(off_a)
        off_b.rename(self.repos[1])
        self.assertIn('pending', [e['type'] for e in self.engine().run_once()['events']])
        off_a.rename(self.repos[0])
        off_c.rename(self.repos[2])
        self.engine().run_once()
        self.assertEqual(self.contents(), ['new'] * 3)

    def test_stale_edit_with_current_head_unavailable_conflicts(self):
        self.seed()
        off_b, off_c = self.root / 'off-b', self.root / 'off-c'
        self.repos[1].rename(off_b)
        self.repos[2].rename(off_c)
        self.put(0, 'new')
        self.engine().run_once()
        self.repos[0].rename(self.root / 'off-a')
        off_b.rename(self.repos[1])
        self.put(1, 'stale-edit')
        result = self.engine().run_once()
        self.assertIn('conflict', [e['type'] for e in result['events']])
        state = json.loads((self.root / 'state/state.json').read_text())
        self.assertEqual(state['files']['f']['head'], inspect(self.root / 'off-a/f').digest)

    def test_all_known_copies_missing_are_pending(self):
        self.seed()
        for p in self.repos:
            (p / 'f').unlink()
        report = self.engine().run_once()
        self.assertIn('pending', [e['type'] for e in report['events']])
        self.assertEqual(set(report['status'].values()), {'rojo'})

    def test_resume_after_failure(self):
        self.put(0, 'one')
        e = self.engine()
        original = e.copy
        def fail(source, target, *args):
            if target.parent == self.repos[2]:
                raise OSError('simulated disconnect')
            return original(source, target, *args)
        with patch.object(e, 'copy', side_effect=fail):
            self.assertEqual(e.run_once()['status']['c'], 'rojo')
        self.assertEqual(set(self.engine().run_once()['status'].values()), {'verde'})
        self.assertEqual(self.contents(), ['one'] * 3)

    def test_target_changed_after_scan_preserved(self):
        self.seed()
        self.put(0, 'new')
        e = self.engine()
        original = e.copy
        def change(source, target, *args):
            target.write_text('concurrent')
            return original(source, target, *args)
        with patch.object(e, 'copy', side_effect=change):
            self.assertIn('error', [v['type'] for v in e.run_once()['events']])
        self.assertEqual((self.repos[1] / 'f').read_text(), 'concurrent')

    def test_symlink_rejected(self):
        (self.repos[0] / 'link').symlink_to(self.repos[1], target_is_directory=True)
        self.assertEqual(self.engine().run_once()['status']['a'], 'rojo')

    def test_exclusive_lock(self):
        e = self.engine()
        e.state_dir.mkdir()
        (e.state_dir / 'run.lock').write_text('123')
        with self.assertRaises(RuntimeError):
            e.run_once()

    def test_protected_and_nested_paths(self):
        for forbidden in ('a/child', '/mnt/windows/test', str(PROJECT.parent / 'CLASES'), '/tmp/ved-sync-external'):
            self.cfg['repositories'][1]['path'] = forbidden
            self.configure()
            with self.assertRaises(ValueError):
                self.engine()

    def test_alternative_paths_ambiguity(self):
        self.cfg['persistent_ids'] = False
        self.cfg['repositories'][0] = {'id': 'a', 'paths': ['absent', 'a']}
        self.configure()
        self.assertEqual(self.engine().run_once()['status']['a'], 'verde')
        (self.root / 'absent').mkdir()
        self.assertEqual(self.engine().run_once()['status']['a'], 'rojo')

    def test_yellow_callback(self):
        updates = []
        self.engine().run_once(on_status=updates.append)
        self.assertEqual(set(updates[0].values()), {'amarillo'})
        self.assertEqual(set(updates[-1].values()), {'verde'})

    def test_two_and_four_repositories(self):
        for count in (2, 4):
            with self.subTest(count=count):
                paths = [self.root / f'r{count}-{i}' for i in range(count)]
                for p in paths:
                    p.mkdir()
                self.cfg['repositories'] = [{'id': p.name, 'path': p.name} for p in paths]
                self.cfg['state_dir'] = f'state-{count}'
                self.configure()
                (paths[-1] / 'f').write_text('data')
                self.assertEqual(set(self.engine().run_once()['status'].values()), {'verde'})
                self.assertTrue(all((p / 'f').read_text() == 'data' for p in paths))


if __name__ == '__main__':
    unittest.main()
