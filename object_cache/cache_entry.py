import logging
from pathlib import Path
from typing import Optional, IO
from .types import *


log = logging.getLogger('CacheEntry')


class CacheEntry:
    def __init__(self, status=EntryStatus.NOT_FOUND, handle: Optional[IO] = None, path: Optional[Path] = None) -> None:
        self.status = status
        self._handle = handle
        if self._handle:
            if path is not None:
                log.error('Cache entry: %s path (%s) ignored', self._handle.name, path)
            self._path = Path(self._handle.name)
        elif path is not None:
            self._path = path
        else:
            if self.status != EntryStatus.NOT_FOUND:
                raise RuntimeError('Existing Cache entry with no path and handle')
        self._type = CacheEntryType.INVALID
        self._data: bytes = bytes(0)
        if self._handle is None:
            return
        try:
            header = self._handle.readline().strip().decode()
            if header == CacheEntryType.REQUEST.value:
                self._type = CacheEntryType.REQUEST
            if header == CacheEntryType.ERROR_MSG.value:
                self._type = CacheEntryType.ERROR_MSG
            if header == CacheEntryType.IMAGE.value:
                self._type = CacheEntryType.IMAGE
        except IOError:
            return
        self._data = self._handle.read()

    def __del__(self):
        if self._handle:
            self._handle.close()

    @property
    def type(self) -> CacheEntryType:
        return self._type

    @property
    def data(self) -> bytes:
        return self._data

    @property
    def path(self) -> Optional[Path]:
        return self._path

    def rename(self, name: Path) -> None:
        if self._handle is None:
            raise RuntimeError(f'Attempt to rename null handle to {name}')
        log.debug('Renaming %s to %s', self._handle.name, name)
        self.path.rename(name)
        self._handle.close()
        self._handle = Path(name).open('rb')
        self._path = Path(self._handle.name)

    def write(self, entry_type: CacheEntryType, data: bytes) -> None:
        with self.path.open('wb') as f:
            self._type = entry_type
            f.write(bytes(f'{self._type.value}\n'.encode()))
            if type(data) == str:
                n = f.write(bytes(data.encode()))
            else:
                n = f.write(data)
            f.close()
            log.debug('entry: %s, type: %s stored %d  bytes', f.name, self._type.name, n)
