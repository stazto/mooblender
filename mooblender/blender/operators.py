import json
from functools import partial
from pathlib import Path
from queue import Empty, SimpleQueue
from types import SimpleNamespace

import bpy
from bpy_extras.io_utils import ImportHelper

from ..formats import PContentPackage, UnsupportedPromobFormat, load_path
from ..formats.pcontent import PContentFormatError
from ..formats.pmob.reader import PmobFormatError
from ..mooble import CatalogItem, CatalogPage
from ..mooble.catalog_store import CatalogStore
from ..mooble.client import thumbnail_cache_path
from ..mooble.search import filter_catalog_items
from .background import (
    JOBS,
    THUMBNAIL_JOBS,
    fetch_file,
    fetch_model,
    fetch_thumbnails,
)
from .properties import (
    ALL_COLLECTIONS,
    ALL_MANUFACTURERS,
    selected_catalog_departments,
    set_collection_items,
    set_manufacturer_items,
)
from .runtime import cache_directory, client_from_context
from .scene_builder import build_document

_ACTIVE_POLLS = set()
_ACTIVE_THUMBNAILS = {}
_CATALOG_INDEXES: dict[str, CatalogPage] = {}


def _catalog_store() -> CatalogStore:
    return CatalogStore(cache_directory() / "catalog.sqlite3")


def _browser_preferences(context):
    try:
        return context.preferences.addons[
            "bl_ext.user_default.mooblender"
        ].preferences
    except KeyError:
        # Direct source registration in the headless compatibility test does
        # not create Blender's installed-extension preference entry.
        return SimpleNamespace(page_size=12)


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


def _set_page(context, page) -> None:
    state = context.window_manager.promob_browser
    _cancel_queued_thumbnails()
    state.view_revision += 1
    thumbnails = {
        item.item_id: (
            item.thumbnail_path,
            item.thumbnail_failed,
        )
        for item in state.items
    }
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
        if not thumbnail_path and item.thumbnail_url:
            cached_path = thumbnail_cache_path(cache_directory(), item)
            if cached_path.is_file() and cached_path.stat().st_size:
                thumbnail_path = str(cached_path)
        entry.thumbnail_path = thumbnail_path
        entry.thumbnail_loading = False
        entry.thumbnail_failed = thumbnail_failed
    state.current_url = page.current_url
    state.error = ""
    state.status = f"{len(state.items)} model(s) loaded"
    state.using_local_index = False
    state.local_result_total = 0
    state.local_result_limit = 0

def _apply_local_index(context, page: CatalogPage, *, limit: int | None = None) -> None:
    state = context.window_manager.promob_browser
    preferences = _browser_preferences(context)
    _CATALOG_INDEXES[page.current_url] = page
    manufacturers = tuple(
        sorted({item.brand for item in page.items if item.brand}, key=str.casefold)
    )
    set_manufacturer_items(manufacturers)
    if state.manufacturer != ALL_MANUFACTURERS and state.manufacturer not in manufacturers:
        state.manufacturer = ALL_MANUFACTURERS
    manufacturer = "" if state.manufacturer == ALL_MANUFACTURERS else state.manufacturer
    collections = tuple(
        sorted(
            {
                item.collection
                for item in page.items
                if item.collection and (not manufacturer or item.brand == manufacturer)
            },
            key=str.casefold,
        )
    )
    set_collection_items(collections)
    if (
        state.collection_filter != ALL_COLLECTIONS
        and state.collection_filter not in collections
    ):
        state.collection_filter = ALL_COLLECTIONS
    collection_filter = (
        "" if state.collection_filter == ALL_COLLECTIONS else state.collection_filter
    )
    matches = filter_catalog_items(
        page.items,
        state.query,
        manufacturer=manufacturer,
        collection=collection_filter,
    )
    visible_limit = min(
        len(matches),
        limit if limit is not None else preferences.page_size,
    )
    visible = CatalogPage(
        categories=(
            page.categories
            if not state.query.strip()
            and state.manufacturer == ALL_MANUFACTURERS
            and state.collection_filter == ALL_COLLECTIONS
            else ()
        ),
        items=matches[:visible_limit],
        current_url=page.current_url,
        pin_name=page.pin_name,
    )
    _set_page(context, visible)
    state.using_local_index = True
    state.local_result_total = len(matches)
    state.local_result_limit = visible_limit
    state.status = f"{visible_limit} of {len(matches)} local match(es)"
    state.has_catalog = True


