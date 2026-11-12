"""Bounded timing history, incremental audit log and throttled console progress."""
from collections import deque
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time
import uuid
import unicodedata
import shutil


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def token(value):
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:24]


class TimingHistory:
    FIELDS = ('operation', 'bytes', 'duration_seconds', 'bytes_per_second',
              'device_type', 'result', 'executed_at')

    def __init__(self, path, limit=1000, keep_open=False, persist=True):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 10 <= limit <= 100000:
            raise ValueError('timing_limit debe ser un entero entre 10 y 100000')
        self.path = Path(path)
        self.persist = persist
        self.keep_open = keep_open
        self.stream = None
        self.writer = None
        self.limit = limit
        self.rows = deque(maxlen=limit)
        count = 0
        if persist and self.path.exists():
            with self.path.open(newline='', encoding='utf-8') as stream:
                for row in csv.DictReader(stream):
                    count += 1
                    try:
                        size = int(row['bytes'])
                        duration = float(row['duration_seconds'])
                        speed = float(row['bytes_per_second'])
                        if size < 0 or duration < 0 or speed < 0 or not all(map(math.isfinite, (duration, speed))):
                            continue
                        self.rows.append(row)
                    except (KeyError, TypeError, ValueError):
                        continue  # Ignore incomplete or malformed historical samples.
            if count != len(self.rows):
                self._compact()

    def _compact(self):
        # Infrequent bounded compaction; normal recording is append-only.
        self.close()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name('.ved-sync-timing-' + uuid.uuid4().hex)
        try:
            with temporary.open('x', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=self.FIELDS)
                writer.writeheader()
                writer.writerows(self.rows)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def record(self, operation, size, duration, device, result):
        size = max(0, int(size))
        duration = max(0.0, float(duration))
        row = dict(zip(self.FIELDS, (operation, size, duration,
                       size / duration if duration else 0.0, device, result, utc_now())))
        if not self.persist:
            self.rows.append(row)
            return
        if len(self.rows) == self.limit:
            # Compact in batches, retaining the newest 90% before appending.
            self.rows = deque(list(self.rows)[max(1, self.limit // 10):], maxlen=self.limit)
            self._compact()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.stream is None:
            needs_header = not self.path.exists() or self.path.stat().st_size == 0
            self.stream = self.path.open('a', newline='', encoding='utf-8')
            self.writer = csv.DictWriter(self.stream, fieldnames=self.FIELDS)
            if needs_header:
                self.writer.writeheader()
        self.writer.writerow(row)
        self.stream.flush()
        if not self.keep_open:
            self.close()
        self.rows.append(row)

    def close(self, durable=False):
        if self.stream is not None:
            try:
                self.stream.flush()
                if durable:
                    os.fsync(self.stream.fileno())
            finally:
                self.stream.close()
                self.stream = None
                self.writer = None

    def speed(self, operation, device):
        speeds = []
        for row in self.rows:
            if row['operation'] != operation or row['device_type'] != device or row['result'] != 'ok':
                continue
            size, duration = int(row['bytes']), float(row['duration_seconds'])
            if size >= 4096 and duration >= 0.005:
                speeds.append(size / duration)
        if len(speeds) < 3:
            return None
        middle = statistics.median(speeds)
        # Median rejects extreme rates; trim tails before weighting recent data.
        good = [s for s in speeds if middle / 4 <= s <= middle * 4]
        if len(good) < 3:
            return None
        weights = range(1, len(good) + 1)
        return sum(s * w for s, w in zip(good, weights)) / sum(weights)


class Console:
    """Fixed direction, status and progress rows; final snapshot when redirected."""
    COLORS = {'verde': '32', 'amarillo': '33', 'rojo': '31', 'gris': '90'}

    def __init__(self, stream, interval=0.25, clock=time.monotonic, *, width=None, ansi=None):
        self.stream, self.clock, self.interval = stream, clock, interval
        self.width = width
        self.last = -math.inf
        self.frame = False
        self._restore_mode = None
        self.ansi = self._enable_terminal() if ansi is None else bool(ansi and stream.isatty())
        self.project = 'VED-SYNC'
        self.location = '.'
        self.files_done, self.files_total = 0, None
        self.statuses = {}
        self.global_state = None
        self.file_state = None
        self.file_name = ''
        self.simulation = False
        self.finished = False
        self.problem = False
        self.success = False
        self.light = 'gris'
        self.error_code = None
        self.direction = None
        self.transfers = []

    def _enable_terminal(self):
        if not self.stream.isatty():
            return False
        if os.name != 'nt':
            return os.environ.get('TERM') != 'dumb'
        # Enable VT only for this process's console, without modifying system settings.
        try:
            import ctypes
            from ctypes import wintypes
            import msvcrt
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            handle = msvcrt.get_osfhandle(self.stream.fileno())
            mode = wintypes.DWORD()
            if kernel.GetConsoleMode(handle, ctypes.byref(mode)) and kernel.SetConsoleMode(handle, mode.value | 4):
                self._restore_mode = (kernel, handle, mode.value)
                return True
        except (ImportError, AttributeError, OSError, ValueError):
            pass
        return False

    @staticmethod
    def _clean(value):
        return ''.join(' ' if unicodedata.category(c) in ('Cc', 'Cf') else c for c in str(value))

    @staticmethod
    def _cells(text):
        return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
                   for c in text)

    @classmethod
    def _clip(cls, text, cells, *, tail=False):
        if cells <= 0:
            return ''
        if cls._cells(text) <= cells:
            return text
        if cells == 1:
            return '~'
        result, used = [], 1  # Reserve one display cell for the ellipsis marker.
        for char in (reversed(text) if tail else text):
            size = cls._cells(char)
            if used + size > cells:
                break
            result.append(char)
            used += size
        return '~' + ''.join(reversed(result)) if tail else ''.join(result) + '~'

    def _representable(self, value):
        text = self._clean(value)
        encoding = getattr(self.stream, 'encoding', None) or 'utf-8'
        return text.encode(encoding, errors='replace').decode(encoding)

    def _icon(self):
        icon = ('✓' if self.success else '!') if self.finished else '⌛'
        encoding = getattr(self.stream, 'encoding', None) or 'utf-8'
        try:
            icon.encode(encoding)
        except UnicodeEncodeError:
            return ('+' if self.success else '!') if self.finished else '>'
        return icon

    @staticmethod
    def bar(progress, width=12):
        percent = progress.get('percent')
        if percent is None:
            bar = '[' + '.' * width + '] indeterminado'
        else:
            filled = min(width, max(0, int(percent * width / 100)))
            bar = '[' + '#' * filled + '-' * (width - filled) + f'] {percent:.1f}%'
        total = progress.get('total')
        eta = progress.get('eta_seconds')
        return (bar + f" {progress.get('processed', 0)}/{total if total is not None else '?'} B ETA "
                + (f'{eta:.1f}s' if eta is not None else 'indeterminado'))

    def lines(self, columns=None):
        # Leave the last terminal column unused to avoid automatic wrapping.
        columns = columns or self.width or self._terminal_width()
        available = max(1, columns - 1)
        label = '[' + self.light.upper() + ']'
        count = f"{self.files_done}/{self.files_total if self.files_total is not None else '?'}"
        project = self._representable(self.project) + (' [SIM]' if self.simulation else '')
        project = self._clip(project, max(1, available // 3))
        suffix = f' {self._icon()} {project} {count}'
        location_width = available - self._cells(label + suffix) - 1
        location = self._clip(self._representable(self.location), max(1, location_width), tail=True)
        top = self._clip(f'{label} {location}{suffix}', available)
        progress = self.global_state or self.file_state or {}
        bottom = self.bar(progress, width=max(3, min(16, available // 5)))
        # Keep per-file progress on the same second row when there is room.
        if self.file_state and not self.finished:
            pct = self.file_state.get('percent')
            detail = f" {pct:.0f}%" if pct is not None else ' ?%'
            room = available - self._cells(bottom + detail + ' | ')
            if room >= 5:
                bottom += ' | ' + self._clip(self._representable(self.file_name or self.file_state.get('operation', 'archivo')), room, tail=True) + detail
        if self.error_code:
            bottom = self._representable('Error: ' + self.error_code + ' | ') + bottom
        if self.finished:
            if self.success:
                message = 'Finalizado correctamente'
            elif self.error_code == 'interrumpido':
                message = 'Interrumpido'
            else:
                message = 'Finalizado con errores' if self.error_code else 'Finalizado con pendientes'
            bottom = self._representable(message + ' | ') + bottom
        elif progress.get('phase') == 'confirmation':
            bottom = self._representable('Guardando y cerrando | ') + bottom
        return self._clip(top, available), self._clip(self._representable(bottom), available)

    def _terminal_width(self):
        try:
            return os.get_terminal_size(self.stream.fileno()).columns
        except (OSError, ValueError, AttributeError):
            return shutil.get_terminal_size(fallback=(120, 24)).columns

    def __call__(self, event):
        kind = event['type']
        if kind == 'cycle_started':
            self.direction = None
            self.transfers = []
            self.statuses.clear()
            self.finished = self.success = self.problem = False
            self.file_state = self.global_state = None
            self.file_name = ''
            self.error_code = None
            self.files_done, self.files_total = 0, None
            self.simulation = event.get('simulation', False)
            self.light = 'amarillo'
        if kind == 'transfer_policy':
            self.transfers = event['transfers']
            allowed = [t for t in self.transfers if t['allowed']]
            if len(allowed) == 1:
                self.direction = (allowed[0]['source_label'], allowed[0]['target_label'])
        if kind == 'transfer_direction':
            self.direction = (str(event['direction_source']), str(event['direction_target']))
        self.project = event.get('display_project', self.project)
        self.location = event.get('display_location', self.location)
        self.files_done = event.get('files_done', self.files_done)
        self.files_total = event.get('files_total', self.files_total)
        if event.get('display_path'):
            self.file_name = event['display_path']
        if kind == 'status':
            key = event.get('repository_ref', event.get('display_repository', '?'))
            self.statuses[key] = event['status']
        if kind in ('error', 'conflict', 'pending', 'interrupted', 'transaction_unconfirmed'):
            self.problem = True
        if kind == 'error':
            self.error_code = str(event.get('code', 'Error'))
            if event.get('display_path'):
                self.error_code += ': ' + str(event['display_path'])
        if kind == 'project_progress':
            self.global_state = event
            if event.get('finished'):
                self.finished = True
                self.success = event.get('phase') == 'confirmed' and not self.problem
        if kind == 'progress':
            if event.get('operation') == 'file':
                self.file_state = event
            elif self.file_state is None or self.file_state.get('operation') != 'file':
                self.file_state = event
        statuses = set(self.statuses.values())
        if self.problem or 'rojo' in statuses:
            self.light = 'rojo'
        elif self.finished:
            self.light = 'verde' if self.success else 'gris' if 'gris' in statuses else 'rojo'
        else:
            self.light = 'gris' if statuses and statuses == {'gris'} else 'amarillo'
        now = self.clock()
        if self.ansi and (not self.frame or kind == 'transfer_policy'
                          or now - self.last >= self.interval or self.finished):
            self._draw()
            self.last = now
        elif not self.ansi and self.finished:
            self._draw()

    def direction_line(self):
        def status(transfer):
            return ('permitido' if transfer['allowed']
                    else 'bloqueado (' + transfer['reason'] + ')')
        if self.direction:
            line = ' → '.join(self.direction)
            selected = next((t for t in self.transfers
                             if (t['source_label'], t['target_label']) == self.direction), None)
            if selected:
                line += ' | ' + status(selected)
                reverse = next((t for t in self.transfers
                                if t['source'] == selected['target']
                                and t['target'] == selected['source']), None)
                if reverse:
                    line += '; ' + reverse['source_label'] + ' → ' + reverse['target_label'] + ': ' + status(reverse)
            return line
        if self.transfers:
            return '; '.join(t['source_label'] + ' → ' + t['target_label'] + ': ' + status(t)
                             for t in self.transfers)
        return 'Dirección: comparando repositorios'

    def _draw(self):
        top, bottom = self.lines()
        columns = self.width or self._terminal_width()
        direction = self.direction_line()
        direction = self._clip(self._representable(direction), max(1, columns - 1))
        if self.ansi:
            color = self.COLORS[self.light]
            top = f'\x1b[{color}m' + top + '\x1b[0m'
            start = '\r\x1b[2A' if self.frame else '\r'
            self.stream.write(start + '\x1b[2K' + direction + '\n\r\x1b[2K' + top + '\n\r\x1b[2K' + bottom)
            self.frame = True
        else:
            self.stream.write(direction + '\n' + top + '\n' + bottom + '\n')
        self.stream.flush()

    def fail(self, code, *, interrupted=False):
        if interrupted and self.finished:
            return  # Stopping idle watch preserves the last completed cycle.
        self.finished, self.success, self.problem = True, False, True
        self.light = 'rojo'
        self.error_code = 'interrumpido' if interrupted else code
        self._draw()

    def close(self):
        if not self.finished and (self.frame or self.global_state is not None):
            self.fail('cierre sin confirmación')
        if self.frame:
            self._draw()
            self.stream.write('\n')
            self.stream.flush()
            self.frame = False
        if self._restore_mode:
            kernel, handle, mode = self._restore_mode
            kernel.SetConsoleMode(handle, mode)
            self._restore_mode = None


class Monitor:
    SAFE_FIELDS = {'operation', 'processed', 'total', 'percent', 'eta_seconds', 'elapsed',
                   'duration_seconds', 'device_type', 'result', 'code', 'transaction',
                   'sha256', 'expected_sha256', 'status', 'finished', 'simulation', 'phase',
                   'files_done', 'files_total', 'transfers', 'completed'}
    TOKEN_FIELDS = {'path', 'repository', 'from', 'to'}

    def __init__(self, directory, project, console=None, limit=1000, clock=time.monotonic, location=None, audit=True):
        self.directory = Path(directory)
        self.project = token(project)
        self.project_label = str(project)
        self.initial_location = str(location or self.directory.parent)
        self.location = self.initial_location
        self.files_total = None
        self.finished_files = set()
        self.console = console
        self.limit = limit
        self.clock = clock
        self.active = False
        self.stream = None
        self.history = None
        self.audit = audit
        self.run_id = None
        self.project_progress = None
        self._last_progress = {}
        self.work_total = 0
        self.work_done = 0
        self.file_budget = 0
        self.transaction_paths = {}
        self._project_last = -math.inf
        self.project_payload = 0
        self.project_speed = None

    def start(self, simulation):
        if self.active:
            raise RuntimeError('El monitor ya está activo')
        self.directory.mkdir(parents=True, exist_ok=True)
        for filename in (('tiempo.csv', 'operaciones.jsonl') if self.audit else ()):
            path = self.directory / filename
            if path.is_symlink() or path.exists() and not path.is_file():
                raise ValueError('Los registros deben ser archivos locales regulares, sin enlaces')
        from .cleanup import reset_activity_logs
        reset_activity_logs(self.directory, 'operaciones.jsonl' if self.audit else 'VED-Sync.cola.log')
        self.history = TimingHistory(self.directory / 'tiempo.csv', self.limit, keep_open=True, persist=self.audit)
        self.stream = (self.directory / 'operaciones.jsonl').open('a', encoding='utf-8') if self.audit else None
        self._project_last = -math.inf
        self.project_progress = None
        self.project_started = self.clock()
        self.project_payload = 0
        self.project_speed = None
        self.location = self.initial_location
        self.files_total = None
        self.finished_files.clear()
        self.transaction_paths.clear()
        self._last_progress.clear()
        self.work_done = 0
        self.work_total = 0
        self.file_budget = 0
        self.run_id = uuid.uuid4().hex
        self.active = True
        self._last_flush = -math.inf
        self.emit('cycle_started', simulation=simulation)
        self.project_update('detection', None, 0, None)

    def emit(self, kind, durable=False, **fields):
        if not self.active:
            return
        event = {'date': utc_now(), 'run': self.run_id, 'project': self.project, 'type': kind}
        if kind in ('cycle_started', 'cycle_finished', 'checkpoint', 'state_loaded'):
            event['process_id'] = os.getpid()
            try:
                with open('/proc/self/status', encoding='ascii') as status:
                    for line in status:
                        if line.startswith(('VmRSS:', 'VmHWM:')):
                            key = 'rss_bytes' if line.startswith('VmRSS:') else 'peak_rss_bytes'
                            event[key] = int(line.split()[1]) * 1024
            except (OSError, ValueError):
                pass  # Optional Linux measurements; other platforms keep the PID.
        for key, value in fields.items():
            if key in self.SAFE_FIELDS:
                event[key] = value
            elif key in self.TOKEN_FIELDS:
                event[key + '_ref'] = token(value)
            if kind == 'error' and key in ('path', 'repository', 'detail', 'errno', 'path2'):
                # Local diagnostics must identify the failing repository and file.
                event[key] = str(value) if key != 'errno' else value
        if self.stream is not None:
            self.stream.write(json.dumps(event, ensure_ascii=True, allow_nan=False) + '\n')
        elif not self.audit and kind in ('cycle_started', 'cycle_finished', 'error',
                                        'interrupted', 'checkpoint_failed'):
            from .worklist import append_trace
            append_trace(self.directory / 'VED-Sync.cola.log', kind, durable=durable,
                         **{k: v for k, v in event.items() if k not in ('date', 'type')})
        now = self.clock()
        # Flush phase boundaries and at most every 250 ms during streaming.
        # Critical intent/commit records always reach fsync before continuing.
        if durable or kind in ('cycle_started', 'cycle_finished', 'operation_started',
                               'error', 'conflict', 'pending') or now - self._last_flush >= 0.25:
            if self.stream is not None:
                self.stream.flush()
            self._last_flush = now
        if durable and self.stream is not None:
            os.fsync(self.stream.fileno())
        if self.console:
            # Ordinary progress names remain transient; errors retain diagnostics.
            view = dict(event)
            if 'location' in fields:
                self.location = str(fields['location'])
            view['display_project'] = self.project_label
            view['display_location'] = self.location
            if kind == 'transfer_direction':
                view['direction_source'] = str(fields['direction_source'])
                view['direction_target'] = str(fields['direction_target'])
            view.setdefault('files_done', len(self.finished_files))
            view.setdefault('files_total', self.files_total)
            if 'repository' in fields:
                view['display_repository'] = str(fields['repository'])
            if 'path' in fields:
                view['display_path'] = Path(str(fields['path'])).name
            transaction = fields.get('transaction')
            if kind == 'transaction_started' and 'path' in fields:
                self.transaction_paths[transaction] = Path(str(fields['path'])).name
            if transaction in self.transaction_paths:
                view['display_path'] = self.transaction_paths[transaction]
            self.console(view)
            if kind == 'transaction_unconfirmed' or kind == 'progress' and fields.get('operation') == 'file' and fields.get('finished'):
                self.transaction_paths.pop(transaction, None)
        return event

    def progress(self, operation_id, **fields):
        now = self.clock()
        if now - self._last_progress.get(operation_id, -math.inf) >= 0.25 or fields.get('finished'):
            self._last_progress[operation_id] = now
            self.emit('progress', **fields)
            if fields.get('operation') == 'file' and self.work_total:
                fraction = min(1, fields['processed'] / fields['total']) if fields['total'] else 0
                processed = self.work_done + fraction * self.file_budget
                self.project_update('synchronization', 30 + 55 * processed / self.work_total,
                                    int(processed), self.work_total)
        if fields.get('finished'):
            self._last_progress.pop(operation_id, None)

    def set_work(self, total, payload=0):
        self.project_payload = payload
        self.project_speed = self.history.speed('project', 'mixed') if self.history else None
        self.work_total, self.work_done = total, 0
        self.project_update('synchronization', 30, 0, total)

    def complete_file(self):
        self.work_done += self.file_budget
        self.file_budget = 0

    def project_update(self, phase, percent, processed=0, total=None, finished=False, eta_seconds=None):
        now = self.clock()
        previous = self.project_progress
        fraction = (percent or 0) / 100
        elapsed = max(0, now - self.project_started)
        if not finished and percent is not None and self.project_payload and self.project_speed:
            expected_duration = self.project_payload / self.project_speed
            if elapsed >= 0.5 and fraction >= 0.35:
                expected_duration = 0.7 * elapsed / fraction + 0.3 * expected_duration
            eta_seconds = max(0, expected_duration * (1 - fraction))
        self.project_progress = dict(phase=phase, percent=percent, processed=processed,
                                     total=total, eta_seconds=eta_seconds, finished=finished)
        if finished or previous is None or previous['phase'] != phase or now - self._project_last >= 0.25:
            self.emit('project_progress', **self.project_progress)
            self._project_last = now

    def plan_files(self, paths):
        self.files_total = len(paths)
        self.finished_files.clear()
        self.emit('file_count', files_done=0, files_total=self.files_total)

    def finish_file(self, relative):
        if relative not in self.finished_files:
            self.finished_files.add(relative)
            self.emit('file_count', files_done=len(self.finished_files), files_total=self.files_total)

    def reconcile_files(self, paths):
        verified = set(paths)
        if verified != self.finished_files:
            self.finished_files = verified
            self.emit('file_count', files_done=len(verified), files_total=self.files_total)

    def operation(self, operation, total, device='unknown', transaction=None):
        return Operation(self, operation, total, device, transaction)

    def close(self, result, completed=None):
        try:
            if self.active:
                self.history.close(durable=True)
                self.emit('cycle_finished', result=result, completed=completed,
                          files_done=len(self.finished_files), files_total=self.files_total, durable=True)
                if completed is not None:
                    previous = self.project_progress or {}
                    self.location = self.initial_location
                    self.project_update('confirmed' if completed else result,
                                        100.0 if completed else previous.get('percent'),
                                        previous.get('processed', 0), previous.get('total'), finished=True)
                    if self.stream is not None:
                        self.stream.flush()
        finally:
            self.active = False
            if self.history:
                self.history.close()
            if self.stream:
                self.stream.close()
                self.stream = None


class Operation:
    def __init__(self, monitor, operation, total, device, transaction):
        self.monitor, self.name, self.total = monitor, operation, max(0, total)
        self.device, self.transaction = device, transaction
        self.processed = 0
        self.started = None
        self.identity = uuid.uuid4().hex

    def __enter__(self):
        self.started = self.monitor.clock()
        self.historical_speed = (self.monitor.history.speed(self.name, self.device)
                                 if self.monitor.history else None)
        self.monitor.emit('operation_started', operation=self.name, total=self.total,
                          device_type=self.device, transaction=self.transaction)
        self.advance(0)
        return self

    def advance(self, amount):
        self.processed += amount
        self.publish(False)

    def publish(self, finished):
        elapsed = max(0, self.monitor.clock() - self.started)
        speed = self.historical_speed
        # A measurable window is needed before trusting an observed transfer rate.
        if elapsed >= 0.5 and self.processed >= 256 * 1024:
            observed = self.processed / elapsed
            speed = observed if speed is None else 0.7 * observed + 0.3 * speed
        eta = max(0, self.total - self.processed) / speed if speed else None
        percent = 100.0 if finished else min(99.0, self.processed / self.total * 100) if self.total else None
        self.monitor.progress(self.identity, operation=self.name, processed=self.processed,
                              total=self.total, percent=percent, eta_seconds=eta,
                              elapsed=elapsed, finished=finished, transaction=self.transaction)

    def __exit__(self, exc_type, exc, tb):
        duration = max(0, self.monitor.clock() - self.started)
        result = 'ok' if exc_type is None else 'interrupted' if issubclass(exc_type, (KeyboardInterrupt, SystemExit)) else 'failed'
        if self.monitor.active:
            self.monitor.history.record(self.name, self.processed, duration, self.device, result)
        self.monitor.emit('operation_finished', operation=self.name, processed=self.processed,
                          total=self.total, duration_seconds=duration, result=result,
                          device_type=self.device, transaction=self.transaction)
        if exc_type is None:
            self.publish(True)
        return False


class EventList(list):
    """Preserve the existing report API while auditing problems when they occur."""
    def __init__(self, monitor):
        super().__init__()
        self.monitor = monitor

    def append(self, event):
        super().append(event)
        fields = {k: v for k, v in event.items() if k not in ('type', 'hashes')}
        # Only error events persist messages and paths; never log file contents.
        if event['type'] == 'error':
            fields.setdefault('code', 'OperationError')
        self.monitor.emit(event['type'], **fields)
