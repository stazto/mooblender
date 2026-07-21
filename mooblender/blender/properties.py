from __future__ import annotations

import bpy

_SEARCH_REVISION = 0


def _search_changed(_self, _context) -> None:
    """Debounce text edits and apply them against the local catalog index."""

    global _SEARCH_REVISION
    _SEARCH_REVISION += 1
    revision = _SEARCH_REVISION

    def submit_search():
        if revision != _SEARCH_REVISION:
            return None
        try:
            state = bpy.context.window_manager.promob_browser
            if state.is_loading:
                return 0.2
            bpy.ops.promob.catalog_search()
        except (AttributeError, RuntimeError):
            pass
        return None

    bpy.app.timers.register(submit_search, first_interval=0.15)


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
    query: bpy.props.StringProperty(name="Search", update=_search_changed)  # type: ignore
    status: bpy.props.StringProperty(default="Select Refresh to load Mooble")  # type: ignore
    is_loading: bpy.props.BoolProperty(default=False, options={"HIDDEN"})  # type: ignore
    error: bpy.props.StringProperty()  # type: ignore
    current_url: bpy.props.StringProperty()  # type: ignore
    next_url: bpy.props.StringProperty()  # type: ignore
    history_json: bpy.props.StringProperty(default="[]", options={"HIDDEN"})  # type: ignore
    page_signature: bpy.props.StringProperty(options={"HIDDEN"})  # type: ignore
    using_local_index: bpy.props.BoolProperty(default=False, options={"HIDDEN"})  # type: ignore
    local_result_total: bpy.props.IntProperty(default=0, options={"HIDDEN"})  # type: ignore
    local_result_limit: bpy.props.IntProperty(default=0, options={"HIDDEN"})  # type: ignore
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
            state.using_local_index = False
            state.local_result_total = 0
            state.local_result_limit = 0
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
    import_structure: bpy.props.EnumProperty(  # type: ignore
        name="Imported structure",
        description="Choose a single Geometry Nodes object or an editable collection hierarchy",
        items=(
            (
                "GEOMETRY_NODES",
                "Single Geometry Nodes object",
                "Import one visible object with procedural opening and finish controls",
            ),
            (
                "COLLECTIONS",
                "Collection hierarchy",
                "Keep every Promob primitive and aggregate as editable Blender objects",
            ),
        ),
        default="GEOMETRY_NODES",
    )

    def draw(self, _context) -> None:
        layout = self.layout
        layout.prop(self, "catalog_url")
        layout.prop(self, "region")
        layout.prop(self, "start_category")
        layout.prop(self, "partnership")
        layout.prop(self, "page_size")
        layout.prop(self, "import_structure")
        layout.label(text="Credentials are never stored by this add-on.", icon="INFO")


CLASSES = (
    PROMOB_PG_catalog_category,
    PROMOB_PG_catalog_item,
    PROMOB_PG_browser_state,
    PROMOB_AP_preferences,
)
