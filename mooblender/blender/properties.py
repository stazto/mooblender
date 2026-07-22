"""Blender properties and preferences used by the Mooble browser."""

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
CATALOG_DEPARTMENTS = (
    ("sync_catalog_furniture", "Moveis", "Móveis", True),
    ("sync_catalog_decor", "Decoracao", "Decor", False),
    ("sync_catalog_construction", "Aberturas", "Construção", False),
    ("sync_catalog_appliances", "Eletrodomesticos", "Eletros", False),
    ("sync_catalog_fireplaces", "G5aMaaCZme", "Lareiras | Churrasqueiras", False),
    ("sync_catalog_layout", "Paredes", "Layout", False),
    ("sync_catalog_lights", "Luminarias", "Luzes", False),
    ("sync_catalog_materials", "Revestimentos", "Materiais", False),
    ("sync_catalog_plants", "qm7nVNRHRi", "Plantas", False),
)


def _manufacturer_items(_self, _context):
    """Provide Blender with the current dynamic manufacturer choices."""
    return _MANUFACTURER_ITEMS


def _collection_items(_self, _context):
    """Provide Blender with collections valid for the selected manufacturer."""
    return _COLLECTION_ITEMS


def set_manufacturer_items(brands) -> None:
    """Replace the dynamic manufacturer enumeration with normalized labels."""
    _MANUFACTURER_ITEMS[:] = [
        (ALL_MANUFACTURERS, "All manufacturers", "Do not filter by manufacturer"),
        *((brand, brand, f"Show only models by {brand}") for brand in brands),
    ]


def set_collection_items(collections) -> None:
    """Replace the dynamic brand-collection enumeration."""
    _COLLECTION_ITEMS[:] = [
        (ALL_COLLECTIONS, "All collections", "Do not filter by brand collection"),
        *((name, name, f"Show only models in {name}") for name in collections),
    ]


def selected_catalog_departments(preferences) -> tuple[str, ...]:
    """Return department identifiers enabled in the add-on preferences."""
    return tuple(
        department_id
        for property_name, department_id, _label, default in CATALOG_DEPARTMENTS
        if getattr(preferences, property_name, default)
    )


def _search_changed(_self, _context) -> None:
    """Debounce text edits and apply them against the local catalog index."""
    global _SEARCH_REVISION
    _SEARCH_REVISION += 1
    revision = _SEARCH_REVISION

    def submit_search():
        """Apply only the most recent edit once Blender's UI becomes idle."""
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
    """Blender representation of one category card in the current page."""

    category_id: bpy.props.StringProperty()  # type: ignore
    name: bpy.props.StringProperty()  # type: ignore
    url: bpy.props.StringProperty()  # type: ignore
    level: bpy.props.IntProperty()  # type: ignore
    item_count: bpy.props.IntProperty(default=-1)  # type: ignore
    selected: bpy.props.BoolProperty(default=False)  # type: ignore


class PROMOB_PG_catalog_item(bpy.types.PropertyGroup):
    """Blender representation of one materialized catalog result card."""

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
    """Per-window browser state persisted in Blender's WindowManager."""

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
    """Invalidate visible state when settings alter snapshot identity or paging."""
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


def _catalog_scope_changed(_self, _context) -> None:
    """Tell the user that scope changes take effect on the next explicit sync."""
    for window_manager in bpy.data.window_managers:
        if hasattr(window_manager, "promob_browser"):
            state = window_manager.promob_browser
            if not state.is_syncing:
                state.status = "Catalog selection changed; select Sync Catalog"


class PROMOB_AP_preferences(bpy.types.AddonPreferences):
    """Network, catalog-scope, and import defaults for Mooblender."""

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
    sync_catalog_furniture: bpy.props.BoolProperty(  # type: ignore
        name="Móveis",
        description="Download the Móveis department during catalog sync",
        default=True,
        update=_catalog_scope_changed,
    )
    sync_catalog_decor: bpy.props.BoolProperty(  # type: ignore
        name="Decor",
        description="Download the Decor department during catalog sync",
        default=False,
        update=_catalog_scope_changed,
    )
    sync_catalog_construction: bpy.props.BoolProperty(  # type: ignore
        name="Construção",
        description="Download the Construção department during catalog sync",
        default=False,
        update=_catalog_scope_changed,
    )
    sync_catalog_appliances: bpy.props.BoolProperty(  # type: ignore
        name="Eletros",
        description="Download the Eletros department during catalog sync",
        default=False,
        update=_catalog_scope_changed,
    )
    sync_catalog_fireplaces: bpy.props.BoolProperty(  # type: ignore
        name="Lareiras | Churrasqueiras",
        description="Download fireplaces and grills during catalog sync",
        default=False,
        update=_catalog_scope_changed,
    )
    sync_catalog_layout: bpy.props.BoolProperty(  # type: ignore
        name="Layout",
        description="Download the Layout department during catalog sync",
        default=False,
        update=_catalog_scope_changed,
    )
    sync_catalog_lights: bpy.props.BoolProperty(  # type: ignore
        name="Luzes",
        description="Download the Luzes department during catalog sync",
        default=False,
        update=_catalog_scope_changed,
    )
    sync_catalog_materials: bpy.props.BoolProperty(  # type: ignore
        name="Materiais",
        description="Download the Materiais department during catalog sync",
        default=False,
        update=_catalog_scope_changed,
    )
    sync_catalog_plants: bpy.props.BoolProperty(  # type: ignore
        name="Plantas",
        description="Download the Plantas department during catalog sync",
        default=False,
        update=_catalog_scope_changed,
    )
    convert_tris_to_quads: bpy.props.BoolProperty(  # type: ignore
        name="Convert triangles to quads",
        description=(
            "Join compatible planar triangle pairs while preserving UV seams "
            "and hard edges"
        ),
        default=False,
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
        """Render connection, paging, and default mesh import preferences."""
        layout = self.layout
        layout.prop(self, "catalog_url")
        layout.prop(self, "region")
        layout.prop(self, "partnership")
        layout.prop(self, "page_size")
        layout.prop(self, "convert_tris_to_quads")
        layout.label(text="Credentials are never stored by this add-on.", icon="INFO")


CLASSES = (
    PROMOB_PG_catalog_category,
    PROMOB_PG_catalog_item,
    PROMOB_PG_browser_state,
    PROMOB_AP_preferences,
)
