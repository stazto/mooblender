"""Persistent, locally queryable mirror of the Mooble catalog."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from collections import deque
from collections.abc import Callable
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .client import MoobleClient
from .models import CatalogCategory, CatalogItem, CatalogPage

SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class CatalogSyncProgress:
    pages: int
    categories: int
    queued_categories: int
    item_records: int
    current_category: str


@dataclass(frozen=True, slots=True)
class CatalogSummary:
    item_count: int
    category_count: int
    synced_at: str


def _selected_category(page: CatalogPage) -> CatalogCategory | None:
    selected = [category for category in page.categories if category.selected]
    return max(selected, key=lambda category: category.level, default=None)


def _direct_children(
    page: CatalogPage,
    current: CatalogCategory,
) -> tuple[CatalogCategory, ...]:
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
) -> tuple[CatalogPage, int]:
    visited: set[str] = set()
    categories: dict[str, CatalogCategory] = {}
    items: dict[str, CatalogItem] = {}
    next_url = url
    pin_name = ""
    pages = 0
    while next_url:
        if next_url in visited:
            raise ValueError("Mooble catalog pagination contains a cycle")
        if pages >= max_pages:
            raise ValueError("Mooble category exceeds the page safety limit")
        visited.add(next_url)
        page = client.browse_url(next_url, cache=False)
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


class CatalogStore:
    """Read a catalog snapshot, or atomically replace it during manual sync."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        if not self.path.is_file():
            return False
        try:
            with closing(self._connect()) as connection:
                return self._metadata(connection, "schema_version") == SCHEMA_VERSION
        except sqlite3.Error:
            return False

    def root_url(self) -> str:
        with closing(self._connect()) as connection:
            return self._metadata(connection, "root_url")

    def summary(self) -> CatalogSummary:
        with closing(self._connect()) as connection:
            item_count = connection.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            category_count = connection.execute(
                "SELECT COUNT(*) FROM categories"
            ).fetchone()[0]
            return CatalogSummary(
                item_count=item_count,
                category_count=category_count,
                synced_at=self._metadata(connection, "synced_at"),
            )

    def page(self, url: str = "") -> CatalogPage | None:
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
        category: str,
        progress: Callable[[CatalogSyncProgress], None] | None = None,
        max_pages_per_category: int = 2048,
        max_categories: int = 4096,
        max_unique_items: int = 100_000,
        max_memberships: int = 1_000_000,
    ) -> CatalogSummary:
        """Download the complete category tree into a temporary database."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        root_url = client.root_url(category=category, search="", page_size=48)
        pages = 0
        memberships = 0
        visited: set[str] = set()
        pending = deque([(root_url, "", 0)])
        try:
            with closing(sqlite3.connect(temporary_path)) as connection:
                self._create_schema(connection)
                while pending:
                    url, parent_url, category_position = pending.popleft()
                    url = client.with_page_size(url, 48)
                    if url in visited:
                        continue
                    if len(visited) >= max_categories:
                        raise ValueError("Mooble catalog exceeds the category safety limit")
                    visited.add(url)
                    completed_pages = pages

                    def report_page(
                        category_pages: int,
                        category_items: int,
                        category_name: str,
                        completed_pages: int = completed_pages,
                        completed_memberships: int = memberships,
                    ) -> None:
                        if progress is not None:
                            progress(
                                CatalogSyncProgress(
                                    pages=completed_pages + category_pages,
                                    categories=len(visited),
                                    queued_categories=len(pending),
                                    item_records=completed_memberships + category_items,
                                    current_category=category_name,
                                )
                            )

                    page, downloaded_pages = _complete_page(
                        client,
                        url,
                        max_pages=max_pages_per_category,
                        progress=report_page,
                    )
                    pages += downloaded_pages
                    current = _selected_category(page)
                    if current is None:
                        current = CatalogCategory(
                            id=category,
                            name=category,
                            url=url,
                            item_count=len(page.items),
                            selected=True,
                        )
                    self._write_category(
                        connection,
                        CatalogCategory(
                            id=current.id,
                            name=current.name,
                            url=url,
                            level=current.level,
                            item_count=current.item_count,
                            selected=True,
                        ),
                        parent_url=parent_url,
                        position=category_position,
                    )
                    for position, child in enumerate(_direct_children(page, current), 1):
                        child_url = client.with_page_size(child.url, 48)
                        normalized_child = CatalogCategory(
                            id=child.id,
                            name=child.name,
                            url=child_url,
                            level=child.level,
                            item_count=child.item_count,
                        )
                        self._write_category(
                            connection,
                            normalized_child,
                            parent_url=url,
                            position=position,
                        )
                        if child_url not in visited:
                            pending.append((child_url, url, position))
                    self._write_items(connection, url, page.items)
                    memberships += len(page.items)
                    if memberships > max_memberships:
                        raise ValueError("Mooble catalog exceeds the membership safety limit")
                    unique_items = connection.execute(
                        "SELECT COUNT(*) FROM items"
                    ).fetchone()[0]
                    if unique_items > max_unique_items:
                        raise ValueError("Mooble catalog exceeds the item safety limit")
                    connection.commit()
                    if progress is not None:
                        progress(
                            CatalogSyncProgress(
                                pages=pages,
                                categories=len(visited),
                                queued_categories=len(pending),
                                item_records=memberships,
                                current_category=current.name,
                            )
                        )
                synced_at = datetime.now(UTC).isoformat(timespec="seconds")
                self._set_metadata(connection, "schema_version", SCHEMA_VERSION)
                self._set_metadata(connection, "root_url", root_url)
                self._set_metadata(connection, "synced_at", synced_at)
                connection.commit()
            os.replace(temporary_path, self.path)
            return self.summary()
        finally:
            client.close()
            with suppress(FileNotFoundError):
                temporary_path.unlink()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
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
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row is not None else ""

    @staticmethod
    def _set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            (key, value),
        )
