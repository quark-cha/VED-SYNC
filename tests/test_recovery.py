import json
import unittest
from unittest.mock import patch

from tests import test_engine
from ved_sync.engine import inspect


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = test_engine.SyncTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def prepare(self):
        self.f.seed()
        digest = inspect(self.f.repos[0] / 'f').digest
        self.f.put(0, 'new version')
        self.f.engine().run_once()
        return digest

    def log(self):
        return [json.loads(line) for line in (self.f.root / 'state/operaciones.jsonl').read_text().splitlines()]

    def test_backup_original_verified_before_substitution_and_no_propagation(self):
        digest = self.prepare()
        original = self.f.root / 'state/versions' / (digest + '.original')
        self.assertEqual(inspect(original).digest, digest)
        self.assertTrue(all(not (p / 'f.original').exists() for p in self.f.repos))
        transactions = [e for e in self.log() if e['type'] == 'transaction_committed']
        for tx in transactions:
            events = [e for e in self.log() if e.get('transaction') == tx['transaction']]
            types = [e['type'] for e in events]
            if any(e['type'] == 'transaction_started' and e.get('expected_sha256') == digest for e in events):
                self.assertLess(types.index('backup'), types.index('transaction_intent'))
            self.assertLess(types.index('transaction_intent'), types.index('transaction_committed'))
            finished = [i for i, e in enumerate(events) if e['type'] == 'progress' and
                        e.get('operation') == 'file' and e.get('percent') == 100]
            self.assertTrue(finished)
            self.assertGreater(finished[0], types.index('transaction_committed'))

    def test_recovery_strictly_verifies_original_and_preserves_replaced_content(self):
        digest = self.prepare()
        replaced = inspect(self.f.repos[1] / 'f').digest
        self.f.engine().recover('b', 'f', digest)
        self.assertEqual((self.f.repos[1] / 'f').read_text(), 'original')
        self.assertEqual((self.f.root / 'state/versions' / (replaced + '.original')).read_text(), 'new version')
        events = self.log()
        verified = max(i for i, e in enumerate(events) if e['type'] == 'recovery_verified')
        last_start = max(i for i, e in enumerate(events) if e['type'] == 'transaction_started')
        self.assertLess(verified, last_start)
        self.assertTrue(any(e['type'] == 'recovery' for e in events))
        self.assertFalse((self.f.root / 'state/run.lock').exists())

    def test_corrupt_original_blocks_recovery_before_touching_target(self):
        digest = self.prepare()
        original = self.f.root / 'state/versions' / (digest + '.original')
        original.write_text('tampered')
        engine = self.f.engine()
        with patch.object(engine, 'copy') as copy:
            with self.assertRaises(OSError):
                engine.recover('b', 'f', digest)
            copy.assert_not_called()
        self.assertEqual(self.f.contents(), ['new version'] * 3)
        self.assertTrue(any(e['type'] == 'verification' and e.get('result') == 'failed' for e in self.log()))
        self.assertFalse((self.f.root / 'state/run.lock').exists())

    def test_missing_original_never_falls_back_to_unverified_legacy(self):
        digest = self.prepare()
        (self.f.root / 'state/versions' / (digest + '.original')).unlink()
        with self.assertRaises(OSError):
            self.f.engine().recover('b', 'f', digest)
        self.assertEqual(self.f.contents(), ['new version'] * 3)

    def test_corrupted_preexisting_backup_prevents_replacement(self):
        self.f.seed()
        digest = inspect(self.f.repos[1] / 'f').digest
        directory = self.f.root / 'state/versions'
        directory.mkdir()
        (directory / (digest + '.original')).write_text('corrupt')
        self.f.put(0, 'edit')
        report = self.f.engine().run_once()
        self.assertIn('error', [e['type'] for e in report['events']])
        self.assertEqual((self.f.repos[1] / 'f').read_text(), 'original')
        self.assertEqual((self.f.repos[2] / 'f').read_text(), 'original')

    def test_recovery_simulation_does_not_write_repository(self):
        digest = self.prepare()
        self.assertEqual(self.f.engine(False).recover('b', 'f', digest)['events'][0]['type'], 'would_recover')
        self.assertEqual(self.f.contents(), ['new version'] * 3)

    def test_recovery_of_missing_file_is_verified(self):
        digest = self.prepare()
        (self.f.repos[2] / 'f').unlink()
        self.f.engine().recover('c', 'f', digest)
        self.assertEqual((self.f.repos[2] / 'f').read_text(), 'original')

    def test_interruption_records_unconfirmed_transaction_releases_lock_and_resumes(self):
        self.f.put(0, 'data')
        engine = self.f.engine()
        with patch.object(engine, '_stream_copy', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                engine.run_once()
        self.assertFalse((self.f.root / 'state/run.lock').exists())
        self.assertTrue(any(e['type'] == 'transaction_unconfirmed' for e in self.log()))
        self.assertFalse(any(e.get('percent') == 100 and e.get('operation') == 'file' for e in self.log()))
        self.assertEqual(set(self.f.engine().run_once()['status'].values()), {'verde'})
        self.assertEqual(self.f.contents(), ['data'] * 3)

    def test_unknown_version_and_unsafe_paths_rejected(self):
        digest = self.prepare()
        for relative in ('../f', '/f', 'sub/../../f', 'f.original'):
            with self.assertRaises(ValueError):
                self.f.engine().recover('b', relative, digest)
        with self.assertRaises(ValueError):
            self.f.engine().recover('b', 'f', '0' * 64)

    def test_original_files_excluded_from_sync(self):
        self.f.put(0, 'data')
        (self.f.repos[0] / 'f.original').write_text('private backup')
        self.f.engine().run_once()
        self.assertFalse((self.f.repos[1] / 'f.original').exists())
        self.assertNotIn('f.original', self.f.engine().state['files'])

    def test_global_100_only_after_state_save_and_final_verification(self):
        self.f.put(0, 'data')
        engine = self.f.engine()
        save = engine.save
        def checked_save():
            self.assertFalse(any(e['type'] == 'project_progress' and e.get('percent') == 100 for e in self.log()))
            save()
        with patch.object(engine, 'save', side_effect=checked_save):
            engine.run_once()
        self.assertTrue(any(e['type'] == 'project_progress' and e.get('percent') == 100 for e in self.log()))

    def test_pending_or_failed_project_never_100(self):
        self.f.put(0, 'left')
        self.f.put(1, 'right')
        self.f.engine().run_once()
        self.assertFalse(any(e['type'] == 'project_progress' and e.get('percent') == 100 for e in self.log()))

    def test_audit_failure_before_intent_prevents_any_replacement(self):
        self.f.seed()
        self.f.put(0, 'edit')
        engine = self.f.engine()
        emit = engine.monitor.emit
        def failure(kind, **fields):
            if kind == 'transaction_intent':
                raise OSError('fictitious audit write failure')
            return emit(kind, **fields)
        with patch.object(engine.monitor, 'emit', side_effect=failure):
            report = engine.run_once()
        self.assertIn('error', [e['type'] for e in report['events']])
        self.assertEqual((self.f.repos[1] / 'f').read_text(), 'original')
        self.assertEqual((self.f.repos[2] / 'f').read_text(), 'original')
        self.assertFalse((self.f.root / 'state/run.lock').exists())

    def test_original_changed_after_recovery_validation_is_rejected(self):
        digest = self.prepare()
        engine = self.f.engine()
        copy = engine.copy
        def change(source, *args):
            source.write_text('tampered after initial validation')
            return copy(source, *args)
        with patch.object(engine, 'copy', side_effect=change):
            with self.assertRaises(OSError):
                engine.recover('b', 'f', digest)
        self.assertEqual(self.f.contents(), ['new version'] * 3)

    def test_completed_file_byte_accounting_includes_backup_and_verifications(self):
        self.prepare()
        files = [e for e in self.log() if e['type'] == 'progress' and
                 e.get('operation') == 'file' and e.get('finished')]
        self.assertTrue(files)
        for event in files:
            self.assertEqual(event['processed'], event['total'])

    def test_timing_record_and_durable_audit_precede_global_100(self):
        self.f.put(0, 'data')
        engine = self.f.engine()
        update = engine.monitor.project_update
        def checked_update(phase, percent, *args, **kwargs):
            if percent == 100:
                engine.monitor.stream.flush()
                self.assertEqual(engine.monitor.history.rows[-1]['operation'], 'project')
                self.assertEqual(self.log()[-1]['type'], 'cycle_finished')
            return update(phase, percent, *args, **kwargs)
        with patch.object(engine.monitor, 'project_update', side_effect=checked_update):
            engine.run_once()

    def test_state_save_failure_never_announces_global_completion(self):
        self.f.put(0, 'data')
        engine = self.f.engine()
        with patch.object(engine, 'save', side_effect=OSError('fictitious full disk')):
            with self.assertRaises(OSError):
                engine.run_once()
        self.assertFalse(any(e['type'] == 'project_progress' and e.get('percent') == 100 for e in self.log()))
        self.assertFalse((self.f.root / 'state/run.lock').exists())

    def test_fallback_without_hard_links_is_verified_and_progress_accounts_bytes(self):
        import errno
        self.f.put(0, 'data')
        with patch('ved_sync.engine.os.link', side_effect=OSError(errno.ENOTSUP, 'unsupported')):
            result = self.f.engine().run_once()
        self.assertEqual(set(result['status'].values()), {'verde'})
        self.assertEqual(self.f.contents(), ['data'] * 3)
        files = [e for e in self.log() if e['type'] == 'progress' and
                 e.get('operation') == 'file' and e.get('finished')]
        self.assertTrue(all(e['processed'] == e['total'] for e in files))

    def test_successful_and_failed_recoveries_have_distinct_timing_results(self):
        from ved_sync.telemetry import TimingHistory
        digest = self.prepare()
        self.f.engine().recover('b', 'f', digest)
        original = self.f.root / 'state/versions' / (digest + '.original')
        original.write_text('corrupt')
        with self.assertRaises(OSError):
            self.f.engine().recover('c', 'f', digest)
        rows = TimingHistory(self.f.root / 'state/tiempo.csv').rows
        results = [r['result'] for r in rows if r['operation'] == 'recovery']
        self.assertEqual(results[-2:], ['ok', 'failed'])

    def test_automatic_missing_file_recovery_also_verifies_original(self):
        self.f.seed()
        digest = inspect(self.f.repos[0] / 'f').digest
        (self.f.repos[1] / 'f').unlink()
        report = self.f.engine().run_once()
        self.assertEqual(set(report['status'].values()), {'verde'})
        self.assertIn('recovery', [e['type'] for e in report['events']])
        original = self.f.root / 'state/versions' / (digest + '.original')
        self.assertEqual(inspect(original).digest, digest)
        verified = max(i for i, e in enumerate(self.log()) if e['type'] == 'recovery_verified')
        intent = max(i for i, e in enumerate(self.log()) if e['type'] == 'transaction_intent')
        self.assertLess(verified, intent)

    def test_corrupt_original_blocks_automatic_missing_file_recovery(self):
        self.f.seed()
        digest = inspect(self.f.repos[0] / 'f').digest
        directory = self.f.root / 'state/versions'
        directory.mkdir()
        (directory / (digest + '.original')).write_text('corrupt')
        (self.f.repos[1] / 'f').unlink()
        report = self.f.engine().run_once()
        self.assertIn('error', [e['type'] for e in report['events']])
        self.assertFalse((self.f.repos[1] / 'f').exists())
        self.assertEqual((self.f.repos[0] / 'f').read_text(), 'original')

    def test_linked_original_is_rejected_before_recovery(self):
        digest = self.prepare()
        original = self.f.root / 'state/versions' / (digest + '.original')
        original.unlink()
        original.symlink_to(original.with_suffix(''))
        with self.assertRaises(OSError):
            self.f.engine().recover('b', 'f', digest)
        self.assertEqual(self.f.contents(), ['new version'] * 3)
