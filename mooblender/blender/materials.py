"""Create and safely reuse Blender materials from neutral Promob data.

Embedded texture bytes are deduplicated and packed into the blend file. A
material is reused only when both its neutral source fingerprint and its current
Blender node-state fingerprint match, so user edits are never silently shared
with a later import.
"""

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

_MATERIAL_SCHEMA_VERSION = 2
_REFRACTIVE_ALPHA_LIMIT = 0.35


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
    # Blender's image loader needs a pathname. The temporary file exists only
    # for decoding; packing transfers ownership into the image datablock before
    # the file is deleted.
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
            first, second = source.mapping_scale
            if source.mapping_type == 1:
                # Cubic mapping stores a physical texture footprint in source
                # millimetres; generated UVs are in Blender metres.
                x_scale = 1000.0 / first if first > 1e-9 else 1.0
                y_scale = 1000.0 / second if second > 1e-9 else 1.0
            else:
                # Planar/fixed mapping already owns normalized UVs and stores a
                # direct scale. Treating PE12A's (1, 1) as millimetres repeated
                # its transparent logo a thousand times across the surface.
                x_scale = first
                y_scale = second
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
    # Node names and sorted links make the digest deterministic inside one blend
    # file. Defaults and image hashes capture edits that do not change topology.
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
        "use_transparency_overlap": getattr(
            material,
            "use_transparency_overlap",
            None,
        ),
        "use_nodes": material.use_nodes,
        "nodes": nodes,
        "links": links,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _source_digest(source: Material, package: PContentPackage | None) -> str:
    """Fingerprint neutral fields and the bytes of referenced resources."""
    source_payload = asdict(source)
    source_payload.pop("name", None)
    texture_names = (
        source.diffuse_texture,
        source.specular_texture,
        source.normal_texture,
        _transparent_texture_name(source.diffuse_texture),
    )
    payload = {
        # Incrementing this version prevents an unmodified material generated by
        # an older shader workflow from being reused after that workflow changes.
        "schema_version": _MATERIAL_SCHEMA_VERSION,
        "source": source_payload,
        "resources": {
            name: hashlib.sha256(data).hexdigest() if data is not None else None
            for name in texture_names
            if name
            for data in (package.resource(name) if package is not None else None,)
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _refraction_ior(source: Material) -> float | None:
    """Return a bounded optical IOR when PMob identifies a refractive surface."""
    value = source.refraction_factor
    if value is None or not math.isfinite(value) or value <= 1.0 + 1e-4:
        return None
    # Match the Principled IOR socket's upper bound while preserving the source
    # value throughout its normal physical range.
    return min(value, 1000.0)


def _unit_interval(value: float | None, *, fallback: float = 0.0) -> float:
    """Clamp a finite optional material scalar to Blender's normalized range."""
    if value is None or not math.isfinite(value):
        return fallback
    return max(0.0, min(1.0, value))


def _connect_alpha(nodes, links, material, principled, opacity, alpha_sources) -> None:
    """Multiply source opacity by every image alpha channel used by a material."""
    previous = None
    for source in alpha_sources:
        multiply = nodes.new("ShaderNodeMath")
        multiply.operation = "MULTIPLY"
        multiply.label = "Promob Texture Alpha"
        if previous is None:
            multiply.inputs[0].default_value = opacity
        else:
            links.new(previous, multiply.inputs[0])
        links.new(source, multiply.inputs[1])
        previous = multiply.outputs[0]
    if previous is None:
        return
    links.new(previous, principled.inputs["Alpha"])
    if (
        hasattr(material, "surface_render_method")
        and material.surface_render_method != "BLENDED"
    ):
        material.surface_render_method = "DITHERED"


def _configure_principled(
    material,
    source: Material,
    package,
    color,
    opacity,
    refraction_ior,
) -> None:
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
    # PMob's version-zero compatibility path derives this normalized scalar from
    # the serialized specular RGB average. Later versions store it directly.
    # Leaving Blender's 0.5 default in place makes zero-roughness glass appear
    # like a polished metal even when PMob explicitly requests no reflection.
    principled.inputs["Specular IOR Level"].default_value = _unit_interval(
        source.specular_power
    )
    if refraction_ior is not None:
        # Eevee transmission requires a scene-level ray-tracing option and makes
        # thick catalog shells appear dark/metallic when that option is off.
        # Alpha blending is stable in both supported Blender versions and does
        # not make the add-on silently alter the user's render settings.
        principled.inputs["IOR"].default_value = refraction_ior
        principled.inputs["Transmission Weight"].default_value = 0.0
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "BLENDED"
        if hasattr(material, "use_transparency_overlap"):
            # Complex glass shells contain front/back and internal surfaces.
            # Rendering every overlap would accumulate the fallback opacity.
            material.use_transparency_overlap = False

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
    # Image Texture exposes a neutral 1.0 Alpha for images without an alpha
    # channel, so it is safe to compose every diffuse image. A separately named
    # transparency image remains an additional, explicit mask.
    _connect_alpha(
        nodes,
        links,
        material,
        principled,
        opacity,
        tuple(
            output
            for output in (
                diffuse.outputs["Alpha"] if diffuse is not None else None,
                transparency.outputs["Color"] if transparency is not None else None,
            )
            if output is not None
        ),
    )


def create_material(
    source: Material,
    index: int,
    package: PContentPackage | None,
):
    """Create or reuse an unmodified Blender material for a Promob material."""
    # Two gates are required for reuse: the source must describe the same finish
    # and the existing datablock must still match the state recorded at import.
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
    source_opacity = max(
        0.0,
        min(1.0, source.opacity if source.opacity is not None else alpha / 255.0),
    )
    refraction_ior = _refraction_ior(source)
    # Several valid glass materials serialize opacity 1.0 because their native
    # renderer derives visibility from refraction. Cap only refractive surfaces;
    # explicitly more-transparent glass keeps its lower source opacity.
    opacity = (
        min(source_opacity, _REFRACTIVE_ALPHA_LIMIT)
        if refraction_ior is not None
        else source_opacity
    )
    color_rgb = (red / 255.0, green / 255.0, blue / 255.0)
    if refraction_ior is not None:
        # The alpha fallback must retain Promob's glass tint. In the observed
        # legacy material model, RGB is modulated by ambient intensity; PE12A's
        # white RGB with ambient 0.0 produces the observed smoked dark fallback.
        ambient = _unit_interval(source.ambient)
        color_rgb = tuple(component * ambient for component in color_rgb)
    color = (*color_rgb, opacity)
    material.diffuse_color = color
    material.metallic = max(0.0, min(1.0, source.metallic or 0.0))
    material.roughness = max(
        0.0,
        min(1.0, source.roughness if source.roughness is not None else 0.5),
    )
    material.use_nodes = True
    _configure_principled(
        material,
        source,
        package,
        color,
        opacity,
        refraction_ior,
    )

    material["promob_material_index"] = index
    material["mooblender_material_schema"] = _MATERIAL_SCHEMA_VERSION
    material["mooblender_material_sha256"] = source_digest
    if source.diffuse_texture:
        material["promob_diffuse_texture"] = source.diffuse_texture
    if source.specular_texture:
        material["promob_specular_texture"] = source.specular_texture
    if source.normal_texture:
        material["promob_normal_texture"] = source.normal_texture
    material["promob_mapping_type"] = source.mapping_type or 0
    if source.refraction_factor is not None:
        material["promob_refraction_factor"] = source.refraction_factor
    material["mooblender_material_state_sha256"] = _material_state_digest(material)
    return material
