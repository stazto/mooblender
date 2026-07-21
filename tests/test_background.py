from __future__ import annotations

import threading
import unittest
from pathlib import Path

from mooblender.blender.background import (
    BackgroundJobs,
    fetch_thumbnails,
)
from mooblender.mooble.models import CatalogItem


class _CatalogClient:
    def __init__(self) -> None:
        self.thumbnail_downloads = 0
        self.closed = False

    def download_thumbnail(self, item: CatalogItem) -> Path:
        self.thumbnail_downloads += 1
        return Path("/cache") / f"{item.id}.png"

    def close(self) -> None:
        self.closed = True

class BackgroundJobsTests(unittest.TestCase):
    def test_runs_work_outside_the_calling_thread(self) -> None:
        jobs = BackgroundJobs(max_workers=1)
        try:
            worker_thread = jobs.submit(threading.get_ident).result(timeout=2)
        finally:
            jobs.shutdown()
        self.assertNotEqual(worker_thread, threading.get_ident())

    def test_thumbnail_fetch_downloads_only_the_requested_items(self) -> None:
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
        client = _CatalogClient()
        thumbnails = fetch_thumbnails(client, (item,))  # type: ignore[arg-type]

        self.assertEqual(thumbnails, {"chair-1": Path("/cache/chair-1.png")})
        self.assertEqual(client.thumbnail_downloads, 1)
        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
