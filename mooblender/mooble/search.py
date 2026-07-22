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
    *,
    manufacturer: str = "",
    collection: str = "",
) -> tuple[CatalogItem, ...]:
    """Return items matching every whitespace-delimited query term.

    Matching is case- and accent-insensitive across the fields shown in the
    browser. An empty query restores the complete cached index.
    """
    terms = tuple(_search_text(term) for term in query.split() if term.strip())
    normalized_manufacturer = _search_text(manufacturer.strip())
    normalized_collection = _search_text(collection.strip())
    matches = []
    for item in items:
        if (
            normalized_manufacturer
            and _search_text(item.brand) != normalized_manufacturer
        ):
            continue
        if normalized_collection and _search_text(item.collection) != normalized_collection:
            continue
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
