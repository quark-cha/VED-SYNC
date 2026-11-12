"""On-demand local cleanup for VED-SYNC, by Víctor Estrada Díaz.

https://estradad.es/ — Code: HL3; https://estradad.es/licencia.php
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import uuid

try:
    import fcntl
except ImportError:
    fcntl = None

PROJECT = Path(__file__).resolve().parents[1]
PROTECTED = {'backups', 'queue-backups', 'versions', '.git'}
LOG = re.compile(r'(?:operaciones\.jsonl?|tiempo\.csv|VED-Sync\.cola\.log)(?:\.\d+)?$', re.I)
ACTIVITY_LOG = re.compile(r'(?:operaciones\.jsonl?|VED-Sync\.cola\.log)(?:\.\d+)?$', re.I)
TEMP = re.compile(r'(?:state-[0-9a-f]{32}\.tmp|\.ved-sync-(?:timing|state)-[^/]+|'
                  r'\.runtime-state\.sqlite(?:-journal|-wal|-shm)?|VED-Sync\.cola\.tmp)$', re.I)
QUEUE = re.compile(r'(?:VED-Sync\.(?:cola|historial)|\.ved-sync-fifo\.sqlite)'
                   r'(?:-journal|-wal|-shm|-mj[0-9a-f]+)?$', re.I)


def local(project, path):
    """Reject escapes and symlinks before considering or removing a file."""
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(project):
        raise ValueError(f'Ruta fuera de VED-SYNC: {path}')
    current = project
    for part in path.relative_to(project).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f'La limpieza no sigue enlaces: {current}')
    return path


def controls(project, config=None):
    found = set()
    base = local(project, project / '.ved-sync')
    if config is None and base.is_dir():
        def fail(error):
            raise error
        for directory, dirs, files in os.walk(base, followlinks=False, onerror=fail):
            dirs[:] = [n for n in dirs if n not in PROTECTED]
            for name in dirs:
                local(project, Path(directory) / name)
            if any(n in ('state.json', 'run.lock') or LOG.fullmatch(n) or TEMP.fullmatch(n)
                   or QUEUE.fullmatch(n) for n in files):
                found.add(local(project, Path(directory)))
    configs = ([config] if config is not None else
               [project / '.ved-sync-config.json', project / '.ved-sync-recuperacion.json',
                project / 'config/example.json'])
    for config_path in configs:
        config_path = local(project, project / config_path if not config_path.is_absolute() else config_path)
        if not config_path.exists() and config is None:
            continue
        cfg = json.loads(config_path.read_text(encoding='utf-8'))
        value = cfg.get('state_dir', '../.ved-sync')
        if not isinstance(value, str):
            raise ValueError(f'state_dir inválido: {config_path}')
        directory = local(project, config_path.parent / os.path.expandvars(os.path.expanduser(value)))
        if any(p in PROTECTED for p in directory.relative_to(project).parts):
            raise ValueError(f'Directorio protegido: {directory}')
        if directory.is_dir():
            found.add(directory)
    return sorted(found)


def pid_alive(pid):
    if pid <= 0:
        raise ValueError('PID de bloqueo inválido')
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def control_lock(project, directory, preview):
    """Hold the engine lock; a new marker also excludes legacy O_EXCL runs."""
    lock = local(project, directory / 'run.lock')
    created = stale = locked = completed = False
    fd = None
    try:
        if preview:
            try:
                fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
            except FileNotFoundError:
                yield
                return
        else:
            try:
                fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                created = True
            except FileExistsError:
                fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, (fcntl.LOCK_SH if preview else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError:
            raise RuntimeError(f'Hay una ejecución activa: {directory}') from None
        marker = os.read(fd, 4096).strip()
        if marker:
            if marker.isdigit():
                if pid_alive(int(marker)):
                    raise RuntimeError(f'Hay una ejecución activa: {directory}')
                stale = True
            else:
                try:
                    value = json.loads(marker)
                except (ValueError, UnicodeError):
                    value = None
                if not isinstance(value, dict) or value.get('protocol') != 'flock-v1':
                    raise RuntimeError(f'Bloqueo no reconocido; se conserva: {lock}')
        if created:
            os.write(fd, str(os.getpid()).encode('ascii'))
            os.fsync(fd)
        yield
        completed = True
    finally:
        if fd is not None:
            # All removals are over before unlinking our temporary/legacy marker.
            try:
                if not preview and locked and (created or (stale and completed)):
                    local(project, lock)
                    if lock.exists() and (lock.stat().st_dev, lock.stat().st_ino) == (
                            os.fstat(fd).st_dev, os.fstat(fd).st_ino):
                        lock.unlink()
            finally:
                os.close(fd)


@dataclass(frozen=True)
class Artifact:
    path: Path
    fingerprint: tuple

    @classmethod
    def inspect(cls, project, path):
        path = local(project, path)
        value = path.stat()
        if not stat.S_ISREG(value.st_mode):
            raise ValueError(f'No es un archivo regular: {path}')
        return cls(path, (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns))

    def check(self, project):
        if self != Artifact.inspect(project, self.path):
            raise RuntimeError(f'Archivo cambiado durante la limpieza: {self.path}')

    def remove(self, project):
        self.check(project)
        descriptor = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parts = self.path.relative_to(project).parts
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            value = os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)
            observed = (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
            if not stat.S_ISREG(value.st_mode) or observed != self.fingerprint:
                raise RuntimeError(f'Archivo cambiado durante la limpieza: {self.path}')
            os.unlink(parts[-1], dir_fd=descriptor)
        finally:
            os.close(descriptor)


def reset_activity_logs(directory, active_name, *, project=PROJECT):
    """Start a fresh activity log while the engine owns this control's run.lock."""
    project = Path(project).resolve()
    directory = local(project, directory)
    if not ACTIVITY_LOG.fullmatch(active_name) or Path(active_name).name != active_name:
        raise ValueError('Nombre de registro de actividad inválido')
    artifacts = [Artifact.inspect(project, p) for p in directory.iterdir()
                 if ACTIVITY_LOG.fullmatch(p.name)]
    for artifact in artifacts:
        artifact.check(project)
    current = next((a for a in artifacts if a.path.name == active_name), None)
    for artifact in artifacts:
        if artifact != current:
            if os.name == 'posix':
                artifact.remove(project)
            else:
                artifact.check(project)
                artifact.path.unlink()
    if current:
        current.check(project)
        descriptor = os.open(current.path, os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            value = os.fstat(descriptor)
            fingerprint = (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
            if not stat.S_ISREG(value.st_mode) or fingerprint != current.fingerprint:
                raise RuntimeError(f'Archivo cambiado durante la limpieza: {current.path}')
            # Preserve the active inode so viewers following the open file see the reset.
            os.ftruncate(descriptor, 0)
        finally:
            os.close(descriptor)


def finished_queue(project, directory):
    if not local(project, directory / 'state.json').is_file():
        return False
    index = local(project, directory / '.ved-sync-fifo.sqlite')
    history = local(project, directory / 'VED-Sync.historial')
    if not index.is_file() or not history.is_file():
        return False
    if any(p.name.endswith(('-journal', '-wal', '-shm')) for p in directory.iterdir()):
        return False  # Preserve recovery journals; they may carry unmerged receipts.
    try:
        with closing(sqlite3.connect(index.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            row = db.execute("SELECT value FROM metadata WHERE key='complete'").fetchone()
            if row is None or json.loads(row[0]) is not True:
                return False
            signature = db.execute("SELECT value FROM metadata WHERE key='signature'").fetchone()
        with closing(sqlite3.connect(history.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            if signature is None or db.execute("SELECT value FROM binding WHERE key='signature'").fetchone() != signature:
                return False
            return db.execute("SELECT 1 FROM inventory WHERE status NOT IN ('verified','absent') LIMIT 1").fetchone() is None
    except (sqlite3.Error, ValueError):
        return False


def plan(project, directories, reset):
    disposable, queues, notes, empty_dirs = [], [], [], []
    for directory in directories:
        queue_files = []
        for path in sorted(directory.iterdir()):
            if LOG.fullmatch(path.name) or TEMP.fullmatch(path.name):
                disposable.append(Artifact.inspect(project, path))
            elif QUEUE.fullmatch(path.name):
                queue_files.append(Artifact.inspect(project, path))
        if queue_files:
            if reset or finished_queue(project, directory):
                queues.append(queue_files)
            else:
                notes.append(f'Cola pendiente o sin cierre confirmado conservada: {directory.relative_to(project)}')
        versions = local(project, directory / 'versions')
        if versions.is_dir():
            disposable.extend(Artifact.inspect(project, p) for p in versions.iterdir()
                              if p.name.startswith('.ved-sync-backup-'))
    for start in (project / '__pycache__', project / 'ved_sync', project / 'tests', project / 'tools'):
        local(project, start)
        if not start.is_dir():
            continue
        for directory, dirs, files in os.walk(start, followlinks=False):
            dirs[:] = [n for n in dirs if not n.startswith('.') and n not in PROTECTED]
            for name in dirs:
                local(project, Path(directory) / name)
            current = Path(directory)
            if current.name == '__pycache__':
                disposable.extend(Artifact.inspect(project, current / n) for n in files
                                  if n.endswith(('.pyc', '.pyo')))
                empty_dirs.append(current)
    empty_dirs.append(local(project, project / '.test-runs'))
    return list(dict.fromkeys(disposable)), queues, notes, empty_dirs


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def archive_queues(project, queues):
    if not queues:
        return None
    name = 'limpieza-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8]
    backup = local(project, project / '.ved-sync/backups' / name)
    backup.mkdir(parents=True)
    manifest = {}
    for group in queues:
        for artifact in group:
            artifact.check(project)
            destination = backup / artifact.path.relative_to(project)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(artifact.path, destination)
            expected = digest(artifact.path)
            if digest(destination) != expected:
                raise OSError(f'Respaldo no verificado: {artifact.path}')
            artifact.check(project)
            with destination.open('rb') as stream:
                os.fsync(stream.fileno())
            manifest[str(artifact.path.relative_to(project))] = expected
    with (backup / 'sha256.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return backup


def retirement_order(artifact):
    name = artifact.path.name.casefold()
    # Remove history before its index. An interrupted retirement must never leave
    # an old verified inventory attached to a fresh index without integrity timers.
    family = (0 if name.startswith('ved-sync.historial') else
              1 if name.startswith('.ved-sync-fifo.sqlite') else 2)
    return (artifact.path.parent, family, name)


def main(argv=None, *, project=PROJECT):
    parser = argparse.ArgumentParser(
        prog='limpieza.sh', add_help=False, description='Limpieza local de VED-SYNC, bajo petición.',
        epilog='Conserva estado, configuración, identidades y respaldos .original/versions/backups. '
               'Rechaza ejecuciones activas. Una cola retirada se reconstruye y verifica en el siguiente arranque.')
    parser._optionals.title = 'Opciones'
    parser.add_argument('-h', '--help', action='help', help='Mostrar esta ayuda y salir')
    parser.add_argument('--simular', action='store_true', help='Mostrar qué se retiraría, sin borrar ni crear respaldos')
    parser.add_argument('--reiniciar-colas', action='store_true',
                        help='Retirar también colas pendientes, con respaldo SHA-256; se reconstruirán al arrancar')
    parser.add_argument('--config', type=Path, help='Limitar los registros y colas al directorio de control de este JSON')
    args = parser.parse_args(argv)
    project = Path(project).resolve()
    try:
        if fcntl is None:
            raise RuntimeError('La limpieza requiere flock; ejecutar en Ubuntu/Linux.')
        directories = controls(project, args.config)
        with ExitStack() as stack:
            for directory in directories:
                stack.enter_context(control_lock(project, directory, args.simular))
            disposable, queues, notes, empty_dirs = plan(project, directories, args.reiniciar_colas)
            all_files = disposable + sorted((a for group in queues for a in group), key=retirement_order)
            if args.simular:
                for artifact in disposable:
                    print('Borrar:', artifact.path.relative_to(project))
                for group in queues:
                    print('Respaldar y retirar cola:', group[0].path.parent.relative_to(project),
                          f'({len(group)} archivos)')
                print(f'Simulación: {len(all_files)} archivos seleccionados; no se ha borrado nada.')
            else:
                backup = archive_queues(project, queues)
                # Validate the whole selection before deleting any selected file.
                for artifact in all_files:
                    artifact.check(project)
                for artifact in all_files:
                    artifact.remove(project)
                for directory in sorted(set(empty_dirs), key=lambda p: len(p.parts), reverse=True):
                    local(project, directory)
                    if directory.is_dir() and not any(directory.iterdir()):
                        directory.rmdir()
                print(f'Limpieza terminada: {len(all_files)} archivos retirados.')
                if backup:
                    print('Respaldo verificado de colas:', backup.relative_to(project))
            for note in notes:
                print(note)
            print('Conservados: configuración, estado, identidades, fuentes y respaldos .original/versions/backups.')
        return 0
    except KeyboardInterrupt:
        print('Limpieza interrumpida. Las colas se respaldan antes de retirarlas.', file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(f'Limpieza cancelada: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