def _load_local_index(context, url: str = "") -> CatalogPage | None:
    state = context.window_manager.promob_browser
    target = url or state.current_url
    if target:
        cached = _CATALOG_INDEXES.get(target)
        if cached is not None:
            return cached
    store = _catalog_store()
    if not store.exists():
        return None
    if not target:
        target = store.root_url()
    page = store.page(target)
    if page is not None:
        _CATALOG_INDEXES[page.current_url] = page
    return page


class _AsyncDownloadOperator:
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


def _cancel_queued_thumbnails() -> None:
    """Cancel preview batches that have not started before changing views."""

    for callback in set(_ACTIVE_THUMBNAILS.values()):
        if not callback.future.cancel():
            continue
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)
        for item_id in callback.item_ids:
            if _ACTIVE_THUMBNAILS.get(item_id) is callback:
                _ACTIVE_THUMBNAILS.pop(item_id, None)


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


class _CatalogSyncCompletion:
    def __init__(self, future, progress_queue) -> None:
        self.future = future
        self.progress_queue = progress_queue

    def __call__(self):
        context = bpy.context
        state = context.window_manager.promob_browser
        latest = None
        try:
            while True:
                latest = self.progress_queue.get_nowait()
        except Empty:
            pass
        if latest is not None:
            state.status = (
                f"Syncing {latest.current_category}: page {latest.pages}, "
                f"{latest.item_records} records, {latest.categories} categories"
            )
        if not self.future.done():
            return 0.1

        state.is_syncing = False
        try:
            summary = self.future.result()
            _CATALOG_INDEXES.clear()
            state.current_url = ""
            state.history_json = "[]"
            page = _load_local_index(context)
            if page is None:
                raise ValueError("the synchronized catalog could not be reopened")
            _apply_local_index(context, page)
            state.catalog_item_count = summary.item_count
            state.catalog_category_count = summary.category_count
            state.catalog_synced_at = summary.synced_at
            state.status = (
                f"Catalog synced: {summary.item_count} models in "
                f"{summary.category_count} categories"
            )
        except Exception as error:
            message = str(error) or type(error).__name__
            state.error = message
            state.status = "Could not sync Mooble catalog"
        finally:
            _ACTIVE_POLLS.discard(self)
        return None


class PROMOB_OT_catalog_refresh(bpy.types.Operator):
    bl_idname = "promob.catalog_refresh"
    bl_label = "Sync Catalog"
    bl_description = "Download and atomically replace the complete local catalog"

    @classmethod
    def poll(cls, context):
        return not context.window_manager.promob_browser.is_syncing

    def execute(self, context):
        if not _online_or_report(self):
            return {"CANCELLED"}
        state = context.window_manager.promob_browser
        preferences = _browser_preferences(context)
        departments = selected_catalog_departments(preferences)
        if not departments:
            state.error = "Select at least one catalog section"
            state.status = "Catalog sync was not started"
            self.report({"WARNING"}, state.error)
            return {"CANCELLED"}
        state.is_syncing = True
        state.error = ""
        state.status = f"Starting sync for {len(departments)} catalog section(s)..."
        progress_queue = SimpleQueue()
        future = JOBS.submit(
            _catalog_store().sync,
            client_from_context(context),
            categories=departments,
            progress=progress_queue.put,
        )
        callback = _CatalogSyncCompletion(future, progress_queue)
        _ACTIVE_POLLS.add(callback)
        bpy.app.timers.register(callback, first_interval=0.1)
        return {"FINISHED"}


