"""Mooblender extension entry point.

Blender imports this module to register the add-on. Keeping bpy imports inside
``register`` and ``unregister`` lets the format and service packages be tested
with ordinary CPython.
"""

from __future__ import annotations


def register() -> None:
    from .blender.registration import register_addon

    register_addon()


def unregister() -> None:
    from .blender.registration import unregister_addon

    unregister_addon()
