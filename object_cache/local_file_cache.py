import logging
from pathlib import Path
from typing import Any, Callable, Optional

from .cache_entry import CacheEntry, CacheEntryType
from .types import ActivationStatus, CreationStatus, EntryStatus

log = logging.getLogger("file_cache")


class ObjectCache:
    """
    Class implementing simple object cache.

    Objects are stored in files in local file-system.
    Location of the cache data is defined by the 'base_dir' passed to the constructor. 2 sub-directories are
    created in 'base_dir': 'pending' and 'active'.
    Entries in the cache (returned asCacheEntry objects) can be in 2 states:
    - CacheEntryStatus.PENDING: located in 'pending' directory
    - CacheEntryStatus.ACTIVE: located in 'active' directory
    On activation, files are atomically moved from pending to active.

    The cache does not parse or use content of cached data.
    """

    def __init__(self, base_dir: Path) -> None:
        if not base_dir.is_dir():
            raise RuntimeError(f"Invalid cache base directory {base_dir}: not a directory")
        d = base_dir.resolve()
        self._active_dir = base_dir.joinpath("active")
        self._pending_dir = base_dir.joinpath("pending")
        self._active_dir.mkdir(exist_ok=True)
        self._pending_dir.mkdir(exist_ok=True)
        log.debug("New ObjectCache: base_dir: %s", d)
        log.debug(
            "active: %d entries, pending: %d entries",
            self.active_count,
            self.pending_count,
        )

    def get_entry(self, entry_id: str) -> Optional[CacheEntry]:
        """
        Locate file matching entry_id if found return CacheEntry object, otherwise None.
        If matching file is found in the 'pending' directory returned CacheEntry has PENDING status.
        If found in 'active' directory, returned CacheEntry has ACTIVE status.
        Return CacheEntry holds opened handle to the file which is closed when the entry is destroyed.
        """
        log.debug("get: %s", entry_id)
        try:
            p = self._active_dir.joinpath(entry_id)
            handle = p.open("rb")
            log.debug("Found active entry: %s", p)
            return CacheEntry(handle=handle, status=EntryStatus.ACTIVE)
        except FileNotFoundError:
            pass
        try:
            p = self._pending_dir.joinpath(entry_id)
            handle = p.open("rb")
            log.debug("Found pending entry: %s", p)
            return CacheEntry(handle=handle, status=EntryStatus.PENDING)
        except FileNotFoundError:
            pass
        log.debug("entry not found: %s", entry_id)
        return None

    def create_entry(self, entry_id: str, entry_type: CacheEntryType, data: Any) -> CreationStatus:
        """
        Attempt to create new cache entry.
        If it already exists return CreationStatus.EXISTING,
        otherwise write provided data to the entry and return CreationStatus.CREATED
        """
        log.debug("create: %s", entry_id)
        entry = self.get_entry(entry_id)
        if entry is not None:
            log.debug(
                "Found existing entry: %s (status: %s, type: %s)",
                entry_id,
                entry.status.value,
                entry.type.value,
            )
            return CreationStatus.EXISTING
        else:
            CacheEntry(EntryStatus.PENDING, path=self._pending_dir.joinpath(entry_id)).write(entry_type, data)
            return CreationStatus.CREATED

    def activate_entry(self, entry_id: str, entry_type: CacheEntryType, data: Any) -> ActivationStatus:
        """
        Move specified entry from pending to active directory and write provided data to it.
        If entry does not exist, return ActivationStatus.FAILED.
        If entry exists and is not in pending state, it remains unmodified and ActivationStatus.FAILED is returned.
        """
        entry = self.get_entry(entry_id)
        if entry is None:
            log.error("Cannot active nonexistent entry %s", entry_id)
            return ActivationStatus.FAILED
        if entry.status != EntryStatus.PENDING:
            log.error("Cannot active %s entry %s", entry.status.value, entry_id)
            return ActivationStatus.FAILED
        else:
            entry.write(entry_type, data)
            entry.rename(self._active_dir.joinpath(entry_id))
            return ActivationStatus.SUCCESS

    def prune(self, is_expired: Callable[[str], bool]):
        """
        Method used for periodic pruning of the cache.
        Provided function 'is_expired' is called to determine whether an entry needs to be evicted.
        Expiration logic relies solely on entry ids.
        """
        log.debug("pruning cache")
        to_remove = []
        for e in self._pending_dir.iterdir():
            eid = e.name
            log.debug("pending entry: %s", eid)
            if is_expired(eid):
                log.debug("expired: %s", eid)
                to_remove.append(e)
        for e in self._active_dir.iterdir():
            eid = e.name
            log.debug("active entry: %s", eid)
            if is_expired(eid):
                log.debug("expired: %s", eid)
                to_remove.append(e)
        for e in to_remove:
            log.info("removing %s", e)
            e.unlink()
        log.debug(
            "cache pruning complete: active: %d, pending: %d",
            self.active_count,
            self.pending_count,
        )

    @property
    def active_count(self):
        return len([e for e in self._active_dir.iterdir()])

    @property
    def pending_count(self):
        return len([e for e in self._pending_dir.iterdir()])

    @property
    def active_entries(self):
        for f in self._active_dir.iterdir():
            yield CacheEntry(handle=f.open("rb"), status=EntryStatus.ACTIVE)

    @property
    def pending_entries(self):
        for f in self._pending_dir.iterdir():
            yield CacheEntry(handle=f.open("rb"), status=EntryStatus.PENDING)
