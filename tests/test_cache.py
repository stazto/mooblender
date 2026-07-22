"""Safety and eviction tests for bounded downloaded-file caches."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from mooblender.mooble.cache import (
    cache_paths_in_use,
    cache_stats,
    clear_download_cache,
    prune_cache_group,
)


class DownloadCacheTests(unittest.TestCase):
    """Verify LRU pruning, active-file protection, and clear boundaries."""

    def test_prune_removes_oldest_files_and_preserves_active_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "models"
            models.mkdir()
            oldest = models / "old.pcontent"
            middle = models / "middle.pcontent"
            active = models / "active.pcontent"
            for path in (oldest, middle, active):
                path.write_bytes(b"1234")
            os.utime(oldest, ns=(1, 1))
            os.utime(middle, ns=(2, 2))
            os.utime(active, ns=(3, 3))

            with cache_paths_in_use((active,)):
                cleanup = prune_cache_group(root, "models", 8)

            self.assertFalse(oldest.exists())
            self.assertTrue(middle.exists())
            self.assertTrue(active.exists())
            self.assertEqual(cleanup.removed_files, 1)
            self.assertEqual(cleanup.remaining_bytes, 8)

    def test_clear_preserves_catalog_external_targets_and_nested_unknowns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "cache"
            models = root / "models"
            thumbnails = root / "thumbnails"
            nested = models / "unknown"
            nested.mkdir(parents=True)
            thumbnails.mkdir(parents=True)
            model = models / "model.pcontent"
            preview = thumbnails / "preview.png"
            nested_file = nested / "keep.bin"
            catalog = root / "catalog.sqlite3"
            external = Path(directory) / "external.bin"
            model.write_bytes(b"model")
            preview.write_bytes(b"preview")
            nested_file.write_bytes(b"nested")
            catalog.write_bytes(b"catalog")
            external.write_bytes(b"external")
            link = models / "external-link"
            link.symlink_to(external)

            cleanup = clear_download_cache(root)

            self.assertFalse(model.exists())
            self.assertFalse(preview.exists())
            self.assertFalse(link.exists())
            self.assertTrue(external.exists())
            self.assertTrue(nested_file.exists())
            self.assertTrue(catalog.exists())
            self.assertEqual(cleanup.removed_files, 3)

    def test_nested_active_users_remain_protected_until_every_user_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "models" / "shared.pcontent"
            model.parent.mkdir()
            model.write_bytes(b"shared")

            with cache_paths_in_use((model,)):
                with cache_paths_in_use((model,)):
                    self.assertEqual(clear_download_cache(root).removed_files, 0)
                self.assertEqual(clear_download_cache(root).removed_files, 0)
            self.assertEqual(clear_download_cache(root).removed_files, 1)

    def test_model_content_and_metadata_are_evicted_as_one_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "models"
            models.mkdir()
            old_content = models / "old.pcontent"
            old_metadata = models / "old.pcontent.json"
            new_content = models / "new.pcontent"
            new_metadata = models / "new.pcontent.json"
            for path in (old_content, old_metadata, new_content, new_metadata):
                path.write_bytes(b"1234")
            os.utime(old_content, ns=(1, 1))
            os.utime(old_metadata, ns=(1, 1))
            os.utime(new_content, ns=(2, 2))
            os.utime(new_metadata, ns=(2, 2))

            cleanup = prune_cache_group(root, "models", 12)

            self.assertFalse(old_content.exists())
            self.assertFalse(old_metadata.exists())
            self.assertTrue(new_content.exists())
            self.assertTrue(new_metadata.exists())
            self.assertEqual(cleanup.removed_files, 2)
            self.assertEqual(cleanup.remaining_bytes, 8)

    def test_stats_include_stale_temporary_files_but_pruning_ignores_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            models = root / "models"
            models.mkdir()
            temporary = models / "partial.tmp"
            temporary.write_bytes(b"partial")

            cleanup = prune_cache_group(root, "models", 0)

            self.assertTrue(temporary.exists())
            self.assertEqual(cleanup.removed_files, 0)
            self.assertEqual(cache_stats(root).bytes, len(b"partial"))
            self.assertEqual(clear_download_cache(root).removed_files, 1)


if __name__ == "__main__":
    unittest.main()
