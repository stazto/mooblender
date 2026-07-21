from __future__ import annotations

import hashlib
import json
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import bpy
from bpy_extras.io_utils import ImportHelper

from ..formats import PContentPackage, UnsupportedPromobFormat, load_path
from ..formats.pcontent import PContentFormatError
from ..formats.pmob.reader import PmobFormatError
from ..mooble import CatalogItem, CatalogPage
from ..mooble.search import filter_catalog_items
from .background import (
    JOBS,
    THUMBNAIL_JOBS,
    fetch_catalog_index,
    fetch_catalog_url,
    fetch_file,
    fetch_model,
    fetch_thumbnails,
)
from .runtime import client_from_context
from .scene_builder import build_document

_ACTIVE_POLLS = set()
_ACTIVE_THUMBNAILS = {}
_CATALOG_INDEXES: dict[str, CatalogPage] = {}


def _browser_preferences(context):
    try:
        return context.preferences.addons[
            "bl_ext.user_default.mooblender"
        ].preferences
    except KeyError:
        # Direct source registration in the headless compatibility test does
        # not create Blender's installed-extension preference entry.
        return SimpleNamespace(start_category="Moveis", page_size=12)


def shutdown_async_operators() -> None:
    callbacks = tuple(_ACTIVE_POLLS) + tuple(_ACTIVE_THUMBNAILS.values())
    for callback in callbacks:
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)
    _ACTIVE_POLLS.clear()
    _ACTIVE_THUMBNAILS.clear()
    _CATALOG_INDEXES.clear()


def _online_or_report(operator) -> bool:
    if bpy.app.online_access:
        return True
    operator.report({"ERROR"}, "Enable Online Access in Blender preferences to use Mooble")
    return False


def _set_page(context, page, *, append: bool = False) -> None:
    state = context.window_manager.promob_browser
    thumbnails = {
        item.item_id: (
            item.thumbnail_path,
            item.thumbnail_failed,
        )
        for item in state.items
    }
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
        thumbnail_path, thumbnail_failed = thumbnails.get(item.id, ("", False))
        entry.thumbnail_path = thumbnail_path
        entry.thumbnail_loading = False
        entry.thumbnail_failed = thumbnail_failed
    state.current_url = page.current_url
    state.next_url = page.next_url
    state.error = ""
    state.status = f"{len(state.items)} model(s) loaded"
    state.page_signature = _page_signature(page) if not append else ""
    state.using_local_index = False
    state.local_result_total = 0
    state.local_result_limit = 0


def _page_signature(page) -> str:
    return hashlib.sha256(repr(page).encode("utf-8")).hexdigest()


def _apply_local_index(context, page: CatalogPage, *, limit: int | None = None) -> None:
    state = context.window_manager.promob_browser
    preferences = _browser_preferences(context)
    _CATALOG_INDEXES[page.current_url] = page
    matches = filter_catalog_items(page.items, state.query)
    visible_limit = min(
        len(matches),
        limit if limit is not None else preferences.page_size,
    )
    visible = CatalogPage(
        categories=page.categories if not state.query.strip() else (),
        items=matches[:visible_limit],
        current_url=page.current_url,
        pin_name=page.pin_name,
    )
    _set_page(context, visible)
    state.using_local_index = True
    state.local_result_total = len(matches)
    state.local_result_limit = visible_limit
    suffix = "" if not page.next_url else " while index refreshes"
    state.status = f"{visible_limit} of {len(matches)} local match(es){suffix}"
    state.history_json = "[]"


def _load_local_index(context) -> CatalogPage | None:
    preferences = _browser_preferences(context)
    client = client_from_context(context)
    try:
        url = client.root_url(
            category=preferences.start_category,
            search="",
            page_size=48,
        )
        cached = _CATALOG_INDEXES.get(url)
        if cached is not None:
            return cached
        cached = client.load_cached_page(url)
        if cached is not None:
            _CATALOG_INDEXES[url] = cached
        return cached
    finally:
        client.close()


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


def _redraw_view3d(context) -> None:
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


