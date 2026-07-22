"""Conversion from neutral Promob models to Blender datablocks."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import zlib
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Any

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

from ..formats.pcontent import PContentPackage
from ..model.dimensions import (
    configurable_dimensions,
    dimension_variables,
    document_geometry_dimensions,
    document_layer_bounds,
    document_layer_dimensions,
    property_dimensions,
    serialized_geometry_dimensions,
)
from ..model.expressions import evaluate_expression
from ..model.openings import control_name, door_motion
from ..model.scene import Material, PmobDocument, Primitive, PrimitiveType
from ..model.topology import prepare_mesh
from ..model.transforms import blender_matrix_rows


def _unique_name(value: str, fallback: str) -> str:
    value = value.strip().replace("\x00", "")
    return value or fallback


def _embedded_image(package: PContentPackage | None, source_name: str | None):
    if package is None:
        return None
    data = package.resource(source_name)
    if data is None:
        return None
    digest = hashlib.sha256(data).hexdigest()
    for image in bpy.data.images:
        if image.get("mooblender_sha256") == digest:
            return image

    suffix = PurePosixPath(source_name or "image.png").suffix.lower()
    if suffix not in {".bmp", ".jpeg", ".jpg", ".png", ".tga", ".tif", ".tiff", ".webp"}:
        suffix = ".img"
    descriptor, temporary_name = tempfile.mkstemp(prefix="mooblender-", suffix=suffix)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        image = bpy.data.images.load(temporary_name, check_existing=False)
        image.name = _unique_name(PurePosixPath(source_name or "Texture").name, "Texture")
        image.pack()
        image["mooblender_sha256"] = digest
        image["promob_resource_name"] = source_name or ""
        return image
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)


def _transparent_texture_name(diffuse_name: str | None) -> str | None:
    if not diffuse_name:
        return None
    stem = PurePosixPath(diffuse_name).stem
    suffix = PurePosixPath(diffuse_name).suffix
    upper = stem.upper()
    if upper.endswith("_DIFFUSE"):
        return stem[: -len("_DIFFUSE")] + "_TRANSPARENT" + suffix
    return None


def _texture_node(nodes, image, *, label: str, non_color: bool = False):
    if image is None:
        return None
    node = nodes.new("ShaderNodeTexImage")
    node.label = label
    node.image = image
    if non_color:
        image.colorspace_settings.name = "Non-Color"
    return node


def _connect_texture_coordinates(nodes, links, source: Material, texture_nodes) -> None:
    texture_nodes = [node for node in texture_nodes if node is not None]
    if not texture_nodes:
        return
    coordinates = nodes.new("ShaderNodeTexCoord")
    vector_output = coordinates.outputs["UV"]
    if source.mapping_number or source.mapping_scale or source.mapping_rotation:
        mapping = nodes.new("ShaderNodeMapping")
        if source.mapping_number:
            x_scale, y_scale = source.mapping_number
            mapping_scale = (x_scale, y_scale, 1.0)
        elif source.mapping_scale:
            width, height = source.mapping_scale
            x_scale = 1000.0 / width if width > 1e-9 else 1.0
            y_scale = 1000.0 / height if height > 1e-9 else 1.0
            mapping_scale = (x_scale, y_scale, 1.0)
        else:
            mapping_scale = (1.0, 1.0, 1.0)
        mapping.inputs["Scale"].default_value = mapping_scale
        mapping.inputs["Rotation"].default_value[2] = math.radians(
            source.mapping_rotation or 0.0
        )
        links.new(vector_output, mapping.inputs["Vector"])
        vector_output = mapping.outputs["Vector"]
    for node in texture_nodes:
        links.new(vector_output, node.inputs["Vector"])


def _socket_default(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "name"):
        return (type(value).__name__, value.name)
    try:
        return tuple(value)
    except TypeError:
        return repr(value)


def _material_state_digest(material) -> str:
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
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _create_material(
    source: Material,
    index: int,
    package: PContentPackage | None,
):
    digest_payload = asdict(source)
    digest_payload.pop("name", None)
    digest_payload["resources"] = {
        texture_name: hashlib.sha256(data).hexdigest() if data is not None else None
        for texture_name in (
            source.diffuse_texture,
            source.specular_texture,
            source.normal_texture,
            _transparent_texture_name(source.diffuse_texture),
        )
        if texture_name
        for data in (package.resource(texture_name) if package is not None else None,)
    }
    digest = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=repr,
        ).encode("utf-8")
    ).hexdigest()
    existing = next(
        (
            material
            for material in bpy.data.materials
            if material.get("mooblender_material_sha256") == digest
            and material.get("mooblender_material_state_sha256")
            == _material_state_digest(material)
        ),
        None,
    )
    if existing is not None:
        existing["promob_mapping_type"] = source.mapping_type or 0
        return existing

    name = _unique_name(source.name, f"Promob Material {index}")
    material = bpy.data.materials.new(name)
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
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    principled = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
    if principled is not None:
        principled.inputs["Base Color"].default_value = color
        principled.inputs["Metallic"].default_value = material.metallic
        principled.inputs["Roughness"].default_value = material.roughness
        principled.inputs["Alpha"].default_value = opacity

        diffuse = _texture_node(
            nodes,
            _embedded_image(package, source.diffuse_texture),
            label="Promob Diffuse",
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
            nodes,
            links,
            source,
            (diffuse, metallic, normal, transparency),
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

    material["promob_material_index"] = index
    material["mooblender_material_sha256"] = digest
    if source.diffuse_texture:
        material["promob_diffuse_texture"] = source.diffuse_texture
    if source.specular_texture:
        material["promob_specular_texture"] = source.specular_texture
    if source.normal_texture:
        material["promob_normal_texture"] = source.normal_texture
    material["promob_mapping_type"] = source.mapping_type or 0
    material["mooblender_material_state_sha256"] = _material_state_digest(material)
    return material


def _entity_code(source: object) -> int:
    return id(source) & 0x7FFFFFFF


def _join_planar_triangles(mesh) -> int:
    """Join compatible triangle pairs while retaining seams and UV boundaries."""

    editable = bmesh.new()
    try:
        editable.from_mesh(mesh)
        candidates = [face for face in editable.faces if len(face.verts) == 3]
        if candidates:
            bmesh.ops.join_triangles(
                editable,
                faces=candidates,
                cmp_seam=True,
                cmp_sharp=True,
                cmp_uvs=True,
                cmp_vcols=True,
                cmp_materials=True,
                angle_face_threshold=math.radians(1.0),
                angle_shape_threshold=math.radians(45.0),
            )
            editable.to_mesh(mesh)
    finally:
        editable.free()
    mesh.update()
    return sum(len(polygon.vertices) == 4 for polygon in mesh.polygons)


def _create_meshes(
    document: PmobDocument,
    materials,
    *,
    material_overrides: dict[str, bpy.types.Material] | None = None,
    entity_code: int,
    convert_tris_to_quads: bool,
):
    scale = document.unit_scale_to_meters
    material_overrides = {
        key.casefold(): value for key, value in (material_overrides or {}).items()
    }
    result: dict[str, list[bpy.types.Mesh]] = {}
    for layer_index, layer in enumerate(document.layers):
        layer_name = _unique_name(layer.name, f"Layer {layer_index}")
        meshes = []
        for mesh_index, source in enumerate(layer.meshes):
            mesh_name = f"{layer_name}_{mesh_index}"
            topology = prepare_mesh(source)
            vertices = [
                tuple(component * scale for component in point) for point in topology.vertices
            ]
            mesh = bpy.data.meshes.new(mesh_name)
            mesh.from_pydata(vertices, [], topology.faces)
            mesh.update()
            layer_attribute = mesh.attributes.new(
                name="mooblender_layer",
                type="INT",
                domain="FACE",
            )
            layer_code = zlib.crc32(layer.name.casefold().encode("utf-8")) & 0x7FFFFFFF
            for value in layer_attribute.data:
                value.value = layer_code
            entity_attribute = mesh.attributes.new(
                name="mooblender_entity",
                type="INT",
                domain="FACE",
            )
            for value in entity_attribute.data:
                value.value = entity_code
            if topology.loop_uvs:
                uv_layer = mesh.uv_layers.new(name="UVMap")
                for loop, (u, v) in zip(mesh.loops, topology.loop_uvs, strict=True):
                    uv_layer.data[loop.index].uv = (u, v)
            quad_count = _join_planar_triangles(mesh) if convert_tris_to_quads else 0
            if topology.loop_normals:
                for polygon in mesh.polygons:
                    polygon.use_smooth = True
                if convert_tris_to_quads:
                    mesh.normals_split_custom_set_from_vertices(topology.vertex_normals)
                else:
                    mesh.normals_split_custom_set(topology.loop_normals)
                mesh.update()
            override = material_overrides.get(layer.name.casefold())
            if override is not None:
                mesh.materials.append(override)
            elif 0 <= source.material_id < len(materials):
                mesh.materials.append(materials[source.material_id])
            mesh["promob_layer"] = layer_name
            mesh["promob_material_id"] = source.material_id
            mesh["promob_source_vertex_count"] = len(source.vertices)
            mesh["mooblender_welded_vertex_count"] = topology.removed_vertex_count
            mesh["mooblender_converted_quad_count"] = quad_count
            meshes.append(mesh)
        result[layer.name.casefold()] = meshes
    return result


def _box_project_uv(
    mesh,
    *,
    final_transform: Matrix,
) -> None:
    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    uv_layer = mesh.uv_layers.new(name="UVMap")
    positions = [final_transform @ vertex.co for vertex in mesh.vertices]
    normal_transform = final_transform.to_3x3().inverted_safe().transposed()
    for polygon in mesh.polygons:
        normal = normal_transform @ polygon.normal
        dominant_axis = max(range(3), key=lambda axis: abs(normal[axis]))
        uv_axes = ((1, 2), (0, 2), (0, 1))[dominant_axis]
        for loop_index in polygon.loop_indices:
            point = positions[mesh.loops[loop_index].vertex_index]
            uv_layer.data[loop_index].uv = (
                point[uv_axes[0]],
                point[uv_axes[1]],
            )


def _instantiate_primitive(
    primitive: Primitive,
    *,
    parent,
    collection,
    meshes_by_layer,
    unit_scale: float,
    source_id: str,
    fallback_index: int,
    layer_corrections: dict[
        str,
        tuple[tuple[float, float, float], tuple[float, float, float]],
    ],
    geometry_scale: tuple[float, float, float],
    document_transform: Matrix | None = None,
):
    name = _unique_name(primitive.name, f"Primitive {fallback_index}")
    node = bpy.data.objects.new(name, None)
    node.empty_display_type = "PLAIN_AXES"
    collection.objects.link(node)
    node.parent = parent
    local_transform = Matrix(
        blender_matrix_rows(primitive.matrix, unit_scale=unit_scale)
    )
    node.matrix_local = local_transform
    document_transform = (document_transform or Matrix.Identity(4)) @ local_transform
    node["promob_primitive_type"] = (
        primitive.kind.name if primitive.kind is not None else "UNKNOWN"
    )
    if primitive.layer_ref:
        node["promob_layer_ref"] = primitive.layer_ref
    if primitive.animation is not None:
        node["promob_animation_times"] = primitive.animation.times
        node["promob_animation_transforms"] = [
            value for matrix in primitive.animation.transforms for value in matrix
        ]
    if source_id:
        node["mooble_item_id"] = source_id

    for mesh_index, mesh in enumerate(meshes_by_layer.get(primitive.layer_ref.casefold(), ())):
        correction_scale, correction_location = layer_corrections.get(
            primitive.layer_ref.casefold(),
            ((1.0, 1.0, 1.0), (0.0, 0.0, 0.0)),
        )
        object_mesh = mesh
        material = mesh.materials[0] if mesh.materials else None
        cubic_mapping = (
            material is not None and material.get("promob_mapping_type") == 1
        )
        if cubic_mapping or not mesh.uv_layers:
            object_mesh = mesh.copy()
            correction_transform = Matrix.Translation(correction_location) @ Matrix.Diagonal(
                (*correction_scale, 1.0)
            )
            scale_transform = Matrix.Diagonal((*geometry_scale, 1.0))
            _box_project_uv(
                object_mesh,
                final_transform=(
                    scale_transform @ document_transform @ correction_transform
                ),
            )
        obj = bpy.data.objects.new(f"{name}_{mesh_index}", object_mesh)
        obj.parent = node
        obj.scale = correction_scale
        obj.location = correction_location
        obj["promob_layer"] = primitive.layer_ref
        obj["promob_material_id"] = mesh.get("promob_material_id", -1)
        if source_id:
            obj["mooble_item_id"] = source_id
        collection.objects.link(obj)

    for child_index, child in enumerate(primitive.children):
        _instantiate_primitive(
            child,
            parent=node,
            collection=collection,
            meshes_by_layer=meshes_by_layer,
            unit_scale=unit_scale,
            source_id=source_id,
            fallback_index=child_index,
            layer_corrections=layer_corrections,
            geometry_scale=geometry_scale,
            document_transform=document_transform,
        )
    return node


def _default_material_assignments(package: PContentPackage) -> dict[str, str]:
    """Return the first/default option's layer assignments for each model group."""

    assignments: dict[str, str] = {}
    seen_groups: set[str] = set()
    models = package.properties.get("Models", [])
    if not isinstance(models, list):
        return assignments
    for model in models:
        if not isinstance(model, dict):
            continue
        group_id = str(model.get("ModelDefinitionId") or model.get("Id") or "")
        if not group_id or group_id in seen_groups:
            continue
        seen_groups.add(group_id)
        components = model.get("Components", [])
        if not isinstance(components, list):
            continue
        for component in components:
            if not isinstance(component, dict):
                continue
            layer = str(component.get("LayerId") or "")
            material_id = str(component.get("MaterialId") or "")
            if layer and material_id:
                assignments[layer] = material_id
    return assignments


