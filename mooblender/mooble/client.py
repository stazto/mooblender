"""Client for the public catalog flow used by the Mooble planner.

The endpoint and response mapping are observations, not a stable public API.
All transport is injectable so schema changes can be tested without Blender.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from .models import CatalogCategory, CatalogItem, CatalogPage, ItemDetails
from .transport import HttpTransport, TransportError


class JsonTransport(Protocol):
    """Minimal injectable HTTP contract used by the Mooble client."""

    def get_json(self, url: str, *, max_bytes: int = ...) -> dict[str, Any]: ...
    def get_bytes(self, url: str, *, max_bytes: int) -> bytes: ...
    def validate_url(self, url: str) -> None: ...


class MoobleError(RuntimeError):
    """Raised when a Mooble response cannot satisfy the client contract."""


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sequence(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def thumbnail_cache_path(cache_dir: str | Path, item: CatalogItem) -> Path:
    """Return the deterministic disk-cache location for an item's preview."""
    suffix = Path(urlparse(item.thumbnail_url).path).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".img"
    safe_key = hashlib.sha256(item.id.encode("utf-8")).hexdigest()[:32]
    return Path(cache_dir) / "thumbnails" / f"{safe_key}{suffix}"


class MoobleClient:
    """Bounded client for catalog browsing, details, models, and previews."""

    DEFAULT_BASE_URL = "https://catalog.mooble.com/api/"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        region: str = "br",
        client_name: str = "mooble",
        partnership: str = "",
        page_size: int = 12,
        cache_dir: str | Path | None = None,
        transport: JsonTransport | None = None,
    ) -> None:
        normalized = base_url.rstrip("/") + "/"
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Mooble base URL must be an absolute HTTPS URL")
        self.base_url = normalized
        self.region = region.lower()
        self.client_name = client_name
        self.partnership = partnership
        self.page_size = min(max(page_size, 1), 48)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        allowed = tuple(
            dict.fromkeys((parsed.hostname.lower(), "catalog.mooble.com", "cdn.mooble.com"))
        )
        self.transport = transport or HttpTransport(allowed_hosts=allowed)

    def close(self) -> None:
        close = getattr(self.transport, "close", None)
        if close is not None:
            close()

    def __enter__(self):
        return self

    def __exit__(self, _exception_type, _exception, _traceback) -> None:
        self.close()

    def root_url(
        self,
        *,
        category: str = "Moveis",
        search: str = "",
        page_size: int | None = None,
    ) -> str:
        requested_page_size = self.page_size if page_size is None else page_size
        params: dict[str, str | int] = {
            "client": self.client_name,
            "pin": "Departamento",
            "partnership": self.partnership,
            "internal": "Item",
            "region": self.region,
            "!Departamento": category,
            "$top": min(max(requested_page_size, 1), 48),
        }
        if search.strip():
            params["search"] = search.strip()
        return urljoin(self.base_url, "explorer/v2") + "?" + urlencode(params)

    @staticmethod
    def with_page_size(url: str, page_size: int) -> str:
        """Normalize a server-provided catalog URL to a bounded page size."""
        if not url:
            return ""
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        if not any(key == "$top" for key, _value in query):
            return url
        bounded = min(max(page_size, 1), 48)
        resized = [
            (key, str(bounded) if key == "$top" else value)
            for key, value in query
        ]
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(resized), parts.fragment)
        )

    def browse(self, *, category: str = "Moveis", search: str = "") -> CatalogPage:
        url = self.root_url(category=category, search=search)
        cached = self.load_cached_page(url)
        live = self.browse_url(url)
        if (
            cached is not None
            and len(cached.items) > len(live.items)
            and cached.items[: len(live.items)] == live.items
            and cached.categories == live.categories
        ):
            preserved = CatalogPage(
                categories=live.categories,
                items=cached.items,
                next_url=cached.next_url,
                current_url=url,
                pin_name=live.pin_name,
            )
            self._write_catalog_cache(url, preserved)
            return preserved
        return live

    def browse_url(self, url: str, *, cache: bool = True) -> CatalogPage:
        try:
            self.transport.validate_url(url)
            payload = self.transport.get_json(url)
            page = self._parse_page(payload, current_url=url)
            if cache:
                self._write_catalog_cache(url, page)
            return page
        except (TransportError, KeyError, TypeError, ValueError) as error:
            raise MoobleError(f"could not browse Mooble catalog: {error}") from error

    def cache_catalog_page(self, url: str, page: CatalogPage) -> None:
        """Persist a completely assembled catalog page atomically."""
        self._write_catalog_cache(url, page)

    def load_cached_page(self, url: str) -> CatalogPage | None:
        if self.cache_dir is None:
            return None
        path = self._catalog_cache_path(url)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("version") != 1 or payload.get("url") != url:
                return None
            return CatalogPage(
                categories=tuple(
                    CatalogCategory(**category) for category in payload["categories"]
                ),
                items=tuple(CatalogItem(**item) for item in payload["items"]),
                next_url=payload["next_url"],
                current_url=url,
                pin_name=payload["pin_name"],
            )
        except (
            AttributeError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return None

    def extend_cached_page(self, base_url: str, page: CatalogPage) -> CatalogPage:
        """Append a pagination response to its catalog's persistent cache."""
        base = self.load_cached_page(base_url)
        if base is None:
            base = CatalogPage(current_url=base_url)

        categories = {
            category.id: category for category in (*base.categories, *page.categories)
        }
        items = {item.id: item for item in (*base.items, *page.items)}
        merged = CatalogPage(
            categories=tuple(categories.values()),
            items=tuple(items.values()),
            next_url=page.next_url,
            current_url=base_url,
            pin_name=base.pin_name or page.pin_name,
        )
        self._write_catalog_cache(base_url, merged)
        return merged

    def _catalog_cache_path(self, url: str) -> Path:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return (self.cache_dir or Path(tempfile.gettempdir()) / "mooblender") / (
            f"catalog/{key}.json"
        )

    def _write_catalog_cache(self, url: str, page: CatalogPage) -> None:
        if self.cache_dir is None:
            return
        payload = {
            "version": 1,
            "url": url,
            "categories": [
                {
                    "id": category.id,
                    "name": category.name,
                    "url": category.url,
                    "level": category.level,
                    "item_count": category.item_count,
                    "selected": category.selected,
                }
                for category in page.categories
            ],
            "items": [
                {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "brand": item.brand,
                    "collection": item.collection,
                    "thumbnail_url": item.thumbnail_url,
                    "detail_url": item.detail_url,
                    "item_type": item.item_type,
                }
                for item in page.items
            ],
            "next_url": page.next_url,
            "pin_name": page.pin_name,
        }
        with suppress(OSError):
            self._atomic_write(
                self._catalog_cache_path(url),
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                ),
            )

    def details(self, item: CatalogItem) -> ItemDetails:
        detail_url = item.detail_url or urljoin(self.base_url, f"explorer/GetSpec/{item.id}")
        return self._details_url(detail_url, fallback_item=item)

    def specification_details(self, specification_id: str) -> ItemDetails:
        if not specification_id:
            raise MoobleError("aggregate specification ID is empty")
        fallback = CatalogItem(id=specification_id, name=specification_id)
        return self._details_url(
            urljoin(self.base_url, f"explorer/GetSpec/{specification_id}"),
            fallback_item=fallback,
        )

    def _details_url(self, detail_url: str, *, fallback_item: CatalogItem) -> ItemDetails:
        try:
            payload = self.transport.get_json(detail_url)
        except (TransportError, ValueError) as error:
            raise MoobleError(f"could not load model details: {error}") from error
        links = _mapping(payload.get("Links"))
        content_url = _string(links.get("Content"))
        if not content_url:
            raise MoobleError("selected model has no downloadable content link")
        self.transport.validate_url(content_url)
        detailed_item = self._parse_item(payload)
        if not detailed_item.id:
            detailed_item = fallback_item
        return ItemDetails(
            item=detailed_item,
            content_url=content_url,
            properties=_mapping(payload.get("Properties")),
        )

    def download_model(
        self,
        item: CatalogItem,
        *,
        max_bytes: int = 256 * 1024 * 1024,
    ) -> Path:
        details = self.details(item)
        return self._download_details(details, cache_key=item.id, max_bytes=max_bytes)

    def download_specification(
        self,
        specification_id: str,
        *,
        max_bytes: int = 256 * 1024 * 1024,
    ) -> Path:
        details = self.specification_details(specification_id)
        return self._download_details(
            details,
            cache_key=specification_id,
            max_bytes=max_bytes,
        )

    def _download_details(
        self,
        details: ItemDetails,
        *,
        cache_key: str,
        max_bytes: int,
    ) -> Path:
        suffix = Path(urlparse(details.content_url).path).suffix.lower() or ".pcontent"
        if suffix not in {".pcontent", ".pmob", ".content", ".mob"}:
            raise MoobleError(f"unsupported downloaded model extension: {suffix}")
        path = self._cache_path("models", cache_key, suffix)
        if path.exists() and path.stat().st_size:
            return path
        try:
            data = self.transport.get_bytes(details.content_url, max_bytes=max_bytes)
        except TransportError as error:
            raise MoobleError(f"could not download model: {error}") from error
        self._atomic_write(path, data)
        metadata = {
            "id": cache_key,
            "name": details.item.name,
            "content_url": details.content_url,
        }
        self._atomic_write(
            path.with_suffix(path.suffix + ".json"),
            json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        return path

    def download_thumbnail(
        self,
        item: CatalogItem,
        *,
        max_bytes: int = 16 * 1024 * 1024,
    ) -> Path | None:
        if not item.thumbnail_url:
            return None
        path = thumbnail_cache_path(
            self.cache_dir or Path(tempfile.gettempdir()) / "mooblender",
            item,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size:
            return path
        try:
            data = self.transport.get_bytes(item.thumbnail_url, max_bytes=max_bytes)
        except TransportError:
            return None
        self._atomic_write(path, data)
        return path

    def _cache_path(self, group: str, key: str, suffix: str) -> Path:
        base = self.cache_dir or Path(tempfile.gettempdir()) / "mooblender"
        safe_key = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        path = base / group / f"{safe_key}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name)
            raise

    @classmethod
    def _parse_page(cls, payload: dict[str, Any], *, current_url: str) -> CatalogPage:
        output = _mapping(payload.get("Output"))
        pin = _mapping(output.get("Pin"))
        available = _mapping(pin.get("AvailableTags"))
        categories = tuple(
            category
            for raw in _sequence(available.get("Data"))
            if (category := cls._parse_category(_mapping(raw))).id
        )
        # Initial Explorer responses nest records under Output.Specifications.
        # GetNext/Specs continuation responses expose the same Data/Links pair
        # directly at the JSON root.
        specifications = _mapping(output.get("Specifications")) or payload
        items = tuple(
            item
            for raw in _sequence(specifications.get("Data"))
            if (item := cls._parse_item(_mapping(raw))).id
        )
        links = _mapping(specifications.get("Links"))
        return CatalogPage(
            categories=categories,
            items=items,
            next_url=_string(links.get("Next")),
            current_url=current_url,
            pin_name=_string(pin.get("Name") or pin.get("Id")),
        )

    @staticmethod
    def _parse_category(raw: dict[str, Any]) -> CatalogCategory:
        return CatalogCategory(
            id=_string(raw.get("Id")),
            name=_string(raw.get("Name")),
            url=_string(raw.get("DataUrl") or raw.get("FilterUrl") or raw.get("PinUrl")),
            level=_optional_int(raw.get("Level")) or 0,
            item_count=_optional_int(raw.get("SpecCount")),
            selected=raw.get("Selected") is True,
        )

    @staticmethod
    def _parse_item(raw: dict[str, Any]) -> CatalogItem:
        links = _mapping(raw.get("Links"))
        brand = _mapping(raw.get("Brand"))
        collection = _mapping(raw.get("Collection"))
        return CatalogItem(
            id=_string(raw.get("Id")),
            name=_string(raw.get("Name")),
            description=_string(raw.get("Description")),
            brand=_string(brand.get("Name")),
            collection=_string(collection.get("Name")),
            thumbnail_url=_string(
                links.get("ContentImageSmall") or links.get("ContentImage")
            ),
            detail_url=_string(raw.get("DetailUrl")),
            item_type=_string(raw.get("Type")),
        )