class _ThumbnailBatchCompletion:
    def __init__(self, item_ids: tuple[str, ...], future) -> None:
        self.item_ids = item_ids
        self.future = future

    def __call__(self):
        if not self.future.done():
            return 0.1

        context = bpy.context
        state = context.window_manager.promob_browser
        entries = {item.item_id: item for item in state.items}
        try:
            paths = self.future.result()
            for item_id in self.item_ids:
                entry = entries.get(item_id)
                if entry is not None:
                    path = paths.get(item_id)
                    entry.thumbnail_path = str(path) if path else ""
                    entry.thumbnail_failed = path is None
        except Exception:
            for item_id in self.item_ids:
                entry = entries.get(item_id)
                if entry is not None:
                    entry.thumbnail_failed = True
        finally:
            for item_id in self.item_ids:
                entry = entries.get(item_id)
                if entry is not None:
                    entry.thumbnail_loading = False
                _ACTIVE_THUMBNAILS.pop(item_id, None)
            _redraw_view3d(context)
        return None


def ensure_thumbnails(context, entries) -> None:
    if not bpy.app.online_access:
        return
    pending = [
        entry
        for entry in entries
        if not entry.thumbnail_path
        and not entry.thumbnail_loading
        and not entry.thumbnail_failed
        and entry.thumbnail_url
        and entry.item_id not in _ACTIVE_THUMBNAILS
    ]
    if not pending:
        return

    items = tuple(_catalog_item(entry) for entry in pending)
    item_ids = tuple(item.id for item in items)
    for entry in pending:
        entry.thumbnail_loading = True
    future = THUMBNAIL_JOBS.submit(
        fetch_thumbnails,
        client_from_context(context),
        items,
    )
    callback = _ThumbnailBatchCompletion(item_ids, future)
    for item_id in item_ids:
        _ACTIVE_THUMBNAILS[item_id] = callback
    bpy.app.timers.register(callback, first_interval=0.1)


class PROMOB_OT_catalog_refresh(_AsyncCatalogOperator, bpy.types.Operator):
    bl_idname = "promob.catalog_refresh"
    bl_label = "Refresh Mooble"
    bl_description = "Load the initial Mooble model collection"

    def execute(self, context):
        if not _online_or_report(self):
            return {"CANCELLED"}
        preferences = _browser_preferences(context)
        client = client_from_context(context)
        cached = client.load_cached_page(
            client.root_url(
                category=preferences.start_category,
                search="",
                page_size=48,
            )
        )
        if cached is not None:
            _apply_local_index(context, cached)
        return self._start(
            context,
            fetch_catalog_index,
            client,
            status=(
                "Refreshing complete Mooble catalog index..."
                if cached is not None
                else "Downloading complete Mooble catalog index..."
            ),
            task_kwargs={
                "category": preferences.start_category,
            },
        )

    @staticmethod
    def _completion(context, page):
        _apply_local_index(context, page)


class PROMOB_OT_catalog_search(bpy.types.Operator):
    bl_idname = "promob.catalog_search"
    bl_label = "Search cached Mooble catalog"
    bl_description = "Filter the complete cached catalog without an API request"

    def execute(self, context):
        state = context.window_manager.promob_browser
        if state.is_loading:
            return {"CANCELLED"}
        page = _load_local_index(context)
        if page is not None:
            _apply_local_index(context, page)
            return {"FINISHED"}
        if bpy.app.online_access:
            return bpy.ops.promob.catalog_refresh()
        state.error = "No local Mooble catalog index is available"
        state.status = "Catalog unavailable offline"
        return {"CANCELLED"}


def refresh_catalog_on_startup():
    if not bpy.app.online_access:
        return 2.0
    try:
        context = bpy.context
        state = context.window_manager.promob_browser
        if state.is_loading:
            return 0.5
        bpy.ops.promob.catalog_refresh()
    except (AttributeError, KeyError, RuntimeError):
        return 0.5
    return None


class PROMOB_OT_catalog_open_category(_AsyncCatalogOperator, bpy.types.Operator):
    bl_idname = "promob.catalog_open_category"
    bl_label = "Open Mooble category"

    url: bpy.props.StringProperty()  # type: ignore

    def execute(self, context):
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
        history_json = json.dumps(history[-50:])
        client = client_from_context(context)
        cached = client.load_cached_page(self.url)
        if cached is not None:
            client.close()
            self._apply_page(context, cached, history_json=history_json)
            state.status = f"{len(state.items)} model(s) restored from cache"
            return {"FINISHED"}
        if not _online_or_report(self):
            client.close()
            return {"CANCELLED"}
        completion = partial(
            self._apply_page,
            history_json=history_json,
        )
        return self._start(
            context,
            fetch_catalog_url,
            client,
            self.url,
            status="Loading Mooble category...",
            task_kwargs=None,
            completion=completion,
        )

    @staticmethod
    def _apply_page(context, page, *, history_json):
        _set_page(context, page)
        context.window_manager.promob_browser.history_json = history_json


