from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy_extras.io_utils import ImportHelper

from ..formats import PContentPackage, UnsupportedPromobFormat, load_path
from ..formats.pcontent import PContentFormatError
from ..formats.pmob.reader import PmobFormatError
from ..mooble import CatalogItem, MoobleError
from .runtime import client_from_context
from .scene_builder import build_document


def _online_or_report(operator) -> bool:
    if bpy.app.online_access:
        return True
    operator.report({"ERROR"}, "Enable Online Access in Blender preferences to use Mooble")
    return False


def _set_page(context, page, *, append: bool = False) -> None:
    state = context.window_manager.promob_browser
    if not append:
        state.categories.clear()
        state.items.clear()
    for category in page.categories:
        entry = state.categories.add()
        entry.category_id = category.id
        entry.name = category.name
        entry.url = category.url
        entry.level = category.level
        entry.item_count = category.item_count if category.item_count is not None else -1
        entry.selected = category.selected
    client = client_from_context(context)
    for item in page.items:
        entry = state.items.add()
        entry.item_id = item.id
        entry.name = item.name
        entry.description = item.description
        entry.brand = item.brand
        entry.collection_name = item.collection
        entry.thumbnail_url = item.thumbnail_url
        entry.detail_url = item.detail_url
        entry.item_type = item.item_type
        thumbnail = client.download_thumbnail(item)
        entry.thumbnail_path = str(thumbnail) if thumbnail else ""
    state.current_url = page.current_url
    state.next_url = page.next_url
    state.error = ""
    state.status = f"{len(state.items)} model(s) loaded"


class PROMOB_OT_catalog_refresh(bpy.types.Operator):
    bl_idname = "promob.catalog_refresh"
    bl_label = "Refresh Mooble"
    bl_description = "Load the initial Mooble model collection"

    def execute(self, context):
        if not _online_or_report(self):
            return {"CANCELLED"}
        state = context.window_manager.promob_browser
        preferences = context.preferences.addons[__package__.split(".")[0]].preferences
        state.status = "Loading Mooble..."
        try:
            page = client_from_context(context).browse(
                category=preferences.start_category,
                search=state.query,
            )
            _set_page(context, page)
            state.history_json = "[]"
        except MoobleError as error:
            state.error = str(error)
            state.status = "Could not load Mooble"
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class PROMOB_OT_catalog_open_category(bpy.types.Operator):
    bl_idname = "promob.catalog_open_category"
    bl_label = "Open Mooble category"

    url: bpy.props.StringProperty()  # type: ignore

    def execute(self, context):
        if not _online_or_report(self):
            return {"CANCELLED"}
        state = context.window_manager.promob_browser
        if not self.url:
            self.report({"WARNING"}, "This category has no navigation URL")
            return {"CANCELLED"}
        try:
            history = json.loads(state.history_json)
            if state.current_url:
                history.append(state.current_url)
            page = client_from_context(context).browse_url(self.url)
            _set_page(context, page)
            state.history_json = json.dumps(history[-50:])
        except (MoobleError, json.JSONDecodeError) as error:
            state.error = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class PROMOB_OT_catalog_back(bpy.types.Operator):
    bl_idname = "promob.catalog_back"
    bl_label = "Back"

    @classmethod
    def poll(cls, context):
        return context.window_manager.promob_browser.history_json not in {"", "[]"}

    def execute(self, context):
        if not _online_or_report(self):
            return {"CANCELLED"}
        state = context.window_manager.promob_browser
        try:
            history = json.loads(state.history_json)
            url = history.pop()
            page = client_from_context(context).browse_url(url)
            _set_page(context, page)
            state.history_json = json.dumps(history)
        except (IndexError, MoobleError, json.JSONDecodeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class PROMOB_OT_catalog_load_more(bpy.types.Operator):
    bl_idname = "promob.catalog_load_more"
    bl_label = "Load More"

    @classmethod
    def poll(cls, context):
        return bool(context.window_manager.promob_browser.next_url)

    def execute(self, context):
        if not _online_or_report(self):
            return {"CANCELLED"}
        state = context.window_manager.promob_browser
        try:
            page = client_from_context(context).browse_url(state.next_url)
            _set_page(context, page, append=True)
        except MoobleError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


def _catalog_item(entry) -> CatalogItem:
    return CatalogItem(
        id=entry.item_id,
        name=entry.name,
        description=entry.description,
        brand=entry.brand,
        collection=entry.collection_name,
        thumbnail_url=entry.thumbnail_url,
        detail_url=entry.detail_url,
        item_type=entry.item_type,
    )


class PROMOB_OT_catalog_import(bpy.types.Operator):
    bl_idname = "promob.catalog_import"
    bl_label = "Import"
    bl_description = "Download and import this Mooble model"

    item_id: bpy.props.StringProperty()  # type: ignore

    def execute(self, context):
        if not _online_or_report(self):
            return {"CANCELLED"}
        state = context.window_manager.promob_browser
        entry = next((item for item in state.items if item.item_id == self.item_id), None)
        if entry is None:
            self.report({"ERROR"}, "Selected Mooble model is no longer in the current page")
            return {"CANCELLED"}
        try:
            path = client_from_context(context).download_model(_catalog_item(entry))
            loaded = load_path(path)
            document = loaded.document if isinstance(loaded, PContentPackage) else loaded
            build_document(document, context, collection_name=entry.name, source_id=entry.item_id)
        except (
            MoobleError,
            UnsupportedPromobFormat,
            PContentFormatError,
            PmobFormatError,
            OSError,
        ) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Imported {entry.name}")
        return {"FINISHED"}


class PROMOB_OT_import_file(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.promob"
    bl_label = "Import Promob model"
    bl_options = {"UNDO"}

    filename_ext = ".pmob"
    filter_glob: bpy.props.StringProperty(  # type: ignore
        default="*.pmob;*.pcontent;*.content;*.mob",
        options={"HIDDEN"},
    )

    def execute(self, context):
        path = Path(self.filepath)
        try:
            loaded = load_path(path)
            document = loaded.document if isinstance(loaded, PContentPackage) else loaded
            build_document(document, context, collection_name=path.stem)
        except (UnsupportedPromobFormat, PContentFormatError, PmobFormatError, OSError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


CLASSES = (
    PROMOB_OT_catalog_refresh,
    PROMOB_OT_catalog_open_category,
    PROMOB_OT_catalog_back,
    PROMOB_OT_catalog_load_more,
    PROMOB_OT_catalog_import,
    PROMOB_OT_import_file,
)
