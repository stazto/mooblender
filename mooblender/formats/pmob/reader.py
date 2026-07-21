"""Convert PMob records into the shared scene model."""

from __future__ import annotations

import struct
from collections.abc import Iterable

from ...model.scene import (
    IDENTITY_MATRIX,
    Animation,
    Material,
    Matrix4,
    Mesh,
    PmobDocument,
    Primitive,
    PrimitiveType,
    SceneLayer,
)
from .content_types import ContentType
from .structure import PmobStructureError, Record, read_structure


class PmobFormatError(ValueError):
    pass


def _require_size(payload: bytes, multiple: int, label: str) -> None:
    if len(payload) % multiple:
        raise PmobFormatError(
            f"{label} payload has {len(payload)} bytes; expected a multiple of {multiple}"
        )


def _ints(payload: bytes) -> list[int]:
    _require_size(payload, 4, "integer list")
    return list(struct.unpack(f"<{len(payload) // 4}i", payload))


def _floats(payload: bytes) -> list[float]:
    _require_size(payload, 4, "float list")
    return list(struct.unpack(f"<{len(payload) // 4}f", payload))


def _vectors(payload: bytes, width: int) -> list[tuple[float, ...]]:
    stride = width * 4
    _require_size(payload, stride, f"{width}D vector list")
    values = _floats(payload)
    return [tuple(values[index:index + width]) for index in range(0, len(values), width)]


def _matrix(payload: bytes) -> Matrix4:
    if len(payload) != 64:
        raise PmobFormatError(f"matrix has {len(payload)} bytes; expected 64")
    return tuple(struct.unpack("<16f", payload))


def _matrices(payload: bytes) -> list[Matrix4]:
    _require_size(payload, 64, "matrix list")
    return [_matrix(payload[index:index + 64]) for index in range(0, len(payload), 64)]


def _int(payload: bytes) -> int:
    if len(payload) != 4:
        raise PmobFormatError(f"integer has {len(payload)} bytes; expected 4")
    return struct.unpack("<i", payload)[0]


def _float(payload: bytes) -> float:
    if len(payload) != 4:
        raise PmobFormatError(f"float has {len(payload)} bytes; expected 4")
    return struct.unpack("<f", payload)[0]


def _string(payload: bytes) -> str:
    if len(payload) % 2:
        raise PmobFormatError("UTF-16LE string has an odd byte length")
    return payload.decode("utf-16-le").rstrip("\x00")


def _color(payload: bytes) -> tuple[int, int, int, int]:
    if len(payload) != 4:
        raise PmobFormatError(f"color has {len(payload)} bytes; expected 4")
    return tuple(payload)  # type: ignore[return-value]


def _children(record: Record, kind: ContentType) -> Iterable[Record]:
    return (child for child in record.children if child.type_id == int(kind))


def _first(record: Record, kind: ContentType) -> Record | None:
    return next(_children(record, kind), None)


def _parse_animation(record: Record) -> Animation:
    animation = Animation()
    for child in record.children:
        if child.type_id == ContentType.ANIMATION_TIME_LIST:
            animation.times = _floats(child.payload)
        elif child.type_id == ContentType.ANIMATION_TRANSFORM_LIST:
            animation.transforms = _matrices(child.payload)
    return animation


def _parse_primitive(record: Record) -> Primitive:
    primitive = Primitive()
    for child in record.children:
        kind = child.type_id
        if kind == ContentType.NAME:
            primitive.name = _string(child.payload)
        elif kind == ContentType.MATRIX:
            primitive.matrix = _matrix(child.payload)
        elif kind == ContentType.PRIMITIVE_TYPE:
            value = _int(child.payload)
            primitive.kind = PrimitiveType(value) if value in (0, 1) else None
        elif kind == ContentType.LAYER_REF:
            primitive.layer_ref = _string(child.payload)
        elif kind == ContentType.ANIMATION:
            primitive.animation = _parse_animation(child)
        elif kind == ContentType.PRIMITIVES_LIST:
            primitive.children = [
                _parse_primitive(grandchild)
                for grandchild in child.children
                if grandchild.type_id == ContentType.PRIMITIVE
            ]
    return primitive


def _parse_mesh(record: Record) -> Mesh:
    mesh = Mesh()
    for child in record.children:
        kind = child.type_id
        if kind == ContentType.MATERIAL_ID:
            mesh.material_id = _int(child.payload)
        elif kind == ContentType.VERTICES:
            mesh.vertices = _vectors(child.payload, 3)  # type: ignore[assignment]
        elif kind == ContentType.INDICES:
            mesh.indices = _ints(child.payload)
        elif kind == ContentType.NORMALS:
            mesh.normals = _vectors(child.payload, 3)  # type: ignore[assignment]
        elif kind == ContentType.TEXT_COORDS:
            mesh.texture_coordinates = _vectors(child.payload, 2)  # type: ignore[assignment]
        elif kind == ContentType.SMOOTH_GROUPS:
            mesh.smooth_groups = _ints(child.payload)
        elif kind == ContentType.LINE_INDICES:
            mesh.line_indices = _ints(child.payload)
        elif kind == ContentType.MESH_SOURCE_TYPE:
            mesh.source_type = _int(child.payload)

    if len(mesh.indices) % 3:
        raise PmobFormatError("mesh index count is not divisible by three")
    if any(index < 0 or index >= len(mesh.vertices) for index in mesh.indices):
        raise PmobFormatError("mesh contains an out-of-range vertex index")
    if mesh.texture_coordinates and len(mesh.texture_coordinates) != len(mesh.vertices):
        raise PmobFormatError("per-vertex UV count does not match vertex count")
    return mesh


