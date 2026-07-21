from __future__ import annotations

import bpy

_SEARCH_REVISION = 0
ALL_MANUFACTURERS = "__ALL_MANUFACTURERS__"
ALL_COLLECTIONS = "__ALL_COLLECTIONS__"
_MANUFACTURER_ITEMS = [
    (ALL_MANUFACTURERS, "All manufacturers", "Do not filter by manufacturer")
]
_COLLECTION_ITEMS = [
    (ALL_COLLECTIONS, "All collections", "Do not filter by brand collection")
]


def _manufacturer_items(_self, _context):
    return _MANUFACTURER_ITEMS


def _collection_items(_self, _context):
    return _COLLECTION_ITEMS


def set_manufacturer_items(brands) -> None:
    _MANUFACTURER_ITEMS[:] = [
        (ALL_MANUFACTURERS, "All manufacturers", "Do not filter by manufacturer"),
        *((brand, brand, f"Show only models by {brand}") for brand in brands),
    ]


def set_collection_items(collections) -> None:
    _COLLECTION_ITEMS[:] = [
        (ALL_COLLECTIONS, "All collections", "Do not filter by brand collection"),
        *((name, name, f"Show only models in {name}") for name in collections),
    ]


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
    manufacturer: bpy.props.EnumProperty(  # type: ignore
        name="Manufacturer",
        items=_manufacturer_items,
        update=_search_changed,
    )
    collection_filter: bpy.props.EnumProperty(  # type: ignore
        name="Collection",
        items=_collection_items,
        update=_search_changed,
    )
    status: bpy.props.StringProperty(default="Select Sync Catalog to load Mooble")  # type: ignore
    is_loading: bpy.props.BoolProperty(default=False, options={"HIDDEN"})  # type: ignore
    is_syncing: bpy.props.BoolProperty(default=False, options={"HIDDEN"})  # type: ignore
    has_catalog: bpy.props.BoolProperty(default=False, options={"HIDDEN"})  # type: ignore
    catalog_item_count: bpy.props.IntProperty(default=0, options={"HIDDEN"})  # type: ignore
    catalog_category_count: bpy.props.IntProperty(default=0, options={"HIDDEN"})  # type: ignore
    catalog_synced_at: bpy.props.StringProperty(options={"HIDDEN"})  # type: ignore
    view_revision: bpy.props.IntProperty(default=0, options={"HIDDEN"})  # type: ignore
    error: bpy.props.StringProperty()  # type: ignore
    current_url: bpy.props.StringProperty()  # type: ignore
    history_json: bpy.props.StringProperty(default="[]", options={"HIDDEN"})  # type: ignore
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
            state.history_json = "[]"
            state.using_local_index = False
            state.local_result_total = 0
            state.local_result_limit = 0
            state.manufacturer = ALL_MANUFACTURERS
            state.collection_filter = ALL_COLLECTIONS
            set_manufacturer_items(())
            set_collection_items(())
            state.categories.clear()
            state.items.clear()
            state.has_catalog = False
            state.catalog_item_count = 0
            state.catalog_category_count = 0
            state.catalog_synced_at = ""
            state.view_revision += 1
            state.status = "Settings changed; select Sync Catalog"


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
