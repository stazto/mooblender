"""Mooblender extension entry point.

Blender imports this module to register the add-on. Keeping bpy imports inside
``register`` and ``unregister`` lets the format and service packages be tested
with ordinary CPython.
"""

from __future__ import annotations


def register() -> None:
    """Register Mooblender classes, properties, handlers, and timers in Blender."""
    from .blender.registration import register_addon

    register_addon()


def unregister() -> None:
    """Unregister Mooblender and release its Blender runtime resources."""
    from .blender.registration import unregister_addon

    unregister_addon()
