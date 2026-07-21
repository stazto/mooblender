"""Blender-independent background work for the Mooble browser."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..formats import PContentPackage, load_path, resolve_aggregates
from ..mooble import CatalogItem
from ..mooble.client import MoobleClient
from ..mooble.models import CatalogPage


def _continuation_page_size(url: str, page_size: int) -> str:
    """Raise an observed continuation URL's existing page size safely."""

    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    if not any(key == "$top" for key, _value in query):
        return url
    resized = [
        (key, str(page_size) if key == "$top" else value)
        for key, value in query
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(resized), parts.fragment)
    )


def _reported_item_count(page: CatalogPage) -> int | None:
    return next(
        (
            category.item_count
            for category in page.categories
            if category.selected and category.item_count is not None
        ),
        None,
    )


def fetch_catalog(
    client: MoobleClient,
    *,
    category: str,
    search: str,
) -> CatalogPage:
    try:
        return client.browse(category=category, search=search)
    finally:
        client.close()


def fetch_catalog_index(
    client: MoobleClient,
    *,
    category: str,
    max_pages: int = 2048,
    max_items: int = 100_000,
) -> CatalogPage:
    """Download every metadata page for a department into its root cache."""

    root_url = client.root_url(category=category, search="", page_size=48)
    visited = {root_url}
    try:
        cached = client.load_cached_page(root_url)
        page = client.browse_url(root_url, cache=False)
        expected_items = _reported_item_count(page)
        if (
            cached is not None
            and not cached.next_url
            and cached.categories == page.categories
            and len(cached.items) >= len(page.items)
            and cached.items[: len(page.items)] == page.items
            and (expected_items is None or len(cached.items) >= expected_items)
        ):
            return cached
        categories = {value.id: value for value in page.categories}
        items = {value.id: value for value in page.items}
        next_url = _continuation_page_size(page.next_url, 48)
        pin_name = page.pin_name
        pages = 1
        while next_url:
            if next_url in visited:
                raise ValueError("Mooble catalog pagination contains a cycle")
            if pages >= max_pages:
                raise ValueError("Mooble catalog exceeds the page safety limit")
            visited.add(next_url)
            page = client.browse_url(next_url, cache=False)
            categories.update((value.id, value) for value in page.categories)
            items.update((value.id, value) for value in page.items)
            next_url = _continuation_page_size(page.next_url, 48)
            pin_name = pin_name or page.pin_name
            pages += 1
            if len(items) > max_items:
                raise ValueError("Mooble catalog exceeds the item safety limit")
        if expected_items is not None and len(items) < expected_items:
            raise ValueError(
                f"Mooble catalog ended after {len(items)} of {expected_items} items"
            )
        merged = CatalogPage(
            categories=tuple(categories.values()),
            items=tuple(items.values()),
            current_url=root_url,
            pin_name=pin_name,
        )
        client.cache_catalog_page(root_url, merged)
        return merged
    finally:
        client.close()


def fetch_catalog_url(
    client: MoobleClient,
    url: str,
    *,
    extend_cache_url: str = "",
) -> CatalogPage:
    try:
        page = client.browse_url(url)
        if extend_cache_url:
            return client.extend_cached_page(extend_cache_url, page)
        return page
    finally:
        client.close()


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
THUMBNAIL_JOBS = BackgroundJobs(max_workers=1)
