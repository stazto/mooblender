#!/usr/bin/env python3
"""Assemble one Sphinx build into Mooblender's versioned Pages site."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import tomllib
from pathlib import Path

RELEASE_TAG = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")


def _replace_tree(source: Path, destination: Path) -> None:
    """Replace one publication channel without disturbing sibling versions."""
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _published_versions(site: Path) -> list[str]:
    """Return semantic-version directories newest first."""
    versions: list[tuple[tuple[int, int, int], str]] = []
    for child in site.iterdir():
        match = RELEASE_TAG.fullmatch(child.name) if child.is_dir() else None
        if match:
            version = tuple(int(part) for part in match.group("version").split("."))
            versions.append((version, child.name))
    return [name for _version, name in sorted(versions, reverse=True)]


def _write_directory_index(site: Path) -> None:
    """Write stable machine-readable and human-readable version indexes."""
    versions = _published_versions(site)
    channels = [
        ("Stable", "stable", "Recommended published documentation"),
        ("Latest", "latest", "Most recently published release"),
        ("Development", "dev", "Documentation from the main branch"),
    ]
    available_channels = [item for item in channels if (site / item[1]).is_dir()]
    metadata = {
        "stable": "stable" if (site / "stable").is_dir() else None,
        "latest": "latest" if (site / "latest").is_dir() else None,
        "development": "dev" if (site / "dev").is_dir() else None,
        "versions": versions,
    }
    (site / "versions.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )

    channel_items = "\n".join(
        f'<li><a href="{path}/">{html.escape(label)}</a> — '
        f"{html.escape(description)}</li>"
        for label, path, description in available_channels
    )
    version_items = "\n".join(
        f'<li><a href="{name}/">{html.escape(name)}</a></li>' for name in versions
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mooblender documentation</title>
  <style>
    body {{
      font: 1rem/1.6 system-ui, sans-serif;
      margin: 3rem auto;
      max-width: 48rem;
      padding: 0 1.5rem;
    }}
    a {{ color: #2457a7; }}
  </style>
</head>
<body>
  <h1>Mooblender documentation</h1>
  <p>Select a documentation channel or a specific published version.</p>
  <h2>Channels</h2>
  <ul>{channel_items}</ul>
  <h2>Published versions</h2>
  <ul>{version_items}</ul>
</body>
</html>
"""
    (site / "index.html").write_text(document, encoding="utf-8")
    (site / ".nojekyll").touch()


def assemble_site(
    built: Path,
    site: Path,
    channel: str,
    *,
    release_tag: str | None = None,
    manifest: Path | None = None,
) -> None:
    """Publish a development build or release into a persistent site tree."""
    built = built.resolve()
    site = site.resolve()
    if not (built / "index.html").is_file():
        raise ValueError(f"Sphinx output has no index.html: {built}")
    if built == site or site in built.parents or built in site.parents:
        raise ValueError("Build and site directories must not contain each other")
    site.mkdir(parents=True, exist_ok=True)

    if channel == "dev":
        _replace_tree(built, site / "dev")
    elif channel == "release":
        match = RELEASE_TAG.fullmatch(release_tag or "")
        if not match:
            raise ValueError("Release tag must have the form vN.N.N")
        if manifest is None:
            raise ValueError("A manifest is required for release publication")
        manifest_version = tomllib.loads(manifest.read_text(encoding="utf-8"))["version"]
        if manifest_version != match.group("version"):
            raise ValueError(
                f"Release tag {release_tag} does not match manifest {manifest_version}"
            )
        for destination in (release_tag, "stable", "latest"):
            _replace_tree(built, site / destination)
    else:
        raise ValueError(f"Unknown documentation channel: {channel}")

    _write_directory_index(site)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--built", type=Path, required=True)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--channel", choices=("dev", "release"), required=True)
    parser.add_argument("--release-tag")
    parser.add_argument("--manifest", type=Path)
    return parser.parse_args()


def main() -> None:
    """Parse command-line arguments and assemble the requested channel."""
    args = _parse_args()
    assemble_site(
        args.built,
        args.site,
        args.channel,
        release_tag=args.release_tag,
        manifest=args.manifest,
    )


if __name__ == "__main__":
    main()
