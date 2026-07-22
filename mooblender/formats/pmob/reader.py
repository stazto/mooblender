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
    """Raised when PMob semantic fields are malformed or inconsistent."""


def _require_size(payload: bytes, multiple: int, label: str) -> None:
    """Require fixed-width payloads to contain only complete values."""
    if len(payload) % multiple:
        raise PmobFormatError(
            f"{label} payload has {len(payload)} bytes; expected a multiple of {multiple}"
        )


def _ints(payload: bytes) -> list[int]:
    """Decode a little-endian array of signed 32-bit integers."""
    _require_size(payload, 4, "integer list")
    return list(struct.unpack(f"<{len(payload) // 4}i", payload))


def _int_lists(payload: bytes) -> list[list[int]]:
    """Decode PMob's repeated ``count, count × int32`` list encoding."""
    groups = []
    offset = 0
    while offset < len(payload):
        if len(payload) - offset < 4:
            raise PmobFormatError("smoothing group is missing its vertex count")
        count = struct.unpack_from("<i", payload, offset)[0]
        offset += 4
        if count < 0:
            raise PmobFormatError("smoothing group has a negative vertex count")
        byte_count = count * 4
        if byte_count > len(payload) - offset:
            raise PmobFormatError("smoothing group extends past the end of its payload")
        groups.append(list(struct.unpack_from(f"<{count}i", payload, offset)))
        offset += byte_count
    return groups


def _floats(payload: bytes) -> list[float]:
    """Decode a little-endian array of 32-bit floating-point values."""
    _require_size(payload, 4, "float list")
    return list(struct.unpack(f"<{len(payload) // 4}f", payload))


def _vectors(payload: bytes, width: int) -> list[tuple[float, ...]]:
    """Group a flat float payload into fixed-width vectors."""
    stride = width * 4
    _require_size(payload, stride, f"{width}D vector list")
    values = _floats(payload)
    return [tuple(values[index:index + width]) for index in range(0, len(values), width)]


def _matrix(payload: bytes) -> Matrix4:
    """Decode one 4-by-4 single-precision transformation matrix."""
    if len(payload) != 64:
        raise PmobFormatError(f"matrix has {len(payload)} bytes; expected 64")
    return tuple(struct.unpack("<16f", payload))


def _matrices(payload: bytes) -> list[Matrix4]:
    """Decode a contiguous list of 4-by-4 transformation matrices."""
    _require_size(payload, 64, "matrix list")
    return [_matrix(payload[index:index + 64]) for index in range(0, len(payload), 64)]


def _int(payload: bytes) -> int:
    """Decode exactly one signed 32-bit integer."""
    if len(payload) != 4:
        raise PmobFormatError(f"integer has {len(payload)} bytes; expected 4")
    return struct.unpack("<i", payload)[0]


def _float(payload: bytes) -> float:
    """Decode exactly one 32-bit floating-point value."""
    if len(payload) != 4:
        raise PmobFormatError(f"float has {len(payload)} bytes; expected 4")
    return struct.unpack("<f", payload)[0]


def _string(payload: bytes) -> str:
    """Decode one null-padded UTF-16LE PMob string."""
    if len(payload) % 2:
        raise PmobFormatError("UTF-16LE string has an odd byte length")
    return payload.decode("utf-16-le").rstrip("\x00")


def _color(payload: bytes) -> tuple[int, int, int, int]:
    """Decode the four raw bytes of a PMob color value."""
    if len(payload) != 4:
        raise PmobFormatError(f"color has {len(payload)} bytes; expected 4")
    return tuple(payload)  # type: ignore[return-value]


def _children(record: Record, kind: ContentType) -> Iterable[Record]:
    """Iterate over direct children matching one known content type."""
    return (child for child in record.children if child.type_id == int(kind))


def _first(record: Record, kind: ContentType) -> Record | None:
    """Return the first direct child matching one content type."""
    return next(_children(record, kind), None)


def _parse_animation(record: Record) -> Animation:
    """Convert animation time and transformation child records."""
    animation = Animation()
    for child in record.children:
        if child.type_id == ContentType.ANIMATION_TIME_LIST:
            animation.times = _floats(child.payload)
        elif child.type_id == ContentType.ANIMATION_TRANSFORM_LIST:
            animation.transforms = _matrices(child.payload)
    return animation


def _parse_primitive(record: Record) -> Primitive:
    """Recursively convert a PMob primitive hierarchy."""
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
    """Decode and validate one neutral indexed mesh."""
    mesh = Mesh()
    integer_lists = {
        ContentType.INDICES: "indices",
        ContentType.LINE_INDICES: "line_indices",
    }
    vector_fields = {
        ContentType.VERTICES: ("vertices", 3),
        ContentType.NORMALS: ("normals", 3),
        ContentType.TEXT_COORDS: ("texture_coordinates", 2),
    }
    for child in record.children:
        kind = child.type_id
        if kind in vector_fields:
            field, width = vector_fields[kind]
            setattr(mesh, field, _vectors(child.payload, width))
        elif kind in integer_lists:
            setattr(mesh, integer_lists[kind], _ints(child.payload))
        elif kind == ContentType.SMOOTH_GROUPS:
            mesh.smooth_groups = _int_lists(child.payload)
        elif kind in {ContentType.MATERIAL_ID, ContentType.MESH_SOURCE_TYPE}:
            field = "material_id" if kind == ContentType.MATERIAL_ID else "source_type"
            setattr(mesh, field, _int(child.payload))

    _validate_mesh(mesh)
    return mesh


