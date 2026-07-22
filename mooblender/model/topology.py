"""Prepare PMob topology for Blender's corner-domain UVs and normals.

PMob often duplicates vertices at UV seams. The preparation pipeline groups
coincident positions, gives serialized normals and smoothing groups precedence
over its angular fallback, and finally compacts indices while keeping UVs and
normals on the original face-corner sequence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product

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
    """Return a unit vector, preserving a zero vector as zero."""
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
    """Compare two points or vectors with an Euclidean tolerance."""
    return sum((a - b) ** 2 for a, b in zip(first, second, strict=True)) <= tolerance**2


def _smooth_angle(first: Vector3, second: Vector3) -> bool:
    """Return whether generated normals belong to the same smooth fan."""
    first = _normalized(first)
    second = _normalized(second)
    if first == (0.0, 0.0, 0.0) or second == (0.0, 0.0, 0.0):
        return False
    dot = sum(a * b for a, b in zip(first, second, strict=True))
    return dot > math.cos(SMOOTH_ANGLE_RADIANS)


@dataclass(slots=True)
class _DisjointSet:
    """Track source vertices that may safely share one Blender vertex."""

    parents: dict[int, int]

    @classmethod
    def from_indices(cls, indices: list[int]) -> _DisjointSet:
        """Create one initially independent set for every used source index."""
        return cls({index: index for index in indices})

    def find(self, index: int) -> int:
        """Return a set root while shortening future lookup paths."""
        while self.parents[index] != index:
            self.parents[index] = self.parents[self.parents[index]]
            index = self.parents[index]
        return index

    def union(self, first: int, second: int) -> None:
        """Merge two compatible source-vertex sets."""
        first_root = self.find(first)
        second_root = self.find(second)
        if first_root != second_root:
            self.parents[second_root] = first_root


def _position_bucket(position: Vector3) -> tuple[int, int, int]:
    """Quantize a position for fast tolerance-neighbor lookup."""
    return tuple(round(component / POSITION_TOLERANCE) for component in position)


def _matching_position_group(
    source: Mesh,
    position: Vector3,
    bucket: tuple[int, int, int],
    groups: list[list[int]],
    buckets: dict[tuple[int, int, int], list[int]],
) -> int | None:
    """Find an existing group in the current or an adjacent tolerance bucket."""
    for offsets in product((-1, 0, 1), repeat=3):
        nearby = tuple(value + offset for value, offset in zip(bucket, offsets, strict=True))
        for candidate in buckets.get(nearby, ()):
            representative = groups[candidate][0]
            if _near(position, source.vertices[representative], POSITION_TOLERANCE):
                return candidate
    return None


def _group_coincident_positions(
    source: Mesh,
    used_indices: list[int],
) -> tuple[list[list[int]], dict[int, int]]:
    """Group used source vertices that occupy the same tolerant position."""
    groups: list[list[int]] = []
    group_by_source: dict[int, int] = {}
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for source_index in used_indices:
        position = source.vertices[source_index]
        bucket = _position_bucket(position)
        group_index = _matching_position_group(source, position, bucket, groups, buckets)
        if group_index is None:
            group_index = len(groups)
            groups.append([])
            buckets.setdefault(bucket, []).append(group_index)
        groups[group_index].append(source_index)
        group_by_source[source_index] = group_index
    return groups, group_by_source


def _merge_compatible_normals(
    groups: list[list[int]],
    normals: list[Vector3],
    *,
    source_normals: bool,
    vertices: _DisjointSet,
) -> None:
    """Merge coincident vertices only when their normal fans are compatible."""
    for group in groups:
        for offset, first in enumerate(group):
            for second in group[offset + 1:]:
                compatible = (
                    _near(normals[first], normals[second], NORMAL_TOLERANCE)
                    if source_normals
                    else _smooth_angle(normals[first], normals[second])
                )
                if compatible:
                    vertices.union(first, second)


def _merge_explicit_smoothing_groups(
    source: Mesh,
    used_indices: list[int],
    position_group_by_source: dict[int, int],
    vertices: _DisjointSet,
) -> None:
    """Apply PMob smoothing groups without joining different positions."""
    used = set(used_indices)
    for group in source.smooth_groups:
        members = [index for index in group if index in used]
        if not members:
            continue
        first = members[0]
        position_group = position_group_by_source[first]
        for second in members[1:]:
            if position_group_by_source[second] == position_group:
                vertices.union(first, second)


def _averaged_normals(
    used_indices: list[int],
    normals: list[Vector3],
    vertices: _DisjointSet,
) -> dict[int, Vector3]:
    """Average source normals for each welded vertex set."""
    members_by_root: dict[int, list[int]] = {}
    for index in used_indices:
        members_by_root.setdefault(vertices.find(index), []).append(index)
    return {
        root: _normalized(
            tuple(sum(normals[index][axis] for index in members) for axis in range(3))
        )
        for root, members in members_by_root.items()
    }


def _compact_vertices(
    source: Mesh,
    used_indices: list[int],
    normals_by_root: dict[int, Vector3],
    vertices: _DisjointSet,
) -> tuple[list[Vector3], list[Vector3], dict[int, int]]:
    """Build compact Blender vertices and a source-to-compact index map."""
    compact_vertices: list[Vector3] = []
    compact_normals: list[Vector3] = []
    compact_by_root: dict[int, int] = {}
    original_to_compact: dict[int, int] = {}
    for source_index in used_indices:
        root = vertices.find(source_index)
        if root not in compact_by_root:
            compact_by_root[root] = len(compact_vertices)
            compact_vertices.append(source.vertices[source_index])
            compact_normals.append(normals_by_root[root])
        original_to_compact[source_index] = compact_by_root[root]
    return compact_vertices, compact_normals, original_to_compact


def prepare_mesh(source: Mesh) -> PreparedMesh:
    """Weld matching PMob vertices without losing corner UVs or hard normals.

    PMob duplicates a position when a UV seam needs a second texture coordinate.
    Blender stores both UVs and custom normals per face corner, so compatible
    copies can share one Blender vertex. Complete serialized normals are the
    strongest evidence. Otherwise, explicit smoothing groups are authoritative:
    a coincident pair omitted from them remains a hard edge. The 45-degree test
    is only a fallback for meshes which provide neither form of smoothing data.
    """
    # Phase 1: establish one normal per source vertex. Generated area-weighted
    # normals are used only when PMob did not serialize a complete normal array.
    has_source_normals = len(source.normals) == len(source.vertices)
    normals = list(source.normals) if has_source_normals else _generated_normals(source)
    used_indices = list(dict.fromkeys(source.indices))
    # Phase 2: spatial bucketing limits expensive tolerance comparisons to the
    # 27 neighboring cells instead of comparing every vertex with every other.
    position_groups, group_by_source = _group_coincident_positions(source, used_indices)
    vertices = _DisjointSet.from_indices(used_indices)
    if has_source_normals:
        # Serialized normals preserve both smooth UV seams and intentional hard
        # edges. A smoothing-group entry must not override conflicting normals.
        _merge_compatible_normals(
            position_groups,
            normals,
            source_normals=True,
            vertices=vertices,
        )
    elif source.smooth_groups:
        # The presence of groups makes their omissions meaningful. Applying the
        # angle heuristic here used to over-weld unlisted hard-edge duplicates.
        _merge_explicit_smoothing_groups(source, used_indices, group_by_source, vertices)
    else:
        # Some legacy meshes omit all smoothing metadata. Retain the observed
        # producer threshold as a conservative compatibility fallback for them.
        _merge_compatible_normals(
            position_groups,
            normals,
            source_normals=False,
            vertices=vertices,
        )
    # Phase 3: the disjoint-set roots define the exact welded topology. Corner
    # arrays below intentionally retain the original index order, preserving UV
    # seams even when their duplicate positions now share a Blender vertex.
    normal_by_root = _averaged_normals(used_indices, normals, vertices)
    compact_vertices, compact_normals, original_to_compact = _compact_vertices(
        source, used_indices, normal_by_root, vertices
    )

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
        loop_normals=[normal_by_root[vertices.find(index)] for index in source.indices],
        loop_uvs=[source.texture_coordinates[index] for index in source.indices]
        if source.texture_coordinates
        else [],
        removed_vertex_count=len(source.vertices) - len(compact_vertices),
    )
