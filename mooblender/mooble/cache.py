"""Bounded, concurrency-safe management of downloaded Mooble cache files."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

DOWNLOAD_CACHE_GROUPS = ("models", "thumbnails")
_CACHE_LOCK = RLock()
_ACTIVE_PATHS: dict[Path, int] = {}


@dataclass(frozen=True, slots=True)
class CacheStats:
    """File count and byte size for one or more managed cache groups."""

    files: int = 0
    bytes: int = 0


@dataclass(frozen=True, slots=True)
class CacheCleanup:
    """Files and bytes removed by one pruning or explicit clear operation."""

    removed_files: int = 0
    removed_bytes: int = 0
    remaining_files: int = 0
    remaining_bytes: int = 0


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    """Stable metadata used to order one cache file without following links."""

    path: Path
    size: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _CacheBundle:
    """One evictable download, including a model's JSON sidecar when present."""

    entries: tuple[_CacheEntry, ...]
    size: int
    modified_ns: int
    name: str


def _absolute(path: str | Path) -> Path:
    """Normalize a path lexically without resolving a potentially hostile link."""
    return Path(os.path.abspath(os.fspath(path)))


def _group_directory(cache_dir: str | Path, group: str) -> Path:
    """Return one allow-listed download directory below the cache root."""
    if group not in DOWNLOAD_CACHE_GROUPS:
        raise ValueError(f"unknown Mooblender download cache group: {group}")
    return _absolute(cache_dir) / group


def _entries(
    directory: Path,
    *,
    include_temporary: bool = False,
) -> tuple[_CacheEntry, ...]:
    """List direct regular files and links using non-following metadata."""
    try:
        children = tuple(directory.iterdir())
    except OSError:
        return ()
    result = []
    for path in children:
        if path.name.endswith(".tmp") and not include_temporary:
            # Atomic writers keep temporary files in the destination folder.
            # Pruning must never race them; explicit clearing may remove stale
            # temporary files because its Blender operator requires idle jobs.
            continue
        try:
            metadata = path.lstat()
        except OSError:
            continue
        if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)):
            # Current caches are intentionally flat. Unknown nested directories
            # are never traversed or deleted by automatic management.
            continue
        result.append(
            _CacheEntry(
                path=_absolute(path),
                size=metadata.st_size,
                modified_ns=metadata.st_mtime_ns,
            )
        )
    return tuple(result)


def cache_stats(cache_dir: str | Path) -> CacheStats:
    """Measure both managed download groups without traversing subdirectories."""
    with _CACHE_LOCK:
        entries = tuple(
            entry
            for group in DOWNLOAD_CACHE_GROUPS
            for entry in _entries(
                _group_directory(cache_dir, group),
                include_temporary=True,
            )
        )
        return CacheStats(
            files=len(entries),
            bytes=sum(entry.size for entry in entries),
        )


def _bundles(group: str, entries: Iterable[_CacheEntry]) -> tuple[_CacheBundle, ...]:
    """Group model content with metadata so pruning never leaves an orphan."""
    grouped: dict[str, list[_CacheEntry]] = {}
    for entry in entries:
        name = entry.path.name
        key = name.removesuffix(".json") if group == "models" else name
        grouped.setdefault(key, []).append(entry)
    return tuple(
        _CacheBundle(
            entries=tuple(group_entries),
            size=sum(entry.size for entry in group_entries),
            modified_ns=max(entry.modified_ns for entry in group_entries),
            name=name,
        )
        for name, group_entries in grouped.items()
    )


@contextmanager
def cache_paths_in_use(paths: Iterable[str | Path]) -> Iterator[None]:
    """Protect download targets from pruning until their caller finishes."""
    normalized = {_absolute(path) for path in paths}
    with _CACHE_LOCK:
        for path in normalized:
            _ACTIVE_PATHS[path] = _ACTIVE_PATHS.get(path, 0) + 1
    try:
        yield
    finally:
        with _CACHE_LOCK:
            for path in normalized:
                users = _ACTIVE_PATHS[path] - 1
                if users:
                    _ACTIVE_PATHS[path] = users
                else:
                    del _ACTIVE_PATHS[path]


def touch_cache_file(path: str | Path) -> None:
    """Mark a cache hit as recently used without failing the import on I/O errors."""
    with _CACHE_LOCK, suppress(OSError):
        os.utime(_absolute(path), follow_symlinks=False)


def prune_cache_group(
    cache_dir: str | Path,
    group: str,
    max_bytes: int,
    *,
    protected: Iterable[str | Path] = (),
) -> CacheCleanup:
    """Remove oldest unprotected files until a managed group meets its limit."""
    directory = _group_directory(cache_dir, group)
    explicit_protected = {_absolute(path) for path in protected}
    limit = max(int(max_bytes), 0)
    with _CACHE_LOCK:
        entries = list(_entries(directory))
        total = sum(entry.size for entry in entries)
        removed_files = 0
        removed_bytes = 0
        protected_paths = explicit_protected | set(_ACTIVE_PATHS)
        bundles = _bundles(group, entries)
        for bundle in sorted(
            bundles,
            key=lambda item: (item.modified_ns, item.name),
        ):
            if total <= limit:
                break
            if any(entry.path in protected_paths for entry in bundle.entries):
                continue
            for entry in bundle.entries:
                try:
                    entry.path.unlink()
                except OSError:
                    continue
                total -= entry.size
                removed_files += 1
                removed_bytes += entry.size
        remaining = _entries(directory)
        return CacheCleanup(
            removed_files=removed_files,
            removed_bytes=removed_bytes,
            remaining_files=len(remaining),
            remaining_bytes=sum(entry.size for entry in remaining),
        )


def clear_download_cache(cache_dir: str | Path) -> CacheCleanup:
    """Delete inactive model and thumbnail files while preserving the catalog."""
    with _CACHE_LOCK:
        entries = tuple(
            entry
            for group in DOWNLOAD_CACHE_GROUPS
            for entry in _entries(
                _group_directory(cache_dir, group),
                include_temporary=True,
            )
        )
        removed_files = 0
        removed_bytes = 0
        for entry in entries:
            if entry.path in _ACTIVE_PATHS:
                continue
            try:
                entry.path.unlink()
            except OSError:
                continue
            removed_files += 1
            removed_bytes += entry.size
        remaining = tuple(
            entry
            for group in DOWNLOAD_CACHE_GROUPS
            for entry in _entries(
                _group_directory(cache_dir, group),
                include_temporary=True,
            )
        )
        return CacheCleanup(
            removed_files=removed_files,
            removed_bytes=removed_bytes,
            remaining_files=len(remaining),
            remaining_bytes=sum(entry.size for entry in remaining),
        )