def _layer_resize_corrections(
    package: PContentPackage | None,
    geometry_scale: tuple[float, float, float],
) -> dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]]:
    if package is None or package.document is None:
        return {}
    edit_states: dict[str, set[object]] = {}
    models = package.properties.get("Models", [])
    if isinstance(models, list):
        for model in models:
            if not isinstance(model, dict):
                continue
            components = model.get("Components", [])
            if not isinstance(components, list):
                continue
            for component in components:
                if not isinstance(component, dict):
                    continue
                layer = str(component.get("LayerId") or "").casefold()
                if layer:
                    edit_states.setdefault(layer, set()).add(component.get("Edit"))

    fixed_candidates = {
        layer for layer, states in edit_states.items() if states == {False}
    }
    if not fixed_candidates:
        return {}
    document_dimensions = document_geometry_dimensions(package.document)
    layer_dimensions = document_layer_dimensions(package.document)
    layer_bounds = document_layer_bounds(package.document)
    populated_bounds = tuple(layer_bounds.values())
    if not populated_bounds:
        return {}
    document_minimum = tuple(
        min(bounds[0][axis] for bounds in populated_bounds) for axis in range(3)
    )
    document_maximum = tuple(
        max(bounds[1][axis] for bounds in populated_bounds) for axis in range(3)
    )
    unit_scale = package.document.unit_scale_to_meters
    corrections = {
        layer: [[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]]
        for layer in layer_bounds
    }
    for axis, global_scale in enumerate(geometry_scale):
        document_size = document_dimensions[axis]
        if abs(global_scale - 1.0) <= 0.01 or document_size <= 1e-9:
            continue
        partial_fixed = [
            layer
            for layer in fixed_candidates
            if layer in layer_bounds
            and layer_dimensions[layer][axis] / document_size < 0.5
        ]
        if not partial_fixed:
            continue
        center = (document_minimum[axis] + document_maximum[axis]) / 2.0
        fixed_low = any(
            (layer_bounds[layer][0][axis] + layer_bounds[layer][1][axis]) / 2.0
            <= center
            for layer in partial_fixed
        )
        fixed_high = any(
            (layer_bounds[layer][0][axis] + layer_bounds[layer][1][axis]) / 2.0
            > center
            for layer in partial_fixed
        )
        for layer, bounds in layer_bounds.items():
            correction_scale, correction_location = corrections[layer]
            if layer in partial_fixed:
                correction_scale[axis] = 1.0 / global_scale
                layer_center = (bounds[0][axis] + bounds[1][axis]) / 2.0
                if layer_center <= center:
                    target_anchor = (
                        global_scale * document_minimum[axis]
                        + bounds[0][axis]
                        - document_minimum[axis]
                    )
                    translation = target_anchor - bounds[0][axis]
                else:
                    target_anchor = (
                        global_scale * document_maximum[axis]
                        - document_maximum[axis]
                        + bounds[1][axis]
                    )
                    translation = target_anchor - bounds[1][axis]
                correction_location[axis] = (
                    translation * unit_scale / global_scale
                )
                continue
            source_minimum = bounds[0][axis]
            source_maximum = bounds[1][axis]
            source_size = source_maximum - source_minimum
            if source_size <= 1e-9:
                continue
            target_minimum = (
                source_minimum
                if fixed_low
                else document_minimum[axis]
                + global_scale * (source_minimum - document_minimum[axis])
            )
            target_maximum = (
                document_minimum[axis]
                + document_size * global_scale
                - (document_maximum[axis] - source_maximum)
                if fixed_high
                else document_minimum[axis]
                + global_scale * (source_maximum - document_minimum[axis])
            )
            effective_scale = (target_maximum - target_minimum) / source_size
            translation = target_minimum - effective_scale * source_minimum
            correction_scale[axis] = effective_scale / global_scale
            correction_location[axis] = translation * unit_scale / global_scale
    return {
        layer: (tuple(scale), tuple(location))
        for layer, (scale, location) in corrections.items()
        if scale != [1.0, 1.0, 1.0] or location != [0.0, 0.0, 0.0]
    }


