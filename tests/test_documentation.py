from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = PROJECT_ROOT / "docs"


class DocumentationTests(unittest.TestCase):
    def test_public_manual_has_expected_pages(self) -> None:
        expected_pages = {
            "about.md",
            "credits.md",
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

    def test_named_platforms_link_to_their_official_pages(self) -> None:
        targets = (
            (re.compile(r"\bMooble\b"), "https://www.mooble.com"),
            (re.compile(r"\bPromob\b"), "https://promob.com"),
        )

        for path in (PROJECT_ROOT / "README.md", *DOCS_ROOT.rglob("*.md")):
            contents = path.read_text(encoding="utf-8")
            for name, official_url in targets:
                if name.search(contents):
                    with self.subTest(path=path.relative_to(PROJECT_ROOT), name=name.pattern):
                        self.assertIn(official_url, contents)

    def test_independence_disclaimer_is_prominent_and_complete(self) -> None:
        for relative_path in ("README.md", "docs/index.md", "docs/credits.md"):
            contents = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
            with self.subTest(path=relative_path):
                self.assertIn("independent", contents)
                self.assertIn("not affiliated", contents)
                self.assertIn("maintained by", contents)

    def test_landing_page_explains_product_and_first_workflow(self) -> None:
        landing = (DOCS_ROOT / "index.md").read_text(encoding="utf-8")

        for expected in (
            "## What you can do",
            "## A typical workflow",
            "Geometry Nodes",
            "Sync Catalog",
            "`.pmob`",
            "`.pcontent`",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, landing)

    def test_credits_describe_platform_product_and_corporate_context(self) -> None:
        credits = (DOCS_ROOT / "credits.md").read_text(encoding="utf-8")

        for expected in (
            "online 3D environment-planning",
            "Promob | A Cyncly Company",
            "more than 30 years",
            "https://planner.mooble.com",
            "https://promob.com/quem-somos/",
            "https://www.cyncly.com",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, credits)

    def test_retired_file_formats_are_absent_from_project_targets(self) -> None:
        retired_suffixes = (".mo" + "b", ".con" + "tent")
        target_files = (
            PROJECT_ROOT / "README.md",
            *DOCS_ROOT.rglob("*.md"),
            *(PROJECT_ROOT / ".agents").rglob("*.md"),
            *(PROJECT_ROOT / "mooblender").rglob("*.py"),
        )

        for path in target_files:
            contents = path.read_text(encoding="utf-8").casefold()
            for suffix in retired_suffixes:
                with self.subTest(path=path.relative_to(PROJECT_ROOT), suffix=suffix):
                    self.assertIsNone(re.search(re.escape(suffix) + r"\b", contents))

    def test_local_import_filter_lists_only_supported_formats(self) -> None:
        operators = (
            PROJECT_ROOT / "mooblender" / "blender" / "operators.py"
        ).read_text(encoding="utf-8")

        self.assertIn('default="*.pmob;*.pcontent"', operators)

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
