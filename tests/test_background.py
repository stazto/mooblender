from __future__ import annotations

import threading
import unittest

from mooblender.blender.background import BackgroundJobs, fetch_catalog
from mooblender.mooble.models import CatalogItem, CatalogPage


class _CatalogClient:
    def __init__(self, page: CatalogPage) -> None:
        self.page = page

    def browse(self, *, category: str, search: str) -> CatalogPage:
        self.arguments = (category, search)
        return self.page

class BackgroundJobsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
