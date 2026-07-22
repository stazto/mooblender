"""Build Blender meshes and primitive hierarchies from neutral Promob scenes."""

from __future__ import annotations

import math
import zlib

import bmesh
import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from ..formats.pcontent import PContentPackage
from ..model.dimensions import (
    document_geometry_dimensions,
    document_layer_bounds,
    document_layer_dimensions,
)
from ..model.scene import PmobDocument, Primitive, PrimitiveType
from ..model.topology import prepare_mesh
from ..model.transforms import blender_matrix_rows
from .materials import create_material


class TransformNode:
    """Lightweight build-time transform that never becomes a Blender object."""

    def __init__(self, name: str, parent: TransformNode | None = None):
        """Create an identity transform beneath an optional parent record."""
        self.name = name
        self.parent = parent
        self.location = Vector((0.0, 0.0, 0.0))
        self.rotation_mode = "XYZ"
        self.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
        self.rotation_quaternion = Quaternion((1.0, 0.0, 0.0, 0.0))
        self.scale = Vector((1.0, 1.0, 1.0))
        self.metadata: dict[str, object] = {}

    def __setitem__(self, key: str, value: object) -> None:
        """Attach diagnostic metadata using Blender-like item syntax."""
        self.metadata[key] = value

    @property
    def matrix_basis(self) -> Matrix:
        """Compose the local translation, rotation, and scale matrix."""
        rotation = (
            self.rotation_quaternion
            if self.rotation_mode == "QUATERNION"
            else self.rotation_euler.to_quaternion()
        )
        return Matrix.LocRotScale(self.location, rotation, self.scale)

    @property
    def matrix_local(self) -> Matrix:
        """Return the local matrix represented by this transform record."""
        return self.matrix_basis

    @matrix_local.setter
    def matrix_local(self, value: Matrix) -> None:
        """Decompose a local matrix into the record's transform channels."""
        location, rotation, scale = value.decompose()
        self.location = location
        self.rotation_mode = "QUATERNION"
        self.rotation_quaternion = rotation
        self.scale = scale


def _unique_name(value: str, fallback: str) -> str:
    """Return a Blender-safe source name or a stable fallback."""
    return value.strip().replace("\x00", "") or fallback


def _entity_code(source: object) -> int:
    """Return a process-local positive integer used as a face scope attribute."""
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
    """Create Blender mesh datablocks for every neutral document layer."""
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
    """Generate physical box-projected UVs after the complete source transform."""
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
    object_parents: dict[bpy.types.Object, TransformNode],
    document_transform: Matrix | None = None,
):
    """Recursively instantiate primitive records and their referenced meshes."""
    name = _unique_name(primitive.name, f"Primitive {fallback_index}")
    node = TransformNode(name, parent)
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
        obj.scale = correction_scale
        obj.location = correction_location
        object_parents[obj] = node
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
            object_parents=object_parents,
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


def _fixed_component_layers(package: PContentPackage) -> set[str]:
    """Return layers consistently marked non-editable by every model option."""
    edit_states: dict[str, set[object]] = {}
    models = package.properties.get("Models", [])
    if not isinstance(models, list):
        return set()
    for model in models:
        components = model.get("Components", []) if isinstance(model, dict) else []
        if not isinstance(components, list):
            continue
        for component in components:
            if not isinstance(component, dict):
                continue
            layer = str(component.get("LayerId") or "").casefold()
            if layer:
                edit_states.setdefault(layer, set()).add(component.get("Edit"))
    return {layer for layer, states in edit_states.items() if states == {False}}


def _fixed_axis_correction(
    bounds,
    *,
    axis: int,
    center: float,
    document_minimum: float,
    document_maximum: float,
    global_scale: float,
    unit_scale: float,
) -> tuple[float, float]:
    """Keep hardware size while anchoring it to the resized low or high edge."""
    layer_center = (bounds[0][axis] + bounds[1][axis]) / 2.0
    if layer_center <= center:
        source_anchor = bounds[0][axis]
        target_anchor = global_scale * document_minimum + source_anchor - document_minimum
    else:
        source_anchor = bounds[1][axis]
        target_anchor = global_scale * document_maximum - document_maximum + source_anchor
    translation = target_anchor - source_anchor
    return 1.0 / global_scale, translation * unit_scale / global_scale


