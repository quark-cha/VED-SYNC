"""Persistent pending-only recovery queues for Víctor Estrada Díaz's VED-SYNC."""
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
import shutil
import errno

from .telemetry import EventList
from .worklist import WorkList


def fingerprint(path):
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino]


def safe_path(engine, root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or engine.excluded(relative):
        raise ValueError('Ruta no admitida en la cola de recuperación')
    target = root / path
    cursor = target
    while cursor != root.parent:
        if cursor.is_symlink():
            raise OSError(f'Enlace no admitido: {cursor}')
        cursor = cursor.parent
    return target


def walk(engine, root):
    from .engine import PROJECT
    def fail(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        base = Path(directory)
        dirs[:] = sorted(n for n in dirs if not engine.excluded((base / n).relative_to(root))
                         and not (base == root and n.casefold() == PROJECT.name.casefold()))
        files = sorted(n for n in files if not engine.excluded((base / n).relative_to(root))
                       and not (base == root and n.casefold() == PROJECT.name.casefold()))
        for name in dirs + files:
            if (base / name).is_symlink():
                raise OSError(f'Enlace no admitido: {base / name}')
        for name in files:
            path = base / name
            if not path.is_file():
                raise OSError(f'Archivo especial no admitido: {path}')
            yield path.relative_to(root).as_posix(), path


def merge_record(previous, incoming):
    history = list(previous.get('history', []))
    known = {(h['sha256'], h['time_ns']) for h in history}
    history.extend(h for h in incoming.get('history', [])
                   if (h['sha256'], h['time_ns']) not in known)
    return {**incoming, 'history': history}


def problem(engine, relative, exc):
    engine.events.append({'type': 'error', 'path': relative, 'code': type(exc).__name__,
                          'detail': str(exc)})


def require_space(directory, needed):
    if shutil.disk_usage(directory).free < needed:
        raise OSError(errno.ENOSPC, 'Espacio insuficiente; la cola conserva sus pendientes')


def rebuild(engine, queue, source_root, *, automatic):
    """Back up the old plan, then publish a fresh FIFO as one transaction."""
    queue.flush()
    queue_path = engine.state_dir / 'VED-Sync.cola'
    paths = (queue_path, queue.index_path, queue.history_path)
    size = sum(p.stat().st_size for p in paths)
    checkpoint_size = engine.state_file.stat().st_size if engine.state_file.exists() else 0
    require_space(engine.state_dir, 2 * size + checkpoint_size + 16 * 1024 * 1024)
    backup = engine.state_dir / 'queue-backups' / str(time.time_ns())
    backup.mkdir(parents=True)
    for path in paths:
        destination = backup / path.name
        shutil.copy2(path, destination)
        def digest(file):
            result = hashlib.sha256()
            with file.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    result.update(chunk)
            return result.digest()
        if digest(path) != digest(destination):
            raise OSError('Respaldo de cola no verificado')
    try:
        queue.connection.execute('DELETE FROM pending_copy')
        queue.connection.execute('DELETE FROM pending_review')
        queue.connection.execute("UPDATE inventory SET status='absent', seen=0")
        queue._progress = None
        for relative, path in walk(engine, source_root):
            stat = fingerprint(path)
            job = queue.get(relative)
            if job is None:
                queue.add(relative, ('', stat[0], stat[1]), source_stat=stat)
            else:
                job['size'], job['weight'] = stat[0], max(1, 5 * stat[0])
                job['data'].update(source=['', stat[0], stat[1]], source_stat=stat,
                                   target_stat=None, verified_ns=None)
                queue.update(job, 'pending', durable=False)
        queue.set_meta('complete', False)
        queue.set_meta('ready', True)
        queue.set_meta('auto_rebuilt', automatic)
        queue.set_meta('stalled_attempts', 0)
        queue.set_meta('attempt_marker', queue.progress())
        queue.flush()
    except BaseException:
        queue.connection.rollback()
        queue._progress = None
        raise
    queue.trace('queue_rebuilt', automatic=automatic, backup=str(backup))
    queue.export_pending()


def bootstrap(engine, queue, source_root, target_root, source_name, target_name):
    """Recover the last inventory from cached metadata without rehashing it all."""
    from .engine import Entry
    count = 0
    for absolute, cached in engine.state.get('hash_cache', {}).items():
        try:
            relative = Path(absolute).relative_to(source_root).as_posix()
        except ValueError:
            continue
        if engine.excluded(relative) or Path(relative).parts[0].casefold() == engine.config_path.parent.name.casefold():
            continue
        digest = cached.get('sha256', '')
        stat = cached.get('stat', [])
        if len(digest) != 64 or len(stat) != 5:
            continue
        entry = Entry(digest, stat[0], stat[1])
        record = engine.state['files'].get(relative, {})
        observations = record.get('observations', {})
        old_target = observations.get(target_name, {})
        done = (record.get('seen', {}).get(source_name) == digest
                and record.get('seen', {}).get(target_name) == digest
                and old_target.get('sha256') == digest)
        if done:
            try:
                source_stat = fingerprint(safe_path(engine, source_root, relative))
                target_stat = fingerprint(safe_path(engine, target_root, relative))
                done = (source_stat == stat and target_stat[:2] ==
                        [old_target['size'], old_target['mtime_ns']])
            except (OSError, KeyError):
                done = False
        queue.add(relative, (digest, entry.size, entry.mtime_ns), done=done,
                  result=record if done else None, source_stat=stat,
                  target_stat=target_stat if done else None)
        count += 1
        if count % 128 == 0:
            queue.flush()
    if not count:
        # A first recovery has no previous inventory to reuse.
        for relative, path in walk(engine, source_root):
            existing = queue.get(relative)
            current_stat = fingerprint(path)
            if existing and existing['data']['source_stat'] == current_stat:
                count += 1
                continue
            entry = engine.cached_inspect(path)
            if existing:
                existing['data'].update(source=[entry.digest, entry.size, entry.mtime_ns],
                                        source_stat=current_stat)
                existing['weight'], existing['size'] = max(1, 5 * entry.size), entry.size
                queue.update(existing, 'pending')
            else:
                queue.add(relative, (entry.digest, entry.size, entry.mtime_ns), source_stat=current_stat)
                queue.flush()
            count += 1
    queue.set_meta('ready', True)
    queue.flush()
    queue.export_pending()
    queue.trace('plan_ready', **queue.progress())


def show_progress(engine, queue):
    queue.export_pending()
    progress = queue.progress()
    engine.monitor.plan_files(range(progress['total']))
    engine.monitor.finished_files = {j['path'] for j in queue.jobs(('done', 'verified'))}
    engine.monitor.emit('file_count', files_done=progress['done'], files_total=progress['total'])
    engine.monitor.set_work(progress['work'], progress['bytes'])
    engine.monitor.work_done = progress['processed']
    percent = 30 + 55 * progress['processed'] / max(1, progress['work'])
    engine.monitor.project_update('synchronization', percent, progress['processed'], progress['work'])
    event = engine.monitor.emit('state_loaded', total=progress['total']) or {}
    queue.trace('resume', **progress, **{k: event[k] for k in
                ('process_id', 'rss_bytes', 'peak_rss_bytes') if k in event})


def save_result(engine, queue, job, source_name, target_name, source, target, source_entry, target_entry):
    relative = job['path']
    record = engine.state['files'].get(relative, {'seen': {}, 'history': []})
    history = list(record.get('history', []))
    if not history or history[-1]['sha256'] != source_entry.digest:
        history.append({'sha256': source_entry.digest, 'time_ns': time.time_ns()})
    result = {'head': source_entry.digest, 'history': history,
              'seen': {**record.get('seen', {}), source_name: source_entry.digest, target_name: target_entry.digest},
              'observations': {name: {'sha256': entry.digest, 'size': entry.size, 'mtime_ns': entry.mtime_ns}
                               for name, entry in ((source_name, source_entry), (target_name, target_entry))}}
    source_stat, target_stat = fingerprint(source), fingerprint(target)
    if (source_stat[:2] != [source_entry.size, source_entry.mtime_ns]
            or target_stat[:2] != [target_entry.size, target_entry.mtime_ns]):
        raise OSError('Archivo cambiado antes de confirmar la cola')
    job['weight'], job['size'] = max(1, 5 * source_entry.size), source_entry.size
    job['data'].update(source=[source_entry.digest, source_entry.size, source_entry.mtime_ns],
                       result=result, source_stat=source_stat, target_stat=target_stat, verified_ns=None)
    # Receipt and dequeue are one durable transaction, before the next file starts.
    queue.update(job, 'done')
    engine.state['files'][relative] = result


def copy_pending(engine, queue, source_root, target_root, source_name, target_name):
    errors = 0
    for job in queue.jobs(('pending',)):
        relative = job['path']
        if engine.excluded(relative):
            queue.update(job, 'absent')
            continue
        queue.trace('checking_pending', path=relative)
        engine.monitor.file_budget = job['weight']
        engine.monitor.emit('synchronization', path=relative, repository=target_name, location=target_root)
        try:
            require_space(engine.state_dir, 16 * 1024 * 1024)
            source = safe_path(engine, source_root, relative)
            target = safe_path(engine, target_root, relative)
            original = engine.inspect_file(source)
            current = engine.inspect_file(target) if target.exists() else None
            if current is None or current.digest != original.digest:
                archives = engine.state_dir / 'versions'
                missing_source = sum(not (archives / (original.digest + suffix)).exists()
                                     for suffix in ('.original', ''))
                missing_target = (sum(not (archives / (current.digest + suffix)).exists()
                                      for suffix in ('.original', '')) if current else 0)
                checkpoint_size = engine.state_file.stat().st_size if engine.state_file.exists() else 0
                require_space(engine.state_dir, (1 + missing_source) * original.size
                              + missing_target * (current.size if current else 0)
                              + checkpoint_size + 16 * 1024 * 1024)
                engine._original(source, original, uuid.uuid4().hex)
                backup = engine.state_dir / 'versions' / (original.digest + '.original')
                backup_entry = engine.inspect_file(backup, expected=original.digest)
                current = engine.copy(backup, target, backup_entry, current, target_root)
                engine.events.append({'type': 'recovery', 'path': relative, 'repository': target_name})
            save_result(engine, queue, job, source_name, target_name, source, target, original, current)
            engine._project_bytes += original.size
            engine.monitor.finish_file(relative)
            engine.monitor.complete_file()
            progress = queue.progress()
            engine.monitor.work_done = progress['processed']
            engine.monitor.project_update('synchronization',
                30 + 55 * progress['processed'] / max(1, progress['work']), progress['processed'], progress['work'])
            engine.checkpoint()
        except (OSError, ValueError) as exc:
            errors += 1
            problem(engine, relative, exc)
            # The failed or interrupted operation remains in pending_copy.
            if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
                engine._queue_disk_full = True
                break
    return errors


def refresh(engine, queue, source_root, target_root, *, new_cycle=False):
    """Review names and metadata, finding additions without discarding the FIFO."""
    epoch = time.time_ns()
    count = 0
    for relative, source in walk(engine, source_root):
        source_stat = fingerprint(source)
        target = safe_path(engine, target_root, relative)
        target_stat = fingerprint(target) if target.exists() else None
        job = queue.get(relative)
        if job is None:
            queue.add(relative, ('', source_stat[0], source_stat[1]), seen=epoch)
        else:
            data = job['data']
            changed = (job['status'] == 'absent' or target_stat is None
                       or (data['source_stat'] is not None and data['source_stat'] != source_stat)
                       or (data['target_stat'] is not None and data['target_stat'] != target_stat))
            if changed:
                job['seen'] = epoch
                queue.update(job, 'pending', durable=False)
            elif (new_cycle and job['status'] == 'verified' and
                  time.time_ns() - (data.get('verified_ns') or 0) >= engine.integrity_seconds * 1e9):
                job['seen'] = epoch
                queue.update(job, 'done', durable=False)
            else:
                queue.touch(job, epoch)
        count += 1
        if count % 128 == 0:
            queue.flush()
    queue.flush()
    for job in queue.jobs():
        if engine.excluded(job['path']):
            if job['status'] != 'absent':
                queue.update(job, 'absent')
            continue
        if job['seen'] != epoch:
            queue.update(job, 'absent')
            engine.events.append({'type': 'preserved', 'path': job['path'],
                                  'detail': 'Ya no está en el origen; se conserva el destino'})
    for relative, _ in walk(engine, target_root):
        job = queue.get(relative)
        if job is None or job['seen'] != epoch:
            engine.events.append({'type': 'preserved', 'path': relative,
                                  'detail': 'Solo en destino: se conserva; copia inversa no permitida'})
    queue.flush()
    queue.export_pending()


def verify_pending(engine, queue, source_root, target_root):
    errors = 0
    progress = queue.progress()
    engine.monitor.project_update('verification', 85 + 13 * progress['verified'] / max(1, progress['total']))
    for job in queue.jobs(('done',)):
        relative = job['path']
        if engine.excluded(relative):
            queue.update(job, 'absent')
            continue
        queue.trace('checking_final', path=relative)
        try:
            source = safe_path(engine, source_root, relative)
            target = safe_path(engine, target_root, relative)
            before_source, before_target = fingerprint(source), fingerprint(target)
            original = engine.inspect_file(source)
            current = engine.inspect_file(target)
            if (original.digest != current.digest or original.digest != job['data']['source'][0]
                    or before_source != fingerprint(source) or before_target != fingerprint(target)):
                queue.update(job, 'pending')
                continue
            job['data'].update(source_stat=before_source, target_stat=before_target, verified_ns=time.time_ns())
            queue.update(job, 'verified')
            progress = queue.progress()
            engine.monitor.project_update('verification',
                85 + 13 * progress['verified'] / max(1, progress['total']))
            engine.checkpoint()
        except (OSError, ValueError) as exc:
            errors += 1
            problem(engine, relative, exc)
    return errors


def run_restore(engine, on_status=None):
    engine.events = EventList(engine.monitor)
    active = engine.available()
    engine.active_paths = active
    transfers = engine.announce_transfer_policy(active)
    if len(active) != len(engine.repos):
        return {'simulation': False, 'status': dict(engine.status), 'events': engine.events}
    source_name = engine.authoritative_source
    target_name = next(n for n in active if n != source_name)
    source_root, target_root = active[source_name], active[target_name]
    permission = engine.transfer_permissions[(source_name, target_name)]
    if not permission['allowed']:
        for name in active:
            engine.status[name] = 'rojo'
            engine.monitor.emit('status', repository=name, status='rojo', location=active[name])
        engine.events.append({'type': 'error', 'repository': target_name,
                              'code': 'TransferNotAllowed', 'detail': permission['reason']})
        if on_status:
            on_status(dict(engine.status))
        return {'simulation': False, 'status': dict(engine.status), 'events': engine.events}
    engine.monitor.emit('transfer_direction', direction_source=engine.repository_labels[source_name],
                        direction_target=engine.repository_labels[target_name])
    signature = hashlib.sha256(json.dumps({'roots': {n: str(p) for n, p in active.items()},
        'source': source_name, 'excludes': engine.exclude_patterns}, sort_keys=True).encode()).hexdigest()
    names = sorted(engine.repos)
    queue = WorkList(engine.state_dir / 'VED-Sync.cola', signature,
                     routes=(names.index(source_name) + 1, names.index(target_name) + 1))
    engine._worklist = queue
    try:
        queue.trace('transfer_policy', transfers=transfers)
        if not queue.meta('ready', False):
            bootstrap(engine, queue, source_root, target_root, source_name, target_name)
        retired = 0
        for job in queue.jobs():
            if engine.excluded(job['path']) and job['status'] != 'absent':
                queue.update(job, 'absent', durable=False)
                retired += 1
        if retired:
            # Retire old exclusions together, before inspecting source/destination contents.
            queue.flush()
            queue.export_pending()
            queue.trace('exclusions_applied', total=retired)
        # Receipts close the gap between the last JSON checkpoint and SIGKILL.
        for job in queue.jobs(('done', 'verified')):
            result = job['data'].get('result')
            if result:
                engine.state['files'][job['path']] = merge_record(engine.state['files'].get(job['path'], {}), result)
        new_cycle = queue.meta('complete', False)
        queue.set_meta('complete', False)
        queue.flush()
        for name in active:
            engine.monitor.emit('status', repository=name, status='amarillo', location=active[name])
        if on_status:
            on_status(dict(engine.status))
        if new_cycle:
            refresh(engine, queue, source_root, target_root, new_cycle=True)
        automatic = queue.attempt(new_cycle)
        if engine.reset_queue or automatic:
            rebuild(engine, queue, source_root, automatic=not engine.reset_queue)
        engine._queue_disk_full = False
        errors = 0
        for _ in range(3):
            show_progress(engine, queue)
            errors += copy_pending(engine, queue, source_root, target_root, source_name, target_name)
            if engine._queue_disk_full:
                progress = queue.progress()
                try:
                    queue.trace('paused_no_space', **progress)
                except OSError:
                    pass  # A full filesystem may also prevent the diagnostic append.
                break
            refresh(engine, queue, source_root, target_root)
            errors += verify_pending(engine, queue, source_root, target_root)
            refresh(engine, queue, source_root, target_root)
            progress = queue.progress()
            if errors or progress['verified'] == progress['total']:
                break
        complete = not errors and progress['verified'] == progress['total']
        if not engine._queue_disk_full:
            engine.monitor.project_update('confirmation', 98, progress['processed'], progress['work'])
            engine.save()
            queue.set_meta('complete', complete)
            queue.flush()
        status = 'verde' if complete else 'rojo'
        for name in active:
            engine.status[name] = status
            engine.monitor.emit('status', repository=name, status=status)
        if on_status:
            on_status(dict(engine.status))
        return {'simulation': False, 'status': dict(engine.status), 'events': engine.events}
    except BaseException as exc:
        try:
            queue.trace('interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'error',
                        code=type(exc).__name__, detail=str(exc))
        except OSError:
            pass
        raise
    finally:
        queue.close()
        engine._worklist = None
