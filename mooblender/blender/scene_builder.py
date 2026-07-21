"""Conversion from the neutral PMob model to Blender datablocks."""

from __future__ import annotations

import bpy

from ..model.scene import Material, PmobDocument


def _unique_name(value: str, fallback: str) -> str:
    value = value.strip().replace("\x00", "")
    return value or fallback


def _create_material(source: Material, index: int):
    name = _unique_name(source.name, f"Promob Material {index}")
    material = bpy.data.materials.new(name)
    alpha, red, green, blue = source.color
    material.diffuse_color = (
        red / 255.0,
        green / 255.0,
        blue / 255.0,
        max(0.0, min(1.0, source.opacity if source.opacity is not None else alpha / 255.0)),
    )
    if source.metallic is not None:
        material.metallic = max(0.0, min(1.0, source.metallic))
    if source.roughness is not None:
        material.roughness = max(0.0, min(1.0, source.roughness))
    material["promob_material_index"] = index
    if source.diffuse_texture:
        material["promob_diffuse_texture"] = source.diffuse_texture
    if source.normal_texture:
        material["promob_normal_texture"] = source.normal_texture
    return material


def build_document(
    document: PmobDocument,
    context,
    *,
    collection_name: str = "",
    source_id: str = "",
) -> bpy.types.Collection:
    name = _unique_name(collection_name or document.name, "Promob Import")
    collection = bpy.data.collections.new(name)
    context.scene.collection.children.link(collection)

    materials = [
        _create_material(material, index)
        for index, material in enumerate(document.materials)
    ]
    scale = document.unit_scale_to_meters
    for layer_index, layer in enumerate(document.layers):
        layer_name = _unique_name(layer.name, f"Layer {layer_index}")
        for mesh_index, source in enumerate(layer.meshes):
            mesh_name = f"{layer_name}_{mesh_index}"
            vertices = [
                tuple(component * scale for component in point) for point in source.vertices
            ]
            mesh = bpy.data.meshes.new(mesh_name)
            mesh.from_pydata(vertices, [], source.triangle_faces())
            mesh.update()

            if source.texture_coordinates:
                uv_layer = mesh.uv_layers.new(name="UVMap")
                for loop in mesh.loops:
                    u, v = source.texture_coordinates[loop.vertex_index]
                    uv_layer.data[loop.index].uv = (u, v)

            if 0 <= source.material_id < len(materials):
                mesh.materials.append(materials[source.material_id])

            obj = bpy.data.objects.new(mesh_name, mesh)
            obj["promob_layer"] = layer_name
            obj["promob_material_id"] = source.material_id
            if source_id:
                obj["mooble_item_id"] = source_id
            collection.objects.link(obj)

    collection["promob_version"] = document.version
    if source_id:
        collection["mooble_item_id"] = source_id
    return collection
