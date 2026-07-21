from __future__ import annotations

import bpy

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
            layout.label(text="Enable Online Access to browse Mooble")
            layout.operator("screen.userpref_show", text="Open Preferences").section = "SYSTEM"
            return

        search = layout.row(align=True)
        search.prop(state, "query", text="", icon="VIEWZOOM")
        search.operator("promob.catalog_refresh", text="", icon="FILE_REFRESH")

        navigation = layout.row(align=True)
        navigation.operator("promob.catalog_back", text="Back", icon="BACK")
        navigation.label(text=state.status)

        if state.error:
            box = layout.box()
            box.label(text=state.error, icon="ERROR")

        if state.categories:
            categories = layout.box()
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

        grid = layout.grid_flow(row_major=True, columns=0, even_columns=True)
        for item in state.items:
            box = grid.box()
            icon_id = icon_for_item(item)
            if icon_id:
                box.template_icon(icon_value=icon_id, scale=6.0)
            box.label(text=item.name)
            if item.brand:
                box.label(text=item.brand, icon="BOOKMARKS")
            if item.collection_name:
                box.label(text=item.collection_name, icon="OUTLINER_COLLECTION")
            operator = box.operator("promob.catalog_import", text="Import", icon="IMPORT")
            operator.item_id = item.item_id

        if state.next_url:
            layout.operator("promob.catalog_load_more", text="Load More", icon="ADD")


CLASSES = (PROMOB_PT_browser,)
