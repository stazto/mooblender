from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = PROJECT_ROOT / "docs"


class DocumentationTests(unittest.TestCase):
    def test_public_manual_has_expected_pages(self) -> None:
        expected_pages = {
            "about.md",
            "development.md",
            "formats/index.md",
            "formats/pcontent.md",
            "formats/pmob.md",
            "index.md",
            "installation.md",
            "mooble.md",
            "troubleshooting.md",
            "user-guide.md",
        }

        for relative_path in expected_pages:
            with self.subTest(page=relative_path):
                self.assertTrue((DOCS_ROOT / relative_path).is_file())

    def test_public_manual_does_not_link_private_agent_notes(self) -> None:
        for path in DOCS_ROOT.rglob("*.md"):
            with self.subTest(path=path.relative_to(PROJECT_ROOT)):
                contents = path.read_text(encoding="utf-8").casefold()
                self.assertNotIn(".agents", contents)

    def test_screenshot_requests_have_private_safe_instructions(self) -> None:
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (DOCS_ROOT / "installation.md", DOCS_ROOT / "user-guide.md")
        )

        self.assertGreaterEqual(sources.count("<!-- SCREENSHOT:"), 9)
        self.assertIn("Do not show personal directories", sources)
        self.assertIn("no private values", sources)

    def test_documentation_version_comes_from_extension_manifest(self) -> None:
        configuration = (DOCS_ROOT / "conf.py").read_text(encoding="utf-8")
        manifest = tomllib.loads(
            (PROJECT_ROOT / "mooblender" / "blender_manifest.toml").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn('MANIFEST["version"]', configuration)
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")

    def test_pages_workflow_builds_strictly_before_deployment(self) -> None:
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "docs.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("python -m sphinx -W --keep-going", workflow)
        self.assertIn("actions/upload-pages-artifact@v4", workflow)
        self.assertIn("actions/deploy-pages@v4", workflow)
        self.assertIn("needs: build", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)


if __name__ == "__main__":
    unittest.main()
