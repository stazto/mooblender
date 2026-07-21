"""Small immutable-ish domain objects produced by Promob format readers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

Vector2 = tuple[float, float]
Vector3 = tuple[float, float, float]
Matrix4 = tuple[float, ...]
Color = tuple[int, int, int, int]  # A, R, G, B

IDENTITY_MATRIX: Matrix4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


class PrimitiveType(IntEnum):
    LAYER = 0
    GROUP = 1


@dataclass(slots=True)
class Animation:
    times: list[float] = field(default_factory=list)
    transforms: list[Matrix4] = field(default_factory=list)


@dataclass(slots=True)
class Primitive:
    name: str = ""
    kind: PrimitiveType | None = None
    layer_ref: str = ""
    matrix: Matrix4 = IDENTITY_MATRIX
    children: list[Primitive] = field(default_factory=list)
    animation: Animation | None = None


@dataclass(slots=True)
class Mesh:
    vertices: list[Vector3] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)
    normals: list[Vector3] = field(default_factory=list)
    texture_coordinates: list[Vector2] = field(default_factory=list)
    smooth_groups: list[int] = field(default_factory=list)
    material_id: int = 0
    line_indices: list[int] = field(default_factory=list)
    source_type: int | None = None

    def triangle_faces(self) -> list[tuple[int, int, int]]:
        return [
            (self.indices[index], self.indices[index + 1], self.indices[index + 2])
            for index in range(0, len(self.indices), 3)
        ]


@dataclass(slots=True)
class SceneLayer:
    name: str = ""
    meshes: list[Mesh] = field(default_factory=list)


@dataclass(slots=True)
class Material:
    name: str = ""
    color: Color = (255, 0, 0, 0)
    specular_color: Color = (255, 0, 0, 0)
    ambient: float = 0.0
    specular_power: float = 0.0
    reflection_max: float | None = None
    reflection_min: float | None = None
    opacity: float = 1.0
    metallic: float | None = None
    roughness: float | None = None
    diffuse_texture: str | None = None
    specular_texture: str | None = None
    normal_texture: str | None = None
    mapping_type: int | None = None
    mapping_scale: Vector2 | None = None
    mapping_number: Vector2 | None = None
    mapping_rotation: float | None = None
    extras: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class PmobDocument:
    name: str = ""
    version: int = 0
    primitive: Primitive | None = None
    layers: list[SceneLayer] = field(default_factory=list)
    materials: list[Material] = field(default_factory=list)
    unknown_record_types: set[int] = field(default_factory=set)

    @property
    def unit_scale_to_meters(self) -> float:
        """Current evidence indicates PMob geometry is stored in millimetres."""

        return 0.001
