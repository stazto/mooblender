"""Shared Blender runtime resources for clients, caches, and previews."""

from __future__ import annotations

from pathlib import Path

import bpy
import bpy.utils.previews

from ..mooble.client import MoobleClient

_previews = None


def preview_collection():
    """Return the lazily allocated Blender preview collection."""
    global _previews
    if _previews is None:
        _previews = bpy.utils.previews.new()
    return _previews


def clear_previews() -> None:
    """Release every loaded preview and reset the shared collection."""
    global _previews
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None


def cache_directory() -> Path:
    """Return Mooblender's Blender-managed cache directory."""
    root = bpy.utils.user_resource("DATAFILES", path="mooblender", create=True)
    return Path(root) / "cache"


def client_from_context(context) -> MoobleClient:
    """Build a client from the active add-on preferences and cache path."""
    preferences = context.preferences.addons[
        "bl_ext.user_default.mooblender"
    ].preferences
    return MoobleClient(
        base_url=preferences.catalog_url,
        region=preferences.region,
        partnership=preferences.partnership,
        page_size=preferences.page_size,
        cache_dir=cache_directory(),
        model_cache_bytes=preferences.model_cache_limit_mb * 1024 * 1024,
        thumbnail_cache_bytes=preferences.thumbnail_cache_limit_mb * 1024 * 1024,
    )


def icon_for_item(item) -> int:
    """Load a cached thumbnail and return its Blender icon identifier."""
    if not item.thumbnail_path:
        return 0
    path = Path(bpy.path.abspath(item.thumbnail_path))
    if not path.is_file():
        return 0
    previews = preview_collection()
    key = f"mooble:{item.item_id}"
    if key not in previews:
        try:
            previews.load(key, str(path), "IMAGE")
        except Exception:
            return 0
    return previews[key].icon_id
