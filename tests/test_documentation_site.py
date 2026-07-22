from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from build_documentation_site import assemble_site


class DocumentationSiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.built = self.root / "built"
        self.site = self.root / "site"
        self.built.mkdir()
        (self.built / "index.html").write_text("new documentation", encoding="utf-8")
        (self.built / "asset.txt").write_text("new asset", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_manifest(self, version: str) -> Path:
        manifest = self.root / "blender_manifest.toml"
        manifest.write_text(f'version = "{version}"\n', encoding="utf-8")
        return manifest

    def test_development_replaces_only_dev_and_preserves_releases(self) -> None:
        for directory in ("dev", "stable", "latest", "v0.4.0"):
            target = self.site / directory
            target.mkdir(parents=True)
            (target / "old.txt").write_text(directory, encoding="utf-8")

        assemble_site(self.built, self.site, "dev")

        self.assertEqual((self.site / "dev/index.html").read_text(), "new documentation")
        self.assertFalse((self.site / "dev/old.txt").exists())
        for directory in ("stable", "latest", "v0.4.0"):
            with self.subTest(directory=directory):
                self.assertEqual((self.site / directory / "old.txt").read_text(), directory)

    def test_release_updates_aliases_and_version_but_preserves_other_content(self) -> None:
        for directory in ("dev", "stable", "latest", "v0.4.0", "v0.5.1"):
            target = self.site / directory
            target.mkdir(parents=True)
            (target / "old.txt").write_text(directory, encoding="utf-8")

        assemble_site(
            self.built,
            self.site,
            "release",
            release_tag="v0.5.1",
            manifest=self._write_manifest("0.5.1"),
        )

        for directory in ("stable", "latest", "v0.5.1"):
            with self.subTest(directory=directory):
                self.assertEqual(
                    (self.site / directory / "index.html").read_text(),
                    "new documentation",
                )
                self.assertFalse((self.site / directory / "old.txt").exists())
        self.assertEqual((self.site / "dev/old.txt").read_text(), "dev")
        self.assertEqual((self.site / "v0.4.0/old.txt").read_text(), "v0.4.0")

    def test_release_requires_valid_matching_tag_and_manifest(self) -> None:
        with self.assertRaisesRegex(ValueError, "vN.N.N"):
            assemble_site(
                self.built,
                self.site,
                "release",
                release_tag="0.5.1",
                manifest=self._write_manifest("0.5.1"),
            )
        with self.assertRaisesRegex(ValueError, "does not match"):
            assemble_site(
                self.built,
                self.site,
                "release",
                release_tag="v0.5.2",
                manifest=self._write_manifest("0.5.1"),
            )

    def test_root_index_and_json_list_channels_and_semantic_versions(self) -> None:
        (self.site / "v0.10.0").mkdir(parents=True)
        (self.site / "v0.9.0").mkdir()

        assemble_site(self.built, self.site, "dev")

        index = (self.site / "index.html").read_text(encoding="utf-8")
        metadata = json.loads((self.site / "versions.json").read_text(encoding="utf-8"))
        self.assertIn('href="dev/"', index)
        self.assertNotIn('href="stable/"', index)
        self.assertEqual(metadata["development"], "dev")
        self.assertIsNone(metadata["stable"])
        self.assertEqual(metadata["versions"], ["v0.10.0", "v0.9.0"])
        self.assertTrue((self.site / ".nojekyll").is_file())


if __name__ == "__main__":
    unittest.main()
