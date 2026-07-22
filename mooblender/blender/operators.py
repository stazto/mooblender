"""Bridge Blender's event loop to catalog, preview, and import workflows.

Network and parsing work runs in worker threads.  Blender collections,
properties, datablocks, and reports are touched only by timer callbacks on the
main thread.  This module owns that boundary as well as the browser's transient
in-memory view of the persistent catalog.
"""

import json
from concurrent.futures import CancelledError
from functools import partial
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event
from types import SimpleNamespace

import bpy
from bpy_extras.io_utils import ImportHelper

from ..formats import PContentPackage, UnsupportedPromobFormat, load_path
from ..formats.pcontent import PContentFormatError
from ..formats.pmob.reader import PmobFormatError
from ..mooble import CatalogItem, CatalogPage
from ..mooble.cache import clear_download_cache
from ..mooble.catalog_store import CatalogStore, CatalogSyncCancelled
from ..mooble.client import thumbnail_cache_path
from ..mooble.localization import (
    CATEGORY_LANGUAGE_SOURCE,
    catalog_country_name,
)
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
from .runtime import cache_directory, clear_previews, client_from_context
from .scene_builder import build_document

# Blender keeps timer callables only while they remain registered.  Strong
# references also give shutdown code a complete list of callbacks to cancel.
_ACTIVE_POLLS = set()

# Thumbnail jobs are indexed per item even though several items share one batch
# callback.  This makes view changes and duplicate-scheduling checks O(1).
_ACTIVE_THUMBNAILS = {}

# SQLite is the durable catalog.  This mapping is only a session-level read
# cache, so discarding it can never lose synchronized data.
_CATALOG_INDEXES: dict[str, CatalogPage] = {}
_ACTIVE_CATALOG_SYNC = None


def _catalog_store() -> CatalogStore:
    """Open the persistent catalog database in the add-on cache directory."""
    return CatalogStore(cache_directory() / "catalog.sqlite3")


def _browser_preferences(context):
    """Return installed preferences or safe defaults for source-based tests."""
    try:
        return context.preferences.addons[
            "bl_ext.user_default.mooblender"
        ].preferences
    except KeyError:
        # Direct source registration in the headless compatibility test does
        # not create Blender's installed-extension preference entry.
        return SimpleNamespace(page_size=12)


def shutdown_async_operators() -> None:
    """Cancel pending UI callbacks and shut down background worker pools."""
    global _ACTIVE_CATALOG_SYNC
    if _ACTIVE_CATALOG_SYNC is not None:
        # The worker will discard its temporary SQLite snapshot at its next
        # request boundary, even though Blender is no longer polling its UI.
        _ACTIVE_CATALOG_SYNC.cancel()
    callbacks = tuple(_ACTIVE_POLLS) + tuple(_ACTIVE_THUMBNAILS.values())
    for callback in callbacks:
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)
    _ACTIVE_POLLS.clear()
    _ACTIVE_THUMBNAILS.clear()
    _CATALOG_INDEXES.clear()
    _ACTIVE_CATALOG_SYNC = None


def _online_or_report(operator) -> bool:
    """Report Blender's disabled network access and return whether it is usable."""
    if bpy.app.online_access:
        return True
    operator.report({"ERROR"}, "Enable Online Access in Blender preferences to use Mooble")
    return False


