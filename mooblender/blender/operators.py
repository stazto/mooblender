from __future__ import annotations

import json
from functools import partial
from pathlib import Path

import bpy
from bpy_extras.io_utils import ImportHelper

from ..formats import PContentPackage, UnsupportedPromobFormat, load_path
from ..formats.pcontent import PContentFormatError
from ..formats.pmob.reader import PmobFormatError
from ..mooble import CatalogItem
from .background import JOBS, fetch_catalog, fetch_catalog_url, fetch_model, fetch_thumbnail
from .runtime import client_from_context
from .scene_builder import build_document

_ACTIVE_POLLS = set()


def shutdown_async_operators() -> None:
    for callback in tuple(_ACTIVE_POLLS):
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)
    _ACTIVE_POLLS.clear()


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
        entry.thumbnail_path = ""
    state.current_url = page.current_url
    state.next_url = page.next_url
    state.error = ""
    state.status = f"{len(state.items)} model(s) loaded"


class _AsyncCatalogOperator:
    error_status = "Could not load Mooble"

    def _start(
        self,
        context,
        function,
        /,
        *args,
        status: str,
        task_kwargs: dict | None = None,
        completion=None,
    ):
        state = context.window_manager.promob_browser
        if state.is_loading:
            self.report({"WARNING"}, "Wait for the current Mooble download to finish")
            return {"CANCELLED"}
        state.is_loading = True
        state.status = status
        state.error = ""
        future = JOBS.submit(function, *args, **(task_kwargs or {}))
        callback = _AsyncCompletion(
            future,
            completion or self._completion,
            self.error_status,
        )
        _ACTIVE_POLLS.add(callback)
        bpy.app.timers.register(callback, first_interval=0.1)
        return {"FINISHED"}

    def _completion(self, context, value):
        raise NotImplementedError


class _AsyncCompletion:
    def __init__(self, future, completion, error_status: str) -> None:
        self.future = future
        self.completion = completion
        self.error_status = error_status

    def __call__(self):
        if not self.future.done():
            return 0.1

        context = bpy.context
        state = context.window_manager.promob_browser
        state.is_loading = False
        try:
            self.completion(context, self.future.result())
        except Exception as error:
            message = str(error) or type(error).__name__
            state.error = message
            state.status = self.error_status
        finally:
            _ACTIVE_POLLS.discard(self)
        return None


class PROMOB_OT_catalog_refresh(_AsyncCatalogOperator, bpy.types.Operator):
    bl_idname = "promob.catalog_refresh"
    bl_label = "Refresh Mooble"
    bl_description = "Load the initial Mooble model collection"

    def execute(self, context):
        if not _online_or_report(self):
            return {"CANCELLED"}
        state = context.window_manager.promob_browser
        preferences = context.preferences.addons[
            "bl_ext.user_default.mooblender"
        ].preferences
        return self._start(
            context,
            fetch_catalog,
            client_from_context(context),
            status="Loading Mooble catalog...",
            task_kwargs={
                "category": preferences.start_category,
                "search": state.query,
            },
        )

    @staticmethod
    def _completion(context, page):
        _set_page(context, page)
        context.window_manager.promob_browser.history_json = "[]"


class PROMOB_OT_catalog_open_category(_AsyncCatalogOperator, bpy.types.Operator):
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
        except json.JSONDecodeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        if state.current_url:
            history.append(state.current_url)
        completion = partial(
            self._apply_page,
            history_json=json.dumps(history[-50:]),
        )
        return self._start(
            context,
            fetch_catalog_url,
            client_from_context(context),
            self.url,
            status="Loading Mooble category...",
            task_kwargs=None,
            completion=completion,
        )

    @staticmethod
    def _apply_page(context, page, *, history_json):
        _set_page(context, page)
        context.window_manager.promob_browser.history_json = history_json


