"""Immutable transport-neutral models returned by the Mooble client."""

from __future__ import annotations

import math
from dataclasses import dataclass


def _millimetre_text(value: float) -> str:
    """Format catalog millimetres compactly without hiding fractional values."""
    if value.is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def format_external_dimensions(width_mm: float, depth_mm: float, height_mm: float) -> str:
    """Return a consistent W/D/H card label, or empty text when incomplete."""
    values = (float(width_mm), float(depth_mm), float(height_mm))
    if not all(math.isfinite(value) and value > 0.0 for value in values):
        return ""
    width, depth, height = (_millimetre_text(value) for value in values)
    return f"W {width} × D {depth} × H {height} mm"


@dataclass(frozen=True, slots=True)
class CatalogCategory:
    """One category node returned by the catalog explorer."""

    id: str
    name: str
    url: str
    level: int = 0
    item_count: int | None = None
    selected: bool = False


@dataclass(frozen=True, slots=True)
class CatalogItem:
    """One catalog result with the metadata needed by Blender's browser."""

    id: str
    name: str
    description: str = ""
    brand: str = ""
    collection: str = ""
    thumbnail_url: str = ""
    detail_url: str = ""
    item_type: str = ""
    width_mm: float = 0.0
    depth_mm: float = 0.0
    height_mm: float = 0.0


@dataclass(frozen=True, slots=True)
class CatalogPage:
    """One normalized catalog page with categories, items, and pagination."""

    categories: tuple[CatalogCategory, ...] = ()
    items: tuple[CatalogItem, ...] = ()
    next_url: str = ""
    current_url: str = ""
    pin_name: str = ""


@dataclass(frozen=True, slots=True)
class ItemDetails:
    """Download metadata resolved from a catalog item's detail endpoint."""

    item: CatalogItem
    content_url: str
    properties: dict[str, object]