class PROMOB_OT_catalog_back(bpy.types.Operator):
    bl_idname = "promob.catalog_back"
    bl_label = "Back"

    @classmethod
    def poll(cls, context):
        state = context.window_manager.promob_browser
        return not state.is_loading and state.history_json not in {"", "[]"}

    def execute(self, context):
        state = context.window_manager.promob_browser
        try:
            history = json.loads(state.history_json)
            if not isinstance(history, list) or not history:
                raise ValueError("Mooble catalog history is empty")
            url = history[-1]
            if not isinstance(url, str) or not url:
                raise ValueError("Previous Mooble catalog URL is invalid")
        except (IndexError, TypeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        client = client_from_context(context)
        try:
            cached = client.load_cached_page(url)
        finally:
            client.close()
        if cached is None:
            self.report({"ERROR"}, "Previous Mooble catalog is not available in cache")
            return {"CANCELLED"}
        history.pop()
        _set_page(context, cached)
        state.history_json = json.dumps(history)
        state.status = f"{len(state.items)} model(s) restored from cache"
        return {"FINISHED"}


class PROMOB_OT_catalog_load_more(_AsyncCatalogOperator, bpy.types.Operator):
    bl_idname = "promob.catalog_load_more"
    bl_label = "Load More"

    @classmethod
    def poll(cls, context):
        state = context.window_manager.promob_browser
        return not state.is_loading and (
            state.local_result_limit < state.local_result_total or bool(state.next_url)
        )

    def execute(self, context):
        state = context.window_manager.promob_browser
        if state.using_local_index:
            page = _load_local_index(context)
            if page is None:
                self.report({"ERROR"}, "Local Mooble catalog index is unavailable")
                return {"CANCELLED"}
            preferences = _browser_preferences(context)
            _apply_local_index(
                context,
                page,
                limit=state.local_result_limit + preferences.page_size,
            )
            return {"FINISHED"}
        if not _online_or_report(self):
            return {"CANCELLED"}
        return self._start(
            context,
            fetch_catalog_url,
            client_from_context(context),
            state.next_url,
            status="Loading more Mooble models...",
            task_kwargs={"extend_cache_url": state.current_url},
        )

    @staticmethod
    def _completion(context, page):
        _set_page(context, page)


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
        preferences = context.preferences.addons[
            "bl_ext.user_default.mooblender"
        ].preferences
        build_document(
            document,
            context,
            collection_name=item_name,
            source_id=item_id,
            structure_mode=preferences.import_structure,
        )
        context.window_manager.promob_browser.status = f"Imported {item_name}"


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
            needs_remote = isinstance(loaded, PContentPackage) and bool(
                loaded.properties.get("Aggregates") or loaded.properties.get("Models")
            )
            if needs_remote and bpy.app.online_access:
                state = context.window_manager.promob_browser
                if state.is_loading:
                    self.report({"WARNING"}, "Wait for the current Mooble download to finish")
                    return {"CANCELLED"}
                state.is_loading = True
                state.error = ""
                state.status = f"Resolving {path.name} components..."
                future = JOBS.submit(fetch_file, client_from_context(context), path)
                callback = _AsyncCompletion(
                    future,
                    partial(self._apply_file, name=path.stem),
                    "Could not import Promob model",
                )
                _ACTIVE_POLLS.add(callback)
                bpy.app.timers.register(callback, first_interval=0.1)
                return {"FINISHED"}
            preferences = context.preferences.addons[
                "bl_ext.user_default.mooblender"
            ].preferences
            build_document(
                loaded,
                context,
                collection_name=path.stem,
                structure_mode=preferences.import_structure,
            )
        except (
            UnsupportedPromobFormat,
            PContentFormatError,
            PmobFormatError,
            OSError,
            ValueError,
        ) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}

    @staticmethod
    def _apply_file(context, loaded, *, name):
        preferences = context.preferences.addons[
            "bl_ext.user_default.mooblender"
        ].preferences
        build_document(
            loaded,
            context,
            collection_name=name,
            structure_mode=preferences.import_structure,
        )
        context.window_manager.promob_browser.status = f"Imported {name}"


CLASSES = (
    PROMOB_OT_catalog_search,
    PROMOB_OT_catalog_refresh,
    PROMOB_OT_catalog_open_category,
    PROMOB_OT_catalog_back,
    PROMOB_OT_catalog_load_more,
    PROMOB_OT_catalog_import,
    PROMOB_OT_import_file,
)