def _remote_material(
    material_id: str,
    package: PContentPackage,
    cache: dict[tuple[int, int], bpy.types.Material],
):
    document = package.document
    if document is None or not document.materials:
        return None
    key = (id(package), 0)
    material = cache.get(key)
    if material is None:
        material = _create_material(document.materials[0], 0, package)
        cache[key] = material
    material["mooble_material_id"] = material_id
    return material


def _document_root(
    document: PmobDocument,
    package: PContentPackage | None,
    *,
    parent,
    collection,
    source_id: str,
    cache: dict[int, dict[str, list[bpy.types.Mesh]]],
    material_cache: dict[tuple[int, int], bpy.types.Material],
    convert_tris_to_quads: bool,
    geometry_scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
):
    cache_key = id(package) if package is not None else id(document)
    meshes_by_layer = cache.get(cache_key)
    if meshes_by_layer is None:
        materials = []
        material_owner = package if package is not None else document
        for index, source_material in enumerate(document.materials):
            material_key = (id(material_owner), index)
            material = material_cache.get(material_key)
            if material is None:
                material = _create_material(source_material, index, package)
                material_cache[material_key] = material
            materials.append(material)
        overrides = {}
        if package is not None:
            for layer, material_id in _default_material_assignments(package).items():
                material_package = package.resolved_materials.get(material_id)
                if material_package is None:
                    continue
                material = _remote_material(material_id, material_package, material_cache)
                if material is not None:
                    overrides[layer] = material
        meshes_by_layer = _create_meshes(
            document,
            materials,
            material_overrides=overrides,
            entity_code=_entity_code(material_owner),
            convert_tris_to_quads=convert_tris_to_quads,
        )
        cache[cache_key] = meshes_by_layer
    primitive = document.primitive
    if primitive is None:
        primitive = Primitive(
            name=document.name or "root",
            kind=PrimitiveType.GROUP,
            children=[
                Primitive(
                    name=layer.name,
                    kind=PrimitiveType.LAYER,
                    layer_ref=layer.name,
                )
                for layer in document.layers
            ],
        )
    return _instantiate_primitive(
        primitive,
        parent=parent,
        collection=collection,
        meshes_by_layer=meshes_by_layer,
        unit_scale=document.unit_scale_to_meters,
        source_id=source_id,
        fallback_index=0,
        layer_corrections=_layer_resize_corrections(package, geometry_scale),
        geometry_scale=geometry_scale,
    )


