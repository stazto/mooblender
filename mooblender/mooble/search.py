"""Local search helpers for cached Mooble catalog metadata."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

from .models import CatalogItem


def _search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def filter_catalog_items(
    items: Iterable[CatalogItem],
    query: str,
) -> tuple[CatalogItem, ...]:
    """Return items matching every whitespace-delimited query term.

    Matching is case- and accent-insensitive across the fields shown in the
    browser. An empty query restores the complete cached index.
    """

    terms = tuple(_search_text(term) for term in query.split() if term.strip())
    if not terms:
        return tuple(items)
    matches = []
    for item in items:
        searchable = _search_text(
            " ".join(
                (
                    item.name,
                    item.description,
                    item.brand,
                    item.collection,
                    item.id,
                )
            )
        )
        if all(term in searchable for term in terms):
            matches.append(item)
    return tuple(matches)
