"""Process-wide and persistent caches for DataFrame metadata."""

from __future__ import annotations

import pickle
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import pandas as pd

from tdxhub.logger import logger

PathLike: TypeAlias = str | Path
_CACHE_READ_ERRORS = (EOFError, OSError, ValueError, pickle.UnpicklingError)


@dataclass
class _CacheEntry:
    frame: pd.DataFrame
    expires_at: float | None


class PersistentDataFrameCache:
    """Share DataFrames in-process and persist them atomically across runs.

    Cache freshness is checked lazily on access. Concurrent callers in the same
    process share a per-file lock; on POSIX systems a file lock also prevents
    duplicate refresh work across processes. Scheduled refresh failures fall
    back to stale data, while an explicit refresh always propagates errors.
    """

    def __init__(self, *, retry_after: float = 300) -> None:
        self._entries: dict[Path, _CacheEntry] = {}
        self._locks: dict[Path, threading.RLock] = {}
        self._state_lock = threading.RLock()
        self._retry_after = retry_after

    @staticmethod
    def _path(filepath: PathLike) -> Path:
        return Path(filepath).expanduser().resolve(strict=False)

    def _lock_for(self, path: Path) -> threading.RLock:
        with self._state_lock:
            return self._locks.setdefault(path, threading.RLock())

    @staticmethod
    def _expires_at(modified_at: float, ttl: float | None) -> float | None:
        return None if ttl is None else modified_at + max(0.0, float(ttl))

    @staticmethod
    def _fresh(entry: _CacheEntry, now: float) -> bool:
        return entry.expires_at is None or entry.expires_at >= now

    @staticmethod
    def _clone(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy(deep=True)
        for position, dtype in enumerate(frame.dtypes):
            if pd.api.types.is_object_dtype(dtype):
                result.isetitem(position, frame.iloc[:, position].map(deepcopy))
        result.attrs = deepcopy(frame.attrs)
        return result

    @staticmethod
    def _read(path: Path, ttl: float | None) -> _CacheEntry | None:
        try:
            modified_at = path.stat().st_mtime
            frame = pd.read_pickle(path)
        except _CACHE_READ_ERRORS:
            return None
        if not isinstance(frame, pd.DataFrame):
            return None
        return _CacheEntry(frame=frame, expires_at=PersistentDataFrameCache._expires_at(modified_at, ttl))

    @staticmethod
    def _write(path: Path, frame: pd.DataFrame) -> float:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as output:
                temporary = Path(output.name)
            frame.to_pickle(temporary)
            temporary.replace(path)
            return path.stat().st_mtime
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @contextmanager
    def _process_lock(self, path: Path):
        """Lock one cache file across processes when the platform supports it."""

        lock_path = path.with_suffix(f"{path.suffix}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock_file:
            try:
                import fcntl
            except ImportError:  # pragma: no cover - Windows fallback
                yield
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def get(
        self,
        filepath: PathLike,
        loader: Callable[[], pd.DataFrame],
        *,
        ttl: float | None,
        refresh: bool = False,
    ) -> pd.DataFrame:
        """Return cached data, refreshing expired data with ``loader``.

        ``refresh=True`` bypasses both memory and disk. Otherwise an expired
        value is returned if refreshing raises, with another refresh attempted
        after ``retry_after`` seconds.
        """

        path = self._path(filepath)
        lock = self._lock_for(path)
        with lock:
            now = time.time()
            stale = self._entries.get(path)
            if not refresh and stale is not None and self._fresh(stale, now):
                return self._clone(stale.frame)

            disk_entry = None if refresh else self._read(path, ttl)
            if disk_entry is not None:
                stale = disk_entry
                if self._fresh(disk_entry, now):
                    self._entries[path] = disk_entry
                    return self._clone(disk_entry.frame)

            with self._process_lock(path):
                # Another process may have refreshed the file while this caller
                # waited for the lock, so inspect it once more before loading.
                if not refresh:
                    disk_entry = self._read(path, ttl)
                    if disk_entry is not None:
                        stale = disk_entry
                        if self._fresh(disk_entry, time.time()):
                            self._entries[path] = disk_entry
                            return self._clone(disk_entry.frame)

                try:
                    frame = loader()
                except Exception:
                    if refresh or stale is None:
                        raise
                    logger.warning("刷新 DataFrame 缓存失败，暂时使用过期数据: %s", path, exc_info=True)
                    self._entries[path] = _CacheEntry(
                        frame=stale.frame,
                        expires_at=time.time() + self._retry_after,
                    )
                    return self._clone(stale.frame)

                if not isinstance(frame, pd.DataFrame):
                    raise TypeError("缓存加载器必须返回 pandas.DataFrame")
                stored = self._clone(frame)
                modified_at = self._write(path, stored)
                self._entries[path] = _CacheEntry(
                    frame=stored,
                    expires_at=self._expires_at(modified_at, ttl),
                )
                return self._clone(stored)

    def clear_memory(self, filepath: PathLike | None = None) -> None:
        """Clear process memory without deleting persistent cache files."""

        with self._state_lock:
            if filepath is None:
                self._entries.clear()
            else:
                self._entries.pop(self._path(filepath), None)