class PROMOB_OT_catalog_back(_AsyncCatalogOperator, bpy.types.Operator):
    bl_idname = "promob.catalog_back"
    bl_label = "Back"

    @classmethod
    def poll(cls, context):
        state = context.window_manager.promob_browser
        return not state.is_loading and state.history_json not in {"", "[]"}

    def execute(self, context):
        if not _online_or_report(self):
            return {"CANCELLED"}
        state = context.window_manager.promob_browser
        try:
            history = json.loads(state.history_json)
            url = history.pop()
        except (IndexError, json.JSONDecodeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        completion = partial(self._apply_page, history_json=json.dumps(history))
        return self._start(
            context,
            fetch_catalog_url,
            client_from_context(context),
            url,
            status="Loading previous Mooble category...",
            task_kwargs=None,
            completion=completion,
        )

    @staticmethod
    def _apply_page(context, page, *, history_json):
        _set_page(context, page)
        context.window_manager.promob_browser.history_json = history_json


class PROMOB_OT_catalog_load_more(_AsyncCatalogOperator, bpy.types.Operator):
    bl_idname = "promob.catalog_load_more"
    bl_label = "Load More"

    @classmethod
    def poll(cls, context):
        state = context.window_manager.promob_browser
        return not state.is_loading and bool(state.next_url)

    def execute(self, context):
        if not _online_or_report(self):
            return {"CANCELLED"}
        state = context.window_manager.promob_browser
        return self._start(
            context,
            fetch_catalog_url,
            client_from_context(context),
            state.next_url,
            status="Loading more Mooble models...",
        )

    @staticmethod
    def _completion(context, page):
        _set_page(context, page, append=True)


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


class PROMOB_OT_catalog_import(_AsyncCatalogOperator, bpy.types.Operator):
    bl_idname = "promob.catalog_import"
    bl_label = "Import"
    bl_description = "Download and import this Mooble model"
    error_status = "Could not import Mooble model"

    item_id: bpy.props.StringProperty()  # type: ignore

    def execute(self, context):
        if not _online_or_report(self):
            return {"CANCELLED"}
        state = context.window_manager.promob_browser
        entry = next((item for item in state.items if item.item_id == self.item_id), None)
        if entry is None:
            self.report({"ERROR"}, "Selected Mooble model is no longer in the current page")
            return {"CANCELLED"}
        completion = partial(
            self._apply_model,
            item_name=entry.name,
            item_id=entry.item_id,
        )
        return self._start(
            context,
            fetch_model,
            client_from_context(context),
            _catalog_item(entry),
            status=f"Downloading {entry.name}...",
            task_kwargs=None,
            completion=completion,
        )

    @staticmethod
    def _apply_model(context, document, *, item_name, item_id):
        build_document(
            document,
            context,
            collection_name=item_name,
            source_id=item_id,
        )
        context.window_manager.promob_browser.status = f"Imported {item_name}"


class PROMOB_OT_catalog_thumbnail(_AsyncCatalogOperator, bpy.types.Operator):
    bl_idname = "promob.catalog_thumbnail"
    bl_label = "Load Preview"
    bl_description = "Download this model thumbnail"
    error_status = "Could not load model preview"

    item_id: bpy.props.StringProperty()  # type: ignore

    def execute(self, context):
        if not _online_or_report(self):
            return {"CANCELLED"}
        state = context.window_manager.promob_browser
        entry = next((item for item in state.items if item.item_id == self.item_id), None)
        if entry is None:
            self.report({"ERROR"}, "Selected Mooble model is no longer in the current page")
            return {"CANCELLED"}
        completion = partial(self._apply_thumbnail, item_id=entry.item_id)
        return self._start(
            context,
            fetch_thumbnail,
            client_from_context(context),
            _catalog_item(entry),
            status=f"Downloading preview for {entry.name}...",
            task_kwargs=None,
            completion=completion,
        )

    @staticmethod
    def _apply_thumbnail(context, path, *, item_id):
        state = context.window_manager.promob_browser
        entry = next((item for item in state.items if item.item_id == item_id), None)
        if entry is not None:
            entry.thumbnail_path = str(path) if path else ""
        state.status = "Preview loaded" if path else "Preview unavailable"


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
    PROMOB_OT_catalog_thumbnail,
    PROMOB_OT_import_file,
)
