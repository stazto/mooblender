"""3D View sidebar panels for browsing and importing cached Mooble assets."""

from __future__ import annotations

import bpy

from .operators import _browser_preferences, ensure_thumbnails
from .properties import CATALOG_DEPARTMENTS
from .runtime import icon_for_item


def _draw_background_status(layout, state) -> None:
    """Keep only panel-wide Online Access feedback at the panel top."""
    if not bpy.app.online_access:
        layout.label(text="Blender is in offline mode", icon="ERROR")
        layout.label(text="The cached catalog remains available")
        layout.operator("screen.userpref_show", text="Open Preferences").section = "SYSTEM"


def _draw_catalog_sync_status(content, state) -> None:
    """Place catalog timing and active sync feedback beside its trigger."""
    sync_status = content.box()
    if state.is_syncing:
        sync_status.label(
            text=state.status or "Syncing catalog...",
            icon="FILE_REFRESH",
        )
        sync_status.label(text="The cached catalog remains available while syncing")
    sync_status.label(text="A full catalog sync can take several minutes", icon="TIME")


def _draw_object_download_status(content, state) -> None:
    """Place selected-object download feedback immediately above search."""
    if state.is_loading:
        loading = content.box()
        loading.label(text=state.status or "Loading Mooble...", icon="INFO")
        loading.label(text="You can keep working while the download finishes")


def _draw_catalog_scope(content, preferences, state) -> None:
    """Draw the department checkboxes that determine the next full sync."""
    scope = content.box()
    scope.enabled = not state.is_syncing
    scope.label(text="Catalog content", icon="CHECKBOX_HLT")
    if not hasattr(preferences, "bl_rna"):
        scope.label(text="Móveis", icon="CHECKMARK")
        return
    options = scope.grid_flow(
        row_major=True,
        columns=2,
        even_columns=True,
        even_rows=False,
        align=True,
    )
    for property_name, _department_id, label, _default in CATALOG_DEPARTMENTS:
        options.prop(preferences, property_name, text=label)


def _draw_import_options(content, preferences, state) -> None:
    """Draw synchronization, mesh-conversion, and snapshot summary controls."""
    sync = content.row()
    sync.enabled = not state.is_syncing and bpy.app.online_access
    sync.operator("promob.catalog_refresh", text="Sync Catalog", icon="FILE_REFRESH")
    _draw_catalog_sync_status(content, state)

    options = content.box()
    options.label(text="Import options", icon="MODIFIER")
    if hasattr(preferences, "bl_rna"):
        options.prop(preferences, "convert_tris_to_quads")
    else:
        options.label(text="Keep triangulated meshes")
    if state.has_catalog and state.catalog_synced_at:
        content.label(
            text=(
                f"{state.catalog_item_count} models in "
                f"{state.catalog_category_count} categories"
            ),
            icon="CHECKMARK",
        )


def _draw_search_and_navigation(content, state) -> None:
    """Draw local filters, navigation, status, and any actionable error."""
    search = content.row(align=True)
    search.prop(state, "query", text="", icon="VIEWZOOM")
    search.operator("promob.catalog_search", text="", icon="VIEWZOOM")
    content.prop(state, "manufacturer", text="Manufacturer")
    content.prop(state, "collection_filter", text="Brand Collection")

    navigation = content.row(align=True)
    navigation.operator("promob.catalog_back", text="Back", icon="BACK")
    if state.is_loading or state.is_syncing:
        # Background-job text has a dedicated box near the action that started
        # it. Keep this row about the cached result set instead of duplicating it.
        navigation.label(text=f"{state.local_result_total} cached model(s)")
    else:
        navigation.label(text=state.status)
    if state.error:
        error = content.box()
        error.label(text=state.error, icon="ERROR")


def _draw_categories(content, state) -> None:
    """Draw cached child categories while omitting the current category."""
    if not state.categories:
        return
    categories = content.box()
    categories.label(text="Collections", icon="FILE_FOLDER")
    for category in state.categories:
        if category.selected:
            continue
        count = f" ({category.item_count})" if category.item_count >= 0 else ""
        operator = categories.operator(
            "promob.catalog_open_category",
            text=f"{category.name}{count}",
            icon="DISCLOSURE_TRI_RIGHT",
        )
        operator.url = category.url


def _draw_catalog_items(content, state) -> None:
    """Draw model cards and a bounded local pagination control."""
    grid = content.grid_flow(row_major=True, columns=0, even_columns=True)
    for item in state.items:
        box = grid.box()
        icon_id = icon_for_item(item)
        if icon_id:
            box.template_icon(icon_value=icon_id, scale=6.0)
        elif item.thumbnail_url and item.thumbnail_loading:
            box.label(text="Loading preview...", icon="TIME")
        elif item.thumbnail_url and item.thumbnail_failed:
            box.label(text="Preview unavailable", icon="ERROR")
        box.label(text=item.name)
        if item.brand:
            box.label(text=item.brand, icon="BOOKMARKS")
        if item.collection_name:
            box.label(text=item.collection_name, icon="OUTLINER_COLLECTION")
        operator = box.operator("promob.catalog_import", text="Import", icon="IMPORT")
        operator.item_id = item.item_id
    if state.local_result_limit < state.local_result_total:
        content.operator("promob.catalog_load_more", text="Load More", icon="ADD")


class PROMOB_PT_browser(bpy.types.Panel):
    """Render the cached Mooble catalog browser in the 3D View sidebar."""

    bl_label = "Mooble Browser"
    bl_idname = "PROMOB_PT_mooble_browser"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mooble"

    def draw(self, context) -> None:
        """Build the panel from the current asynchronous browser state."""
        layout = self.layout
        state = context.window_manager.promob_browser
        _draw_background_status(layout, state)

        # Model downloads disable actions that could start conflicting work,
        # while their status remains readable outside the disabled columns.
        catalog_controls = layout.column()
        catalog_controls.enabled = not state.is_loading
        preferences = _browser_preferences(context)
        _draw_catalog_scope(catalog_controls, preferences, state)
        _draw_import_options(catalog_controls, preferences, state)

        _draw_object_download_status(layout, state)
        browser = layout.column()
        browser.enabled = not state.is_loading
        _draw_search_and_navigation(browser, state)
        _draw_categories(browser, state)
        ensure_thumbnails(context, state.items)
        _draw_catalog_items(browser, state)


CLASSES = (PROMOB_PT_browser,)
