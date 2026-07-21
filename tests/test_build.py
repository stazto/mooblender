from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_blender_addon import (
    DEFAULT_SOURCE,
    BuildError,
    build_addon,
    collect_source_files,
    development_version,
    version_from_git_tag,
)


class BuildAddonTests(unittest.TestCase):
    def test_archive_has_blender_extension_at_its_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = build_addon(DEFAULT_SOURCE, Path(temporary_directory), dev_build=1)

            self.assertEqual(archive_path.name, "mooblender-0.1.0-dev001.zip")
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()

            expected = [path.as_posix() for path in collect_source_files(DEFAULT_SOURCE)]
            self.assertEqual(names, expected)
            self.assertIn("blender_manifest.toml", names)
            self.assertIn("__init__.py", names)
            self.assertNotIn("mooblender/blender_manifest.toml", names)
            self.assertFalse(any("__pycache__" in name for name in names))

    def test_git_tag_controls_archive_and_manifest_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = build_addon(
                DEFAULT_SOURCE,
                Path(temporary_directory),
                git_tag="v1.2.3",
                dev_build=42,
            )

            self.assertEqual(archive_path.name, "mooblender-1.2.3-dev042.zip")
            with zipfile.ZipFile(archive_path) as archive:
                manifest = archive.read("blender_manifest.toml").decode("utf-8")
            self.assertIn('version = "1.2.3-dev042"', manifest)

    def test_stable_git_tag_is_accepted(self) -> None:
        self.assertEqual(version_from_git_tag("v1.2.3"), "1.2.3")

    def test_development_suffix_is_generated(self) -> None:
        self.assertEqual(development_version("1.2.3", 7), "1.2.3-dev007")
        self.assertEqual(development_version("1.2.3", 1234), "1.2.3-dev1234")

    def test_invalid_git_tags_are_rejected(self) -> None:
        for tag in ("release-1.2.3", "v1.2.3-dev001", "v1.2.3-alpha", "v1.2"):
            with self.subTest(tag=tag), self.assertRaisesRegex(BuildError, "release tag must"):
                version_from_git_tag(tag)

    def test_archive_is_reproducible(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_directory,
            tempfile.TemporaryDirectory() as second_directory,
        ):
            first = build_addon(DEFAULT_SOURCE, Path(first_directory), dev_build=1)
            second = build_addon(DEFAULT_SOURCE, Path(second_directory), dev_build=1)

            first_digest = hashlib.sha256(first.read_bytes()).digest()
            second_digest = hashlib.sha256(second.read_bytes()).digest()
            self.assertEqual(first_digest, second_digest)


if __name__ == "__main__":
    unittest.main()
