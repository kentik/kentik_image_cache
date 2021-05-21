import logging
from .cache_entry import CacheEntry
from pathlib import Path
from typing import Any, Callable
from .types import *


log = logging.getLogger('file_cache')


class ObjectCache:
    def __init__(self, base_dir: Path) -> None:
        if not base_dir.is_dir():
            raise RuntimeError(f'Invalid cache base directory {base_dir}: not a directory')
        d = base_dir.resolve()
        self._active_dir = base_dir.joinpath('active')
        self._pending_dir = base_dir.joinpath('pending')
        self._active_dir.mkdir(exist_ok=True)
        self._pending_dir.mkdir(exist_ok=True)
        log.debug('New ObjectCache: base_dir: %s', d)
        log.debug('active: %d entries, pending: %d entries', self.active_count, self.pending_count)

    def get_entry(self, entry_id: str) -> CacheEntry:
        log.debug('get: %s', entry_id)
        try:
            p = self._active_dir.joinpath(entry_id)
            handle = p.open('rb')
            log.debug('Found active entry: %s', p)
            return CacheEntry(handle=handle, status=EntryStatus.ACTIVE)
        except FileNotFoundError:
            pass
        try:
            p = self._pending_dir.joinpath(entry_id)
            handle = p.open('rb')
            log.debug('Found pending entry: %s', p)
            return CacheEntry(handle=handle, status=EntryStatus.PENDING)
        except FileNotFoundError:
            pass
        log.debug('entry not found: %s', entry_id)
        return CacheEntry(handle=None, status=EntryStatus.NOT_FOUND)

    def create_entry(self, entry_id: str, entry_type: CacheEntryType, data: Any) -> CreationStatus:
        log.debug('create: %s', entry_id)
        entry = self.get_entry(entry_id)
        if entry.status != EntryStatus.NOT_FOUND:
            log.debug('Found existing entry: %s (status: %s, type: %s)', entry_id, entry.status.value, entry.type.value)
            return CreationStatus.EXISTING
        CacheEntry(EntryStatus.PENDING, path=self._pending_dir.joinpath(entry_id)).write(entry_type, data)
        return CreationStatus.CREATED

    def activate_entry(self, entry_id: str, entry_type: CacheEntryType, data: Any) -> ActivationStatus:
        entry = self.get_entry(entry_id)
        if entry.status != EntryStatus.PENDING:
            log.error('Cannot active %s entry %s', entry.status.value, entry_id)
            return ActivationStatus.FAILED
        else:
            entry.write(entry_type, data)
            entry.rename(self._active_dir.joinpath(entry_id))

    def prune(self, is_expired: Callable[[str], bool]):
        log.debug('pruning cache')
        to_remove = []
        for e in self._pending_dir.iterdir():
            eid = e.name
            log.debug('pending entry: %s', eid)
            if is_expired(eid):
                log.debug('expired: %s', eid)
                to_remove.append(e)
        for e in self._active_dir.iterdir():
            eid = e.name
            log.debug('active entry: %s', eid)
            if is_expired(eid):
                log.debug('expired: %s', eid)
                to_remove.append(e)
        for e in to_remove:
            log.debug('removing %s', e)
            e.unlink()
        log.debug('cache pruning complete: active: %d, pending: %d', self.active_count, self.pending_count)

    @property
    def active_count(self):
        return len([e for e in self._active_dir.iterdir()])

    @property
    def pending_count(self):
        return len([e for e in self._pending_dir.iterdir()])