def _raw_aggregate(package: PContentPackage, index: int) -> dict[str, object]:
    aggregates = package.properties.get("Aggregates", [])
    if not isinstance(aggregates, list) or not 0 <= index < len(aggregates):
        return {}
    value = aggregates[index]
    return value if isinstance(value, dict) else {}


def _add_open_driver(
    target,
    index: int,
    controller,
    controller_data_path: str,
    expression: str,
) -> None:
    driver = target.driver_add("rotation_euler" if index == 2 else "location", index).driver
    driver.type = "SCRIPTED"
    driver.expression = expression
    variable = driver.variables.new()
    variable.name = "open_ratio"
    variable.type = "SINGLE_PROP"
    variable.targets[0].id = controller
    variable.targets[0].data_path = controller_data_path


def _add_dimension_driver(
    target,
    axis: int,
    controller,
    controller_data_path: str,
    default_value: float,
) -> None:
    driver = target.driver_add("scale", axis).driver
    driver.type = "SCRIPTED"
    driver.expression = f"dimension/{default_value:.17g}"
    variable = driver.variables.new()
    variable.name = "dimension"
    variable.type = "SINGLE_PROP"
    variable.targets[0].id = controller
    variable.targets[0].data_path = controller_data_path


def _apply_open_services(
    package: PContentPackage,
    *,
    prefix: tuple[int, ...],
    controller,
    opening_control: Callable[[dict[str, object], str], tuple[str, str]],
    aggregate_nodes: dict[tuple[int, ...], dict[str, Any]],
    controlled_paths: set[tuple[int, ...]],
) -> int:
    services = package.properties.get("OpenServices", [])
    if not isinstance(services, list):
        return 0
    applied = 0
    for service in services:
        if not isinstance(service, dict):
            continue
        raw_path = service.get("AggregatePath", [])
        if not isinstance(raw_path, list):
            continue
        # Observed paths alternate aggregate-container index and selected
        # definition index, for example [2, 0] addresses aggregate 2 using its
        # first/default specification. Our resolved tree stores container
        # indices because only the selected specification becomes geometry.
        path = prefix + tuple(
            value
            for offset, value in enumerate(raw_path)
            if offset % 2 == 0 and isinstance(value, int)
        )
        if path in controlled_paths:
            continue
        data = aggregate_nodes.get(path)
        if data is None:
            continue
        motion = data["motion"]
        content = data["content"]
        dimensions = data["dimensions"]
        width, depth, height = dimensions
        inverted = bool(data["inverted"])
        variables: dict[str, float | bool] = {
            **dimension_variables(dimensions),
            "I": inverted,
            "INVERTED": inverted,
        }
        service_type = str(service.get("Type", "")).casefold()
        maximum = evaluate_expression(service.get("Max"), variables)
        if service_type == "door":
            pivot, angle = door_motion(
                service,
                (width, depth, height),
                inverted=inverted,
            )
            if abs(angle) <= 1e-12:
                continue
            controller_data_path, control_name = opening_control(
                service,
                data["placement"].name,
            )
            motion.location = tuple(value * 0.001 for value in pivot)
            content.location = tuple(-value * 0.001 for value in pivot)
            _add_open_driver(
                motion,
                2,
                controller,
                controller_data_path,
                f"{angle:.17g}*open_ratio",
            )
        elif service_type == "drawer":
            distance = maximum * -0.001
            if abs(distance) <= 1e-12:
                continue
            controller_data_path, control_name = opening_control(
                service,
                data["placement"].name,
            )
            _add_open_driver(
                motion,
                1,
                controller,
                controller_data_path,
                f"{distance:.17g}*open_ratio",
            )
        else:
            continue
        motion["mooblender_open_service"] = control_name
        motion["mooblender_open_service_type"] = str(service.get("Type", ""))
        controlled_paths.add(path)
        applied += 1
    return applied


