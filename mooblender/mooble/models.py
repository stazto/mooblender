from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CatalogCategory:
    id: str
    name: str
    url: str
    level: int = 0
    item_count: int | None = None
    selected: bool = False


@dataclass(frozen=True, slots=True)
class CatalogItem:
    id: str
    name: str
    description: str = ""
    brand: str = ""
    collection: str = ""
    thumbnail_url: str = ""
    detail_url: str = ""
    item_type: str = ""


@dataclass(frozen=True, slots=True)
class CatalogPage:
    categories: tuple[CatalogCategory, ...] = ()
    items: tuple[CatalogItem, ...] = ()
    next_url: str = ""
    current_url: str = ""
    pin_name: str = ""


@dataclass(frozen=True, slots=True)
class ItemDetails:
    item: CatalogItem
    content_url: str
    properties: dict[str, object]
