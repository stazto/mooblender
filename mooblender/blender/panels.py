from __future__ import annotations

import bpy

from .operators import ensure_thumbnails
from .runtime import icon_for_item


class PROMOB_PT_browser(bpy.types.Panel):
    bl_label = "Mooble Browser"
    bl_idname = "PROMOB_PT_mooble_browser"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mooble"

    def draw(self, context) -> None:
        layout = self.layout
        state = context.window_manager.promob_browser

        if not bpy.app.online_access:
            layout.label(text="Blender is in offline mode", icon="ERROR")
            layout.label(text="The cached catalog remains available")
            layout.operator("screen.userpref_show", text="Open Preferences").section = "SYSTEM"

        if state.is_syncing:
            syncing = layout.box()
            syncing.label(text=state.status or "Syncing catalog...", icon="FILE_REFRESH")
            syncing.label(text="The cached catalog remains available while syncing")

        if state.is_loading:
            loading = layout.box()
            loading.label(text=state.status or "Loading Mooble...", icon="INFO")
            loading.label(text="You can keep working while the download finishes")

        content = layout.column()
        content.enabled = not state.is_loading

        sync = content.row()
        sync.enabled = not state.is_syncing and bpy.app.online_access
        sync.operator("promob.catalog_refresh", text="Sync Catalog", icon="FILE_REFRESH")
        if state.has_catalog and state.catalog_synced_at:
            content.label(
                text=(
                    f"{state.catalog_item_count} models in "
                    f"{state.catalog_category_count} categories"
                ),
                icon="CHECKMARK",
            )

        search = content.row(align=True)
        search.prop(state, "query", text="", icon="VIEWZOOM")
        search.operator("promob.catalog_search", text="", icon="VIEWZOOM")
        content.prop(state, "manufacturer", text="Manufacturer")

        navigation = content.row(align=True)
        navigation.operator("promob.catalog_back", text="Back", icon="BACK")
        navigation.label(text=state.status)

        if state.error:
            box = content.box()
            box.label(text=state.error, icon="ERROR")

        if state.categories:
            categories = content.box()
            categories.label(text="Collections", icon="FILE_FOLDER")
            for category in state.categories:
                if category.selected:
                    continue
                label = category.name
                if category.item_count >= 0:
                    label += f" ({category.item_count})"
                operator = categories.operator(
                    "promob.catalog_open_category",
                    text=label,
                    icon="DISCLOSURE_TRI_RIGHT",
                )
                operator.url = category.url

        ensure_thumbnails(context, state.items)

        grid = content.grid_flow(row_major=True, columns=0, even_columns=True)
        for item in state.items:
            box = grid.box()
            icon_id = icon_for_item(item)
            if icon_id:
                box.template_icon(icon_value=icon_id, scale=6.0)
            elif item.thumbnail_url:
                if item.thumbnail_loading:
                    box.label(text="Loading preview...", icon="TIME")
                elif item.thumbnail_failed:
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


CLASSES = (PROMOB_PT_browser,)