def _build_package_tree(
    package: PContentPackage,
    *,
    parent,
    collection,
    source_id: str,
    cache: dict[int, dict[str, list[bpy.types.Mesh]]],
    material_cache: dict[tuple[int, int], bpy.types.Material],
    aggregate_nodes: dict[tuple[int, ...], dict[str, Any]],
    dimension_nodes: list[dict[str, Any]] | None,
    convert_tris_to_quads: bool,
    prefix: tuple[int, ...] = (),
    current_dimensions: tuple[float, float, float] | None = None,
    document_scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
    control_label: str = "",
    dimension_controls_enabled: bool = True,
):
    logical_dimensions = property_dimensions(package.properties)
    drawing_dimensions = property_dimensions(
        package.properties,
        "DrawingDimension",
    )
    serialized_dimensions = serialized_geometry_dimensions(
        package.properties,
        document=package.document,
        fallback=logical_dimensions,
    )
    parent_dimensions = current_dimensions or tuple(
        drawing
        if abs(drawing) > 1e-9
        else logical
        if abs(logical) > 1e-9
        else serialized
        for drawing, logical, serialized in zip(
            drawing_dimensions,
            logical_dimensions,
            serialized_dimensions,
            strict=True,
        )
    )
    package_parent = parent
    dimensions = (
        tuple(
            dimension
            for dimension in configurable_dimensions(
                package.properties,
                defaults=parent_dimensions,
            )
            if dimension.minimum <= dimension.default <= dimension.maximum
        )
        if dimension_controls_enabled
        else ()
    )
    if dimension_nodes is not None and dimensions:
        label = _unique_name(
            control_label or (package.document.name if package.document else ""),
            "Entity",
        )
        package_parent = bpy.data.objects.new(f"{label} Parameters", None)
        package_parent.parent = parent
        package_parent["mooblender_configurable_dimensions"] = len(dimensions)
        collection.objects.link(package_parent)
        dimension_nodes.append(
            {
                "label": control_label,
                "object": package_parent,
                "dimensions": dimensions,
            }
        )
    if package.document is not None:
        document_parent = package_parent
        if document_scale != (1.0, 1.0, 1.0):
            document_name = _unique_name(package.document.name, "Aggregate")
            document_parent = bpy.data.objects.new(f"{document_name} Geometry Scale", None)
            document_parent.parent = package_parent
            document_parent.scale = document_scale
            document_parent["mooblender_geometry_scale"] = document_scale
            collection.objects.link(document_parent)
        _document_root(
            package.document,
            package,
            parent=document_parent,
            collection=collection,
            source_id=source_id,
            cache=cache,
            material_cache=material_cache,
            convert_tris_to_quads=convert_tris_to_quads,
            geometry_scale=document_scale,
        )
    for resolved in package.resolved_aggregates:
        raw = _raw_aggregate(package, resolved.index)
        child = resolved.package
        default_dimensions = property_dimensions(child.properties)
        variables: dict[str, float | bool] = dimension_variables(
            default_dimensions,
            parent=parent_dimensions,
        )
        target_dimensions = property_dimensions(
            raw,
            variables=variables,
            fallback=default_dimensions,
        )
        variables.update(dimension_variables(target_dimensions))
        visible_condition = raw.get("VisibleCondition")
        if visible_condition is not None and not bool(
            evaluate_expression(visible_condition, variables)
        ):
            continue
        position = raw.get("Position", {})
        position = position if isinstance(position, dict) else {}
        location = tuple(
            evaluate_expression(position.get(axis), variables) * 0.001
            for axis in ("X", "Y", "Z")
        )
        rotation = math.radians(evaluate_expression(position.get("Rotation"), variables))
        raw_normal = raw.get("Normal", {})
        raw_normal = raw_normal if isinstance(raw_normal, dict) else {}
        normal = Vector(
            tuple(
                evaluate_expression(raw_normal.get(axis), variables)
                for axis in ("X", "Y", "Z")
            )
        )
        if normal.length_squared <= 1e-12:
            normal = Vector((0.0, 0.0, 1.0))
        else:
            normal.normalize()
        orientation = Vector((0.0, 0.0, 1.0)).rotation_difference(normal)
        spin = Quaternion((0.0, 0.0, 1.0), rotation)
        inverted = raw.get("Inverted") is True
        geometry_dimensions = serialized_geometry_dimensions(
            child.properties,
            document=child.document,
            fallback=default_dimensions,
        )
        scale = [
            target / geometry if geometry else 1.0
            for target, geometry in zip(
                target_dimensions,
                geometry_dimensions,
                strict=True,
            )
        ]
        fallback = f"Aggregate {resolved.index}"
        name = _unique_name(str(raw.get("Description") or raw.get("Id") or ""), fallback)
        placement = bpy.data.objects.new(name, None)
        placement.empty_display_type = "CUBE"
        placement.parent = package_parent
        placement.location = location
        placement.rotation_mode = "QUATERNION"
        placement.rotation_quaternion = orientation @ spin
        placement.scale.x = -1.0 if inverted else 1.0
        placement["mooble_specification_id"] = resolved.specification_id
        placement["promob_aggregate_index"] = resolved.index
        collection.objects.link(placement)

        motion = bpy.data.objects.new(f"{name} Opening", None)
        motion.parent = placement
        collection.objects.link(motion)
        content = bpy.data.objects.new(f"{name} Content", None)
        content.parent = motion
        collection.objects.link(content)
        path = prefix + (resolved.index,)
        aggregate_nodes[path] = {
            "placement": placement,
            "motion": motion,
            "content": content,
            "dimensions": target_dimensions,
            "inverted": inverted,
        }
        _build_package_tree(
            child,
            parent=content,
            collection=collection,
            source_id=source_id,
            cache=cache,
            material_cache=material_cache,
            aggregate_nodes=aggregate_nodes,
            dimension_nodes=dimension_nodes,
            convert_tris_to_quads=convert_tris_to_quads,
            prefix=path,
            current_dimensions=target_dimensions,
            document_scale=tuple(scale),
            control_label=name,
            dimension_controls_enabled=(
                dimension_controls_enabled and raw.get("Constant") is not True
            ),
        )


