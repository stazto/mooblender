"""Prepare PMob topology for corner-domain UVs and normals."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .scene import Mesh, Vector2, Vector3

POSITION_TOLERANCE = 1e-5
NORMAL_TOLERANCE = 1e-5
SMOOTH_ANGLE_RADIANS = math.radians(45.0)


@dataclass(slots=True)
class PreparedMesh:
    """Compact topology plus source data retained for every face corner."""

    vertices: list[Vector3]
    vertex_normals: list[Vector3]
    faces: list[tuple[int, int, int]]
    loop_normals: list[Vector3]
    loop_uvs: list[Vector2]
    removed_vertex_count: int


def _normalized(vector: Vector3) -> Vector3:
    length_squared = sum(component * component for component in vector)
    if length_squared <= 0.0:
        return (0.0, 0.0, 0.0)
    inverse_length = 1.0 / math.sqrt(length_squared)
    return (
        vector[0] * inverse_length,
        vector[1] * inverse_length,
        vector[2] * inverse_length,
    )


def _generated_normals(source: Mesh) -> list[Vector3]:
    """Generate area-weighted normals before PMob smoothing is applied."""

    accumulated = [[0.0, 0.0, 0.0] for _vertex in source.vertices]
    for first, second, third in source.triangle_faces():
        a = source.vertices[first]
        b = source.vertices[second]
        c = source.vertices[third]
        ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        normal = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        for index in (first, second, third):
            accumulated[index][0] += normal[0]
            accumulated[index][1] += normal[1]
            accumulated[index][2] += normal[2]

    return [_normalized(tuple(value)) for value in accumulated]


def _near(first: Vector3, second: Vector3, tolerance: float) -> bool:
    return sum((a - b) ** 2 for a, b in zip(first, second, strict=True)) <= tolerance**2


def _smooth_angle(first: Vector3, second: Vector3) -> bool:
    first = _normalized(first)
    second = _normalized(second)
    if first == (0.0, 0.0, 0.0) or second == (0.0, 0.0, 0.0):
        return False
    dot = sum(a * b for a, b in zip(first, second, strict=True))
    return dot > math.cos(SMOOTH_ANGLE_RADIANS)


def prepare_mesh(source: Mesh) -> PreparedMesh:
    """Weld matching PMob vertices without losing corner UVs or hard normals.

    PMob duplicates a position when a UV seam needs a second texture coordinate.
    Its smoothing groups make the copies share a normal. Blender stores both UVs
    and custom normals per face corner, so copies with matching positions and
    normals can share one Blender vertex. Copies with different normals remain
    separate and continue to define a hard edge.
    """

    has_source_normals = len(source.normals) == len(source.vertices)
    normals = (
        list(source.normals)
        if has_source_normals
        else _generated_normals(source)
    )
    used_indices = list(dict.fromkeys(source.indices))
    position_groups: list[list[int]] = []
    position_group_by_source: dict[int, int] = {}
    position_buckets: dict[tuple[int, int, int], list[int]] = {}
    for source_index in used_indices:
        position = source.vertices[source_index]
        bucket = tuple(round(component / POSITION_TOLERANCE) for component in position)
        group_index = None
        for x_offset in (-1, 0, 1):
            for y_offset in (-1, 0, 1):
                for z_offset in (-1, 0, 1):
                    nearby = (
                        bucket[0] + x_offset,
                        bucket[1] + y_offset,
                        bucket[2] + z_offset,
                    )
                    for candidate in position_buckets.get(nearby, ()):
                        representative = position_groups[candidate][0]
                        if _near(
                            position,
                            source.vertices[representative],
                            POSITION_TOLERANCE,
                        ):
                            group_index = candidate
                            break
                    if group_index is not None:
                        break
                if group_index is not None:
                    break
            if group_index is not None:
                break
        if group_index is None:
            group_index = len(position_groups)
            position_groups.append([])
            position_buckets.setdefault(bucket, []).append(group_index)
        position_groups[group_index].append(source_index)
        position_group_by_source[source_index] = group_index

    parents = {index: index for index in used_indices}

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    for group in position_groups:
        for offset, first in enumerate(group):
            for second in group[offset + 1:]:
                compatible = (
                    _near(normals[first], normals[second], NORMAL_TOLERANCE)
                    if has_source_normals
                    else _smooth_angle(normals[first], normals[second])
                )
                if compatible:
                    union(first, second)

    used_set = set(used_indices)
    for group in source.smooth_groups:
        members = [index for index in group if index in used_set]
        if not members:
            continue
        first = members[0]
        first_position_group = position_group_by_source[first]
        for second in members[1:]:
            if position_group_by_source[second] == first_position_group:
                union(first, second)

    members_by_root: dict[int, list[int]] = {}
    for index in used_indices:
        members_by_root.setdefault(find(index), []).append(index)
    normal_by_root = {
        root: _normalized(tuple(
            sum(normals[index][axis] for index in members) for axis in range(3)
        ))
        for root, members in members_by_root.items()
    }

    compact_vertices: list[Vector3] = []
    compact_normals: list[Vector3] = []
    compact_by_root: dict[int, int] = {}
    original_to_compact: dict[int, int] = {}
    for source_index in used_indices:
        root = find(source_index)
        if root not in compact_by_root:
            compact_by_root[root] = len(compact_vertices)
            compact_vertices.append(source.vertices[source_index])
            compact_normals.append(normal_by_root[root])
        original_to_compact[source_index] = compact_by_root[root]

    compact_indices = [original_to_compact[index] for index in source.indices]
    faces = [
        (
            compact_indices[index],
            compact_indices[index + 1],
            compact_indices[index + 2],
        )
        for index in range(0, len(compact_indices), 3)
    ]
    return PreparedMesh(
        vertices=compact_vertices,
        vertex_normals=compact_normals,
        faces=faces,
        loop_normals=[normal_by_root[find(index)] for index in source.indices],
        loop_uvs=[source.texture_coordinates[index] for index in source.indices]
        if source.texture_coordinates
        else [],
        removed_vertex_count=len(source.vertices) - len(compact_vertices),
    )
