"""Durable FIFO recovery work for VED-SYNC, by Víctor Estrada Díaz."""
import json
import sqlite3
import os
import csv
import hashlib
import shutil
from datetime import datetime, timezone


def append_trace(log_path, event, /, *, durable=False, limit=4 * 1024 * 1024, **fields):
    """Append a bounded local record, including after the queue has closed."""
    previous = log_path.with_name(log_path.name + '.1')
    if log_path.is_symlink() or previous.is_symlink():
        raise OSError('Registro de cola enlazado no admitido')
    if log_path.exists() and log_path.stat().st_size >= limit:
        log_path.replace(previous)
    with log_path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'date': datetime.now(timezone.utc).isoformat(),
                                'event': event, **fields}, ensure_ascii=True) + '\n')
        if durable:
            stream.flush()
            os.fsync(stream.fileno())


class WorkList:
    """Each confirmed file survives process death independently of state.json."""
    LOG_LIMIT = 4 * 1024 * 1024
    def __init__(self, path, signature, routes=(1, 2)):
        self.path = path
        self.routes = list(routes)
        self.index_path = path.with_name('.ved-sync-fifo.sqlite')
        self.history_path = path.with_name(path.stem + '.historial')
        if path.is_symlink() or self.history_path.is_symlink() or self.index_path.is_symlink():
            raise OSError('Cola enlazada no admitida')
        self._migrate_binary_queue()
        self.connection = sqlite3.connect(self.index_path)
        self._progress = None
        self.log_path = path.with_name(path.name + '.log')
        try:
            self.connection.execute('PRAGMA journal_mode=DELETE')
            self.connection.execute('PRAGMA synchronous=FULL')
            self.connection.execute('PRAGMA cache_size=-2048')
            self.connection.execute('ATTACH DATABASE ? AS history', (str(self.history_path),))
            self.connection.execute('PRAGMA history.journal_mode=DELETE')
            self.connection.execute('PRAGMA history.synchronous=FULL')
            self.connection.execute('PRAGMA history.cache_size=-2048')
            self.connection.executescript('''
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS history.binding (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS history.inventory (
                    id INTEGER PRIMARY KEY, path TEXT UNIQUE, status TEXT NOT NULL,
                    weight INTEGER NOT NULL, size INTEGER NOT NULL, data TEXT NOT NULL,
                    seen INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS history.job_status ON inventory(status, id);
                CREATE TABLE IF NOT EXISTS pending_copy (sequence INTEGER PRIMARY KEY, job_id INTEGER UNIQUE);
                CREATE TABLE IF NOT EXISTS pending_review (sequence INTEGER PRIMARY KEY, job_id INTEGER UNIQUE);
            ''')
            previous = self.meta('signature')
            saved = self.connection.execute('SELECT value FROM history.binding WHERE key=?', ('signature',)).fetchone()
            saved = json.loads(saved[0]) if saved else None
            if ((previous is not None and previous != signature)
                    or (saved is not None and saved != signature)):
                raise ValueError('La configuración no coincide con la cola persistente; '
                                 'conservar y revisar VED-Sync.cola antes de cambiar el plan')
            if previous is not None and saved is None:
                raise ValueError('Falta el historial de la cola; no se modifica el plan pendiente')
            self.set_meta('signature', signature)
            self.set_meta('routes', self.routes)
            self.connection.execute('INSERT OR REPLACE INTO history.binding VALUES (?,?)',
                                    ('signature', json.dumps(signature)))
            if previous is None:
                self.connection.execute("INSERT OR IGNORE INTO pending_copy(job_id) SELECT id FROM inventory WHERE status='pending' ORDER BY id")
                self.connection.execute("INSERT OR IGNORE INTO pending_review(job_id) SELECT id FROM inventory WHERE status='done' ORDER BY id")
            self.connection.commit()
            self.export_pending()
        except BaseException:
            self.connection.close()
            raise

    def meta(self, key, default=None):
        row = self.connection.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        self.connection.execute('INSERT OR REPLACE INTO metadata VALUES (?, ?)',
                                (key, json.dumps(value, ensure_ascii=False)))

    def flush(self):
        self.connection.commit()

    def _migrate_binary_queue(self):
        if not self.path.exists():
            return
        with self.path.open('rb') as stream:
            binary = stream.read(16) == b'SQLite format 3\x00'
        if not binary:
            return
        if self.index_path.exists():
            raise ValueError('Existen dos índices de cola; se conservan para revisión')
        backup = self.path.parent / 'queue-backups' / 'text-format'
        backup.mkdir(parents=True, exist_ok=True)
        for source in (self.path, self.history_path):
            if not source.exists():
                continue
            destination = backup / source.name
            if not destination.exists():
                shutil.copy2(source, destination)
            def digest(file):
                h = hashlib.sha256()
                with file.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        h.update(chunk)
                return h.digest()
            if digest(source) != digest(destination):
                raise OSError('Respaldo de conversión de cola no verificado')
        self.path.replace(self.index_path)

    def export_pending(self):
        """Publish only pending copies as origin;destination;relative_path text."""
        temporary = self.path.with_name(self.path.name + '.tmp')
        if self.path.is_symlink() or temporary.is_symlink():
            raise OSError('Vista de cola enlazada no admitida')
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream, delimiter=';', lineterminator='\n')
                for job in self.jobs(('pending',)):
                    writer.writerow([job['data'].get('origin', self.routes[0]),
                                     job['data'].get('destination', self.routes[1]), job['path']])
                stream.flush()
                os.fsync(stream.fileno())
                if hasattr(os, 'posix_fadvise'):
                    try:
                        os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
                    except OSError:
                        pass
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def trace(self, event, **fields):
        # One bounded text log and one previous segment, separate from pending work.
        append_trace(self.log_path, event, limit=self.LOG_LIMIT, **fields)

    @staticmethod
    def unpack(row):
        return {'id': row[0], 'path': row[1], 'status': row[2], 'weight': row[3],
                'size': row[4], 'data': json.loads(row[5]), 'seen': row[6]}

    def get(self, path):
        row = self.connection.execute('SELECT * FROM inventory WHERE path=?', (path,)).fetchone()
        return self.unpack(row) if row else None

    def add(self, path, source, *, done=False, result=None, seen=0, source_stat=None, target_stat=None):
        data = {'source': list(source), 'result': result, 'source_stat': source_stat,
                'target_stat': target_stat, 'verified_ns': None,
                'origin': self.routes[0], 'destination': self.routes[1]}
        cursor = self.connection.execute('INSERT OR IGNORE INTO inventory(path,status,weight,size,data,seen) '
                                'VALUES (?,?,?,?,?,?)', (path, 'done' if done else 'pending',
                                max(1, 5 * source[1]), source[1], json.dumps(data), seen))
        if cursor.rowcount:
            self._progress = None
            table = 'pending_review' if done else 'pending_copy'
            self.connection.execute(f'INSERT INTO {table}(job_id) VALUES (?)', (cursor.lastrowid,))

    def update(self, job, status, *, durable=True):
        previous_status = job['status']
        previous = (self.connection.execute('SELECT status,weight,size FROM inventory WHERE id=?',
                    (job['id'],)).fetchone() if self._progress is not None else None)
        self.connection.execute('UPDATE inventory SET status=?, weight=?, size=?, data=?, seen=? WHERE id=?',
                                (status, job['weight'], job['size'], json.dumps(job['data']),
                                 job['seen'], job['id']))
        for table, needed in [('pending_copy', status == 'pending'), ('pending_review', status == 'done')]:
            if needed:
                self.connection.execute(f'INSERT OR IGNORE INTO {table}(job_id) VALUES (?)', (job['id'],))
            else:
                self.connection.execute(f'DELETE FROM {table} WHERE job_id=?', (job['id'],))
        job['status'] = status
        if previous is not None:
            self._adjust(previous[0], previous[1], previous[2], -1)
            self._adjust(status, job['weight'], job['size'], 1)
        if durable:
            self.flush()
            if status == 'pending' or previous_status == 'pending':
                self.export_pending()
            self.trace({'done': 'copy_confirmed', 'verified': 'verification_confirmed',
                        'pending': 'pending', 'absent': 'source_absent'}[status], path=job['path'])

    def touch(self, job, epoch):
        self.connection.execute('UPDATE inventory SET seen=? WHERE id=?', (epoch, job['id']))

    def jobs(self, statuses=None):
        """Keyset iteration allows commits and updates without replaying rows."""
        if statuses in (('pending',), ('done',)):
            table = 'pending_copy' if statuses == ('pending',) else 'pending_review'
            last = 0
            while True:
                row = self.connection.execute(f'SELECT p.sequence, i.* FROM {table} p JOIN inventory i '
                    'ON i.id=p.job_id WHERE p.sequence>? ORDER BY p.sequence LIMIT 1', (last,)).fetchone()
                if row is None:
                    return
                last = row[0]
                yield self.unpack(row[1:])
        last = 0
        while True:
            query = 'SELECT * FROM inventory WHERE id>?'
            parameters = [last]
            if statuses:
                query += ' AND status IN (' + ','.join('?' for _ in statuses) + ')'
                parameters.extend(statuses)
            row = self.connection.execute(query + ' ORDER BY id LIMIT 1', parameters).fetchone()
            if row is None:
                return
            last = row[0]
            yield self.unpack(row)

    def progress(self):
        if self._progress is not None:
            return dict(self._progress)
        row = self.connection.execute('''SELECT count(*), coalesce(sum(weight),0),
            coalesce(sum(CASE WHEN status IN ('done','verified') THEN 1 ELSE 0 END),0),
            coalesce(sum(CASE WHEN status IN ('done','verified') THEN weight ELSE 0 END),0),
            coalesce(sum(CASE WHEN status='verified' THEN 1 ELSE 0 END),0),
            coalesce(sum(size),0) FROM inventory WHERE status!='absent' ''').fetchone()
        self._progress = dict(zip(('total', 'work', 'done', 'processed', 'verified', 'bytes'), row))
        return dict(self._progress)

    def _adjust(self, status, weight, size, direction):
        if status == 'absent':
            return
        for key, amount in [('total', 1), ('work', weight), ('bytes', size),
                            ('done', int(status in ('done', 'verified'))),
                            ('processed', weight if status in ('done', 'verified') else 0),
                            ('verified', int(status == 'verified'))]:
            self._progress[key] += direction * amount

    def close(self):
        self.connection.close()

    def attempt(self, new_cycle=False):
        marker = self.progress()
        previous = self.meta('attempt_marker')
        advanced = (previous is not None and
                    (marker['done'] > previous['done'] or marker['verified'] > previous['verified']
                     or marker['processed'] > previous['processed']))
        stalled = (self.meta('stalled_attempts', 0) + 1
                   if previous is not None and not advanced and not new_cycle
                   and marker['verified'] < marker['total'] else 0)
        if advanced or new_cycle:
            self.set_meta('auto_rebuilt', False)
        self.set_meta('stalled_attempts', stalled)
        self.set_meta('attempt_marker', marker)
        self.flush()
        return stalled >= 2 and not self.meta('auto_rebuilt', False)
