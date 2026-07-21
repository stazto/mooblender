from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mooblender.mooble.catalog_store import CatalogStore
from mooblender.mooble.client import MoobleClient
from mooblender.mooble.models import CatalogCategory, CatalogItem, CatalogPage


class _CatalogClient:
    ROOT_URL = "https://catalog.mooble.com/furniture?%24top=48"
    CHILD_URL = "https://catalog.mooble.com/kitchen?%24top=48"
    DECOR_ROOT_URL = "https://catalog.mooble.com/decor?%24top=48"
    DECOR_CHILD_URL = "https://catalog.mooble.com/accessories?%24top=48"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.closed = False
        self.urls: list[str] = []

    def root_url(self, *, category: str, **_kwargs) -> str:
        return {
            "Moveis": self.ROOT_URL,
            "Decoracao": self.DECOR_ROOT_URL,
        }[category]

    def with_page_size(self, url: str, page_size: int) -> str:
        return MoobleClient.with_page_size(url, page_size)

    def browse_url(self, url: str, *, cache: bool) -> CatalogPage:
        if cache:
            raise AssertionError("catalog synchronization wrote the legacy page cache")
        self.urls.append(url)
        if self.fail:
            raise ValueError("sync failed")
        root = CatalogCategory(
            id="root",
            name="Furniture",
            url=self.ROOT_URL,
            level=0,
            item_count=2,
            selected=True,
        )
        child = CatalogCategory(
            id="child",
            name="Kitchen",
            url="https://catalog.mooble.com/kitchen?$top=12",
            level=1,
            item_count=1,
            selected=url == self.CHILD_URL,
        )
        if url == self.ROOT_URL:
            return CatalogPage(
                categories=(root, child),
                items=(
                    CatalogItem(id="one", name="One", brand="Maker A"),
                    CatalogItem(id="two", name="Two", brand="Maker B"),
                ),
                current_url=url,
                pin_name="Departamento",
            )
        if url == self.CHILD_URL:
            return CatalogPage(
                categories=(root, child),
                items=(CatalogItem(id="two", name="Two", brand="Maker B"),),
                current_url=url,
                pin_name="Departamento",
            )
        decor = CatalogCategory(
            id="decor",
            name="Decor",
            url=self.DECOR_ROOT_URL,
            level=0,
            item_count=2,
            selected=True,
        )
        accessories = CatalogCategory(
            id="accessories",
            name="Accessories",
            url="https://catalog.mooble.com/accessories?$top=12",
            level=1,
            item_count=1,
            selected=url == self.DECOR_CHILD_URL,
        )
        if url == self.DECOR_ROOT_URL:
            return CatalogPage(
                categories=(decor, accessories),
                items=(
                    CatalogItem(id="two", name="Two", brand="Maker B"),
                    CatalogItem(id="three", name="Three", brand="Maker C"),
                ),
                current_url=url,
                pin_name="Departamento",
            )
        if url == self.DECOR_CHILD_URL:
            return CatalogPage(
                categories=(decor, accessories),
                items=(CatalogItem(id="three", name="Three", brand="Maker C"),),
                current_url=url,
                pin_name="Departamento",
            )
        raise AssertionError(f"unexpected URL: {url}")

    def close(self) -> None:
        self.closed = True


class CatalogStoreTests(unittest.TestCase):
    def test_sync_persists_items_categories_and_memberships(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CatalogStore(Path(directory) / "catalog.sqlite3")
            client = _CatalogClient()
            progress = []

            summary = store.sync(
                client,  # type: ignore[arg-type]
                categories=("Moveis",),
                progress=progress.append,
            )

            self.assertTrue(client.closed)
            self.assertEqual(client.urls, [client.ROOT_URL, client.CHILD_URL])
            self.assertEqual(summary.item_count, 2)
            self.assertEqual(summary.category_count, 2)
            self.assertTrue(summary.synced_at)
            self.assertEqual(progress[-1].categories, 2)

            root = store.page()
            self.assertIsNotNone(root)
            assert root is not None
            self.assertEqual([item.id for item in root.items], ["one", "two"])
            self.assertEqual(
                [category.name for category in root.categories],
                ["Catalog", "Furniture"],
            )

            furniture = store.page(client.ROOT_URL)
            self.assertIsNotNone(furniture)
            assert furniture is not None
            self.assertEqual(
                [category.name for category in furniture.categories],
                ["Furniture", "Kitchen"],
            )

            child = store.page(client.CHILD_URL)
            self.assertIsNotNone(child)
            assert child is not None
            self.assertEqual([item.id for item in child.items], ["two"])
            self.assertEqual([category.name for category in child.categories], ["Kitchen"])

    def test_sync_combines_selected_departments_under_one_local_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CatalogStore(Path(directory) / "catalog.sqlite3")
            client = _CatalogClient()

            summary = store.sync(
                client,  # type: ignore[arg-type]
                categories=("Moveis", "Decoracao", "Moveis"),
            )

            self.assertEqual(
                client.urls,
                [
                    client.ROOT_URL,
                    client.DECOR_ROOT_URL,
                    client.CHILD_URL,
                    client.DECOR_CHILD_URL,
                ],
            )
            self.assertEqual(summary.item_count, 3)
            self.assertEqual(summary.category_count, 4)
            root = store.page()
            self.assertIsNotNone(root)
            assert root is not None
            self.assertEqual([item.id for item in root.items], ["one", "two", "three"])
            self.assertEqual(
                [category.name for category in root.categories],
                ["Catalog", "Furniture", "Decor"],
            )

    def test_failed_sync_preserves_the_previous_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CatalogStore(Path(directory) / "catalog.sqlite3")
            store.sync(_CatalogClient(), categories=("Moveis",))  # type: ignore[arg-type]

            with self.assertRaisesRegex(ValueError, "sync failed"):
                store.sync(  # type: ignore[arg-type]
                    _CatalogClient(fail=True),
                    categories=("Moveis",),
                )

            root = store.page()
            self.assertIsNotNone(root)
            assert root is not None
            self.assertEqual([item.id for item in root.items], ["one", "two"])

    def test_sync_requires_at_least_one_department(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CatalogStore(Path(directory) / "catalog.sqlite3")
            client = _CatalogClient()

            with self.assertRaisesRegex(ValueError, "at least one"):
                store.sync(client, categories=())  # type: ignore[arg-type]

            self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
