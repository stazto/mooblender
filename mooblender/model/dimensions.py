"""Dimension helpers for PContent entities and aggregate geometry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .expressions import evaluate_expression
from .scene import PmobDocument, Primitive
from .transforms import transform_point_row_vector

Dimension3 = tuple[float, float, float]
Bounds3 = tuple[Dimension3, Dimension3]
_FIELDS = ("Width", "Depth", "Height")


@dataclass(frozen=True, slots=True)
class ConfigurableDimension:
    """One user-editable insertion dimension observed in PContent metadata."""

    axis: int
    name: str
    default: float
    minimum: float
    maximum: float


_CONFIGURABLE_AXES = (
    ("X", "Width", "Largura"),
    ("Y", "Depth", "Profundidade"),
    ("Z", "Height", "Altura"),
)


def dimension_variables(
    dimensions: Dimension3,
    *,
    parent: Dimension3 | None = None,
) -> dict[str, float]:
    """Return the short and long dimension names used by Mooble formulas."""

    width, depth, height = dimensions
    values = {
        "W": width,
        "D": depth,
        "H": height,
        "WIDTH": width,
        "DEPTH": depth,
        "HEIGHT": height,
    }
    if parent is not None:
        parent_width, parent_depth, parent_height = parent
        values.update(
            PW=parent_width,
            PD=parent_depth,
            PH=parent_height,
            PARENTWIDTH=parent_width,
            PARENTDEPTH=parent_depth,
            PARENTHEIGHT=parent_height,
        )
    return values


def _dimension_value(value: object, coordinate: str, field: str) -> float:
    if not isinstance(value, Mapping):
        return 0.0
    return evaluate_expression(value.get(coordinate, value.get(field)))


def configurable_dimensions(
    properties: Mapping[str, object],
    *,
    defaults: Dimension3 | None = None,
) -> tuple[ConfigurableDimension, ...]:
    """Return axes whose observed ``InsertDimension`` range is editable.

    Mooble's catalog payload uses X/Y/Z for these limits, while the decompiled
    domain model names the same values Width/Depth/Height. Supporting both
    spellings keeps this parser tied to semantics instead of one serializer.
    Values remain in Promob millimetres at this Blender-independent boundary.
    """

    insertion = properties.get("InsertDimension")
    if not isinstance(insertion, Mapping):
        return ()
    minimum = insertion.get("Min")
    maximum = insertion.get("Max")
    current = defaults or property_dimensions(properties)
    result = []
    for axis, (coordinate, field, name) in enumerate(_CONFIGURABLE_AXES):
        lower = _dimension_value(minimum, coordinate, field)
        upper = _dimension_value(maximum, coordinate, field)
        default = current[axis]
        if default > 0.0 and upper > lower:
            result.append(
                ConfigurableDimension(
                    axis=axis,
                    name=name,
                    default=default,
                    minimum=lower,
                    maximum=upper,
                )
            )
    return tuple(result)


def property_dimensions(
    properties: Mapping[str, object],
    field: str = "Dimension",
    *,
    variables: Mapping[str, float | bool] | None = None,
    fallback: Dimension3 = (0.0, 0.0, 0.0),
) -> Dimension3:
    raw = properties.get(field, {})
    if not isinstance(raw, dict):
        return fallback
    return tuple(
        evaluate_expression(raw.get(name), variables, default=fallback[index])
        for index, name in enumerate(_FIELDS)
    )  # type: ignore[return-value]


def bounding_box_dimensions(properties: Mapping[str, object]) -> Dimension3:
    raw = properties.get("GeometryBoundingBox", {})
    if not isinstance(raw, dict):
        return (0.0, 0.0, 0.0)
    minimum = raw.get("Min", {})
    maximum = raw.get("Max", {})
    if not isinstance(minimum, dict) or not isinstance(maximum, dict):
        return (0.0, 0.0, 0.0)
    return tuple(
        max(
            0.0,
            evaluate_expression(maximum.get(axis))
            - evaluate_expression(minimum.get(axis)),
        )
        for axis in ("X", "Y", "Z")
    )  # type: ignore[return-value]


def _document_points_by_layer(
    document: PmobDocument | None,
) -> dict[str, list[tuple[float, float, float]]]:
    if document is None:
        return {}
    layers = {layer.name.casefold(): layer for layer in document.layers}
    points: dict[str, list[tuple[float, float, float]]] = {
        name: [] for name in layers
    }

    def append_layer(layer_ref: str, transforms) -> None:
        layer_name = layer_ref.casefold()
        layer = layers.get(layer_name)
        if layer is None:
            return
        for mesh in layer.meshes:
            for source_point in mesh.vertices:
                point = source_point
                for matrix in reversed(transforms):
                    point = transform_point_row_vector(point, matrix)
                points[layer_name].append(point)

    def visit(primitive: Primitive, transforms=()) -> None:
        current = transforms + (primitive.matrix,)
        if primitive.layer_ref:
            append_layer(primitive.layer_ref, current)
        for child in primitive.children:
            visit(child, current)

    if document.primitive is not None:
        visit(document.primitive)
    else:
        for layer in document.layers:
            append_layer(layer.name, ())
    return points


def _point_dimensions(points: list[tuple[float, float, float]]) -> Dimension3:
    if not points:
        return (0.0, 0.0, 0.0)
    minimum = tuple(min(point[index] for point in points) for index in range(3))
    maximum = tuple(max(point[index] for point in points) for index in range(3))
    return tuple(maximum[index] - minimum[index] for index in range(3))  # type: ignore[return-value]


def _point_bounds(points: list[tuple[float, float, float]]) -> Bounds3 | None:
    if not points:
        return None
    return (
        tuple(min(point[index] for point in points) for index in range(3)),
        tuple(max(point[index] for point in points) for index in range(3)),
    )  # type: ignore[return-value]


def document_geometry_dimensions(document: PmobDocument | None) -> Dimension3:
    """Measure PMob geometry after applying its serialized primitive transforms."""

    points_by_layer = _document_points_by_layer(document)
    return _point_dimensions(
        [point for points in points_by_layer.values() for point in points]
    )


def document_layer_dimensions(document: PmobDocument | None) -> dict[str, Dimension3]:
    """Measure each PMob layer after applying its primitive transforms."""

    return {
        name: _point_dimensions(points)
        for name, points in _document_points_by_layer(document).items()
    }


def document_layer_bounds(document: PmobDocument | None) -> dict[str, Bounds3]:
    """Return transformed minimum/maximum coordinates for each PMob layer."""

    result = {}
    for name, points in _document_points_by_layer(document).items():
        bounds = _point_bounds(points)
        if bounds is not None:
            result[name] = bounds
    return result


def serialized_geometry_dimensions(
    properties: Mapping[str, object],
    *,
    document: PmobDocument | None = None,
    fallback: Dimension3 = (0.0, 0.0, 0.0),
) -> Dimension3:
    """Return the dimensions represented by the serialized PMob geometry.

    Parametric entities distinguish their logical ``Dimension`` from the PMob's
    current ``DrawingDimension``. Aggregate target dimensions must scale from
    the latter (or its geometry bounding box), not from the logical defaults.
    """

    measured = document_geometry_dimensions(document)
    drawing = property_dimensions(properties, "DrawingDimension")
    bounds = bounding_box_dimensions(properties)
    return tuple(
        measured[index] if measured[index] > 0.0
        else drawing[index] if drawing[index] > 0.0
        else bounds[index] if bounds[index] > 0.0
        else fallback[index]
        for index in range(3)
    )  # type: ignore[return-value]