def _set_page(context, page) -> None:
    """Replace visible entries while retaining already cached preview paths."""
    state = context.window_manager.promob_browser
    # A new page invalidates queued preview work, but a running batch may still
    # finish. ``view_revision`` records the collection change, while completion
    # code updates only entries that still exist in the current view.
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
        entry.width_mm = item.width_mm
        entry.depth_mm = item.depth_mm
        entry.height_mm = item.height_mm
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
    """Apply local search, manufacturer, collection, and display-limit filters."""
    state = context.window_manager.promob_browser
    preferences = _browser_preferences(context)
    _CATALOG_INDEXES[page.current_url] = page

    # Filter choices are derived from the unfiltered category page.  Collections
    # are then narrowed by manufacturer, matching the dependency order shown in
    # the UI without issuing another catalog request.
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
    """Load a category from memory first and then from the disk snapshot."""
    state = context.window_manager.promob_browser
    target = url or state.current_url
    if target:
        cached = _CATALOG_INDEXES.get(target)
        if cached is not None:
            return cached
    store = _catalog_store()
    if not store.exists():
        return None
    preferences = _browser_preferences(context)
    expected_country = getattr(preferences, "region", "")
    expected_language = getattr(preferences, "category_language", "")
    if (
        expected_country
        and expected_language
        and not store.matches_identity(expected_country, expected_language)
    ):
        state.status = "Catalog source or language changed; select Sync Catalog"
        return None
    if not target:
        target = store.root_url()
    page = store.page(target)
    if page is not None:
        _CATALOG_INDEXES[page.current_url] = page
    return page


class _AsyncDownloadOperator:
    """Connect a background future to Blender's timer-driven user interface."""

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
        """Start one exclusive browser job without blocking Blender's main thread."""
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
        """Apply the completed result; concrete operators must implement this."""
        raise NotImplementedError


class _AsyncCompletion:
    """Poll a future from Blender's main thread and deliver its result safely."""

    def __init__(self, future, completion, error_status: str) -> None:
        """Store the future, success callback, and user-facing failure status."""
        self.future = future
        self.completion = completion
        self.error_status = error_status

    def __call__(self):
        """Continue polling or finish the job and clear the loading state."""
        if not self.future.done():
            # Returning a delay asks Blender to call the same timer again.  The
            # callback must not block here or the entire interface would freeze.
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
    """Request a redraw so asynchronously loaded previews become visible."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


class _ThumbnailBatchCompletion:
    """Install the results of a batch preview download into visible entries."""

    def __init__(self, item_ids: tuple[str, ...], future) -> None:
        """Remember which visible entries belong to the shared future."""
        self.item_ids = item_ids
        self.future = future

    def __call__(self):
        """Poll the preview batch and update every surviving visible entry."""
        if not self.future.done():
            return 0.1

        context = bpy.context
        state = context.window_manager.promob_browser
        # Navigation can replace the RNA collection while a batch is running.
        # Re-resolve IDs at completion instead of holding stale RNA references.
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
    """Schedule previews only for visible entries without a cached thumbnail."""
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

    # One submission represents the visible viewport.  Its worker performs a
    # small bounded fan-out, reducing timer and executor overhead versus one
    # future per card while still keeping downloads on demand.
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
    """Forward sync progress and atomically expose the completed catalog."""

    def __init__(self, future, progress_queue, cancel_event: Event) -> None:
        """Store the future, progress channel, and cooperative cancellation flag."""
        self.future = future
        self.progress_queue = progress_queue
        self.cancel_event = cancel_event

    def cancel(self) -> None:
        """Request worker cancellation and cancel it immediately if still queued."""
        self.cancel_event.set()
        self.future.cancel()

    def __call__(self):
        """Refresh progress text until the new database snapshot is ready."""
        global _ACTIVE_CATALOG_SYNC
        context = bpy.context
        state = context.window_manager.promob_browser
        # Workers may publish progress faster than Blender redraws.  Drain the
        # queue and render only the newest snapshot so stale messages cannot
        # make the progress display appear to move backwards.
        latest = None
        try:
            while True:
                latest = self.progress_queue.get_nowait()
        except Empty:
            pass
        if self.cancel_event.is_set():
            state.status = "Cancelling catalog sync..."
        elif latest is not None:
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
            state.catalog_source_country = summary.source_country
            state.catalog_category_language = summary.category_language
            state.status = (
                f"{catalog_country_name(summary.source_country)} catalog synced: "
                f"{summary.item_count} models in {summary.category_count} categories"
            )
        except (CancelledError, CatalogSyncCancelled):
            state.error = ""
            state.status = "Catalog sync cancelled; cached catalog unchanged"
        except Exception as error:
            message = str(error) or type(error).__name__
            state.error = message
            state.status = "Could not sync Mooble catalog"
        finally:
            _ACTIVE_POLLS.discard(self)
            if _ACTIVE_CATALOG_SYNC is self:
                _ACTIVE_CATALOG_SYNC = None
        return None


class PROMOB_OT_catalog_refresh(bpy.types.Operator):
    """Synchronize selected Mooble departments into the local snapshot."""

    bl_idname = "promob.catalog_refresh"
    bl_label = "Sync Catalog"
    bl_description = "Download and atomically replace the complete local catalog"

    @classmethod
    def poll(cls, context):
        """Disable a second catalog sync while the first one is running."""
        return not context.window_manager.promob_browser.is_syncing

    def execute(self, context):
        """Start a full snapshot sync for the selected catalog departments."""
        global _ACTIVE_CATALOG_SYNC
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
        cancel_event = Event()
        # The worker owns the temporary database and the client.  The main
        # thread owns only a queue and cancellation event, keeping bpy entirely
        # outside the synchronization implementation.
        future = JOBS.submit(
            _catalog_store().sync,
            client_from_context(context),
            categories=departments,
            category_language=getattr(
                preferences,
                "category_language",
                CATEGORY_LANGUAGE_SOURCE,
            ),
            progress=progress_queue.put,
            cancelled=cancel_event.is_set,
        )
        callback = _CatalogSyncCompletion(future, progress_queue, cancel_event)
        _ACTIVE_CATALOG_SYNC = callback
        _ACTIVE_POLLS.add(callback)
        bpy.app.timers.register(callback, first_interval=0.1)
        return {"FINISHED"}


class PROMOB_OT_catalog_cancel(bpy.types.Operator):
    """Cooperatively stop the active catalog synchronization."""

    bl_idname = "promob.catalog_cancel"
    bl_label = "Cancel Sync"
    bl_description = "Stop synchronization and keep the previous cached catalog"

    @classmethod
    def poll(cls, context):
        """Enable cancellation only while this process owns an active sync."""
        return (
            context.window_manager.promob_browser.is_syncing
            and _ACTIVE_CATALOG_SYNC is not None
        )

    def execute(self, context):
        """Signal cancellation without blocking Blender's main thread."""
        if _ACTIVE_CATALOG_SYNC is None:
            return {"CANCELLED"}
        _ACTIVE_CATALOG_SYNC.cancel()
        context.window_manager.promob_browser.status = "Cancelling catalog sync..."
        return {"FINISHED"}


