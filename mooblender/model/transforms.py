"""Transform helpers for Promob's row-vector matrix convention."""

from __future__ import annotations

from .scene import Matrix4


def blender_matrix_rows(
    source: Matrix4,
    *,
    unit_scale: float = 0.001,
) -> tuple[tuple[float, float, float, float], ...]:
    """Transpose a Promob matrix for Blender and convert its translation.

    Promob/Mooble.Math3D multiplies row vectors and stores translation in
    M41/M42/M43. Blender multiplies column vectors and expects translation in
    the last column, so transposition preserves the transform. The linear 3x3
    part is intentionally not unit-scaled: observed PMob root transforms use a
    scale of 10 to convert centimetre-like mesh coordinates to millimetres.
    """
    if len(source) != 16:
        raise ValueError("a PMob transform must contain 16 values")
    return (
        (source[0], source[4], source[8], source[12] * unit_scale),
        (source[1], source[5], source[9], source[13] * unit_scale),
        (source[2], source[6], source[10], source[14] * unit_scale),
        (source[3], source[7], source[11], source[15]),
    )


def transform_point_row_vector(point: tuple[float, float, float], matrix: Matrix4):
    """Apply a source matrix using the convention confirmed in Mooble.Math3D."""
    x, y, z = point
    return (
        x * matrix[0] + y * matrix[4] + z * matrix[8] + matrix[12],
        x * matrix[1] + y * matrix[5] + z * matrix[9] + matrix[13],
        x * matrix[2] + y * matrix[6] + z * matrix[10] + matrix[14],
    )
