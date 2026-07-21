from __future__ import annotations

import bpy

from . import operators, panels, properties
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


def unregister_addon() -> None:
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    del bpy.types.WindowManager.promob_browser
    clear_previews()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
