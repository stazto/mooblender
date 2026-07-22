"""Blender-independent conversion of observed Promob opening services."""

from __future__ import annotations

import math
from collections.abc import Mapping

from .dimensions import dimension_variables
from .expressions import evaluate_expression


def service_name(service: Mapping[str, object], fallback: str) -> str:
    """Return the component name shown by Mooble, preferring pt-BR metadata."""

    localizations = service.get("Localizations", ())
    if isinstance(localizations, list):
        for localization in localizations:
            if (
                isinstance(localization, Mapping)
                and str(localization.get("Id", "")).casefold() == "pt-br"
                and str(localization.get("Name", "")).strip()
            ):
                return str(localization["Name"]).strip()
    description = str(service.get("Description", "")).strip()
    return description or fallback


def control_name(service: Mapping[str, object], fallback: str) -> str:
    """Return a recognizable modifier label for one opening component."""

    name = service_name(service, fallback)
    service_type = str(service.get("Type", "")).strip()
    kind = service_type.casefold()
    descriptive_terms = {
        "door": ("door", "porta"),
        "drawer": ("drawer", "gaveta"),
    }.get(kind, ())
    if not descriptive_terms or any(term in name.casefold() for term in descriptive_terms):
        return name
    return f"{service_type}: {name}"


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

    variables: dict[str, float | bool] = {
        **dimension_variables(dimensions),
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