def _stretch_axis_correction(
    bounds,
    *,
    axis: int,
    fixed_low: bool,
    fixed_high: bool,
    document_minimum: float,
    document_maximum: float,
    document_size: float,
    global_scale: float,
    unit_scale: float,
) -> tuple[float, float] | None:
    """Stretch a panel only through the space not reserved by fixed hardware."""
    source_minimum = bounds[0][axis]
    source_maximum = bounds[1][axis]
    source_size = source_maximum - source_minimum
    if source_size <= 1e-9:
        return None
    target_minimum = (
        source_minimum
        if fixed_low
        else document_minimum + global_scale * (source_minimum - document_minimum)
    )
    target_maximum = (
        document_minimum
        + document_size * global_scale
        - (document_maximum - source_maximum)
        if fixed_high
        else document_minimum + global_scale * (source_maximum - document_minimum)
    )
    effective_scale = (target_maximum - target_minimum) / source_size
    translation = target_minimum - effective_scale * source_minimum
    return (
        effective_scale / global_scale,
        translation * unit_scale / global_scale,
    )


def _correct_resized_axis(
    corrections,
    layer_bounds,
    partial_fixed,
    *,
    axis: int,
    document_minimum: float,
    document_maximum: float,
    document_size: float,
    global_scale: float,
    unit_scale: float,
) -> None:
    """Apply fixed-hardware and stretchable-panel corrections to one axis."""
    center = (document_minimum + document_maximum) / 2.0
    fixed_low = any(
        (layer_bounds[layer][0][axis] + layer_bounds[layer][1][axis]) / 2.0 <= center
        for layer in partial_fixed
    )
    fixed_high = any(
        (layer_bounds[layer][0][axis] + layer_bounds[layer][1][axis]) / 2.0 > center
        for layer in partial_fixed
    )
    for layer, bounds in layer_bounds.items():
        if layer in partial_fixed:
            result = _fixed_axis_correction(
                bounds,
                axis=axis,
                center=center,
                document_minimum=document_minimum,
                document_maximum=document_maximum,
                global_scale=global_scale,
                unit_scale=unit_scale,
            )
        else:
            result = _stretch_axis_correction(
                bounds,
                axis=axis,
                fixed_low=fixed_low,
                fixed_high=fixed_high,
                document_minimum=document_minimum,
                document_maximum=document_maximum,
                document_size=document_size,
                global_scale=global_scale,
                unit_scale=unit_scale,
            )
        if result is not None:
            corrections[layer][0][axis], corrections[layer][1][axis] = result


def _layer_resize_corrections(
    package: PContentPackage | None,
    geometry_scale: tuple[float, float, float],
) -> dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]]:
    """Compute per-layer corrections that keep fixed hardware from stretching."""
    if package is None or package.document is None:
        return {}
    fixed_candidates = _fixed_component_layers(package)
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
        _correct_resized_axis(
            corrections,
            layer_bounds,
            partial_fixed,
            axis=axis,
            document_minimum=document_minimum[axis],
            document_maximum=document_maximum[axis],
            document_size=document_size,
            global_scale=global_scale,
            unit_scale=unit_scale,
        )
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
    """Create the first material from a resolved material specification package."""
    document = package.document
    if document is None or not document.materials:
        return None
    key = (id(package), 0)
    material = cache.get(key)
    if material is None:
        material = create_material(document.materials[0], 0, package)
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
    object_parents: dict[bpy.types.Object, TransformNode],
    geometry_scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
):
    """Create or reuse one document's materials, meshes, and primitive records."""
    cache_key = id(package) if package is not None else id(document)
    meshes_by_layer = cache.get(cache_key)
    if meshes_by_layer is None:
        materials = []
        material_owner = package if package is not None else document
        for index, source_material in enumerate(document.materials):
            material_key = (id(material_owner), index)
            material = material_cache.get(material_key)
            if material is None:
                material = create_material(source_material, index, package)
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
        object_parents=object_parents,
    )
