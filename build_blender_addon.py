#!/usr/bin/env python3
"""Build the Mooblender Blender extension as a deterministic ZIP archive."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
import tomllib
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = PROJECT_ROOT / "mooblender"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "dist"
_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")
_VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+\Z")
_MANIFEST_VERSION_PATTERN = re.compile(r'^version\s*=\s*"[^"]+"\s*$', re.MULTILINE)
_SKIPPED_DIRECTORY_NAMES = {"__pycache__"}
_SKIPPED_SUFFIXES = {".pyc", ".pyo", ".zip"}


class BuildError(RuntimeError):
    """Raised when the extension source cannot be packaged safely."""


@dataclass(frozen=True)
class ExtensionMetadata:
    """Validated identity and base version read from the Blender manifest."""

    extension_id: str
    version: str


def read_metadata(source: Path) -> ExtensionMetadata:
    """Read and validate the minimum metadata required for packaging."""
    manifest = source / "blender_manifest.toml"
    initializer = source / "__init__.py"
    if not manifest.is_file() or not initializer.is_file():
        raise BuildError("source must contain blender_manifest.toml and __init__.py")

    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise BuildError(f"could not read Blender manifest: {error}") from error

    extension_id = data.get("id")
    version = data.get("version")
    if not isinstance(extension_id, str) or not _ID_PATTERN.fullmatch(extension_id):
        raise BuildError("manifest id must use lowercase letters, digits, and underscores")
    if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
        raise BuildError("manifest version must be MAJOR.MINOR.PATCH")
    return ExtensionMetadata(extension_id=extension_id, version=version)


def version_from_git_tag(tag: str) -> str:
    """Return and validate the extension version represented by a release tag."""
    if not tag.startswith("v"):
        raise BuildError("release tag must start with 'v'")
    version = tag[1:]
    if not _VERSION_PATTERN.fullmatch(version):
        raise BuildError("release tag must be vMAJOR.MINOR.PATCH")
    return version


def development_version(version: str, build_number: int) -> str:
    """Append the normalized development sequence used by Blender packages."""
    if not _VERSION_PATTERN.fullmatch(version):
        raise BuildError("development version base must be MAJOR.MINOR.PATCH")
    if build_number < 1:
        raise BuildError("development build number must be positive")
    return f"{version}-dev{build_number:03d}"


def detect_dev_build() -> int:
    """Derive the development sequence from CI or the local Git history."""
    configured = os.environ.get("MOOBLENDER_DEV_BUILD")
    if configured:
        try:
            build_number = int(configured)
        except ValueError as error:
            raise BuildError("MOOBLENDER_DEV_BUILD must be a positive integer") from error
        if build_number < 1:
            raise BuildError("MOOBLENDER_DEV_BUILD must be a positive integer")
        return build_number

    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        build_number = int(result.stdout.strip())
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError) as error:
        raise BuildError(
            "could not derive development build number; set MOOBLENDER_DEV_BUILD"
        ) from error
    if build_number < 1:
        raise BuildError("Git history must contain at least one commit")
    return build_number


def _manifest_bytes(path: Path, version: str) -> bytes:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise BuildError(f"could not read Blender manifest: {error}") from error
    text, replacements = _MANIFEST_VERSION_PATTERN.subn(f'version = "{version}"', text)
    if replacements != 1:
        raise BuildError("Blender manifest must contain exactly one version field")
    return text.encode("utf-8")


def collect_source_files(source: Path) -> tuple[Path, ...]:
    """Return deterministic, safe archive members relative to ``source``."""
    if not source.is_dir():
        raise BuildError(f"extension source directory does not exist: {source}")

    files: list[Path] = []
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if path.is_symlink():
            raise BuildError(f"symbolic links are not allowed in the extension: {relative}")
        if any(part.startswith(".") or part in _SKIPPED_DIRECTORY_NAMES for part in relative.parts):
            continue
        if path.is_file() and path.suffix.lower() not in _SKIPPED_SUFFIXES:
            files.append(relative)
    return tuple(sorted(files, key=lambda path: path.as_posix()))


def _zip_timestamp() -> tuple[int, int, int, int, int, int]:
    raw_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if raw_epoch is None:
        return (2026, 1, 1, 0, 0, 0)
    try:
        timestamp = datetime.fromtimestamp(int(raw_epoch), tz=UTC)
    except (ValueError, OverflowError, OSError) as error:
        raise BuildError("SOURCE_DATE_EPOCH must be a valid Unix timestamp") from error
    if not 1980 <= timestamp.year <= 2107:
        raise BuildError("SOURCE_DATE_EPOCH is outside the ZIP timestamp range")
    return (
        timestamp.year,
        timestamp.month,
        timestamp.day,
        timestamp.hour,
        timestamp.minute,
        timestamp.second - timestamp.second % 2,
    )


def build_addon(
    source: Path = DEFAULT_SOURCE,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    git_tag: str | None = None,
    dev_build: int | None = None,
) -> Path:
    """Build the deterministic development archive and return its path."""
    source = source.resolve()
    metadata = read_metadata(source)
    base_version = version_from_git_tag(git_tag) if git_tag else metadata.version
    build_number = dev_build if dev_build is not None else detect_dev_build()
    version = development_version(base_version, build_number)
    files = collect_source_files(source)
    if not files:
        raise BuildError("extension source contains no packageable files")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{metadata.extension_id}-{version}.zip"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=output_path.name + ".", suffix=".tmp", dir=output_dir
    )
    os.close(descriptor)
    try:
        with zipfile.ZipFile(
            temporary_name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for relative in files:
                info = zipfile.ZipInfo(relative.as_posix(), date_time=_zip_timestamp())
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                if relative.as_posix() == "blender_manifest.toml":
                    contents = _manifest_bytes(source / relative, version)
                else:
                    contents = (source / relative).read_bytes()
                archive.writestr(info, contents, compresslevel=9)
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, output_path)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise
    return output_path


def main() -> int:
    """Run the command-line extension builder."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--git-tag",
        default=os.environ.get("MOOBLENDER_GIT_TAG") or None,
        help="target tag such as v0.1.0; overrides the manifest base version in the ZIP",
    )
    parser.add_argument(
        "--dev-build",
        type=int,
        default=None,
        help="development sequence; defaults to MOOBLENDER_DEV_BUILD or Git commit count",
    )
    arguments = parser.parse_args()
    try:
        archive = build_addon(
            arguments.source,
            arguments.output_dir,
            git_tag=arguments.git_tag,
            dev_build=arguments.dev_build,
        )
    except BuildError as error:
        parser.error(str(error))
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