class PROMOB_OT_cache_clear(bpy.types.Operator):
    """Clear downloaded models and thumbnails while retaining the catalog."""

    bl_idname = "promob.cache_clear"
    bl_label = "Clear Downloads"
    bl_description = (
        "Delete cached models and thumbnails; the synchronized catalog is preserved"
    )

    @classmethod
    def poll(cls, context):
        """Allow clearing only when no job can still be using a cache file."""
        state = context.window_manager.promob_browser
        return not state.is_loading and not state.is_syncing and not _ACTIVE_THUMBNAILS

    def invoke(self, context, event):
        """Ask for confirmation before deleting downloaded cache files."""
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        """Release preview handles, clear downloads, and refresh visible cards."""
        clear_previews()
        cleanup = clear_download_cache(cache_directory())
        for window_manager in bpy.data.window_managers:
            if not hasattr(window_manager, "promob_browser"):
                continue
            state = window_manager.promob_browser
            for item in state.items:
                item.thumbnail_path = ""
                item.thumbnail_loading = False
                item.thumbnail_failed = False
            state.view_revision += 1
            state.status = (
                f"Cleared {cleanup.removed_files} download cache file(s) "
                f"({cleanup.removed_bytes / (1024 * 1024):.1f} MB); catalog kept"
            )
        self.report({"INFO"}, "Mooblender download cache cleared; catalog preserved")
        return {"FINISHED"}


