"""Repository-local identity, independent of file version selection."""
import os
from pathlib import Path
import tempfile
import uuid

IDENTITY_FILE = '.ved-sync-id'
LOCAL_CONFIG_FILE = '.ved-sync-config.json'
# .git may be a directory or a worktree file; both remain local.
INTERNAL_FILES = frozenset({IDENTITY_FILE, LOCAL_CONFIG_FILE, '.git', '.test-runs'})
INTERNAL_PREFIXES = ('.ved-sync-',)
INTERNAL_SUFFIXES = ('.original',)
LOCAL_QUEUE_FILES = frozenset('ved-sync.cola' + suffix for suffix in
                            ('', '-journal', '-wal', '-shm', '.log', '.log.1', '.tmp'))
LOCAL_HISTORY_FILES = frozenset('ved-sync.historial' + suffix for suffix in ('', '-journal', '-wal', '-shm'))
LOCAL_AUDIT_FILES = frozenset({'operaciones.jsonl', 'operaciones.json', 'tiempo.csv'})


def is_internal(name):
    return (name in INTERNAL_FILES or name.casefold() == '.test-runs' or name.startswith(INTERNAL_PREFIXES)
            or name.endswith(INTERNAL_SUFFIXES) or name.casefold() in LOCAL_QUEUE_FILES
            or name.casefold() in LOCAL_HISTORY_FILES or name.casefold() in LOCAL_AUDIT_FILES
            or name.casefold().startswith('ved-sync.cola-mj'))


def read_identity(root):
    path = root / IDENTITY_FILE
    if path.is_symlink():
        raise ValueError('El identificador no puede ser un enlace simbólico')
    try:
        with path.open('rb') as stream:
            value = stream.read(128)
    except FileNotFoundError:
        return None
    parsed = uuid.UUID(value.decode('ascii').strip())
    if parsed.version != 4 or parsed.variant != uuid.RFC_4122:
        raise ValueError('Se requiere un UUID v4')
    return str(parsed)


def repository_identity(root, create=False):
    value = read_identity(root)
    if value is not None or not create:
        return value
    staged = None
    try:
        # Publish a fully written file without ever replacing an existing ID.
        fd, temp = tempfile.mkstemp(prefix='.ved-sync-id-', dir=root)
        staged = Path(temp)
        with os.fdopen(fd, 'w', encoding='ascii') as stream:
            stream.write(str(uuid.uuid4()) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(staged, root / IDENTITY_FILE)
        except FileExistsError:
            pass  # Another process won: read its complete identity below.
    except OSError:
        # Read-only media or filesystems without atomic hard links stay ID-less.
        return read_identity(root)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    return read_identity(root)
