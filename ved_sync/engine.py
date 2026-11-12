"""Conservative multi-repository synchronizer; only Python's standard library."""
from __future__ import annotations

import hashlib
import fnmatch
import json
import os
import errno
import re
from pathlib import Path
import shutil
import tempfile
import time
import uuid
import gc
from dataclasses import dataclass

from .identity import is_internal, repository_identity, read_identity
from .telemetry import EventList, Monitor, token
from .state import load_state, dump_state, DiskStore

PROJECT = Path(__file__).resolve().parents[1]
DISK_STATE_BYTES = 8 * 1024 * 1024
IO_WINDOW = 16 * 1024 * 1024


def release_cache(stream, offset=0, length=0):
    """Release this stream's clean page cache where the OS supports it."""
    if hasattr(os, 'posix_fadvise') and hasattr(os, 'POSIX_FADV_DONTNEED'):
        try:
            os.posix_fadvise(stream.fileno(), offset, length, os.POSIX_FADV_DONTNEED)
        except OSError:
            pass


@dataclass(frozen=True, slots=True)
class Entry:
    digest: str
    size: int
    mtime_ns: int


def inspect(path: Path, progress=None) -> Entry:
    before = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        consumed = released = 0
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
            consumed += len(chunk)
            if consumed - released >= IO_WINDOW:
                release_cache(stream, released, consumed - released)
                released = consumed
            if progress:
                progress(len(chunk))
        release_cache(stream)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError(f'Archivo cambiado durante lectura: {path}')
    return Entry(h.hexdigest(), after.st_size, after.st_mtime_ns)


def inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


