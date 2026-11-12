import unittest
from tests import test_engine
from ved_sync.engine import Engine

class ProjectTests(unittest.TestCase):
    def test_independent_projects_and_dynamic_addition(self):
        fixtures = []
        for _ in range(2):
            f = test_engine.SyncTests()
            f.setUp()
            self.addCleanup(f.doCleanups)
            fixtures.append(f)
        for i, f in enumerate(fixtures):
            f.put(0, f'project-{i}')
            f.engine().run_once()
            self.assertEqual(f.contents(), [f'project-{i}'] * 3)
        f = fixtures[0]
        (f.root / 'new-usb').mkdir()
        f.cfg['repositories'].append({'id': 'usb', 'path': 'new-usb'})
        f.configure()
        self.assertEqual(set(f.engine().run_once()['status'].values()), {'verde'})
        self.assertEqual((f.root / 'new-usb/f').read_text(), 'project-0')
        self.assertEqual(fixtures[1].contents(), ['project-1'] * 3)

    def test_startup_templates_are_simulation_only(self):
        from ved_sync.engine import PROJECT
        for name in ('ved-sync.service.example', 'windows-login.cmd.example'):
            content = (PROJECT / 'startup' / name).read_text()
            self.assertIn('--watch', content)
            self.assertNotIn('--apply', content)
