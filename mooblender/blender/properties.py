from __future__ import annotations

import bpy


class PROMOB_PG_catalog_category(bpy.types.PropertyGroup):
    category_id: bpy.props.StringProperty()  # type: ignore
    name: bpy.props.StringProperty()  # type: ignore
    url: bpy.props.StringProperty()  # type: ignore
    level: bpy.props.IntProperty()  # type: ignore
    item_count: bpy.props.IntProperty(default=-1)  # type: ignore
    selected: bpy.props.BoolProperty(default=False)  # type: ignore


class PROMOB_PG_catalog_item(bpy.types.PropertyGroup):
    item_id: bpy.props.StringProperty()  # type: ignore
    name: bpy.props.StringProperty()  # type: ignore
    description: bpy.props.StringProperty()  # type: ignore
    brand: bpy.props.StringProperty()  # type: ignore
    collection_name: bpy.props.StringProperty()  # type: ignore
    thumbnail_url: bpy.props.StringProperty()  # type: ignore
    thumbnail_path: bpy.props.StringProperty(subtype="FILE_PATH")  # type: ignore
    thumbnail_loading: bpy.props.BoolProperty(default=False, options={"HIDDEN"})  # type: ignore
    thumbnail_failed: bpy.props.BoolProperty(default=False, options={"HIDDEN"})  # type: ignore
    detail_url: bpy.props.StringProperty()  # type: ignore
    item_type: bpy.props.StringProperty()  # type: ignore


class PROMOB_PG_browser_state(bpy.types.PropertyGroup):
    query: bpy.props.StringProperty(name="Search")  # type: ignore
    status: bpy.props.StringProperty(default="Select Refresh to load Mooble")  # type: ignore
    is_loading: bpy.props.BoolProperty(default=False, options={"HIDDEN"})  # type: ignore
    error: bpy.props.StringProperty()  # type: ignore
    current_url: bpy.props.StringProperty()  # type: ignore
    next_url: bpy.props.StringProperty()  # type: ignore
    history_json: bpy.props.StringProperty(default="[]", options={"HIDDEN"})  # type: ignore
    page_signature: bpy.props.StringProperty(options={"HIDDEN"})  # type: ignore
    categories: bpy.props.CollectionProperty(type=PROMOB_PG_catalog_category)  # type: ignore
    items: bpy.props.CollectionProperty(type=PROMOB_PG_catalog_item)  # type: ignore


def _reset_browser(_self, _context) -> None:
    for window_manager in bpy.data.window_managers:
        if hasattr(window_manager, "promob_browser"):
            state = window_manager.promob_browser
            state.current_url = ""
            state.next_url = ""
            state.history_json = "[]"
            state.page_signature = ""
            state.categories.clear()
            state.items.clear()
            state.is_loading = False
            state.status = "Settings changed; select Refresh"


class PROMOB_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = "bl_ext.user_default.mooblender"

    catalog_url: bpy.props.StringProperty(  # type: ignore
        name="Catalog API",
        description="Mooble catalog API base URL",
        default="https://catalog.mooble.com/api/",
        update=_reset_browser,
    )
    region: bpy.props.StringProperty(  # type: ignore
        name="Region",
        description="Mooble region code",
        default="br",
        update=_reset_browser,
    )
    start_category: bpy.props.StringProperty(  # type: ignore
        name="Start category",
        description="Initial Departamento tag identifier",
        default="Moveis",
        update=_reset_browser,
    )
    partnership: bpy.props.StringProperty(  # type: ignore
        name="Partnership",
        description="Optional Mooble partnership identifier",
        default="",
        update=_reset_browser,
    )
    page_size: bpy.props.IntProperty(  # type: ignore
        name="Page size",
        default=12,
        min=1,
        max=48,
        update=_reset_browser,
    )

    def draw(self, _context) -> None:
        layout = self.layout
        layout.prop(self, "catalog_url")
        layout.prop(self, "region")
        layout.prop(self, "start_category")
        layout.prop(self, "partnership")
        layout.prop(self, "page_size")
        layout.label(text="Credentials are never stored by this add-on.", icon="INFO")


CLASSES = (
    PROMOB_PG_catalog_category,
    PROMOB_PG_catalog_item,
    PROMOB_PG_browser_state,
    PROMOB_AP_preferences,
)
