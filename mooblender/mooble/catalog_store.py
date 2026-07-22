"""Persistent, locally queryable mirror of the Mooble catalog."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections import deque
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from .client import MoobleClient
from .models import CatalogCategory, CatalogItem, CatalogPage

SCHEMA_VERSION = "2"
LOCAL_ROOT_URL = "mooblender://catalog/root"


class CatalogSyncCancelled(RuntimeError):
    """Raised when the user cooperatively stops a catalog synchronization."""


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    """Stop at a safe sync boundary when the caller requested cancellation."""
    if cancelled is not None and cancelled():
        raise CatalogSyncCancelled("Catalog synchronization was cancelled")


@dataclass(frozen=True, slots=True)
class CatalogSyncProgress:
    """Immutable progress snapshot emitted during a full catalog sync."""

    pages: int
    categories: int
    queued_categories: int
    item_records: int
    current_category: str


@dataclass(frozen=True, slots=True)
class CatalogSummary:
    """Counts and timestamp describing the published local snapshot."""

    item_count: int
    category_count: int
    synced_at: str


@dataclass(frozen=True, slots=True)
class _CategoryRequest:
    """Queue entry retaining a category's parent and stable display order."""

    url: str
    parent_url: str
    position: int
    fallback_id: str


class _SyncProgressTracker:
    """Combine parallel category progress into coherent immutable snapshots."""

    def __init__(
        self,
        callback: Callable[[CatalogSyncProgress], None] | None,
    ) -> None:
        """Initialize counters protected against concurrent worker updates."""
        self.callback = callback
        self.lock = Lock()
        self.completed_pages = 0
        self.completed_items = 0
        self.categories = 0
        self.outstanding = 0
        self.active: dict[str, tuple[int, int, str]] = {}

    def set_work(self, *, categories: int, outstanding: int) -> None:
        """Update discovered and outstanding category counts atomically."""
        with self.lock:
            self.categories = categories
            self.outstanding = outstanding

    def category_page(
        self,
        key: str,
        pages: int,
        items: int,
        category_name: str,
    ) -> None:
        """Record intermediate pagination progress for one active category."""
        with self.lock:
            self.active[key] = (pages, items, category_name)
            snapshot = self._snapshot(category_name)
            if self.callback is not None:
                self.callback(snapshot)

    def category_complete(
        self,
        key: str,
        *,
        pages: int,
        items: int,
        category_name: str,
        categories: int,
        outstanding: int,
    ) -> None:
        """Move one category's active counters into completed totals."""
        with self.lock:
            self.active.pop(key, None)
            self.completed_pages += pages
            self.completed_items += items
            self.categories = categories
            self.outstanding = outstanding
            snapshot = self._snapshot(category_name)
            if self.callback is not None:
                self.callback(snapshot)

    def _snapshot(self, category_name: str) -> CatalogSyncProgress:
        """Combine completed totals with every currently active download."""
        return CatalogSyncProgress(
            pages=self.completed_pages + sum(value[0] for value in self.active.values()),
            categories=self.categories,
            queued_categories=self.outstanding,
            item_records=(
                self.completed_items + sum(value[1] for value in self.active.values())
            ),
            current_category=category_name,
        )


def _selected_category(page: CatalogPage) -> CatalogCategory | None:
    """Choose the deepest category marked as the current page."""
    selected = [category for category in page.categories if category.selected]
    return max(selected, key=lambda category: category.level, default=None)


def _direct_children(
    page: CatalogPage,
    current: CatalogCategory,
) -> tuple[CatalogCategory, ...]:
    """Return only immediate navigable children of the current category."""
    return tuple(
        category
        for category in page.categories
        if not category.selected
        and category.level == current.level + 1
        and category.url
    )


