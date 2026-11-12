"""Optional local measurement using only disposable repositories in VED-SYNC.

The reference suppresses telemetry via mocks solely to measure its cost; this is
not an available synchronization mode. Native disk/network measurements remain
necessary before production.
"""
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from ved_sync.engine import Engine
from ved_sync.telemetry import Monitor, TimingHistory


def measure(root, size, enabled):
    root.mkdir()
    for name in ('a', 'b', 'c'):
        (root / name).mkdir()
    config = root / 'config.json'
    config.write_text(json.dumps({'project': 'benchmark', 'state_dir': 'state', 'persistent_ids': False,
                                 'repositories': [{'id': n, 'path': n, 'device_type': 'local'}
                                                  for n in ('a', 'b', 'c')]}))
    (root / 'a/file.bin').write_bytes(b'x' * size)
    engine = Engine(config, apply=True)
    started = time.perf_counter()
    if enabled:
        report = engine.run_once()
    else:
        with patch.object(Monitor, 'emit'), patch.object(TimingHistory, 'record'):
            report = engine.run_once()
    duration = time.perf_counter() - started
    if set(report['status'].values()) != {'verde'}:
        raise RuntimeError('Benchmark no verificado')
    return duration


def main():
    parent = PROJECT / '.test-runs'
    parent.mkdir(exist_ok=True)
    size = 16 * 1024 * 1024
    samples = {'audit_enabled': [], 'reference_without_telemetry': []}
    with tempfile.TemporaryDirectory(dir=parent) as directory:
        root = Path(directory)
        for repeat in range(3):
            # Alternate order to reduce warm-cache bias.
            for enabled in ((False, True) if repeat % 2 == 0 else (True, False)):
                key = 'audit_enabled' if enabled else 'reference_without_telemetry'
                samples[key].append(measure(root / f'{repeat}-{enabled}', size, enabled))
    medians = {k: statistics.median(v) for k, v in samples.items()}
    print(json.dumps({'file_bytes': size, 'repositories': 3, 'samples_seconds': samples,
                      'median_seconds': medians,
                      'relative_difference_percent': 100 * (medians['audit_enabled'] /
                                                           medians['reference_without_telemetry'] - 1),
                      'scope': 'Linux local fictitious repositories; includes fsync; no GUI or network'}, indent=2))


if __name__ == '__main__':
    main()