def _modifier_socket_value(modifier, socket, value):
    interface_values = getattr(getattr(modifier, "properties", None), "inputs", None)
    if interface_values is not None and hasattr(interface_values, socket.identifier):
        socket_value = getattr(interface_values, socket.identifier)
        socket_value.value = value
        return socket_value.path_from_id("value")
    modifier[socket.identifier] = value
    return modifier.path_from_id(f'["{socket.identifier}"]')


def _geometry_nodes_controller(name: str, collection, source_collection):
    mesh = bpy.data.meshes.new(f"{name} Geometry")
    controller = bpy.data.objects.new(name, mesh)
    collection.objects.link(controller)
    modifier = controller.modifiers.new(name="Mooblender", type="NODES")
    node_group = bpy.data.node_groups.new(f"{name} Controls", "GeometryNodeTree")
    modifier.node_group = node_group

    output_socket = node_group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )
    nodes = node_group.nodes
    links = node_group.links
    collection_info = nodes.new("GeometryNodeCollectionInfo")
    collection_info.inputs["Collection"].default_value = source_collection
    realize = nodes.new("GeometryNodeRealizeInstances")
    group_input = nodes.new("NodeGroupInput")
    output = nodes.new("NodeGroupOutput")
    output.is_active_output = True
    links.new(collection_info.outputs["Instances"], realize.inputs["Geometry"])
    links.new(realize.outputs["Geometry"], output.inputs[output_socket.name])
    return controller, modifier, group_input, realize, output


def _make_socket_single_value(socket) -> None:
    socket.structure_type = "SINGLE"


def _keep_modifier_input_active(node_group, group_input, socket) -> None:
    value_sink = node_group.nodes.new("ShaderNodeMath")
    value_sink.operation = "MULTIPLY"
    value_sink.hide = True
    value_sink.label = "Modifier input driver"
    value_sink.inputs[1].default_value = 0.0
    node_group.links.new(group_input.outputs[socket.name], value_sink.inputs[0])


def _add_dimension_controls(
    dimension_nodes: list[dict[str, Any]],
    *,
    controller,
    modifier,
    group_input,
) -> int:
    if not dimension_nodes:
        return 0

    node_group = modifier.node_group
    used_names = {item.name for item in node_group.interface.items_tree}
    defaults = []
    controls = 0
    for data in dimension_nodes:
        label = str(data["label"])
        target = data["object"]
        for dimension in data["dimensions"]:
            base = f"{label}: {dimension.name}" if label else dimension.name
            name = base
            suffix = 2
            while name in used_names:
                name = f"{base} ({suffix})"
                suffix += 1
            used_names.add(name)
            socket = node_group.interface.new_socket(
                name=name,
                in_out="INPUT",
                socket_type="NodeSocketFloat",
            )
            _make_socket_single_value(socket)
            socket.subtype = "DISTANCE"
            socket.default_value = dimension.default * 0.001
            socket.min_value = dimension.minimum * 0.001
            socket.max_value = dimension.maximum * 0.001
            socket.description = (
                f"Mooble range: {dimension.minimum:g}–{dimension.maximum:g} mm"
            )
            defaults.append((socket, dimension.default * 0.001, target, dimension.axis))
            controls += 1

    node_group.interface_update(bpy.context)
    for socket, value, target, axis in defaults:
        _keep_modifier_input_active(node_group, group_input, socket)
        data_path = _modifier_socket_value(modifier, socket, value)
        _add_dimension_driver(target, axis, controller, data_path, value)
    node_group.interface_update(bpy.context)
    if controls:
        controller["mooblender_dimension_control_count"] = controls
    return controls


def _model_groups(package: PContentPackage):
    groups: dict[tuple[int, str], dict[str, object]] = {}
    stack = [package]
    visited: set[int] = set()
    while stack:
        current = stack.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        models = current.properties.get("Models", [])
        if isinstance(models, list):
            for model in models:
                if not isinstance(model, dict):
                    continue
                group_id = str(model.get("ModelDefinitionId") or model.get("Id") or "")
                if not group_id:
                    continue
                group = groups.setdefault(
                    (id(current), group_id),
                    {
                        "name": str(model.get("ModelDefinitionName") or group_id),
                        "options": [],
                        "materials": {},
                        "scope": _entity_code(current),
                    },
                )
                option_id = str(model.get("Id") or model.get("Name") or "")
                options = group["options"]
                if isinstance(options, list) and not any(
                    isinstance(item, dict) and item.get("id") == option_id
                    for item in options
                ):
                    components = model.get("Components", [])
                    assignments = {
                        str(component.get("LayerId")): str(component.get("MaterialId"))
                        for component in components
                        if isinstance(component, dict)
                        and component.get("LayerId")
                        and component.get("MaterialId")
                    } if isinstance(components, list) else {}
                    options.append(
                        {
                            "id": option_id,
                            "name": str(model.get("Name") or option_id),
                            "assignments": assignments,
                        }
                    )
                materials = group["materials"]
                if isinstance(materials, dict):
                    materials.update(current.resolved_materials)
        stack.extend(item.package for item in current.resolved_aggregates)
    return groups