def _complete_page(
    client: MoobleClient,
    url: str,
    *,
    max_pages: int,
    progress: Callable[[int, int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[CatalogPage, int]:
    """Download and merge every paginated response for one category."""
    visited: set[str] = set()
    categories: dict[str, CatalogCategory] = {}
    items: dict[str, CatalogItem] = {}
    next_url = url
    pin_name = ""
    pages = 0
    while next_url:
        # HTTP requests cannot be interrupted safely from another thread.  The
        # worker checks immediately before and after each bounded request, so a
        # cancellation waits for at most the active response and publishes no
        # partial category.
        _raise_if_cancelled(cancelled)
        if next_url in visited:
            raise ValueError("Mooble catalog pagination contains a cycle")
        if pages >= max_pages:
            raise ValueError("Mooble category exceeds the page safety limit")
        visited.add(next_url)
        page = client.browse_url(next_url, cache=False)
        _raise_if_cancelled(cancelled)
        categories.update((category.id, category) for category in page.categories)
        items.update((item.id, item) for item in page.items)
        next_url = client.with_page_size(page.next_url, 48)
        pin_name = pin_name or page.pin_name
        pages += 1
        if progress is not None:
            selected = _selected_category(page)
            progress(
                pages,
                len(items),
                selected.name if selected is not None else url,
            )

    complete = CatalogPage(
        categories=tuple(categories.values()),
        items=tuple(items.values()),
        current_url=url,
        pin_name=pin_name,
    )
    selected = _selected_category(complete)
    if (
        selected is not None
        and selected.item_count is not None
        and len(complete.items) < selected.item_count
    ):
        raise ValueError(
            f"Mooble category {selected.name!r} ended after "
            f"{len(complete.items)} of {selected.item_count} items"
        )
    return complete, pages


class _CatalogCrawler:
    """Coordinate bounded parallel downloads while serializing SQLite writes."""

    def __init__(
        self,
        store,
        client: MoobleClient,
        connection: sqlite3.Connection,
        progress: _SyncProgressTracker,
        *,
        workers: int,
        max_pages: int,
        max_categories: int,
        max_unique_items: int,
        max_memberships: int,
        cancelled: Callable[[], bool] | None,
    ) -> None:
        """Configure bounded work queues, safety limits, and the write connection."""
        self.store = store
        self.client = client
        self.connection = connection
        self.progress = progress
        self.workers = min(max(workers, 1), 8)
        self.max_pages = max_pages
        self.max_categories = max_categories
        self.max_unique_items = max_unique_items
        self.max_memberships = max_memberships
        self.cancelled = cancelled
        self.pending: deque[_CategoryRequest] = deque()
        self.in_flight: dict[Future[tuple[CatalogPage, int]], _CategoryRequest] = {}
        self.visited: set[str] = set()
        self.memberships = 0
        self.department_item_ids: dict[int, tuple[str, ...]] = {}

    def crawl(self, requests) -> dict[int, tuple[str, ...]]:
        """Download every reachable category and persist each completed page."""
        self.pending.extend(requests)
        with ThreadPoolExecutor(
            max_workers=self.workers,
            thread_name_prefix="mooblender-catalog",
        ) as executor:
            while self.pending or self.in_flight:
                _raise_if_cancelled(self.cancelled)
                self._fill_workers(executor)
                if not self.in_flight:
                    continue
                completed, _unfinished = wait(
                    tuple(self.in_flight), return_when=FIRST_COMPLETED
                )
                for future in completed:
                    _raise_if_cancelled(self.cancelled)
                    self._consume(future)
        return self.department_item_ids

    def _fill_workers(self, executor: ThreadPoolExecutor) -> None:
        """Submit unseen categories until the bounded worker pool is full."""
        while self.pending and len(self.in_flight) < self.workers:
            _raise_if_cancelled(self.cancelled)
            request = self.pending.popleft()
            request = _CategoryRequest(
                self.client.with_page_size(request.url, 48),
                request.parent_url,
                request.position,
                request.fallback_id,
            )
            if request.url in self.visited:
                continue
            if len(self.visited) >= self.max_categories:
                raise ValueError("Mooble catalog exceeds the category safety limit")
            self.visited.add(request.url)

            def report_page(
                pages: int,
                items: int,
                category_name: str,
                key: str = request.url,
            ) -> None:
                """Attribute worker pagination progress to this request URL."""
                self.progress.category_page(key, pages, items, category_name)

            future = executor.submit(
                _complete_page,
                self.client,
                request.url,
                max_pages=self.max_pages,
                progress=report_page,
                cancelled=self.cancelled,
            )
            self.in_flight[future] = request
            self._update_work()

    def _consume(self, future: Future[tuple[CatalogPage, int]]) -> None:
        """Serialize one completed download into SQLite and queue its children."""
        _raise_if_cancelled(self.cancelled)
        request = self.in_flight.pop(future)
        page, downloaded_pages = future.result()
        current = _selected_category(page) or CatalogCategory(
            id=request.fallback_id,
            name=request.fallback_id,
            url=request.url,
            item_count=len(page.items),
            selected=True,
        )
        self._write_current(request, current)
        self._queue_children(request, current, page)
        self.store._write_items(self.connection, request.url, page.items)
        if request.parent_url == LOCAL_ROOT_URL:
            self.department_item_ids[request.position] = tuple(
                item.id for item in page.items
            )
        self._check_item_limits(len(page.items))
        self.connection.commit()
        self.progress.category_complete(
            request.url,
            pages=downloaded_pages,
            items=len(page.items),
            category_name=current.name,
            categories=len(self.visited),
            outstanding=len(self.pending) + len(self.in_flight),
        )

    def _write_current(
        self,
        request: _CategoryRequest,
        current: CatalogCategory,
    ) -> None:
        """Persist the canonical selected row for the downloaded category."""
        normalized = CatalogCategory(
            id=current.id,
            name=current.name,
            url=request.url,
            level=current.level,
            item_count=current.item_count,
            selected=True,
        )
        self.store._write_category(
            self.connection,
            normalized,
            parent_url=request.parent_url,
            position=request.position,
        )

    def _queue_children(
        self,
        request: _CategoryRequest,
        current: CatalogCategory,
        page: CatalogPage,
    ) -> None:
        """Persist immediate children and enqueue unseen category pages."""
        for position, child in enumerate(_direct_children(page, current), 1):
            child_url = self.client.with_page_size(child.url, 48)
            normalized = CatalogCategory(
                id=child.id,
                name=child.name,
                url=child_url,
                level=child.level,
                item_count=child.item_count,
            )
            self.store._write_category(
                self.connection,
                normalized,
                parent_url=request.url,
                position=position,
            )
            if child_url not in self.visited:
                self.pending.append(
                    _CategoryRequest(child_url, request.url, position, child.id)
                )

    def _check_item_limits(self, page_items: int) -> None:
        """Enforce separate limits for memberships and unique catalog items."""
        self.memberships += page_items
        if self.memberships > self.max_memberships:
            raise ValueError("Mooble catalog exceeds the membership safety limit")
        unique_items = self.connection.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        if unique_items > self.max_unique_items:
            raise ValueError("Mooble catalog exceeds the item safety limit")

    def _update_work(self) -> None:
        """Publish the crawler's current discovered and outstanding work."""
        self.progress.set_work(
            categories=len(self.visited),
            outstanding=len(self.pending) + len(self.in_flight),
        )


class CatalogStore:
    """Read a catalog snapshot, or atomically replace it during manual sync."""

    def __init__(self, path: str | Path) -> None:
        """Bind the store to one SQLite snapshot path without opening it yet."""
        self.path = Path(path)

    def exists(self) -> bool:
        """Return whether a readable snapshot with the current schema exists."""
        if not self.path.is_file():
            return False
        try:
            with closing(self._connect()) as connection:
                return self._metadata(connection, "schema_version") == SCHEMA_VERSION
        except sqlite3.Error:
            return False

    def root_url(self) -> str:
        """Return the synthetic root URL recorded in snapshot metadata."""
        with closing(self._connect()) as connection:
            return self._metadata(connection, "root_url")

    def summary(self) -> CatalogSummary:
        """Read published item/category counts and synchronization timestamp."""
        with closing(self._connect()) as connection:
            item_count = connection.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            category_count = connection.execute(
                "SELECT COUNT(*) FROM categories WHERE url != ?",
                (LOCAL_ROOT_URL,),
            ).fetchone()[0]
            return CatalogSummary(
                item_count=item_count,
                category_count=category_count,
                synced_at=self._metadata(connection, "synced_at"),
            )

    def page(self, url: str = "") -> CatalogPage | None:
        """Reconstruct one cached page with direct children and item membership."""
        with closing(self._connect()) as connection:
            target = url or self._metadata(connection, "root_url")
            current_row = connection.execute(
                """
                SELECT id, name, url, level, item_count
                FROM categories WHERE url = ?
                """,
                (target,),
            ).fetchone()
            if current_row is None:
                return None
            current = CatalogCategory(
                id=current_row[0],
                name=current_row[1],
                url=current_row[2],
                level=current_row[3],
                item_count=current_row[4],
                selected=True,
            )
            children = tuple(
                CatalogCategory(
                    id=row[0],
                    name=row[1],
                    url=row[2],
                    level=row[3],
                    item_count=row[4],
                )
                for row in connection.execute(
                    """
                    SELECT id, name, url, level, item_count
                    FROM categories
                    WHERE parent_url = ?
                    ORDER BY position, name COLLATE NOCASE
                    """,
                    (target,),
                )
            )
            items = tuple(
                CatalogItem(
                    id=row[0],
                    name=row[1],
                    description=row[2],
                    brand=row[3],
                    collection=row[4],
                    thumbnail_url=row[5],
                    detail_url=row[6],
                    item_type=row[7],
                )
                for row in connection.execute(
                    """
                    SELECT i.id, i.name, i.description, i.brand, i.collection_name,
                           i.thumbnail_url, i.detail_url, i.item_type
                    FROM category_items AS ci
                    JOIN items AS i ON i.id = ci.item_id
                    WHERE ci.category_url = ?
                    ORDER BY ci.position
                    """,
                    (target,),
                )
            )
            return CatalogPage(
                categories=(current, *children),
                items=items,
                current_url=target,
                pin_name="Departamento",
            )

    def sync(
        self,
        client: MoobleClient,
        *,
        categories: tuple[str, ...],
        progress: Callable[[CatalogSyncProgress], None] | None = None,
        max_download_workers: int = 4,
        max_pages_per_category: int = 2048,
        max_categories: int = 4096,
        max_unique_items: int = 100_000,
        max_memberships: int = 1_000_000,
        cancelled: Callable[[], bool] | None = None,
    ) -> CatalogSummary:
        """Download selected department trees into one atomic local database."""
        categories = tuple(dict.fromkeys(category for category in categories if category))
        if not categories:
            client.close()
            raise ValueError("Select at least one Mooble catalog section")

        try:
            _raise_if_cancelled(cancelled)
            source_urls = tuple(
                client.root_url(category=category, search="", page_size=48)
                for category in categories
            )
        except Exception:
            client.close()
            raise
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        requests = (
            _CategoryRequest(url, LOCAL_ROOT_URL, position, category)
            for position, (category, url) in enumerate(
                zip(categories, source_urls, strict=True),
                1,
            )
        )
        progress_tracker = _SyncProgressTracker(progress)
        try:
            with closing(sqlite3.connect(temporary_path)) as connection:
                self._create_schema(connection)
                self._write_category(
                    connection,
                    CatalogCategory(
                        id="mooblender-root",
                        name="Catalog",
                        url=LOCAL_ROOT_URL,
                        level=-1,
                        item_count=0,
                        selected=True,
                    ),
                    parent_url="",
                    position=0,
                )
                department_item_ids = _CatalogCrawler(
                    self,
                    client,
                    connection,
                    progress_tracker,
                    workers=max_download_workers,
                    max_pages=max_pages_per_category,
                    max_categories=max_categories,
                    max_unique_items=max_unique_items,
                    max_memberships=max_memberships,
                    cancelled=cancelled,
                ).crawl(requests)
                _raise_if_cancelled(cancelled)
                root_item_ids: list[str] = []
                root_item_set: set[str] = set()
                for position in sorted(department_item_ids):
                    for item_id in department_item_ids[position]:
                        if item_id not in root_item_set:
                            root_item_set.add(item_id)
                            root_item_ids.append(item_id)
                self._write_category(
                    connection,
                    CatalogCategory(
                        id="mooblender-root",
                        name="Catalog",
                        url=LOCAL_ROOT_URL,
                        level=-1,
                        item_count=len(root_item_ids),
                        selected=True,
                    ),
                    parent_url="",
                    position=0,
                )
                connection.executemany(
                    """
                    INSERT INTO category_items(category_url, item_id, position)
                    VALUES (?, ?, ?)
                    """,
                    (
                        (LOCAL_ROOT_URL, item_id, position)
                        for position, item_id in enumerate(root_item_ids)
                    ),
                )
                synced_at = datetime.now(UTC).isoformat(timespec="seconds")
                self._set_metadata(connection, "schema_version", SCHEMA_VERSION)
                self._set_metadata(connection, "root_url", LOCAL_ROOT_URL)
                self._set_metadata(
                    connection,
                    "departments",
                    json.dumps(categories, separators=(",", ":")),
                )
                self._set_metadata(
                    connection,
                    "source_urls",
                    json.dumps(source_urls, separators=(",", ":")),
                )
                self._set_metadata(connection, "synced_at", synced_at)
                connection.commit()
            # Check once more at the final safe boundary before publishing the
            # completed temporary database over the usable snapshot.
            _raise_if_cancelled(cancelled)
            os.replace(temporary_path, self.path)
            return self.summary()
        finally:
            client.close()
            with suppress(FileNotFoundError):
                temporary_path.unlink()

    def _connect(self) -> sqlite3.Connection:
        """Open the published snapshot in query-only mode."""
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        """Create the normalized schema used by a fresh temporary snapshot."""
        connection.executescript(
            """
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE items (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                brand TEXT NOT NULL,
                collection_name TEXT NOT NULL,
                thumbnail_url TEXT NOT NULL,
                detail_url TEXT NOT NULL,
                item_type TEXT NOT NULL
            );
            CREATE TABLE categories (
                url TEXT PRIMARY KEY,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                parent_url TEXT NOT NULL,
                level INTEGER NOT NULL,
                item_count INTEGER,
                position INTEGER NOT NULL
            );
            CREATE TABLE category_items (
                category_url TEXT NOT NULL,
                item_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (category_url, item_id)
            );
            CREATE INDEX category_items_url_position
                ON category_items(category_url, position);
            CREATE INDEX categories_parent_position
                ON categories(parent_url, position);
            """
        )

    @staticmethod
    def _write_category(
        connection: sqlite3.Connection,
        category: CatalogCategory,
        *,
        parent_url: str,
        position: int,
    ) -> None:
        """Insert or update one category while preserving hierarchy metadata."""
        connection.execute(
            """
            INSERT INTO categories(url, id, name, parent_url, level, item_count, position)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                id=excluded.id,
                name=excluded.name,
                parent_url=excluded.parent_url,
                level=excluded.level,
                item_count=excluded.item_count,
                position=excluded.position
            """,
            (
                category.url,
                category.id,
                category.name,
                parent_url,
                category.level,
                category.item_count,
                position,
            ),
        )

    @staticmethod
    def _write_items(
        connection: sqlite3.Connection,
        category_url: str,
        items: tuple[CatalogItem, ...],
    ) -> None:
        """Upsert unique items and record their ordered category membership."""
        connection.executemany(
            """
            INSERT INTO items(
                id, name, description, brand, collection_name,
                thumbnail_url, detail_url, item_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                description=excluded.description,
                brand=excluded.brand,
                collection_name=excluded.collection_name,
                thumbnail_url=excluded.thumbnail_url,
                detail_url=excluded.detail_url,
                item_type=excluded.item_type
            """,
            (
                (
                    item.id,
                    item.name,
                    item.description,
                    item.brand,
                    item.collection,
                    item.thumbnail_url,
                    item.detail_url,
                    item.item_type,
                )
                for item in items
            ),
        )
        connection.executemany(
            """
            INSERT INTO category_items(category_url, item_id, position)
            VALUES (?, ?, ?)
            """,
            ((category_url, item.id, position) for position, item in enumerate(items)),
        )

    @staticmethod
    def _metadata(connection: sqlite3.Connection, key: str) -> str:
        """Read a metadata value, returning an empty string when absent."""
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row is not None else ""

    @staticmethod
    def _set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
        """Insert or replace one metadata value in the temporary snapshot."""
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            (key, value),
        )
