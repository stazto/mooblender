"""Convert neutral Promob packages into one Blender scene object.

The scene builder resolves package-level meaning: selected aggregates,
dimensions, visibility, placement, openings, and source mesh ownership.  It
stores that information in lightweight :class:`TransformNode` records and then
hands the result to :mod:`geometry_nodes`, which owns all procedural graph
construction.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import bpy
from mathutils import Matrix, Quaternion, Vector

from ..formats.pcontent import PContentPackage
from ..model.customization import (
    can_mirror,
    is_optional_aggregate,
    selected_model_information,
)
from ..model.dimensions import (
    configurable_dimensions,
    dimension_variables,
    property_dimensions,
    serialized_geometry_dimensions,
)
from ..model.expressions import evaluate_condition, evaluate_expression
from ..model.openings import control_name, door_motion
from ..model.scene import PmobDocument
from .geometry_nodes import (
    TransformControls,
    add_dimension_controls,
    add_material_options,
    add_mirror_control,
    add_visibility_controls,
    compile_hierarchy,
    create_controller,
    make_socket_single_value,
    record_transform_control,
    set_modifier_value,
)
from .mesh_builder import TransformNode, _document_root, _unique_name


def _aggregate_orientation(normal: Vector, rotation: float) -> Quaternion:
    """Build Promob's attachment frame without an ambiguous shortest-arc roll.

    Promob supplies the local positive-Z direction but not the remaining roll
    around that axis.  Projecting a stable global vertical reference onto the
    attachment plane produces deterministic X/Y axes for opposing side parts.
    """
    vertical_reference = Vector((0.0, 0.0, -1.0))
    local_x = vertical_reference - normal * vertical_reference.dot(normal)
    if local_x.length_squared <= 1e-12:
        # Top/bottom normals are parallel to the reference, so use global X as
        # the only non-degenerate deterministic fallback.
        local_x = Vector((1.0, 0.0, 0.0))
    else:
        local_x.normalize()
    local_y = normal.cross(local_x).normalized()
    orientation = Matrix(
        (
            tuple(local_x),
            tuple(local_y),
            tuple(normal),
        )
    ).transposed().to_quaternion()
    return orientation @ Quaternion((0.0, 0.0, 1.0), rotation)


def _raw_aggregate(package: PContentPackage, index: int) -> dict[str, object]:
    """Return one raw aggregate dictionary, or an empty mapping if malformed."""
    aggregates = package.properties.get("Aggregates", [])
    if not isinstance(aggregates, list) or not 0 <= index < len(aggregates):
        return {}
    value = aggregates[index]
    return value if isinstance(value, dict) else {}


def _apply_open_services(
    package: PContentPackage,
    *,
    prefix: tuple[int, ...],
    opening_control: Callable[[dict[str, object], str], tuple[Any, str]],
    aggregate_nodes: dict[tuple[int, ...], dict[str, Any]],
    controlled_paths: set[tuple[int, ...]],
    transform_controls: TransformControls,
) -> int:
    """Translate Promob door/drawer services into independent node controls."""
    services = package.properties.get("OpenServices", [])
    if not isinstance(services, list):
        return 0

    applied = 0
    for service in services:
        if not isinstance(service, dict):
            continue
        raw_path = service.get("AggregatePath", [])
        if not isinstance(raw_path, list):
            continue

        # Observed paths alternate aggregate-container index and selected
        # definition index.  For example, [2, 0] addresses aggregate 2 using
        # its first/default specification.  The resolved tree stores only the
        # container indices because only one selected definition has geometry.
        path = prefix + tuple(
            value
            for offset, value in enumerate(raw_path)
            if offset % 2 == 0 and isinstance(value, int)
        )
        if path in controlled_paths:
            # Several metadata records can describe the same movable part.
            # The first valid service owns its one user-facing control.
            continue
        aggregate = aggregate_nodes.get(path)
        if aggregate is None:
            continue

        motion = aggregate["motion"]
        content = aggregate["content"]
        dimensions = aggregate["dimensions"]
        width, depth, height = dimensions
        inverted = bool(aggregate["inverted"])
        variables: dict[str, float | bool] = {
            **dimension_variables(dimensions),
            "I": inverted,
            "INVERTED": inverted,
        }
        service_type = str(service.get("Type", "")).casefold()
        maximum = evaluate_expression(service.get("Max"), variables)

        if service_type == "door":
            pivot, angle = door_motion(
                service,
                (width, depth, height),
                inverted=inverted,
            )
            if abs(angle) <= 1e-12:
                continue
            socket, display_name = opening_control(
                service,
                aggregate["placement"].name,
            )

            # Rotate around a local pivot by translating into pivot space,
            # applying the controlled Z rotation, and translating back.
            motion.location = tuple(value * 0.001 for value in pivot)
            content.location = tuple(-value * 0.001 for value in pivot)
            record_transform_control(
                transform_controls,
                motion,
                "rotation",
                2,
                socket,
                factor=angle,
            )
        elif service_type == "drawer":
            # Promob's positive opening distance points opposite Blender's
            # cabinet-local Y direction.
            distance = maximum * -0.001
            if abs(distance) <= 1e-12:
                continue
            socket, display_name = opening_control(
                service,
                aggregate["placement"].name,
            )
            record_transform_control(
                transform_controls,
                motion,
                "translation",
                1,
                socket,
                factor=distance,
            )
        else:
            continue

        # Metadata remains on the temporary record while the hierarchy is
        # compiled.  It is useful for diagnostics but creates no Blender empty.
        motion["mooblender_open_service"] = display_name
        motion["mooblender_open_service_type"] = str(service.get("Type", ""))
        controlled_paths.add(path)
        applied += 1
    return applied


def _package_dimensions(
    package: PContentPackage,
    current_dimensions: tuple[float, float, float] | None,
) -> tuple[float, float, float]:
    """Choose the dimensions used by expressions in one package scope."""
    if current_dimensions is not None:
        return current_dimensions

    logical = property_dimensions(package.properties)
    drawing = property_dimensions(package.properties, "DrawingDimension")
    serialized = serialized_geometry_dimensions(
        package.properties,
        document=package.document,
        fallback=logical,
    )
    # Drawing dimensions describe the authored coordinate system and are most
    # reliable for parent formulas.  Missing axes fall back to logical metadata
    # and finally to measured serialized geometry.
    return tuple(
        authored
        if abs(authored) > 1e-9
        else declared
        if abs(declared) > 1e-9
        else measured
        for authored, declared, measured in zip(
            drawing,
            logical,
            serialized,
            strict=True,
        )
    )


def _configurable_dimensions(
    package: PContentPackage,
    defaults: tuple[float, float, float],
    enabled: bool,
):
    """Return only editable axes whose default lies inside the declared range."""
    if not enabled:
        return ()
    return tuple(
        dimension
        for dimension in configurable_dimensions(
            package.properties,
            defaults=defaults,
        )
        if dimension.minimum <= dimension.default <= dimension.maximum
    )


def _build_package_tree(
    package: PContentPackage,
    *,
    parent: TransformNode,
    collection,
    source_id: str,
    cache: dict[int, dict[str, list[bpy.types.Mesh]]],
    material_cache: dict[tuple[int, int], bpy.types.Material],
    aggregate_nodes: dict[tuple[int, ...], dict[str, Any]],
    dimension_nodes: list[dict[str, Any]] | None,
    option_nodes: list[dict[str, Any]] | None,
    object_parents: dict[bpy.types.Object, TransformNode],
    convert_tris_to_quads: bool,
    prefix: tuple[int, ...] = (),
    current_dimensions: tuple[float, float, float] | None = None,
    document_scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
    control_label: str = "",
    dimension_controls_enabled: bool = True,
) -> None:
    """Build temporary transform records and source meshes for one package."""
    model_information = selected_model_information(package.properties)
    parent_dimensions = _package_dimensions(package, current_dimensions)
    package_parent = parent

    editable_dimensions = _configurable_dimensions(
        package,
        parent_dimensions,
        dimension_controls_enabled,
    )
    if dimension_nodes is not None and editable_dimensions:
        label = _unique_name(
            control_label or (package.document.name if package.document else ""),
            "Entity",
        )
        package_parent = TransformNode(f"{label} Parameters", parent)
        package_parent["mooblender_configurable_dimensions"] = len(
            editable_dimensions
        )
        dimension_nodes.append(
            {
                "label": control_label,
                "object": package_parent,
                "dimensions": editable_dimensions,
            }
        )

    if package.document is not None:
        document_parent = package_parent
        if document_scale != (1.0, 1.0, 1.0):
            # Keep document redimensioning separate from aggregate placement.
            # This prevents nested aggregate coordinates from being scaled a
            # second time when only the child mesh envelope must stretch.
            document_name = _unique_name(package.document.name, "Aggregate")
            document_parent = TransformNode(
                f"{document_name} Geometry Scale",
                package_parent,
            )
            document_parent.scale = document_scale
            document_parent["mooblender_geometry_scale"] = document_scale
        _document_root(
            package.document,
            package,
            parent=document_parent,
            collection=collection,
            source_id=source_id,
            cache=cache,
            material_cache=material_cache,
            convert_tris_to_quads=convert_tris_to_quads,
            object_parents=object_parents,
            geometry_scale=document_scale,
        )

    for resolved in package.resolved_aggregates:
        raw = _raw_aggregate(package, resolved.index)
        child = resolved.package
        default_dimensions = property_dimensions(child.properties)
        variables: dict[str, float | bool] = dimension_variables(
            default_dimensions,
            parent=parent_dimensions,
        )
        target_dimensions = property_dimensions(
            raw,
            variables=variables,
            fallback=default_dimensions,
        )
        variables.update(dimension_variables(target_dimensions))

        visible_condition = raw.get("VisibleCondition")
        if visible_condition is not None and not evaluate_condition(
            visible_condition,
            variables,
            model_information,
        ):
            continue

        position = raw.get("Position", {})
        position = position if isinstance(position, dict) else {}
        location = tuple(
            evaluate_expression(position.get(axis), variables) * 0.001
            for axis in ("X", "Y", "Z")
        )
        axial_rotation = math.radians(
            evaluate_expression(position.get("Rotation"), variables)
        )
        raw_normal = raw.get("Normal", {})
        raw_normal = raw_normal if isinstance(raw_normal, dict) else {}
        normal = Vector(
            tuple(
                evaluate_expression(raw_normal.get(axis), variables)
                for axis in ("X", "Y", "Z")
            )
        )
        if normal.length_squared <= 1e-12:
            normal = Vector((0.0, 0.0, 1.0))
        else:
            normal.normalize()

        inverted = raw.get("Inverted") is True
        geometry_dimensions = serialized_geometry_dimensions(
            child.properties,
            document=child.document,
            fallback=default_dimensions,
        )
        geometry_scale = tuple(
            target / measured if measured else 1.0
            for target, measured in zip(
                target_dimensions,
                geometry_dimensions,
                strict=True,
            )
        )

        fallback = f"Aggregate {resolved.index}"
        name = _unique_name(
            str(raw.get("Description") or raw.get("Id") or ""),
            fallback,
        )
        placement = TransformNode(name, package_parent)
        placement.location = location
        placement.rotation_mode = "QUATERNION"
        placement.rotation_quaternion = _aggregate_orientation(
            normal,
            axial_rotation,
        )
        placement.scale.x = -1.0 if inverted else 1.0
        placement["mooble_specification_id"] = resolved.specification_id
        placement["promob_aggregate_index"] = resolved.index

        if option_nodes is not None and is_optional_aggregate(raw):
            option_nodes.append(
                {
                    "label": name,
                    "object": placement,
                    "default_scale": tuple(placement.scale),
                }
            )

        # The extra motion/content pair provides a clean pivot space for doors
        # and an independent translation space for drawers.  They are Python
        # records only and become Transform Geometry nodes during compilation.
        motion = TransformNode(f"{name} Opening", placement)
        content = TransformNode(f"{name} Content", motion)
        path = prefix + (resolved.index,)
        aggregate_nodes[path] = {
            "placement": placement,
            "motion": motion,
            "content": content,
            "dimensions": target_dimensions,
            "inverted": inverted,
        }

        _build_package_tree(
            child,
            parent=content,
            collection=collection,
            source_id=source_id,
            cache=cache,
            material_cache=material_cache,
            aggregate_nodes=aggregate_nodes,
            dimension_nodes=dimension_nodes,
            option_nodes=option_nodes,
            object_parents=object_parents,
            convert_tris_to_quads=convert_tris_to_quads,
            prefix=path,
            current_dimensions=target_dimensions,
            document_scale=geometry_scale,
            control_label=name,
            dimension_controls_enabled=(
                dimension_controls_enabled and raw.get("Constant") is not True
            ),
        )


def _opening_control_factory(controller_nodes):
    """Return a callback that lazily creates unique opening controls."""
    control_name_counts: dict[str, int] = {}
    opening_panel = None

    def create_opening_control(
        service: dict[str, object],
        fallback: str,
    ) -> tuple[Any, str]:
        """Create or reuse the Doors and Drawers panel for one service."""
        nonlocal opening_panel
        modifier = controller_nodes.modifier
        node_group = modifier.node_group
        if opening_panel is None:
            opening_panel = node_group.interface.new_panel(
                name="Doors and Drawers",
                description="Independent opening controls for movable components",
                default_closed=False,
            )

        base_name = control_name(service, fallback)
        count = control_name_counts.get(base_name, 0) + 1
        control_name_counts[base_name] = count
        display_name = base_name if count == 1 else f"{base_name} ({count})"
        socket = node_group.interface.new_socket(
            name=display_name,
            in_out="INPUT",
            socket_type="NodeSocketFloat",
            parent=opening_panel,
        )
        make_socket_single_value(socket)
        socket.default_value = 0.0
        socket.min_value = 0.0
        socket.max_value = 1.0
        socket.description = f"Open {base_name}"
        node_group.interface_update(bpy.context)
        set_modifier_value(modifier, socket, 0.0)
        return socket, display_name

    return create_opening_control


def _add_package_controls(
    package: PContentPackage,
    controller_nodes,
    hierarchy_root: TransformNode,
    aggregate_nodes: dict[tuple[int, ...], dict[str, Any]],
    dimension_nodes: list[dict[str, Any]],
    option_nodes: list[dict[str, Any]],
    transform_controls: TransformControls,
    material_cache: dict[tuple[int, int], bpy.types.Material],
) -> None:
    """Create every modifier panel and bind it to package transform records."""
    add_material_options(
        package,
        controller_nodes=controller_nodes,
        material_cache=material_cache,
    )

    has_mirror = can_mirror(package.properties)
    options_panel = (
        controller_nodes.modifier.node_group.interface.new_panel(
            name="Options",
            description="Optional components included with this model",
            default_closed=False,
        )
        if option_nodes or has_mirror
        else None
    )
    add_visibility_controls(
        option_nodes,
        controller_nodes=controller_nodes,
        panel=options_panel,
        transform_controls=transform_controls,
    )
    add_mirror_control(
        package,
        hierarchy_root=hierarchy_root,
        controller_nodes=controller_nodes,
        panel=options_panel,
        transform_controls=transform_controls,
    )

    # Opening services can live at any resolved package depth.  Pairing each
    # package with its aggregate-index prefix maps local paths back into the
    # one global transform-record dictionary.
    open_services = 0
    controlled_paths: set[tuple[int, ...]] = set()
    create_opening_control = _opening_control_factory(controller_nodes)
    stack = [(package, ())]
    visited: set[tuple[int, tuple[int, ...]]] = set()
    while stack:
        current, prefix = stack.pop()
        marker = (id(current), prefix)
        if marker in visited:
            continue
        visited.add(marker)
        open_services += _apply_open_services(
            current,
            prefix=prefix,
            opening_control=create_opening_control,
            aggregate_nodes=aggregate_nodes,
            controlled_paths=controlled_paths,
            transform_controls=transform_controls,
        )
        stack.extend(
            (item.package, prefix + (item.index,))
            for item in current.resolved_aggregates
        )
    if open_services:
        controller_nodes.controller["mooblender_open_service_count"] = open_services

    parameters_panel = (
        controller_nodes.modifier.node_group.interface.new_panel(
            name="Parameters",
            description="Configurable dimensions and other model parameters",
            default_closed=False,
        )
        if dimension_nodes
        else None
    )
    add_dimension_controls(
        dimension_nodes,
        controller_nodes=controller_nodes,
        panel=parameters_panel,
        transform_controls=transform_controls,
    )


def build_document(
    source: PmobDocument | PContentPackage,
    context,
    *,
    collection_name: str = "",
    source_id: str = "",
    convert_tris_to_quads: bool = False,
) -> bpy.types.Object:
    """Build one scene-linked Geometry Nodes controller from neutral source data."""
    package = source if isinstance(source, PContentPackage) else None
    document = package.document if package is not None else source
    if document is None and package is not None and not package.resolved_aggregates:
        raise ValueError("this PContent aggregate has not been resolved")

    document_name = document.name if document is not None else ""
    name = _unique_name(collection_name or document_name, "Promob Import")
    destination = context.collection or context.scene.collection

    # Only the controller is linked to the active scene.  Source meshes live in
    # an unlinked collection and are referenced by Object Info nodes.
    source_collection = bpy.data.collections.new(f"{name} Source")
    controller_nodes = create_controller(name, destination)
    hierarchy_root = TransformNode(f"{name} Hierarchy")

    aggregate_nodes: dict[tuple[int, ...], dict[str, Any]] = {}
    dimension_nodes: list[dict[str, Any]] = []
    option_nodes: list[dict[str, Any]] = []
    transform_controls: TransformControls = {}
    object_parents: dict[bpy.types.Object, TransformNode] = {}
    mesh_cache: dict[int, dict[str, list[bpy.types.Mesh]]] = {}
    material_cache: dict[tuple[int, int], bpy.types.Material] = {}

    if package is not None:
        _build_package_tree(
            package,
            parent=hierarchy_root,
            collection=source_collection,
            source_id=source_id,
            cache=mesh_cache,
            material_cache=material_cache,
            aggregate_nodes=aggregate_nodes,
            dimension_nodes=dimension_nodes,
            option_nodes=option_nodes,
            object_parents=object_parents,
            convert_tris_to_quads=convert_tris_to_quads,
        )
        _add_package_controls(
            package,
            controller_nodes,
            hierarchy_root,
            aggregate_nodes,
            dimension_nodes,
            option_nodes,
            transform_controls,
            material_cache,
        )
    elif document is not None:
        _document_root(
            document,
            None,
            parent=hierarchy_root,
            collection=source_collection,
            source_id=source_id,
            cache=mesh_cache,
            material_cache=material_cache,
            convert_tris_to_quads=convert_tris_to_quads,
            object_parents=object_parents,
        )

    # Graph compilation is deliberately last: every socket-driven transform
    # must be known before the Transform Geometry nodes are generated.
    compile_hierarchy(
        controller_nodes,
        source_collection,
        hierarchy_root,
        transform_controls,
        object_parents,
    )

    controller = controller_nodes.controller
    source_collection["mooblender_node_source"] = True
    controller["promob_version"] = document.version if document is not None else 0
    if source_id:
        controller["mooble_item_id"] = source_id
    controller["mooblender_convert_tris_to_quads"] = convert_tris_to_quads
    controller["mooblender_realize_instances_socket"] = (
        controller_nodes.realize_socket.identifier
    )
    return controller