def _create_remote_materials(groups, cache):
    result = {}
    for group in groups.values():
        scope = int(group.get("scope", 0))
        materials = group.get("materials", {})
        if not isinstance(materials, dict):
            continue
        for material_id, package in materials.items():
            key = (scope, material_id)
            if key in result or not isinstance(package, PContentPackage):
                continue
            material = _remote_material(material_id, package, cache)
            if material is not None:
                result[key] = material
    return result


def _menu_option_names(options: list[dict[str, object]]) -> list[str]:
    names: list[str] = []
    counts: dict[str, int] = {}
    for index, option in enumerate(options):
        base = str(option.get("name") or option.get("id") or f"Style {index + 1}")
        count = counts.get(base, 0) + 1
        counts[base] = count
        names.append(base if count == 1 else f"{base} ({count})")
    return names


def _modifier_menu_value(modifier, socket, name: str, index: int) -> None:
    interface_values = getattr(getattr(modifier, "properties", None), "inputs", None)
    if interface_values is not None and hasattr(interface_values, socket.identifier):
        getattr(interface_values, socket.identifier).value = name
        return
    try:
        items = modifier.id_properties_ui(socket.identifier).as_dict().get("items", ())
        value = next(item[-1] for item in items if item[0] == name)
    except (KeyError, StopIteration, TypeError):
        value = index
    modifier[socket.identifier] = value


def _add_material_options(
    package: PContentPackage,
    *,
    controller,
    modifier,
    group_input,
    realize,
    output,
    material_cache: dict[tuple[int, int], bpy.types.Material],
) -> int:
    groups = _model_groups(package)
    materials = _create_remote_materials(groups, material_cache)
    if not materials:
        return 0
    node_group = modifier.node_group
    links = node_group.links
    output_geometry = output.inputs.get("Geometry")
    for link in list(output_geometry.links):
        node_group.links.remove(link)
    geometry = realize.outputs["Geometry"]
    controls = 0
    menu_defaults = []
    bundles: dict[tuple[str, tuple[str, ...]], list[dict[str, object]]] = {}
    for group in groups.values():
        options = group.get("options")
        if not isinstance(options, list) or len(options) < 2:
            continue
        option_names = tuple(_menu_option_names(options))
        group_name = str(group.get("name") or "Material")
        bundles.setdefault((group_name, option_names), []).append(group)

    used_names = {item.name for item in node_group.interface.items_tree}
    for (group_name, option_names), bundled_groups in bundles.items():
        applications = []
        for group in bundled_groups:
            options = group["options"]
            scope = int(group.get("scope", 0))
            layers = sorted(
                {
                    layer
                    for option in options
                    if isinstance(option, dict)
                    for layer in option.get("assignments", {})
                }
            )
            usable_layers = [
                layer
                for layer in layers
                if all(
                    isinstance(option, dict)
                    and materials.get(
                        (scope, option.get("assignments", {}).get(layer))
                    )
                    is not None
                    for option in options
                )
            ]
            if usable_layers:
                applications.append((scope, options, usable_layers))
        if not applications:
            continue

        base_name = f"Finish: {group_name}"
        socket_name = base_name
        suffix = 2
        while socket_name in used_names:
            socket_name = f"{base_name} ({suffix})"
            suffix += 1
        used_names.add(socket_name)
        socket = node_group.interface.new_socket(
            name=socket_name,
            in_out="INPUT",
            socket_type="NodeSocketMenu",
        )
        _make_socket_single_value(socket)
        socket.description = " / ".join(option_names)
        option_output = group_input.outputs[socket.name]
        style_switch = node_group.nodes.new("GeometryNodeMenuSwitch")
        style_switch.data_type = "INT"
        style_switch.enum_items.clear()
        for index, name in enumerate(option_names):
            style_switch.enum_items.new(name)
            style_switch.inputs[index + 1].default_value = index
        socket.from_socket(style_switch, style_switch.inputs["Menu"])
        socket.name = socket_name
        links.new(option_output, style_switch.inputs["Menu"])
        for scope, options, usable_layers in applications:
            for layer in usable_layers:
                named_layer = node_group.nodes.new("GeometryNodeInputNamedAttribute")
                named_layer.data_type = "INT"
                named_layer.inputs["Name"].default_value = "mooblender_layer"
                compare_layer = node_group.nodes.new("FunctionNodeCompare")
                compare_layer.data_type = "INT"
                compare_layer.operation = "EQUAL"
                compare_layer.inputs["B"].default_value = (
                    zlib.crc32(layer.casefold().encode("utf-8")) & 0x7FFFFFFF
                )
                named_entity = node_group.nodes.new("GeometryNodeInputNamedAttribute")
                named_entity.data_type = "INT"
                named_entity.inputs["Name"].default_value = "mooblender_entity"
                compare_entity = node_group.nodes.new("FunctionNodeCompare")
                compare_entity.data_type = "INT"
                compare_entity.operation = "EQUAL"
                compare_entity.inputs["B"].default_value = scope
                selection = node_group.nodes.new("FunctionNodeBooleanMath")
                selection.operation = "AND"
                material_switch = node_group.nodes.new("GeometryNodeIndexSwitch")
                material_switch.data_type = "MATERIAL"
                while len(material_switch.index_switch_items) < len(options):
                    material_switch.index_switch_items.new()
                while len(material_switch.index_switch_items) > len(options):
                    material_switch.index_switch_items.remove(
                        material_switch.index_switch_items[-1]
                    )
                for index, option in enumerate(options):
                    material_id = option["assignments"][layer]
                    material_switch.inputs[index + 1].default_value = materials[
                        (scope, material_id)
                    ]
                set_material = node_group.nodes.new("GeometryNodeSetMaterial")
                links.new(named_layer.outputs["Attribute"], compare_layer.inputs["A"])
                links.new(named_entity.outputs["Attribute"], compare_entity.inputs["A"])
                links.new(compare_layer.outputs["Result"], selection.inputs[0])
                links.new(compare_entity.outputs["Result"], selection.inputs[1])
                links.new(selection.outputs["Boolean"], set_material.inputs["Selection"])
                links.new(
                    style_switch.outputs["Output"],
                    material_switch.inputs["Index"],
                )
                links.new(
                    material_switch.outputs["Output"],
                    set_material.inputs["Material"],
                )
                links.new(geometry, set_material.inputs["Geometry"])
                geometry = set_material.outputs["Geometry"]
        socket.default_value = option_names[0]
        menu_defaults.append((socket, option_names[0], 0))
        controls += 1
    links.new(geometry, output_geometry)
    node_group.interface_update(bpy.context)
    for socket, name, index in menu_defaults:
        _modifier_menu_value(modifier, socket, name, index)
    node_group.interface_update(bpy.context)
    if controls:
        controller["mooblender_material_option_count"] = controls
    return controls


