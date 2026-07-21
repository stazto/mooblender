"""Blender-independent conversion of observed Promob opening services."""

from __future__ import annotations

import math
from collections.abc import Mapping

from .expressions import evaluate_expression


def door_motion(
    service: Mapping[str, object],
    dimensions: tuple[float, float, float],
    *,
    inverted: bool,
) -> tuple[tuple[float, float, float], float]:
    """Return the Blender-local hinge and opening angle for a door service.

    Promob door expressions describe inverted entities in their already-mirrored
    coordinate space. Mooblender represents that inversion with a negative-X
    aggregate placement, so the hinge X and rotation handedness must be mapped
    back to the unmirrored child coordinates before creating the Blender pivot.
    """

    width, depth, height = dimensions
    variables: dict[str, float | bool] = {
        "W": width,
        "D": depth,
        "H": height,
        "I": inverted,
        "INVERTED": inverted,
    }
    pivot = [
        evaluate_expression(service.get(axis), variables)
        for axis in ("X", "Y", "Z")
    ]
    if inverted:
        pivot[0] *= -1.0

    maximum = evaluate_expression(service.get("Max"), variables)
    reverse = bool(evaluate_expression(service.get("Invert"), variables))
    direction = -1.0 if reverse else 1.0
    # Opening-service rotation uses Promob's row-vector handedness. Mirrored
    # aggregate placement reverses that handedness once more.
    direction *= -1.0
    if inverted:
        direction *= -1.0
    return (pivot[0], pivot[1], pivot[2]), math.radians(maximum) * direction
