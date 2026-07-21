"""Promob file identification and high-level loading."""

from __future__ import annotations

from pathlib import Path

from .aggregates import AggregateResolutionError, resolve_aggregates
from .pcontent import PContentPackage, read_pcontent
from .pmob.reader import read_pmob


class UnsupportedPromobFormat(ValueError):
    pass


def load_path(path: str | Path):
    source = Path(path)
    extension = source.suffix.lower()
    if extension == ".pmob":
        return read_pmob(source.read_bytes())
    if extension == ".pcontent":
        return read_pcontent(source.read_bytes())
    if extension in {".content", ".mob"}:
        raise UnsupportedPromobFormat(
            f"{extension} identification is planned but not yet verified; "
            "the importer will not guess its format"
        )
    raise UnsupportedPromobFormat(f"unsupported extension: {extension or '<none>'}")


__all__ = [
    "PContentPackage",
    "AggregateResolutionError",
    "UnsupportedPromobFormat",
    "load_path",
    "read_pcontent",
    "read_pmob",
    "resolve_aggregates",
]