class PROMOB_OT_catalog_search(bpy.types.Operator):
    """Apply search and brand filters to the current cached category."""

    bl_idname = "promob.catalog_search"
    bl_label = "Search cached Mooble catalog"
    bl_description = "Filter the current cached category without an API request"

    def execute(self, context):
        """Recompute the visible result set solely from the local snapshot."""
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
    """Restore the local snapshot from Blender's startup timer."""
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
        state.catalog_source_country = summary.source_country
        state.catalog_category_language = summary.category_language
        state.status = (
            f"{summary.item_count} cached models ready from "
            f"{catalog_country_name(summary.source_country)}"
        )
    except (AttributeError, KeyError, OSError, RuntimeError, ValueError):
        # Registration and workspace restoration can briefly leave bpy.context
        # incomplete.  Retrying is safe because this path only reads the
        # published snapshot and replaces transient UI collections.
        return 0.5
    return None


class PROMOB_OT_catalog_open_category(bpy.types.Operator):
    """Open one category already stored in the local catalog snapshot."""

    bl_idname = "promob.catalog_open_category"
    bl_label = "Open Mooble category"

    url: bpy.props.StringProperty()  # type: ignore

    def execute(self, context):
        """Open a cached category and append the current category to history."""
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
    """Return to the previous category in local navigation history."""

    bl_idname = "promob.catalog_back"
    bl_label = "Back"

    @classmethod
    def poll(cls, context):
        """Enable Back only when local navigation has a previous category."""
        state = context.window_manager.promob_browser
        return not state.is_loading and state.history_json not in {"", "[]"}

    def execute(self, context):
        """Restore the last category without making a network request."""
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
    """Expose another bounded batch of the current local query results."""

    bl_idname = "promob.catalog_load_more"
    bl_label = "Load More"

    @classmethod
    def poll(cls, context):
        """Enable pagination when more local matches remain hidden."""
        state = context.window_manager.promob_browser
        return not state.is_loading and state.local_result_limit < state.local_result_total

    def execute(self, context):
        """Increase the visible slice of the current local result set."""
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
    """Convert mutable Blender UI state into an immutable catalog value."""
    return CatalogItem(
        id=entry.item_id,
        name=entry.name,
        description=entry.description,
        brand=entry.brand,
        collection=entry.collection_name,
        thumbnail_url=entry.thumbnail_url,
        detail_url=entry.detail_url,
        item_type=entry.item_type,
        width_mm=entry.width_mm,
        depth_mm=entry.depth_mm,
        height_mm=entry.height_mm,
    )


class PROMOB_OT_catalog_import(_AsyncDownloadOperator, bpy.types.Operator):
    """Download and import one selected catalog item asynchronously."""

    bl_idname = "promob.catalog_import"
    bl_label = "Import"
    bl_description = "Download and import this Mooble model"
    error_status = "Could not import Mooble model"

    item_id: bpy.props.StringProperty()  # type: ignore

    def execute(self, context):
        """Download the selected model and schedule its main-thread import."""
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
        """Build the downloaded model after its worker future completes."""
        build_document(
            document,
            context,
            collection_name=item_name,
            source_id=item_id,
            convert_tris_to_quads=convert_tris_to_quads,
        )
        context.window_manager.promob_browser.status = f"Imported {item_name}"


class PROMOB_OT_import_file(bpy.types.Operator, ImportHelper):
    """Import a supported local Promob file through Blender's file browser."""

    bl_idname = "import_scene.promob"
    bl_label = "Import Promob model"
    bl_options = {"UNDO"}

    filename_ext = ".pmob"
    filter_glob: bpy.props.StringProperty(  # type: ignore
        default="*.pmob;*.pcontent",
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
        """Initialize import options from add-on preferences before browsing."""
        self.convert_tris_to_quads = bool(
            getattr(_browser_preferences(context), "convert_tris_to_quads", False)
        )
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        """Parse a local file, resolving remote package references if required."""
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
        """Build a remotely resolved local package on Blender's main thread."""
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
    PROMOB_OT_catalog_cancel,
    PROMOB_OT_cache_clear,
    PROMOB_OT_catalog_open_category,
    PROMOB_OT_catalog_back,
    PROMOB_OT_catalog_load_more,
    PROMOB_OT_catalog_import,
    PROMOB_OT_import_file,
)
