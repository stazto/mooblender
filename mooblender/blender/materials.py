"""Create and reuse Blender materials from neutral Promob material data."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict
from pathlib import PurePosixPath

import bpy

from ..formats.pcontent import PContentPackage
from ..model.scene import Material


def _clean_name(value: str, fallback: str) -> str:
    """Remove NUL characters that Blender cannot store in datablock names."""
    return value.strip().replace("\x00", "") or fallback


def _embedded_image(package: PContentPackage | None, source_name: str | None):
    """Load one package resource through a temporary file and pack it in Blender."""
    if package is None:
        return None
    data = package.resource(source_name)
    if data is None:
        return None
    digest = hashlib.sha256(data).hexdigest()
    existing = next(
        (image for image in bpy.data.images if image.get("mooblender_sha256") == digest),
        None,
    )
    if existing is not None:
        return existing

    suffix = PurePosixPath(source_name or "image.png").suffix.lower()
    if suffix not in {".bmp", ".jpeg", ".jpg", ".png", ".tga", ".tif", ".tiff", ".webp"}:
        suffix = ".img"
    descriptor, temporary_name = tempfile.mkstemp(prefix="mooblender-", suffix=suffix)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        image = bpy.data.images.load(temporary_name, check_existing=False)
        image.name = _clean_name(PurePosixPath(source_name or "Texture").name, "Texture")
        image.pack()
        image["mooblender_sha256"] = digest
        image["promob_resource_name"] = source_name or ""
        return image
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)


def _transparent_texture_name(diffuse_name: str | None) -> str | None:
    """Map the observed ``*_DIFFUSE`` convention to its alpha resource."""
    if not diffuse_name:
        return None
    stem = PurePosixPath(diffuse_name).stem
    suffix = PurePosixPath(diffuse_name).suffix
    if stem.upper().endswith("_DIFFUSE"):
        return stem[: -len("_DIFFUSE")] + "_TRANSPARENT" + suffix
    return None


def _texture_node(nodes, image, *, label: str, non_color: bool = False):
    """Create one image-texture node, or return None for a missing image."""
    if image is None:
        return None
    node = nodes.new("ShaderNodeTexImage")
    node.label = label
    node.image = image
    if non_color:
        image.colorspace_settings.name = "Non-Color"
    return node


def _connect_texture_coordinates(nodes, links, source: Material, texture_nodes) -> None:
    """Connect all material images to one shared physical mapping chain."""
    texture_nodes = [node for node in texture_nodes if node is not None]
    if not texture_nodes:
        return
    coordinates = nodes.new("ShaderNodeTexCoord")
    vector_output = coordinates.outputs["UV"]
    if source.mapping_number or source.mapping_scale or source.mapping_rotation:
        mapping = nodes.new("ShaderNodeMapping")
        if source.mapping_number:
            x_scale, y_scale = source.mapping_number
        elif source.mapping_scale:
            width, height = source.mapping_scale
            x_scale = 1000.0 / width if width > 1e-9 else 1.0
            y_scale = 1000.0 / height if height > 1e-9 else 1.0
        else:
            x_scale = y_scale = 1.0
        mapping.inputs["Scale"].default_value = (x_scale, y_scale, 1.0)
        mapping.inputs["Rotation"].default_value[2] = math.radians(
            source.mapping_rotation or 0.0
        )
        links.new(vector_output, mapping.inputs["Vector"])
        vector_output = mapping.outputs["Vector"]
    for node in texture_nodes:
        links.new(vector_output, node.inputs["Vector"])


def _socket_default(value):
    """Convert Blender socket values into stable JSON-compatible values."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "name"):
        return (type(value).__name__, value.name)
    try:
        return tuple(value)
    except TypeError:
        return repr(value)


