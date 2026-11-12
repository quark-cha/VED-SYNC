import os
import unittest
from unittest.mock import patch
from tests import test_engine
from ved_sync.engine import inspect

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.f = test_engine.SyncTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_restart_reuses_hashes(self):
        self.f.seed()
        with patch('ved_sync.engine.inspect', wraps=inspect) as hasher:
            self.assertEqual(set(self.f.engine().run_once()['status'].values()), {'verde'})
            self.assertEqual(hasher.call_count, 0)

    def test_periodic_integrity_forces_hashes(self):
        self.f.seed()
        self.f.cfg['integrity_seconds'] = 0
        self.f.configure()
        with patch('ved_sync.engine.inspect', wraps=inspect) as hasher:
            self.f.engine().run_once()
            self.assertGreaterEqual(hasher.call_count, 6)

    def test_same_size_date_edit_invalidates_cache(self):
        self.f.seed()
        p = self.f.repos[2] / 'f'
        old = p.stat()
        p.write_text('modified')
        os.utime(p, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.f.engine().run_once()
        self.assertEqual(self.f.contents(), ['modified'] * 3)

    def test_expired_cache_detects_content_even_with_unchanged_metadata(self):
        self.f.seed()
        e = self.f.engine()
        for record in e.state['hash_cache'].values():
            record['verified_ns'] = 0
            record['sha256'] = 'invalid cached digest'
        e.save()
        self.assertEqual(self.f.engine().run_once()['events'], [])
        self.assertTrue(all(r['sha256'] != 'invalid cached digest'
                            for r in self.f.engine().state['hash_cache'].values()))