class Engine:
    def __init__(self, config: Path, *, apply: bool = False, allow_external: bool = False,
                 restore_projects: bool = False, console=None, reset_queue: bool = False):
        self.config_path = Path(config).resolve()
        self._checkpoint_enabled = False
        self._checkpoint_last = 0.0
        self._worklist = None
        cfg = json.loads(self.config_path.read_text(encoding='utf-8'))
        self.exclude_patterns = cfg.get('exclude_patterns', [])
        if not isinstance(self.exclude_patterns, list) or not all(
                isinstance(p, str) and p and not p.startswith('/') and '..' not in p.split('/')
                for p in self.exclude_patterns):
            raise ValueError('exclude_patterns debe contener patrones relativos no vacíos')
        self.authoritative_source = cfg.get('authoritative_source')
        self.restore_projects = restore_projects
        self.reset_queue = reset_queue
        if reset_queue and not (restore_projects and apply):
            raise ValueError('Reiniciar la cola requiere --restore-projects y --apply')
        self.integrity_seconds = float(cfg.get("integrity_seconds", 300))
        if not 0 <= self.integrity_seconds < float("inf"):
            raise ValueError("integrity_seconds debe ser un número finito >= 0")
        self.interval = float(cfg.get('interval_seconds', 5))
        if self.interval < 1:
            raise ValueError('interval_seconds debe ser >= 1')
        self.persistent_ids = cfg.get("persistent_ids", True)
        if not isinstance(self.persistent_ids, bool):
            raise ValueError("persistent_ids debe ser booleano")
        self.device_types = {}
        self.repository_labels = {}
        self.expected_ids = {}
        self.search_roots = {}
        self.discovery = {}
        self.read_only = set()
        self.optional_writes = set()
        self.repos = {}
        for repo in cfg['repositories']:
            name = repo['id']
            if not isinstance(name, str) or not name or name in self.repos:
                raise ValueError('Identificador vacío o duplicado')
            if repo.get('uuid') is not None:
                parsed = uuid.UUID(repo['uuid'])
                if parsed.version != 4 or parsed.variant != uuid.RFC_4122:
                    raise ValueError('uuid debe ser UUID v4')
                self.expected_ids[name] = str(parsed)
            device = repo.get('device_type', 'unknown')
            if device not in ('local', 'usb', 'network', 'unknown'):
                raise ValueError('device_type debe ser local, usb, network o unknown')
            self.device_types[name] = device
            label = repo.get('label', name)
            if not isinstance(label, str) or not label:
                raise ValueError('label debe ser texto no vacío')
            self.repository_labels[name] = label
            if not isinstance(repo.get('read_only', False), bool):
                raise ValueError('read_only debe ser booleano')
            if repo.get('read_only', False):
                self.read_only.add(name)
            policy = repo.get('write_policy', 'required')
            if policy not in ('required', 'if_possible'):
                raise ValueError('write_policy debe ser required o if_possible')
            if policy == 'if_possible':
                self.optional_writes.add(name)
            # Multiple platform-specific alternatives, resolved relative to config.
            candidates = repo.get('paths', [repo.get('path')])
            discovery = repo.get('mounted_subdirectory')
            if discovery is not None:
                if not isinstance(discovery, str):
                    raise ValueError('mounted_subdirectory debe ser texto')
                sub = Path(discovery)
                if not discovery or sub.is_absolute() or '..' in sub.parts or '\\' in discovery or ':' in discovery:
                    raise ValueError('mounted_subdirectory debe ser una carpeta relativa segura')
                self.discovery[name] = sub
                if candidates == [None]:
                    candidates = []
            if (not candidates and discovery is None) or not isinstance(candidates, list) or not all(isinstance(p, str) and p for p in candidates):
                raise ValueError('Cada repositorio requiere path o paths')
            self.repos[name] = [self.resolve(p) for p in candidates]
            roots = repo.get('search_roots', [])
            if not isinstance(roots, list) or not all(isinstance(p, str) and p for p in roots):
                raise ValueError('search_roots debe ser una lista de rutas')
            self.search_roots[name] = [self.resolve(p) for p in roots]
            if discovery is not None and (not roots or candidates):
                raise ValueError('El USB descubierto requiere search_roots y no admite rutas fijas')
        if len(self.repos) < 2:
            raise ValueError('Se requieren al menos dos repositorios')
        if self.authoritative_source is not None and self.authoritative_source not in self.read_only:
            raise ValueError('authoritative_source debe identificar un repositorio de solo lectura')
        if restore_projects:
            if not self.authoritative_source or len(self.repos) != 2:
                raise ValueError('La recuperación SRC-VED requiere un origen autoritativo y un destino')
            destinations = [p for n, paths in self.repos.items() if n != self.authoritative_source for p in paths]
            if destinations != [PROJECT.parent]:
                raise ValueError('La recuperación SRC-VED solo admite como destino el padre de VED-SYNC')
        all_paths = [p for paths in self.repos.values() for p in paths]
        for i, p in enumerate(all_paths):
            for q in all_paths[i + 1:]:
                if inside(p, q) or inside(q, p):
                    raise ValueError('Rutas de repositorios duplicadas o anidadas')
        self.state_dir = self.resolve(cfg.get('state_dir', '../.ved-sync'))
        if not inside(self.state_dir, PROJECT):
            raise ValueError('El registro debe permanecer dentro de VED-SYNC')
        if any((inside(self.state_dir, p) or inside(p, self.state_dir))
               and not (restore_projects and p == PROJECT.parent) for p in all_paths):
            raise ValueError('El registro debe estar separado de los repositorios')
        self.apply = apply
        self.allow_external = allow_external
        if apply:
            for name, paths in self.repos.items():
                if name not in self.read_only:
                    for p in paths:
                        self.check_write(p)
        self.status = {name: 'gris' for name in self.repos}
        self.state_file = self.state_dir / 'state.json'
        self._disk_store = None
        # Large checkpoints are loaded only after acquiring the cycle lock.
        self._state_deferred = (self.state_file.exists() and (self.restore_projects
                                or self.state_file.stat().st_size >= DISK_STATE_BYTES))
        self.state = {'files': {}} if self._state_deferred else load_state(self.state_file)
        self.monitor = Monitor(self.state_dir, cfg.get('project', self.config_path.stem), console,
                               cfg.get('timing_limit', 1000), location=PROJECT, audit=not self.restore_projects)
        self.events = EventList(self.monitor)
        self.active_paths = {}
        self.transfer_permissions = {}

    def resolve(self, value):
        return (self.config_path.parent / os.path.expandvars(os.path.expanduser(value))).resolve()

    def close(self):
        if self._disk_store is not None:
            self._disk_store.close()
            self._disk_store = None

    def check_write(self, path):
        path = path.resolve()
        if inside(path, Path('/mnt/windows')):
            raise ValueError('Prohibido escribir en /mnt/windows')
        if inside(path, PROJECT.parent) and not inside(path, PROJECT):
            if self.restore_projects and self.authoritative_source:
                return
            raise ValueError('Prohibido escribir en otros proyectos de SRC-VED')
        if not inside(path, PROJECT) and not self.allow_external:
            raise ValueError('Para repositorios externos se requiere --allow-external')

    def announce_transfer_policy(self, active):
        """Resolve permitted directions before inspecting or copying file contents."""
        transfers = []
        for source in self.repos:
            for target in self.repos:
                if source == target:
                    continue
                reason = None
                if target in self.read_only:
                    reason = 'solo lectura'
                elif self.authoritative_source and source != self.authoritative_source:
                    reason = 'origen no autorizado'
                elif source not in active or target not in active:
                    reason = 'repositorio no disponible'
                else:
                    try:
                        self.check_write(active[target])
                    except ValueError:
                        reason = 'destino protegido'
                    if reason is None and not os.access(active[target], os.W_OK | os.X_OK):
                        reason = 'sin permiso de escritura'
                    if reason is None and hasattr(os, 'statvfs') and hasattr(os, 'ST_RDONLY'):
                        try:
                            if os.statvfs(active[target]).f_flag & os.ST_RDONLY:
                                reason = 'sistema de archivos de solo lectura'
                        except OSError:
                            reason = 'no se puede comprobar el destino'
                transfers.append({'source': source, 'target': target,
                                  'source_label': self.repository_labels[source],
                                  'target_label': self.repository_labels[target],
                                  'allowed': reason is None, 'reason': reason})
        self.transfer_permissions = {(t['source'], t['target']): t for t in transfers}
        self.monitor.emit('transfer_policy', transfers=transfers)
        return transfers

    def available(self):
        active = {}
        identities = {}
        bindings = self.state.setdefault('repository_ids', {})
        candidates = {}
        fresh = set()
        for name, paths in self.repos.items():
            self.status[name] = 'gris'
            found = []
            paths = list(paths)
            expected = self.expected_ids.get(name, bindings.get(name))
            if expected:
                for search_root in self.search_roots[name]:
                    try:
                        # Bounded discovery: root and its immediate children only.
                        locations = [search_root] + sorted(search_root.iterdir())
                    except OSError:
                        continue
                    for location in locations:
                        if name in self.discovery:
                            # Never mount devices or select an arbitrary connected USB.
                            if location.is_symlink() or not os.path.ismount(location):
                                continue
                            location = location / self.discovery[name]
                            if any(p.is_symlink() for p in [location, *location.parents]):
                                continue
                        if location in paths or not location.is_dir() or location.is_symlink():
                            continue
                        try:
                            if read_identity(location) == expected:
                                paths.append(location)
                        except (OSError, ValueError):
                            continue
            for path in paths:
                if (inside(path, self.state_dir) or inside(self.state_dir, path)) and not (
                        self.restore_projects and path == PROJECT.parent):
                    self.status[name] = 'rojo'
                    self.events.append({'type': 'error', 'repository': name,
                                        'detail': 'El registro debe estar separado de los repositorios descubiertos',
                                        'code': 'ControlDirectoryOverlap'})
                    continue
                if not path.is_dir():
                    continue
                try:
                    # Simulation and disabled identities never write metadata.
                    writable = self.apply and name not in self.read_only
                    if writable and self.persistent_ids:
                        self.check_write(path)
                    if writable and self.persistent_ids and read_identity(path) is None:
                        fresh.add(path)
                    identity = repository_identity(path, writable and self.persistent_ids)
                    found.append((path, identity))
                    if identity:
                        identities.setdefault(identity, []).append((name, path))
                except (OSError, ValueError) as exc:
                    self.status[name] = 'rojo'
                    self.events.append({'type': 'error', 'repository': name, 'detail': str(exc), 'code': type(exc).__name__})
            candidates[name] = found
        duplicates = {identity for identity, locations in identities.items() if len(locations) > 1}
        for name, found in candidates.items():
            if self.status[name] == 'rojo':
                continue
            expected = self.expected_ids.get(name, bindings.get(name))
            if any(identity in duplicates for _, identity in found):
                detail = 'UUID duplicado: repositorios separados; sincronización bloqueada'
            else:
                matching = [(p, i) for p, i in found if expected and i == expected]
                selected = matching if matching else found
                if len(selected) > 1:
                    detail = 'Varias rutas disponibles para el mismo repositorio'
                elif selected:
                    path, identity = selected[0]
                    if expected and identity and identity != expected and path not in fresh:
                        detail = 'UUID distinto del repositorio esperado'
                    else:
                        active[name] = path
                        self.status[name] = 'amarillo'
                        if identity and self.apply:
                            bindings[name] = identity
                        continue
                else:
                    continue
            self.status[name] = 'rojo'
            self.events.append({'type': 'error', 'repository': name, 'detail': detail})
        names = list(active)
        blocked = set()
        for index, name in enumerate(names):
            for other in names[index + 1:]:
                if inside(active[name], active[other]) or inside(active[other], active[name]):
                    blocked.update((name, other))
        for name in blocked:
            active.pop(name)
            self.status[name] = 'rojo'
            self.events.append({'type': 'error', 'repository': name, 'detail': 'Rutas descubiertas duplicadas o anidadas'})
        return active

    def scan(self, root):
        self.monitor.emit('repository_scan', location=root)
        result = (self._disk_store.mapping('scan:' + uuid.uuid4().hex,
                  encode=lambda e: [e.digest, e.size, e.mtime_ns], decode=lambda e: Entry(*e))
                  if getattr(self, '_disk_store', None) is not None else {})
        def fail(error):
            raise error
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail):
            if self.monitor.active and self.monitor.project_progress:
                progress = self.monitor.project_progress
                self.monitor.project_update(progress['phase'], progress['percent'], progress['processed'], progress['total'])
            dirs[:] = [name for name in dirs if not self.excluded((Path(directory) / name).relative_to(root))]
            files = [name for name in files if not self.excluded((Path(directory) / name).relative_to(root))]
            if self.restore_projects and Path(directory) == root:
                # VED-SYNC on Ubuntu is the current working engine and is never restored.
                dirs[:] = [name for name in dirs if name.casefold() != PROJECT.name.casefold()]
                files = [name for name in files if name.casefold() != PROJECT.name.casefold()]
            for item in dirs + files:
                p = Path(directory) / item
                if p.is_symlink():
                    raise OSError(f'Enlace simbólico no admitido: {p}')
            for name in files:
                p = Path(directory) / name
                if not p.is_file():
                    raise OSError(f'Archivo especial no admitido: {p}')
                result[p.relative_to(root).as_posix()] = self.cached_inspect(p)
        return result

    def excluded(self, relative):
        # Path normalizes the root marker './'; actual dot-prefixed names stay excluded.
        parts = Path(relative).parts
        if any(part.startswith('.') or is_internal(part) for part in parts):
            return True
        for pattern in getattr(self, 'exclude_patterns', ()):
            pattern = pattern.casefold().rstrip('/')
            if '/' not in pattern:
                if any(fnmatch.fnmatchcase(part.casefold(), pattern) for part in parts):
                    return True
            elif any(fnmatch.fnmatchcase('/'.join(parts[:n]).casefold(), pattern)
                     for n in range(1, len(parts) + 1)):
                return True
        return False

    def cached_inspect(self, path):
        # Metadata is an optimization, never a replacement for periodic SHA-256.
        stat = path.stat()
        fingerprint = [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
                       stat.st_dev, stat.st_ino]
        cache = self.state.setdefault('hash_cache', {})
        key = str(path)
        previous = cache.get(key)
        now = time.time_ns()
        if (previous and previous['stat'] == fingerprint
                and 0 <= now - previous['verified_ns'] < self.integrity_seconds * 1e9):
            self.checkpoint()
            return Entry(previous['sha256'], stat.st_size, stat.st_mtime_ns)
        entry = self.inspect_file(path)
        cache[key] = {'stat': fingerprint, 'sha256': entry.digest, 'verified_ns': now}
        self.checkpoint()
        return entry

    def checkpoint(self, *, force=False):
        """Persist verified observations periodically while holding the cycle lock."""
        if not self._checkpoint_enabled:
            return
        now = time.monotonic()
        if force or now - self._checkpoint_last >= 30:
            if force or self._worklist is None:
                self.save()
            else:
                # FIFO receipts are already durable per operation; avoid exporting
                # the whole JSON while copying or checking the pending queue.
                self._worklist.flush()
            self._checkpoint_last = time.monotonic()
            event = self.monitor.emit('checkpoint', result='ok')
            if self._worklist is not None and event:
                self._worklist.trace('checkpoint', **{k: event[k] for k in
                    ('process_id', 'rss_bytes', 'peak_rss_bytes') if k in event})

    def save(self):
        if self._state_deferred:
            raise RuntimeError('El estado debe cargarse bajo bloqueo antes de guardarlo')
        self.state_dir.mkdir(parents=True, exist_ok=True)
        target = self.state_dir / ('state-' + uuid.uuid4().hex + '.tmp')
        try:
            with target.open('w', encoding='utf-8') as f:
                dump_state(self.state, f)
                f.flush()
                os.fsync(f.fileno())
                release_cache(f)
            os.replace(target, self.state_file)
        finally:
            target.unlink(missing_ok=True)

    def device(self, path):
        for name, root in self.active_paths.items():
            if inside(path, root):
                return self.device_types[name]
        return 'local' if inside(path, self.state_dir) else 'unknown'

    def inspect_file(self, path, transaction=None, parent=None, expected=None):
        with self.monitor.operation('sha256', path.stat().st_size, self.device(path), transaction) as operation:
            def advance(size):
                operation.advance(size)
                if parent:
                    parent.advance(size)
            entry = inspect(path, progress=advance)
            if expected is not None and entry.digest != expected:
                self.monitor.emit('verification', result='failed', transaction=transaction,
                                  path=path, expected_sha256=expected, sha256=entry.digest)
                raise OSError('Verificación SHA-256 fallida')
            self.monitor.emit('verification', result='ok', transaction=transaction,
                              path=path, sha256=entry.digest, expected_sha256=expected)
            return entry

    def _stream_copy(self, source, target, *, exclusive=False, operation='write', transaction=None, parent=None):
        with self.monitor.operation(operation, source.stat().st_size, self.device(target), transaction) as progress:
            with source.open('rb') as inp, target.open('xb' if exclusive else 'wb') as out:
                consumed = released = 0
                while chunk := inp.read(1024 * 1024):
                    out.write(chunk)
                    consumed += len(chunk)
                    if self.restore_projects and consumed - released >= IO_WINDOW:
                        out.flush()
                        os.fsync(out.fileno())
                        release_cache(inp, released, consumed - released)
                        release_cache(out, released, consumed - released)
                        released = consumed
                    progress.advance(len(chunk))
                    if parent:
                        parent.advance(len(chunk))
                out.flush()
                os.fsync(out.fileno())
                release_cache(inp)
                release_cache(out)
            shutil.copystat(source, target)

    def _publish(self, staged, target, transaction=None, parent=None):
        try:
            os.link(staged, target)  # Complete file, exclusive atomic publication.
        except OSError as exc:
            if exc.errno not in (errno.EPERM, errno.ENOTSUP, errno.EXDEV, errno.EOPNOTSUPP):
                raise
            # Unsupported filesystems retain exclusive creation and full verification.
            if parent:
                parent.total += staged.stat().st_size
            self._stream_copy(staged, target, exclusive=True, transaction=transaction, parent=parent)

    def _original(self, source, expected, transaction, parent=None):
        """Create immutable .original plus the legacy hash archive; verify both."""
        self.monitor.emit('backup_started', transaction=transaction, path=source, sha256=expected.digest)
        if self.inspect_file(source, transaction, parent) != expected:
            raise OSError('Destino cambiado antes del respaldo')
        directory = self.state_dir / 'versions'
        if directory.is_symlink():
            raise OSError('Directorio de respaldos enlazado no admitido')
        directory.mkdir(parents=True, exist_ok=True)
        for archive in (directory / (expected.digest + '.original'), directory / expected.digest):
            if archive.is_symlink():
                raise OSError('Respaldo enlazado no admitido')
            if not archive.exists():
                fd, temporary = tempfile.mkstemp(prefix='.ved-sync-backup-', dir=directory)
                os.close(fd)
                staged = Path(temporary)
                try:
                    self._stream_copy(source, staged, operation='backup', transaction=transaction, parent=parent)
                    # Never publish an unverified .original.
                    self.inspect_file(staged, transaction, parent, expected=expected.digest)
                    self._publish(staged, archive, transaction)
                finally:
                    staged.unlink(missing_ok=True)
            self.inspect_file(archive, transaction, parent, expected=expected.digest)
        self.monitor.emit('backup', transaction=transaction, path=source, sha256=expected.digest,
                          result='ok')

    def _file_work(self, source, target):
        missing = sum(not p.exists() for p in (
            self.state_dir / 'versions' / ((target.digest if target else '') + '.original'),
            self.state_dir / 'versions' / (target.digest if target else '')))
        return 5 * source.size + (5 + 2 * missing) * (target.size if target else 0)

    def copy(self, source, target, expected_source, expected_target, root):
        if self.excluded(target.relative_to(root)):
            raise ValueError('Archivo interno excluido de copias y versiones')
        self.check_write(target)
        cursor = target
        while cursor != root.parent:
            if cursor.is_symlink():
                raise OSError(f'Enlace simbólico: {cursor}')
            cursor = cursor.parent
        transaction = uuid.uuid4().hex
        self.monitor.emit('transaction_started', transaction=transaction, path=target,
                          sha256=expected_source.digest,
                          expected_sha256=expected_target.digest if expected_target else None)
        total = self._file_work(expected_source, expected_target)
        staged = None
        try:
            with self.monitor.operation('file', total, self.device(target), transaction) as progress:
                if self.inspect_file(source, transaction, progress) != expected_source:
                    raise OSError('Origen modificado desde el escaneo')
                if target.exists():
                    if expected_target is None or self.inspect_file(target, transaction, progress) != expected_target:
                        raise OSError('Destino modificado desde el escaneo')
                elif expected_target is not None:
                    raise OSError('Destino desaparecido desde el escaneo')
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temp = tempfile.mkstemp(prefix='.ved-sync-', dir=target.parent)
                os.close(fd)
                staged = Path(temp)
                self._stream_copy(source, staged, transaction=transaction, parent=progress)
                self.inspect_file(staged, transaction, progress, expected_source.digest)
                if self.inspect_file(source, transaction, progress) != expected_source:
                    raise OSError('Origen inestable')
                if expected_target is not None:
                    self._original(target, expected_target, transaction, progress)
                    if self.inspect_file(target, transaction, progress) != expected_target:
                        raise OSError('Destino cambiado durante el respaldo')
                self.monitor.emit('transaction_intent', transaction=transaction, path=target,
                                  sha256=expected_source.digest,
                                  expected_sha256=expected_target.digest if expected_target else None,
                                  durable=True)
                if expected_target is not None:
                    os.replace(staged, target)
                else:
                    self._publish(staged, target, transaction, progress)
                final_entry = self.inspect_file(target, transaction, progress, expected_source.digest)
                self.monitor.emit('transaction_committed', transaction=transaction, path=target,
                                  sha256=expected_source.digest, result='ok', durable=True)
                # File progress may finish only after durable confirmation.
            return final_entry
        except BaseException as exc:
            self.monitor.emit('transaction_unconfirmed', transaction=transaction, path=target,
                              code=type(exc).__name__, result='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                              durable=True)
            raise
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)

    def _run(self, action):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        lock = self.state_dir / 'run.lock'
        fd, advisory = self._acquire_lock(lock)
        result = 'failed'
        completed = False
        started = time.monotonic()
        try:
            if not advisory:
                os.write(fd, str(os.getpid()).encode())
            self.monitor.start(not self.apply)
            # Release the previous inventory before constructing its replacement.
            self.state = None
            if self._disk_store is not None:
                self._disk_store.close()
                self._disk_store = None
            gc.collect()
            if self.restore_projects or (self.state_file.exists()
                                        and self.state_file.stat().st_size >= DISK_STATE_BYTES):
                self._disk_store = DiskStore(self.state_dir / '.runtime-state.sqlite')
            self.state = load_state(self.state_file, self._disk_store)
            self._state_deferred = False
            if self._disk_store is not None:
                self.state.setdefault('files', self._disk_store.mapping('files'))
                self.state.setdefault('hash_cache', self._disk_store.mapping('hash_cache'))
            self._checkpoint_last = time.monotonic()
            self._checkpoint_enabled = self.apply
            self.monitor.emit('state_loaded', total=len(self.state['files']))
            report = action()
            result = 'ok' if all(s == 'verde' for s in report['status'].values()) else 'pending'
            completed = result == 'ok' and not any(e['type'].startswith('would_') for e in report['events'])
            return report
        except BaseException as exc:
            result = 'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed'
            if result == 'interrupted':
                try:
                    self.checkpoint(force=True)
                except Exception as checkpoint_error:
                    self.monitor.emit('checkpoint_failed', code=type(checkpoint_error).__name__,
                                      result='failed', durable=True)
            self.monitor.emit('interrupted' if result == 'interrupted' else 'error',
                              code=type(exc).__name__, result=result, detail=str(exc),
                              **({'path': exc.filename} if isinstance(exc, OSError) and exc.filename else {}),
                              durable=True)
            raise
        finally:
            try:
                timing_recorded = False
                try:
                    if self.monitor.active:
                        self.monitor.history.record('project', self._project_bytes, time.monotonic() - started,
                                                    'mixed', result)
                    timing_recorded = True
                finally:
                    self.monitor.close(result if timing_recorded else 'failed', completed=completed and timing_recorded)
            finally:
                self._checkpoint_enabled = False
                try:
                    if self._disk_store is not None:
                        self.close()
                        self.state = {'files': {}}
                        self._state_deferred = True
                finally:
                    try:
                        if advisory:
                            # Keep the inode: unlinking an advisory lock races the next owner.
                            os.ftruncate(fd, 0)
                            os.fsync(fd)
                    finally:
                        os.close(fd)
                        if not advisory:
                            lock.unlink(missing_ok=True)

    def _acquire_lock(self, lock):
        if self.restore_projects:
            try:
                import fcntl
            except ImportError:
                pass
            else:
                fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                try:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise RuntimeError(f'Otra ejecución activa: {lock}') from None
                    previous = os.read(fd, 4096).strip()
                    if previous:
                        try:
                            marker = json.loads(previous)
                        except (ValueError, UnicodeError):
                            marker = None
                        if not (isinstance(marker, dict) and marker.get('protocol') == 'flock-v1'):
                            if not previous.isdigit():
                                raise RuntimeError(f'Bloqueo antiguo no reconocible: {lock}')
                            try:
                                os.kill(int(previous), 0)
                            except ProcessLookupError:
                                pass
                            except PermissionError:
                                raise RuntimeError(f'Otra ejecución o bloqueo pendiente: {lock}') from None
                            else:
                                raise RuntimeError(f'Otra ejecución o bloqueo pendiente: {lock}')
                    os.ftruncate(fd, 0)
                    os.lseek(fd, 0, os.SEEK_SET)
                    os.write(fd, json.dumps({'protocol': 'flock-v1', 'pid': os.getpid()}).encode())
                    os.fsync(fd)
                    return fd, True
                except BaseException:
                    os.close(fd)
                    raise
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError(f'Otra ejecución o bloqueo pendiente: {lock}') from None
        return fd, False

    def run_once(self, on_status=None):
        self._project_bytes = 0
        return self._run(lambda: self._cycle(on_status))

    def recover(self, repository, relative, digest):
        """Explicit rollback: never recover without a fresh .original SHA-256."""
        self._project_bytes = 0
        path = Path(relative)
        if (not relative or path.is_absolute() or '..' in path.parts or '\\' in relative
                or self.excluded(path)):
            raise ValueError('Ruta de recuperación inválida')
        if repository not in self.repos or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Repositorio o SHA-256 inválido')
        if repository in self.read_only:
            raise ValueError('No se permite recuperar sobre un repositorio de solo lectura')
        def action():
            self.events = EventList(self.monitor)
            active = self.available()
            self.active_paths = active
            if repository not in active:
                raise ValueError('Repositorio no disponible o identidad ambigua')
            self.monitor.plan_files([path.as_posix()])
            record = self.state['files'].get(path.as_posix(), {})
            if digest not in {item['sha256'] for item in record.get('history', [])}:
                raise ValueError('La versión no pertenece al historial de este archivo')
            original = self.state_dir / 'versions' / (digest + '.original')
            if original.parent.is_symlink() or original.is_symlink():
                raise OSError('Respaldo enlazado no admitido')
            with self.monitor.operation('recovery' if self.apply else 'recovery_check',
                                        original.stat().st_size, self.device(active[repository] / path)) as recovery_progress:
                # This is uncached and occurs before touching the recovery destination.
                source = self.inspect_file(original, expected=digest)
                self.monitor.emit('recovery_verified', path=active[repository] / path, repository=repository,
                                  sha256=digest, result='ok', durable=True, location=active[repository])
                target = active[repository] / path
                if target.is_symlink() or any(p.is_symlink() for p in target.parents if inside(p, active[repository])):
                    raise OSError('Enlace en destino de recuperación')
                previous = self.inspect_file(target) if target.exists() else None
                if not self.apply:
                    self.events.append({'type': 'would_recover', 'repository': repository, 'path': path.as_posix()})
                    self.status[repository] = 'rojo'
                else:
                    self.monitor.project_update('recovery', 30, 0, source.size)
                    self.copy(original, target, source, previous, active[repository])
                    self._project_bytes = source.size
                    if previous and previous.digest not in {h['sha256'] for h in record['history']}:
                        record['history'].append({'sha256': previous.digest, 'time_ns': time.time_ns()})
                    self.state['files'][path.as_posix()] = record
                    self.save()
                    self.monitor.finish_file(path.as_posix())
                    recovery_progress.advance(source.size)
                    self.events.append({'type': 'recovery', 'repository': repository, 'path': path.as_posix()})
                    # A rollback is an explicit edit, not a fabricated synchronized head.
                    self.status[repository] = 'rojo'
                for name in active:
                    self.status[name] = 'rojo'  # Explicit recovery needs a new whole-project comparison.
                    self.monitor.emit('status', repository=name, status=self.status[name])
                return {'simulation': not self.apply, 'status': dict(self.status), 'events': self.events}
        return self._run(action)

    def _cycle(self, on_status):
        if self.restore_projects and self.apply:
            from .restore import run_restore
            return run_restore(self, on_status)
        self.events = EventList(self.monitor)
        self.monitor.emit('detection')
        active = self.available()
        self.active_paths = active
        self.announce_transfer_policy(active)
        for name, status in self.status.items():
            self.monitor.emit('status', repository=name, status=status,
                              location=active.get(name, next(iter(self.repos[name]), 'USB pendiente')))
        self.monitor.emit('comparison')
        self.monitor.project_update('comparison', None)
        if on_status:
            on_status(dict(self.status))
        scans = {}
        for name, root in active.items():
            try:
                scans[name] = self.scan(root)
            except OSError as exc:
                self.status[name] = 'gris' if isinstance(exc, PermissionError) else 'rojo'
                self.events.append({'type': 'error', 'repository': name, 'detail': str(exc),
                                    'code': type(exc).__name__, **({'path': exc.filename} if exc.filename else {})})
        jobs = []
        relatives = sorted(relative for relative in set(self.state['files']).union(*(set(s) for s in scans.values()))
                           if not self.excluded(relative))
        self.monitor.plan_files([relative for relative in relatives if self.authoritative_source is None
                                 or relative in scans.get(self.authoritative_source, {})])
        for index, relative in enumerate(relatives):
            self.monitor.project_update('comparison', 5 + 25 * index / max(1, len(relatives)))
            if any(is_internal(part) for part in Path(relative).parts):
                continue
            entries = {n: s[relative] for n, s in scans.items() if relative in s}
            record = self.state['files'].get(relative, {'seen': {}, 'head': None})
            if self.authoritative_source is not None:
                source_entry = entries.get(self.authoritative_source)
                if source_entry is None:
                    self.events.append({'type': 'preserved', 'path': relative,
                                        'detail': 'Solo en destino: se conserva; copia inversa no permitida'})
                    continue
                jobs.append((relative, entries, None, source_entry.digest, self.authoritative_source))
                continue
            if not entries:
                for n in scans:
                    self.status[n] = 'rojo'
                self.events.append({'type': 'pending', 'path': relative, 'detail': 'Archivo conocido ausente en todos los repositorios accesibles'})
                continue
            changed = {e.digest for n, e in entries.items() if record['seen'].get(n) != e.digest}
            hashes = {e.digest for e in entries.values()}
            if not changed and record['head'] and record['head'] not in hashes:
                for n in scans:
                    self.status[n] = 'rojo'
                self.events.append({'type': 'pending', 'path': relative, 'detail': 'La versión vigente está en un repositorio no disponible'})
                continue
            if record['head'] and any(
                e.digest != record['head'] and e.digest in changed and record['seen'].get(n) != record['head']
                for n, e in entries.items()
            ):
                for n in scans:
                    self.status[n] = 'rojo'
                self.events.append({'type': 'conflict', 'path': relative, 'detail': 'Edición basada en una versión antigua o desconocida'})
                continue
            if len(hashes) == 1:
                chosen = next(iter(hashes))
            elif len(changed) == 1 and all(
                record['head'] is None or record['seen'].get(n) == record['head']
                for n, e in entries.items() if e.digest in changed
            ):
                chosen = next(iter(changed))
            elif not changed and record['head'] in hashes:
                chosen = record['head']
            else:
                for n in scans:
                    self.status[n] = 'rojo'
                self.events.append({'type': 'conflict', 'path': relative, 'hashes': {n: e.digest for n, e in entries.items()}})
                continue
            source_name = next(n for n, e in entries.items() if e.digest == chosen)
            jobs.append((relative, entries, None, chosen, source_name))
        work = {(relative, name): self._file_work(entries[source_name], entries.get(name))
                for relative, entries, _, chosen, source_name in jobs for name in scans
                if name not in entries or entries[name].digest != chosen}
        payload = sum(entries[source_name].size
                      for _, entries, _, chosen, source_name in jobs for name in scans
                      if name not in entries or entries[name].digest != chosen)
        self.monitor.set_work(sum(work.values()), payload)
        for relative, entries, record, chosen, source_name in jobs:
            record = self.state['files'].get(relative, {'seen': {}, 'head': None})
            source = active[source_name] / relative
            for name in scans:
                current = entries.get(name)
                if current and current.digest == chosen:
                    continue
                permission = self.transfer_permissions[(source_name, name)]
                if not permission['allowed']:
                    self.status[name] = 'rojo'
                    self.events.append({'type': 'pending', 'repository': name, 'path': relative,
                                        'detail': 'Copia no permitida: ' + permission['reason']})
                    self.monitor.complete_file()
                    continue
                self.monitor.emit('transfer_direction',
                                  direction_source=self.repository_labels[source_name],
                                  direction_target=self.repository_labels[name])
                self.monitor.file_budget = work[(relative, name)]
                self.events.append({'type': 'copy' if self.apply else 'would_copy', 'path': relative, 'from': source_name, 'to': name})
                if not self.apply:
                    self.status[name] = 'rojo'
                    self.status[source_name] = 'rojo'
                    self.monitor.complete_file()
                    continue
                self.monitor.emit('synchronization', path=relative, repository=name, location=active[name])
                try:
                    copy_source, source_entry = source, entries[source_name]
                    recovering = source_name in self.read_only or (current is None and name in record['seen'])
                    if recovering:
                        # A known missing file is a recovery, not a first import.
                        # Protect and verify an .original before touching its destination.
                        self._original(source, source_entry, uuid.uuid4().hex)
                        copy_source = self.state_dir / 'versions' / (chosen + '.original')
                        source_entry = self.inspect_file(copy_source, expected=chosen)
                        self.monitor.emit('recovery_verified', path=active[name] / relative,
                                          repository=name, sha256=chosen, result='ok', durable=True)
                    entries[name] = self.copy(copy_source, active[name] / relative, source_entry, current, active[name])
                    self._project_bytes += entries[source_name].size
                    if recovering:
                        self.events.append({'type': 'recovery', 'path': relative, 'repository': name})
                except (OSError, ValueError) as exc:
                    self.status[name] = 'rojo'
                    denied = isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS)
                    kind = 'write_unavailable' if name in self.optional_writes and denied else 'error'
                    self.events.append({'type': kind, 'path': relative, 'repository': name,
                                        'detail': str(exc), 'code': type(exc).__name__})
                self.monitor.complete_file()
            if len(scans) == len(self.repos) and all(
                    name in entries and entries[name].digest == chosen for name in scans):
                self.monitor.finish_file(relative)
            if self.apply:
                history = record.get('history', [])
                if not history or history[-1]['sha256'] != chosen:
                    history = history + [{'sha256': chosen, 'time_ns': time.time_ns()}]
                self.state['files'][relative] = {
                    'head': chosen, 'history': history,
                    'seen': {**record['seen'], **{n: e.digest for n, e in entries.items() if e.digest == chosen}},
                    'observations': {n: {'sha256': e.digest, 'size': e.size, 'mtime_ns': e.mtime_ns} for n, e in entries.items()}
                }
                self.checkpoint()
        self.monitor.project_update('verification', 85, self._project_bytes, self._project_bytes)
        expected = {relative: chosen for relative, _, _, chosen, _ in jobs}
        jobs.clear()
        # Initial entries and superseded records are no longer needed.
        scans = {name: None for name in scans}
        record = entries = None
        gc.collect()
        # Re-scan before reporting green, including files introduced during copying.
        final_scans = {}
        for name in scans:
            try:
                final_scans[name] = {p: e.digest for p, e in self.scan(active[name]).items()}
            except OSError as exc:
                self.status[name] = 'gris' if isinstance(exc, PermissionError) else 'rojo'
                self.events.append({'type': 'error', 'repository': name, 'detail': str(exc),
                                    'code': type(exc).__name__, **({'path': exc.filename} if exc.filename else {})})
        if self.authoritative_source is not None:
            reference = final_scans.get(self.authoritative_source)
            equal = reference is not None and reference == expected and all(
                all(scan.get(relative) == digest for relative, digest in reference.items())
                for scan in final_scans.values())
        else:
            equal = bool(final_scans) and all(s == next(iter(final_scans.values()))
                                              for s in final_scans.values())
        if not equal:
            for name in scans:
                self.status[name] = 'rojo'
        # Authoritative recovery verifies the source files, preserving destination extras.
        all_present = len(scans) == len(final_scans) == len(self.repos)
        if any(s == 'rojo' for s in self.status.values()):
            for name in scans:
                self.status[name] = 'rojo'
        for name in scans:
            if self.status[name] == 'amarillo':
                self.status[name] = 'verde' if all_present else 'rojo'
        self.monitor.reconcile_files(
            relative for relative, chosen in expected.items()
            if len(final_scans) == len(self.repos)
            and all(scan.get(relative) == chosen for scan in final_scans.values()))
        self.monitor.project_update('confirmation', 98, self._project_bytes, self._project_bytes)
        if self.apply:
            self.save()
        for name, status in self.status.items():
            self.monitor.emit('status', repository=name, status=status)
        if on_status:
            on_status(dict(self.status))
        return {'simulation': not self.apply, 'status': dict(self.status), 'events': self.events}