def _material_state_digest(material) -> str:
    """Fingerprint editable Blender state so user-modified materials are not reused."""
    node_tree = material.node_tree if material.use_nodes else None
    nodes = []
    links = []
    if node_tree is not None:
        nodes = [
            {
                "name": node.name,
                "type": node.bl_idname,
                "label": node.label,
                "settings": {
                    name: getattr(node, name)
                    for name in (
                        "blend_type",
                        "data_type",
                        "extension",
                        "interpolation",
                        "operation",
                        "projection",
                        "vector_type",
                    )
                    if hasattr(node, name)
                },
                "image": (
                    node.image.get("mooblender_sha256") or node.image.name
                    if getattr(node, "image", None) is not None
                    else None
                ),
                "inputs": [
                    (socket.identifier, _socket_default(socket.default_value))
                    for socket in node.inputs
                    if hasattr(socket, "default_value")
                ],
            }
            for node in sorted(node_tree.nodes, key=lambda item: item.name)
        ]
        links = sorted(
            (
                link.from_node.name,
                link.from_socket.identifier,
                link.to_node.name,
                link.to_socket.identifier,
            )
            for link in node_tree.links
        )
    payload = {
        "diffuse_color": tuple(material.diffuse_color),
        "metallic": material.metallic,
        "roughness": material.roughness,
        "surface_render_method": getattr(material, "surface_render_method", None),
        "use_nodes": material.use_nodes,
        "nodes": nodes,
        "links": links,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _source_digest(source: Material, package: PContentPackage | None) -> str:
    """Fingerprint neutral fields and the bytes of referenced resources."""
    payload = asdict(source)
    payload.pop("name", None)
    texture_names = (
        source.diffuse_texture,
        source.specular_texture,
        source.normal_texture,
        _transparent_texture_name(source.diffuse_texture),
    )
    payload["resources"] = {
        name: hashlib.sha256(data).hexdigest() if data is not None else None
        for name in texture_names
        if name
        for data in (package.resource(name) if package is not None else None,)
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _configure_principled(material, source: Material, package, color, opacity) -> None:
    """Populate the Principled shader and its optional texture nodes."""
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    principled = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
    if principled is None:
        return
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Metallic"].default_value = material.metallic
    principled.inputs["Roughness"].default_value = material.roughness
    principled.inputs["Alpha"].default_value = opacity

    diffuse = _texture_node(
        nodes, _embedded_image(package, source.diffuse_texture), label="Promob Diffuse"
    )
    metallic = _texture_node(
        nodes,
        _embedded_image(package, source.specular_texture),
        label="Promob Metallic",
        non_color=True,
    )
    normal = _texture_node(
        nodes,
        _embedded_image(package, source.normal_texture),
        label="Promob Normal",
        non_color=True,
    )
    transparency = _texture_node(
        nodes,
        _embedded_image(package, _transparent_texture_name(source.diffuse_texture)),
        label="Promob Transparency",
        non_color=True,
    )
    _connect_texture_coordinates(
        nodes, links, source, (diffuse, metallic, normal, transparency)
    )
    if diffuse is not None:
        links.new(diffuse.outputs["Color"], principled.inputs["Base Color"])
    if metallic is not None:
        links.new(metallic.outputs["Color"], principled.inputs["Metallic"])
    if normal is not None:
        normal_map = nodes.new("ShaderNodeNormalMap")
        links.new(normal.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])
    if transparency is not None:
        links.new(transparency.outputs["Color"], principled.inputs["Alpha"])
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "DITHERED"


def create_material(
    source: Material,
    index: int,
    package: PContentPackage | None,
):
    """Create or reuse an unmodified Blender material for a Promob material."""
    source_digest = _source_digest(source, package)
    existing = next(
        (
            material
            for material in bpy.data.materials
            if material.get("mooblender_material_sha256") == source_digest
            and material.get("mooblender_material_state_sha256")
            == _material_state_digest(material)
        ),
        None,
    )
    if existing is not None:
        existing["promob_mapping_type"] = source.mapping_type or 0
        return existing

    material = bpy.data.materials.new(_clean_name(source.name, f"Promob Material {index}"))
    red, green, blue, alpha = source.color
    opacity = max(
        0.0,
        min(1.0, source.opacity if source.opacity is not None else alpha / 255.0),
    )
    color = (red / 255.0, green / 255.0, blue / 255.0, opacity)
    material.diffuse_color = color
    material.metallic = max(0.0, min(1.0, source.metallic or 0.0))
    material.roughness = max(
        0.0,
        min(1.0, source.roughness if source.roughness is not None else 0.5),
    )
    material.use_nodes = True
    _configure_principled(material, source, package, color, opacity)

    material["promob_material_index"] = index
    material["mooblender_material_sha256"] = source_digest
    if source.diffuse_texture:
        material["promob_diffuse_texture"] = source.diffuse_texture
    if source.specular_texture:
        material["promob_specular_texture"] = source.specular_texture
    if source.normal_texture:
        material["promob_normal_texture"] = source.normal_texture
    material["promob_mapping_type"] = source.mapping_type or 0
    material["mooblender_material_state_sha256"] = _material_state_digest(material)
    return material
