from __future__ import annotations

from contextlib import suppress

import bpy

from . import operators, panels, properties
from .background import JOBS, THUMBNAIL_JOBS
from .runtime import clear_previews

CLASSES = properties.CLASSES + operators.CLASSES + panels.CLASSES


def _menu_import(self, _context) -> None:
    self.layout.operator(
        operators.PROMOB_OT_import_file.bl_idname,
        text="Promob Model (.pmob, .pcontent)",
    )


def register_addon() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.promob_browser = bpy.props.PointerProperty(
        type=properties.PROMOB_PG_browser_state
    )
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    bpy.app.timers.register(operators.load_catalog_on_startup, first_interval=0.5)


def unregister_addon() -> None:
    if bpy.app.timers.is_registered(operators.load_catalog_on_startup):
        bpy.app.timers.unregister(operators.load_catalog_on_startup)
    with suppress(RuntimeError):
        bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    operators.shutdown_async_operators()
    JOBS.shutdown()
    THUMBNAIL_JOBS.shutdown()
    if hasattr(bpy.types.WindowManager, "promob_browser"):
        del bpy.types.WindowManager.promob_browser
    clear_previews()
    for cls in reversed(CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
