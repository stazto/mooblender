"""Blender-independent background work for the Mooble browser."""

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
    if not items:
        return {}
    workers = min(4, len(items))
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            paths = executor.map(client.download_thumbnail, items)
            return {item.id: path for item, path in zip(items, paths, strict=True)}
    finally:
        client.close()


def fetch_model(client: MoobleClient, item: CatalogItem):
    try:
        path = client.download_model(item)
        loaded = load_path(path)
        if isinstance(loaded, PContentPackage):
            def load_aggregate(specification_id: str) -> PContentPackage:
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
    try:
        loaded = load_path(path)
        if isinstance(loaded, PContentPackage):
            def load_aggregate(specification_id: str) -> PContentPackage:
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
        self._max_workers = max_workers
        self._executor: ThreadPoolExecutor | None = None

    def submit(
        self,
        function: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="mooblender",
            )
        return self._executor.submit(function, *args, **kwargs)

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None


JOBS = BackgroundJobs()
# One stale in-flight preview batch must not hold up the newly visible cards.
THUMBNAIL_JOBS = BackgroundJobs(max_workers=2)
