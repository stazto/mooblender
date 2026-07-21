"""Headless registration and scene-building smoke test for supported Blender LTS releases."""

from __future__ import annotations

import sys
from pathlib import Path

import bpy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import mooblender  # noqa: E402
from mooblender.blender.panels import PROMOB_PT_browser  # noqa: E402
from mooblender.blender.scene_builder import build_document  # noqa: E402
from mooblender.model.scene import Material, Mesh, PmobDocument, SceneLayer  # noqa: E402


def main() -> None:
    collection = None
    registered = False
    try:
        mooblender.register()
        registered = True
        if PROMOB_PT_browser.bl_category != "Mooble":
            raise AssertionError("Mooblender panel is not in the Mooble sidebar tab")
        if not getattr(PROMOB_PT_browser, "is_registered", False):
            raise AssertionError("Mooblender panel did not register")
        if not hasattr(bpy.types.WindowManager, "promob_browser"):
            raise AssertionError("Mooblender browser state did not register")
        state = bpy.context.window_manager.promob_browser
        if state.is_loading:
            raise AssertionError("Mooblender browser started in a loading state")

        source = Mesh(
            vertices=[(0.0, 0.0, 0.0), (1000.0, 0.0, 0.0), (0.0, 1000.0, 0.0)],
            indices=[0, 1, 2],
            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        )
        document = PmobDocument(
            name="Mooblender LTS Smoke Test",
            version=2,
            layers=[SceneLayer(name="Compatibility", meshes=[source])],
            materials=[
                Material(
                    name="Compatibility Material",
                    color=(255, 64, 128, 255),
                    metallic=0.25,
                    roughness=0.75,
                )
            ],
        )
        collection = build_document(document, bpy.context)
        obj = collection.objects[0]
        if len(obj.data.vertices) != 3 or len(obj.data.polygons) != 1:
            raise AssertionError("scene builder produced invalid triangle geometry")
        if len(obj.data.uv_layers) != 1 or len(obj.data.materials) != 1:
            raise AssertionError("scene builder did not preserve UVs and material assignment")
        if tuple(obj.data.vertices[1].co) != (1.0, 0.0, 0.0):
            raise AssertionError("scene builder did not convert millimetres to metres")
        print(f"Mooblender smoke test passed on Blender {bpy.app.version_string}")
    finally:
        if collection is not None:
            materials = {
                material
                for obj in collection.objects
                for material in obj.data.materials
                if material is not None
            }
            for obj in list(collection.objects):
                mesh = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                bpy.data.meshes.remove(mesh)
            bpy.data.collections.remove(collection)
            for material in materials:
                bpy.data.materials.remove(material)
        if registered:
            mooblender.unregister()


if __name__ == "__main__":
    main()
