"""Read large legacy JSON checkpoints without holding their full text in RAM."""
import json
import sys
import sqlite3
from collections.abc import MutableMapping, Mapping


class DiskMap(MutableMapping):
    """JSON records in a bounded SQLite working cache, one record at a time."""
    def __init__(self, store, section, encode=None, decode=None):
        self.store, self.section = store, section
        self.encode = encode or (lambda value: value)
        self.decode = decode or (lambda value: value)

    def __getitem__(self, key):
        row = self.store.connection.execute(
            'SELECT value FROM records WHERE section=? AND key=?', (self.section, key)).fetchone()
        if row is None:
            raise KeyError(key)
        return self.decode(json.loads(row[0]))

    def __setitem__(self, key, value):
        self.store.connection.execute('INSERT OR REPLACE INTO records VALUES (?, ?, ?)',
            (self.section, key, json.dumps(self.encode(value), ensure_ascii=False, separators=(',', ':'))))

    def __delitem__(self, key):
        if not self.store.connection.execute('DELETE FROM records WHERE section=? AND key=?',
                (self.section, key)).rowcount:
            raise KeyError(key)

    def __contains__(self, key):
        return self.store.connection.execute('SELECT 1 FROM records WHERE section=? AND key=?',
                                             (self.section, key)).fetchone() is not None

    def __iter__(self):
        for row in self.store.connection.execute('SELECT key FROM records WHERE section=?', (self.section,)):
            yield row[0]

    def __len__(self):
        return self.store.connection.execute('SELECT count(*) FROM records WHERE section=?',
                                             (self.section,)).fetchone()[0]

    def items(self):
        for key, value in self.store.connection.execute(
                'SELECT key, value FROM records WHERE section=?', (self.section,)):
            yield key, self.decode(json.loads(value))


class DiskStore:
    """Disposable working data; the atomically saved JSON remains authoritative."""
    def __init__(self, path):
        self.path, self.connection = path, None
        if path.is_symlink():
            raise OSError('Caché de trabajo enlazada no admitida')
        path.unlink(missing_ok=True)  # Only used while holding the engine's run.lock.
        try:
            self.connection = sqlite3.connect(path)
            self.connection.execute('PRAGMA journal_mode=OFF')
            self.connection.execute('PRAGMA synchronous=OFF')
            self.connection.execute('PRAGMA cache_size=-4096')
            self.connection.execute('PRAGMA temp_store=FILE')
            self.connection.execute('CREATE TABLE records (section TEXT, key TEXT, value TEXT, '
                                    'PRIMARY KEY(section, key)) WITHOUT ROWID')
        except BaseException:
            self.close()
            raise

    def mapping(self, section, **kwargs):
        return DiskMap(self, section, **kwargs)

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
            self.path.unlink(missing_ok=True)

    def __del__(self):
        try:
            self.close()
        except (OSError, sqlite3.Error):
            pass


def dump_state(state, stream):
    """Export disk or memory sections with bounded per-record serialization."""
    stream.write('{')
    for index, (key, section) in enumerate(state.items()):
        if index:
            stream.write(',')
        stream.write(json.dumps(key) + ':')
        if isinstance(section, Mapping):
            stream.write('{')
            for item_index, (name, value) in enumerate(section.items()):
                if item_index:
                    stream.write(',')
                stream.write(json.dumps(name, ensure_ascii=False) + ':')
                stream.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
            stream.write('}')
        else:
            json.dump(section, stream, ensure_ascii=False)
    stream.write('}')


def load_state(path, store=None):
    if not path.exists():
        return ({'files': store.mapping('files'), 'hash_cache': store.mapping('hash_cache')}
                if store is not None else {'files': {}})
    # Repeated metadata keys share storage across independently decoded records.
    decoder = json.JSONDecoder(object_pairs_hook=lambda pairs: {
        sys.intern(k): sys.intern(v) if isinstance(v, str) and len(v) == 64 else v
        for k, v in pairs})
    with path.open(encoding='utf-8') as stream:
        buffer = ''
        ended = False

        def fill():
            nonlocal buffer, ended
            chunk = stream.read(65536)
            buffer += chunk
            ended = not chunk

        def peek():
            nonlocal buffer
            buffer = buffer.lstrip()
            while not buffer and not ended:
                fill()
                buffer = buffer.lstrip()
            return buffer[:1]

        def take(expected):
            nonlocal buffer
            if peek() != expected:
                raise ValueError('Estado JSON inválido: se esperaba ' + expected)
            buffer = buffer[1:]

        def value():
            nonlocal buffer
            peek()
            while True:
                try:
                    result, end = decoder.raw_decode(buffer)
                    # A number may continue in the following chunk.
                    if end == len(buffer) and not ended:
                        fill()
                        continue
                    buffer = buffer[end:]
                    return result
                except json.JSONDecodeError:
                    if ended:
                        raise
                    fill()

        def mapping(read_value, section=None):
            take('{')
            result = store.mapping(section) if store is not None and section else {}
            if peek() != '}':
                while True:
                    key = value()
                    if not isinstance(key, str):
                        raise ValueError('Clave JSON no textual')
                    take(':')
                    result[key] = read_value(key)
                    if peek() != ',':
                        break
                    take(',')
            take('}')
            return result

        state = mapping(lambda key: mapping(lambda _: value(), key)
                        if key in ('files', 'hash_cache') else value())
        if peek():
            raise ValueError('Contenido posterior al estado JSON')
        return state
