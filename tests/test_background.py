from __future__ import annotations

import threading
import unittest
from pathlib import Path

from mooblender.blender.background import (
    BackgroundJobs,
    fetch_catalog,
    fetch_catalog_index,
    fetch_thumbnails,
)
from mooblender.mooble.models import CatalogItem, CatalogPage


class _CatalogClient:
    def __init__(self, page: CatalogPage) -> None:
        self.page = page
        self.thumbnail_downloads = 0
        self.closed = False

    def browse(self, *, category: str, search: str) -> CatalogPage:
        self.arguments = (category, search)
        return self.page

    def download_thumbnail(self, item: CatalogItem) -> Path:
        self.thumbnail_downloads += 1
        return Path("/cache") / f"{item.id}.png"

    def close(self) -> None:
        self.closed = True

class BackgroundJobsTests(unittest.TestCase):
    def test_complete_catalog_index_uses_one_request_when_first_page_is_unchanged(
        self,
    ) -> None:
        first = CatalogItem(id="one", name="One")
        cached = CatalogPage(
            items=(first, CatalogItem(id="two", name="Two")),
            current_url="https://catalog.mooble.com/root",
        )

        class CachedIndexClient:
            def __init__(self):
                self.closed = False
                self.urls = []

            def root_url(self, **_kwargs):
                return cached.current_url

            def load_cached_page(self, _url):
                return cached

            def browse_url(self, url, *, cache):
                self.urls.append((url, cache))
                return CatalogPage(items=(first,), current_url=url)

            def close(self):
                self.closed = True

        client = CachedIndexClient()

        result = fetch_catalog_index(client, category="Moveis")  # type: ignore[arg-type]

        self.assertIs(result, cached)
        self.assertEqual(client.urls, [(cached.current_url, False)])
        self.assertTrue(client.closed)

    def test_catalog_index_follows_and_merges_every_page(self) -> None:
        class IndexClient:
            def __init__(self):
                self.closed = False
                self.urls = []

            def root_url(self, *, category, search, page_size):
                self.arguments = (category, search, page_size)
                return "https://catalog.mooble.com/root"

            def load_cached_page(self, _url):
                return None

            def browse_url(self, url, *, cache):
                self.urls.append(url)
                if url.endswith("root"):
                    return CatalogPage(
                        items=(CatalogItem(id="one", name="One"),),
                        next_url="https://catalog.mooble.com/page-2",
                        current_url=url,
                    )
                return CatalogPage(
                    items=(CatalogItem(id="two", name="Two"),),
                    current_url=url,
                )

            def cache_catalog_page(self, url, page):
                self.base_url = url
                self.cached = page

            def close(self):
                self.closed = True

        client = IndexClient()

        page = fetch_catalog_index(client, category="Moveis")  # type: ignore[arg-type]

        self.assertEqual([item.id for item in page.items], ["one", "two"])
        self.assertEqual(client.arguments, ("Moveis", "", 48))
        self.assertEqual(
            client.urls,
            [
                "https://catalog.mooble.com/root",
                "https://catalog.mooble.com/page-2",
            ],
        )
        self.assertEqual(client.base_url, "https://catalog.mooble.com/root")
        self.assertEqual(client.cached, page)
        self.assertTrue(client.closed)

    def test_runs_work_outside_the_calling_thread(self) -> None:
        jobs = BackgroundJobs(max_workers=1)
        try:
            worker_thread = jobs.submit(threading.get_ident).result(timeout=2)
        finally:
            jobs.shutdown()
        self.assertNotEqual(worker_thread, threading.get_ident())

    def test_catalog_fetch_does_not_download_thumbnails(self) -> None:
        item = CatalogItem(
            id="chair-1",
            name="Chair",
            description="",
            brand="",
            collection="",
            thumbnail_url="https://cdn.mooble.com/chair.png",
            detail_url="",
            item_type="Item",
        )
        page = CatalogPage(
            categories=(),
            items=(item,),
            next_url="",
            current_url="https://catalog.mooble.com/page",
            pin_name="Departamento",
        )
        client = _CatalogClient(page)

        downloaded = fetch_catalog(client, category="Moveis", search="chair")  # type: ignore[arg-type]

        self.assertEqual(client.arguments, ("Moveis", "chair"))
        self.assertEqual(downloaded, page)
        self.assertEqual(client.thumbnail_downloads, 0)
        self.assertTrue(client.closed)

        client.closed = False
        thumbnails = fetch_thumbnails(client, (item,))  # type: ignore[arg-type]

        self.assertEqual(thumbnails, {"chair-1": Path("/cache/chair-1.png")})
        self.assertEqual(client.thumbnail_downloads, 1)
        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