def build_document(
    source: PmobDocument | PContentPackage,
    context,
    *,
    collection_name: str = "",
    source_id: str = "",
    convert_tris_to_quads: bool = False,
) -> bpy.types.Object:
    package = source if isinstance(source, PContentPackage) else None
    document = package.document if package is not None else source
    if document is None and package is not None and not package.resolved_aggregates:
        raise ValueError("this PContent aggregate has not been resolved")

    document_name = document.name if document is not None else ""
    name = _unique_name(collection_name or document_name, "Promob Import")
    destination = context.collection or context.scene.collection
    source_collection = bpy.data.collections.new(f"{name} Source")
    (
        root,
        geometry_modifier,
        group_input,
        realize,
        group_output,
    ) = _geometry_nodes_controller(
        name,
        destination,
        source_collection,
    )
    hierarchy_root = bpy.data.objects.new(f"{name} Hierarchy", None)
    hierarchy_root.empty_display_type = "CUBE"
    source_collection.objects.link(hierarchy_root)
    target_collection = source_collection
    control_name_counts: dict[str, int] = {}

    def opening_control(
        service: dict[str, object],
        fallback: str,
    ) -> tuple[str, str]:
        base = control_name(service, fallback)
        count = control_name_counts.get(base, 0) + 1
        control_name_counts[base] = count
        name = base if count == 1 else f"{base} ({count})"
        socket = geometry_modifier.node_group.interface.new_socket(
            name=name,
            in_out="INPUT",
            socket_type="NodeSocketFloat",
        )
        _make_socket_single_value(socket)
        socket.default_value = 0.0
        socket.min_value = 0.0
        socket.max_value = 1.0
        socket.description = f"Open {base}"
        geometry_modifier.node_group.interface_update(bpy.context)
        _keep_modifier_input_active(
            geometry_modifier.node_group,
            group_input,
            socket,
        )
        return _modifier_socket_value(geometry_modifier, socket, 0.0), name

    aggregate_nodes: dict[tuple[int, ...], dict[str, Any]] = {}
    dimension_nodes: list[dict[str, Any]] = []
    cache: dict[int, dict[str, list[bpy.types.Mesh]]] = {}
    material_cache: dict[tuple[int, int], bpy.types.Material] = {}
    if package is not None:
        _build_package_tree(
            package,
            parent=hierarchy_root,
            collection=target_collection,
            source_id=source_id,
            cache=cache,
            material_cache=material_cache,
            aggregate_nodes=aggregate_nodes,
            dimension_nodes=dimension_nodes,
            convert_tris_to_quads=convert_tris_to_quads,
        )
        open_services = 0
        controlled_paths: set[tuple[int, ...]] = set()
        stack = [(package, ())]
        visited: set[tuple[int, tuple[int, ...]]] = set()
        while stack:
            current, prefix = stack.pop()
            marker = (id(current), prefix)
            if marker in visited:
                continue
            visited.add(marker)
            open_services += _apply_open_services(
                current,
                prefix=prefix,
                controller=root,
                opening_control=opening_control,
                aggregate_nodes=aggregate_nodes,
                controlled_paths=controlled_paths,
            )
            stack.extend(
                (item.package, prefix + (item.index,))
                for item in current.resolved_aggregates
            )
        if open_services:
            root["mooblender_open_service_count"] = open_services
        _add_material_options(
            package,
            controller=root,
            modifier=geometry_modifier,
            group_input=group_input,
            realize=realize,
            output=group_output,
            material_cache=material_cache,
        )
        _add_dimension_controls(
            dimension_nodes,
            controller=root,
            modifier=geometry_modifier,
            group_input=group_input,
        )
    elif document is not None:
        _document_root(
            document,
            None,
            parent=hierarchy_root,
            collection=target_collection,
            source_id=source_id,
            cache=cache,
            material_cache=material_cache,
            convert_tris_to_quads=convert_tris_to_quads,
        )
    source_collection["mooblender_node_source"] = True
    root["promob_version"] = document.version if document is not None else 0
    if source_id:
        root["mooble_item_id"] = source_id
    root["mooblender_convert_tris_to_quads"] = convert_tris_to_quads
    return root
