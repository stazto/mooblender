"""Sphinx configuration for the public Mooblender manual."""

from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = tomllib.loads(
    (PROJECT_ROOT / "mooblender" / "blender_manifest.toml").read_text(encoding="utf-8")
)

project = "Mooblender"
author = "Dante Dex"
copyright = "2026, Dante Dex"
version = MANIFEST["version"]
release = MANIFEST["version"]

extensions = ["myst_parser"]
source_suffix = {".md": "markdown"}
master_doc = "index"
language = "en"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

myst_enable_extensions = ["colon_fence", "deflist", "fieldlist", "substitution"]
myst_heading_anchors = 3

html_theme = "furo"
html_title = f"{project} {release}"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_theme_options = {
    "source_repository": "https://github.com/dantedex/mooblender/",
    "source_branch": "main",
    "source_directory": "docs/",
}
