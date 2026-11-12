"""Run tests with a Python audit guard against writes outside this project.

Child processes are covered by their CLI fixtures, not by Python's audit hooks.
This supplements the sandbox; it is not a general security boundary.
"""
import os
from pathlib import Path
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.chdir(PROJECT)
checked = 0


def check(path, dir_fd=None):
    global checked
    if isinstance(path, int):
        return  # Already opened descriptor.
    path = Path(os.fsdecode(path))
    if not path.is_absolute() and dir_fd is not None and dir_fd != -1:
        descriptor = Path('/proc/self/fd') / str(dir_fd)
        if not descriptor.exists():
            raise PermissionError('No se puede verificar dir_fd en esta plataforma')
        path = descriptor.resolve() / path
    path = path.resolve()
    if path != PROJECT and PROJECT not in path.parents:
        raise PermissionError(f'Prueba intentando escribir fuera del proyecto: {path}')
    checked += 1


def guard(event, args):
    if event == 'open':
        path, mode, flags = args
        if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            check(path)
    elif event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime'):
        check(args[0], args[-1] if event in ('os.remove', 'os.rmdir') else None)
    elif event in ('os.rename', 'os.link'):
        check(args[0], args[2])
        check(args[1], args[3])
    elif event == 'os.symlink':
        check(args[1], args[2])


if __name__ == '__main__':
    sys.addaudithook(guard)
    suite = unittest.defaultTestLoader.discover(str(PROJECT / 'tests'), top_level_dir=str(PROJECT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    temporary_root = PROJECT / '.test-runs'
    if temporary_root.is_dir() and not any(temporary_root.iterdir()):
        temporary_root.rmdir()
        print('Carpeta temporal de pruebas eliminada.')
    print(f'Operaciones Python de escritura verificadas dentro de VED-SYNC: {checked}')
    raise SystemExit(not result.wasSuccessful())