class PROMOB_OT_catalog_search(bpy.types.Operator):
    bl_idname = "promob.catalog_search"
    bl_label = "Search cached Mooble catalog"
    bl_description = "Filter the current cached category without an API request"

    def execute(self, context):
        state = context.window_manager.promob_browser
        if state.is_loading:
            return {"CANCELLED"}
        page = _load_local_index(context)
        if page is not None:
            _apply_local_index(context, page)
            return {"FINISHED"}
        state.error = "No local catalog is available; select Sync Catalog first"
        state.status = "Catalog has not been synced"
        return {"CANCELLED"}


def load_catalog_on_startup():
    try:
        context = bpy.context
        state = context.window_manager.promob_browser
        if state.is_loading or state.is_syncing:
            return 0.5
        page = _load_local_index(context)
        if page is None:
            state.has_catalog = False
            state.status = "No local catalog; select Sync Catalog"
            return None
        _apply_local_index(context, page)
        summary = _catalog_store().summary()
        state.catalog_item_count = summary.item_count
        state.catalog_category_count = summary.category_count
        state.catalog_synced_at = summary.synced_at
        state.status = f"{summary.item_count} cached models ready"
    except (AttributeError, KeyError, OSError, RuntimeError, ValueError):
        return 0.5
    return None


class PROMOB_OT_catalog_open_category(bpy.types.Operator):
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
        page = _load_local_index(context, self.url)
        if page is None:
            self.report({"ERROR"}, "Category is missing from the local catalog")
            return {"CANCELLED"}
        _apply_local_index(context, page)
        state.history_json = history_json
        state.status = f"{state.local_result_total} cached model(s) in category"
        return {"FINISHED"}


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
        page = _load_local_index(context, url)
        if page is None:
            self.report({"ERROR"}, "Previous category is missing from the local catalog")
            return {"CANCELLED"}
        history.pop()
        _apply_local_index(context, page)
        state.history_json = json.dumps(history)
        state.status = f"{state.local_result_total} cached model(s) in category"
        return {"FINISHED"}


class PROMOB_OT_catalog_load_more(bpy.types.Operator):
    bl_idname = "promob.catalog_load_more"
    bl_label = "Load More"

    @classmethod
    def poll(cls, context):
        state = context.window_manager.promob_browser
        return not state.is_loading and state.local_result_limit < state.local_result_total

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
        self.report({"ERROR"}, "Catalog results are not available locally")
        return {"CANCELLED"}


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


class PROMOB_OT_catalog_import(_AsyncDownloadOperator, bpy.types.Operator):
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
            convert_tris_to_quads=bool(
                getattr(_browser_preferences(context), "convert_tris_to_quads", False)
            ),
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
    def _apply_model(
        context,
        document,
        *,
        item_name,
        item_id,
        convert_tris_to_quads,
    ):
        build_document(
            document,
            context,
            collection_name=item_name,
            source_id=item_id,
            convert_tris_to_quads=convert_tris_to_quads,
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
    convert_tris_to_quads: bpy.props.BoolProperty(  # type: ignore
        name="Convert triangles to quads",
        description=(
            "Join compatible planar triangle pairs while preserving UV seams "
            "and hard edges"
        ),
        default=False,
    )

    def invoke(self, context, event):
        self.convert_tris_to_quads = bool(
            getattr(_browser_preferences(context), "convert_tris_to_quads", False)
        )
        return ImportHelper.invoke(self, context, event)

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
                    partial(
                        self._apply_file,
                        name=path.stem,
                        convert_tris_to_quads=self.convert_tris_to_quads,
                    ),
                    "Could not import Promob model",
                )
                _ACTIVE_POLLS.add(callback)
                bpy.app.timers.register(callback, first_interval=0.1)
                return {"FINISHED"}
            build_document(
                loaded,
                context,
                collection_name=path.stem,
                convert_tris_to_quads=self.convert_tris_to_quads,
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
    def _apply_file(context, loaded, *, name, convert_tris_to_quads):
        build_document(
            loaded,
            context,
            collection_name=name,
            convert_tris_to_quads=convert_tris_to_quads,
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