def _validate_mesh(mesh: Mesh) -> None:
    """Reject inconsistent indices and per-vertex fields before scene conversion."""
    if len(mesh.indices) % 3:
        raise PmobFormatError("mesh index count is not divisible by three")
    if any(index < 0 or index >= len(mesh.vertices) for index in mesh.indices):
        raise PmobFormatError("mesh contains an out-of-range vertex index")
    if mesh.texture_coordinates and len(mesh.texture_coordinates) != len(mesh.vertices):
        raise PmobFormatError("per-vertex UV count does not match vertex count")
    if mesh.normals and len(mesh.normals) != len(mesh.vertices):
        raise PmobFormatError("per-vertex normal count does not match vertex count")
    if any(
        index < 0 or index >= len(mesh.vertices)
        for group in mesh.smooth_groups
        for index in group
    ):
        raise PmobFormatError("smoothing group contains an out-of-range vertex index")


def _parse_layer(record: Record) -> SceneLayer:
    """Decode a named scene layer and all mesh records it owns."""
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


_MATERIAL_FIELDS = {
    ContentType.NAME: ("name", _string),
    ContentType.COLOR: ("color", _color),
    ContentType.SPECULAR_COLOR: ("specular_color", _color),
    ContentType.AMBIENT_INTENSITY: ("ambient", _float),
    ContentType.SPECULAR_POWER: ("specular_power", _float),
    ContentType.REFLECTION_MAX: ("reflection_max", _float),
    ContentType.REFLECTION_MIN: ("reflection_min", _float),
    ContentType.OPACITY: ("opacity", _float),
    ContentType.METALLIC: ("metallic", _float),
    ContentType.ROUGHNESS: ("roughness", _float),
    ContentType.DIFFUSE_TEXTURE: ("diffuse_texture", _string),
    ContentType.SPECULAR_TEXTURE: ("specular_texture", _string),
    ContentType.NORMAL_TEXTURE: ("normal_texture", _string),
    ContentType.MAPPING_TYPE: ("mapping_type", _int),
    ContentType.MAPPING_ROTATION: ("mapping_rotation", _float),
}
_MATERIAL_VECTOR_FIELDS = {
    ContentType.MAPPING_SCALE: "mapping_scale",
    ContentType.MAPPING_NUMBER: "mapping_number",
}
_MATERIAL_FLOAT_EXTRAS = {
    ContentType.BORDER_WIDTH,
    ContentType.DIFFUSE,
    ContentType.CRAND,
    ContentType.EMISSION,
    ContentType.TRANSLUCENCY,
    ContentType.FRESNEL_TERM,
    ContentType.REFRACTION_FACTOR,
}
_MATERIAL_BOOL_EXTRAS = {
    ContentType.MIRROR,
    ContentType.CONSERVE_ENERGY,
    ContentType.APPLY_TEXTURE_IN_FRAMES,
}


def _material_extra(child: Record) -> object | None:
    """Decode the heterogeneous material fields retained as neutral extras."""
    kind = child.type_id
    if kind in _MATERIAL_FLOAT_EXTRAS:
        return _float(child.payload)
    if kind in _MATERIAL_BOOL_EXTRAS:
        if len(child.payload) != 1:
            raise PmobFormatError("boolean material field is not one byte")
        return bool(child.payload[0])
    if kind == ContentType.BORDER_COLOR:
        return _color(child.payload)
    return None


def _parse_material(record: Record) -> Material:
    """Decode known material channels and retain supported extra fields."""
    material = Material()
    for child in record.children:
        kind = child.type_id
        if kind in _MATERIAL_FIELDS:
            field, decoder = _MATERIAL_FIELDS[kind]
            setattr(material, field, decoder(child.payload))
        elif kind in _MATERIAL_VECTOR_FIELDS:
            setattr(material, _MATERIAL_VECTOR_FIELDS[kind], _vectors(child.payload, 2)[0])
        else:
            extra = _material_extra(child)
            if extra is not None:
                material.extras[ContentType(kind).name.lower()] = extra
    return material


def _collect_unknown_types(root: Record) -> set[int]:
    """Collect unrecognized record IDs for format research and diagnostics."""
    unknown: set[int] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current.known_type is None:
            unknown.add(current.type_id)
        stack.extend(current.children)
    return unknown


def read_pmob(data: bytes) -> PmobDocument:
    """Decode one bounded PMob byte tree into the neutral scene model."""
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
