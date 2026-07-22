"""Blender-independent worker entry points for the Mooble browser.

These functions deliberately return neutral Python models or filesystem paths.
They never import ``bpy``: all Blender datablock construction remains in the
main-thread timer completions in :mod:`mooblender.blender.operators`.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from ..formats import PContentPackage, load_path, resolve_aggregates
from ..mooble import CatalogItem
from ..mooble.client import MoobleClient


def fetch_thumbnails(
    client: MoobleClient,
    items: tuple[CatalogItem, ...],
) -> dict[str, Any]:
    """Download one visible thumbnail batch and close its worker client."""
    if not items:
        return {}
    # The outer preview executor keeps batches responsive across page changes;
    # this inner, bounded pool parallelizes the independent HTTP requests within
    # the one currently visible batch.
    workers = min(4, len(items))
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            paths = executor.map(client.download_thumbnail, items)
            return {item.id: path for item, path in zip(items, paths, strict=True)}
    finally:
        client.close()


def fetch_model(client: MoobleClient, item: CatalogItem):
    """Download, parse, and recursively resolve one catalog model."""
    try:
        # Aggregate resolution belongs in the same worker as the root download.
        # The main thread receives a fully resolved package tree and never
        # pauses halfway through Blender object creation for more I/O.
        path = client.download_model(item)
        loaded = load_path(path)
        if isinstance(loaded, PContentPackage):
            def load_aggregate(specification_id: str) -> PContentPackage:
                """Download and parse one referenced aggregate specification."""
                child = load_path(client.download_specification(specification_id))
                if not isinstance(child, PContentPackage):
                    raise ValueError(
                        f"aggregate {specification_id} is not a PContent package"
                    )
                return child

            resolve_aggregates(loaded, load_aggregate)
        return loaded
    finally:
        client.close()


def fetch_file(client: MoobleClient, path):
    """Parse a local file and download only aggregate dependencies it references."""
    try:
        loaded = load_path(path)
        if isinstance(loaded, PContentPackage):
            def load_aggregate(specification_id: str) -> PContentPackage:
                """Download a dependency referenced by the local root package."""
                child = load_path(client.download_specification(specification_id))
                if not isinstance(child, PContentPackage):
                    raise ValueError(
                        f"aggregate {specification_id} is not a PContent package"
                    )
                return child

            resolve_aggregates(loaded, load_aggregate)
        return loaded
    finally:
        client.close()


class BackgroundJobs:
    """Own a lazily created worker pool that can survive add-on reloads."""

    def __init__(self, *, max_workers: int = 2) -> None:
        """Configure a pool that will be allocated only on first submission."""
        self._max_workers = max_workers
        self._executor: ThreadPoolExecutor | None = None

    def submit(
        self,
        function: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        """Submit work, creating the persistent executor when necessary."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="mooblender",
            )
        return self._executor.submit(function, *args, **kwargs)

    def shutdown(self) -> None:
        """Cancel queued work and release the pool without blocking Blender."""
        if self._executor is not None:
            # Running HTTP calls finish under their own transport timeouts.
            # Waiting here would stall add-on disable or Blender shutdown.
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None


JOBS = BackgroundJobs()
# One stale in-flight preview batch must not hold up the newly visible cards.
THUMBNAIL_JOBS = BackgroundJobs(max_workers=2)