def _parse_layer(record: Record) -> SceneLayer:
    layer = SceneLayer()
    name = _first(record, ContentType.NAME)
    if name:
        layer.name = _string(name.payload)
    mesh_list = _first(record, ContentType.MESH_LIST)
    if mesh_list:
        layer.meshes = [
            _parse_mesh(child)
            for child in mesh_list.children
            if child.type_id == ContentType.MESH
        ]
    return layer


def _parse_material(record: Record) -> Material:
    material = Material()
    extras: dict[str, object] = {}
    for child in record.children:
        kind = child.type_id
        if kind == ContentType.NAME:
            material.name = _string(child.payload)
        elif kind == ContentType.COLOR:
            material.color = _color(child.payload)
        elif kind == ContentType.SPECULAR_COLOR:
            material.specular_color = _color(child.payload)
        elif kind == ContentType.AMBIENT_INTENSITY:
            material.ambient = _float(child.payload)
        elif kind == ContentType.SPECULAR_POWER:
            material.specular_power = _float(child.payload)
        elif kind == ContentType.REFLECTION_MAX:
            material.reflection_max = _float(child.payload)
        elif kind == ContentType.REFLECTION_MIN:
            material.reflection_min = _float(child.payload)
        elif kind == ContentType.OPACITY:
            material.opacity = _float(child.payload)
        elif kind == ContentType.METALLIC:
            material.metallic = _float(child.payload)
        elif kind == ContentType.ROUGHNESS:
            material.roughness = _float(child.payload)
        elif kind == ContentType.DIFFUSE_TEXTURE:
            material.diffuse_texture = _string(child.payload)
        elif kind == ContentType.SPECULAR_TEXTURE:
            material.specular_texture = _string(child.payload)
        elif kind == ContentType.NORMAL_TEXTURE:
            material.normal_texture = _string(child.payload)
        elif kind == ContentType.MAPPING_TYPE:
            material.mapping_type = _int(child.payload)
        elif kind == ContentType.MAPPING_SCALE:
            material.mapping_scale = _vectors(child.payload, 2)[0]  # type: ignore[assignment]
        elif kind == ContentType.MAPPING_NUMBER:
            material.mapping_number = _vectors(child.payload, 2)[0]  # type: ignore[assignment]
        elif kind == ContentType.MAPPING_ROTATION:
            material.mapping_rotation = _float(child.payload)
        elif kind in {
            ContentType.BORDER_WIDTH,
            ContentType.DIFFUSE,
            ContentType.CRAND,
            ContentType.EMISSION,
            ContentType.TRANSLUCENCY,
            ContentType.FRESNEL_TERM,
            ContentType.REFRACTION_FACTOR,
        }:
            extras[ContentType(kind).name.lower()] = _float(child.payload)
        elif kind in {
            ContentType.MIRROR,
            ContentType.CONSERVE_ENERGY,
            ContentType.APPLY_TEXTURE_IN_FRAMES,
        }:
            if len(child.payload) != 1:
                raise PmobFormatError("boolean material field is not one byte")
            extras[ContentType(kind).name.lower()] = bool(child.payload[0])
        elif kind == ContentType.BORDER_COLOR:
            extras["border_color"] = _color(child.payload)
    material.extras = extras
    return material


def _collect_unknown_types(root: Record) -> set[int]:
    unknown: set[int] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current.known_type is None:
            unknown.add(current.type_id)
        stack.extend(current.children)
    return unknown


def read_pmob(data: bytes) -> PmobDocument:
    try:
        root = read_structure(data)
    except PmobStructureError as error:
        raise PmobFormatError(str(error)) from error

    document = PmobDocument(unknown_record_types=_collect_unknown_types(root))
    for child in root.children:
        kind = child.type_id
        if kind == ContentType.NAME:
            document.name = _string(child.payload)
        elif kind == ContentType.VERSION:
            document.version = _int(child.payload)
        elif kind == ContentType.PRIMITIVE:
            document.primitive = _parse_primitive(child)
        elif kind == ContentType.LAYER_LIST:
            document.layers = [
                _parse_layer(layer)
                for layer in child.children
                if layer.type_id == ContentType.LAYER
            ]
        elif kind == ContentType.MATERIAL_LIST:
            document.materials = [
                _parse_material(material)
                for material in child.children
                if material.type_id == ContentType.MATERIAL
            ]

    if document.version == 0:
        for material in document.materials:
            _, red, green, blue = material.specular_color
            material.specular_power = (red + green + blue) / 765.0

    if document.primitive is None:
        document.primitive = Primitive(
            name="root",
            kind=PrimitiveType.GROUP,
            matrix=IDENTITY_MATRIX,
            children=[
                Primitive(
                    name=layer.name,
                    kind=PrimitiveType.LAYER,
                    layer_ref=layer.name,
                )
                for layer in document.layers
            ],
        )
    return document
