"""Conversion from neutral Promob models to Blender datablocks."""

from __future__ import annotations

import math
import zlib
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
from .mesh_builder import _document_root, _entity_code, _remote_material, _unique_name


def _aggregate_orientation(normal: Vector, rotation: float) -> Quaternion:
    """Build Promob's normal frame without an ambiguous shortest-arc roll."""
    vertical_reference = Vector((0.0, 0.0, -1.0))
    local_x = vertical_reference - normal * vertical_reference.dot(normal)
    if local_x.length_squared <= 1e-12:
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
    aggregates = package.properties.get("Aggregates", [])
    if not isinstance(aggregates, list) or not 0 <= index < len(aggregates):
        return {}
    value = aggregates[index]
    return value if isinstance(value, dict) else {}


def _add_open_driver(
    target,
    index: int,
    controller,
    controller_data_path: str,
    expression: str,
) -> None:
    driver = target.driver_add("rotation_euler" if index == 2 else "location", index).driver
    driver.type = "SCRIPTED"
    driver.expression = expression
    variable = driver.variables.new()
    variable.name = "open_ratio"
    variable.type = "SINGLE_PROP"
    variable.targets[0].id = controller
    variable.targets[0].data_path = controller_data_path


def _add_dimension_driver(
    target,
    axis: int,
    controller,
    controller_data_path: str,
    default_value: float,
) -> None:
    driver = target.driver_add("scale", axis).driver
    driver.type = "SCRIPTED"
    driver.expression = f"dimension/{default_value:.17g}"
    variable = driver.variables.new()
    variable.name = "dimension"
    variable.type = "SINGLE_PROP"
    variable.targets[0].id = controller
    variable.targets[0].data_path = controller_data_path


def _add_visibility_driver(
    target,
    controller,
    controller_data_path: str,
    default_scale: tuple[float, float, float],
) -> None:
    for axis, scale in enumerate(default_scale):
        driver = target.driver_add("scale", axis).driver
        driver.type = "SCRIPTED"
        driver.expression = f"{scale:.17g}*enabled"
        variable = driver.variables.new()
        variable.name = "enabled"
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = controller
        variable.targets[0].data_path = controller_data_path


def _add_mirror_drivers(
    target,
    controller,
    controller_data_path: str,
    mirror_offset: float,
) -> None:
    expressions = {
        ("scale", 0): "1-2*reverse",
        ("location", 0): f"{mirror_offset:.17g}*reverse",
    }
    for (property_name, axis), expression in expressions.items():
        driver = target.driver_add(property_name, axis).driver
        driver.type = "SCRIPTED"
        driver.expression = expression
        variable = driver.variables.new()
        variable.name = "reverse"
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = controller
        variable.targets[0].data_path = controller_data_path


def _apply_open_services(
    package: PContentPackage,
    *,
    prefix: tuple[int, ...],
    controller,
    opening_control: Callable[[dict[str, object], str], tuple[str, str]],
    aggregate_nodes: dict[tuple[int, ...], dict[str, Any]],
    controlled_paths: set[tuple[int, ...]],
) -> int:
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
        # definition index, for example [2, 0] addresses aggregate 2 using its
        # first/default specification. Our resolved tree stores container
        # indices because only the selected specification becomes geometry.
        path = prefix + tuple(
            value
            for offset, value in enumerate(raw_path)
            if offset % 2 == 0 and isinstance(value, int)
        )
        if path in controlled_paths:
            continue
        data = aggregate_nodes.get(path)
        if data is None:
            continue
        motion = data["motion"]
        content = data["content"]
        dimensions = data["dimensions"]
        width, depth, height = dimensions
        inverted = bool(data["inverted"])
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
            controller_data_path, control_name = opening_control(
                service,
                data["placement"].name,
            )
            motion.location = tuple(value * 0.001 for value in pivot)
            content.location = tuple(-value * 0.001 for value in pivot)
            _add_open_driver(
                motion,
                2,
                controller,
                controller_data_path,
                f"{angle:.17g}*open_ratio",
            )
        elif service_type == "drawer":
            distance = maximum * -0.001
            if abs(distance) <= 1e-12:
                continue
            controller_data_path, control_name = opening_control(
                service,
                data["placement"].name,
            )
            _add_open_driver(
                motion,
                1,
                controller,
                controller_data_path,
                f"{distance:.17g}*open_ratio",
            )
        else:
            continue
        motion["mooblender_open_service"] = control_name
        motion["mooblender_open_service_type"] = str(service.get("Type", ""))
        controlled_paths.add(path)
        applied += 1
    return applied


def _build_package_tree(
    package: PContentPackage,
    *,
    parent,
    collection,
    source_id: str,
    cache: dict[int, dict[str, list[bpy.types.Mesh]]],
    material_cache: dict[tuple[int, int], bpy.types.Material],
    aggregate_nodes: dict[tuple[int, ...], dict[str, Any]],
    dimension_nodes: list[dict[str, Any]] | None,
    option_nodes: list[dict[str, Any]] | None,
    convert_tris_to_quads: bool,
    prefix: tuple[int, ...] = (),
    current_dimensions: tuple[float, float, float] | None = None,
    document_scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
    control_label: str = "",
    dimension_controls_enabled: bool = True,
):
    model_information = selected_model_information(package.properties)
    logical_dimensions = property_dimensions(package.properties)
    drawing_dimensions = property_dimensions(
        package.properties,
        "DrawingDimension",
    )
    serialized_dimensions = serialized_geometry_dimensions(
        package.properties,
        document=package.document,
        fallback=logical_dimensions,
    )
    parent_dimensions = current_dimensions or tuple(
        drawing
        if abs(drawing) > 1e-9
        else logical
        if abs(logical) > 1e-9
        else serialized
        for drawing, logical, serialized in zip(
            drawing_dimensions,
            logical_dimensions,
            serialized_dimensions,
            strict=True,
        )
    )
    package_parent = parent
    dimensions = (
        tuple(
            dimension
            for dimension in configurable_dimensions(
                package.properties,
                defaults=parent_dimensions,
            )
            if dimension.minimum <= dimension.default <= dimension.maximum
        )
        if dimension_controls_enabled
        else ()
    )
    if dimension_nodes is not None and dimensions:
        label = _unique_name(
            control_label or (package.document.name if package.document else ""),
            "Entity",
        )
        package_parent = bpy.data.objects.new(f"{label} Parameters", None)
        package_parent.parent = parent
        package_parent["mooblender_configurable_dimensions"] = len(dimensions)
        collection.objects.link(package_parent)
        dimension_nodes.append(
            {
                "label": control_label,
                "object": package_parent,
                "dimensions": dimensions,
            }
        )
    if package.document is not None:
        document_parent = package_parent
        if document_scale != (1.0, 1.0, 1.0):
            document_name = _unique_name(package.document.name, "Aggregate")
            document_parent = bpy.data.objects.new(f"{document_name} Geometry Scale", None)
            document_parent.parent = package_parent
            document_parent.scale = document_scale
            document_parent["mooblender_geometry_scale"] = document_scale
            collection.objects.link(document_parent)
        _document_root(
            package.document,
            package,
            parent=document_parent,
            collection=collection,
            source_id=source_id,
            cache=cache,
            material_cache=material_cache,
            convert_tris_to_quads=convert_tris_to_quads,
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
        rotation = math.radians(evaluate_expression(position.get("Rotation"), variables))
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
        orientation = _aggregate_orientation(normal, rotation)
        inverted = raw.get("Inverted") is True
        geometry_dimensions = serialized_geometry_dimensions(
            child.properties,
            document=child.document,
            fallback=default_dimensions,
        )
        scale = [
            target / geometry if geometry else 1.0
            for target, geometry in zip(
                target_dimensions,
                geometry_dimensions,
                strict=True,
            )
        ]
        fallback = f"Aggregate {resolved.index}"
        name = _unique_name(str(raw.get("Description") or raw.get("Id") or ""), fallback)
        placement = bpy.data.objects.new(name, None)
        placement.empty_display_type = "CUBE"
        placement.parent = package_parent
        placement.location = location
        placement.rotation_mode = "QUATERNION"
        placement.rotation_quaternion = orientation
        placement.scale.x = -1.0 if inverted else 1.0
        placement["mooble_specification_id"] = resolved.specification_id
        placement["promob_aggregate_index"] = resolved.index
        collection.objects.link(placement)
        if option_nodes is not None and is_optional_aggregate(raw):
            option_nodes.append(
                {
                    "label": name,
                    "object": placement,
                    "default_scale": tuple(placement.scale),
                }
            )

        motion = bpy.data.objects.new(f"{name} Opening", None)
        motion.parent = placement
        collection.objects.link(motion)
        content = bpy.data.objects.new(f"{name} Content", None)
        content.parent = motion
        collection.objects.link(content)
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
            convert_tris_to_quads=convert_tris_to_quads,
            prefix=path,
            current_dimensions=target_dimensions,
            document_scale=tuple(scale),
            control_label=name,
            dimension_controls_enabled=(
                dimension_controls_enabled and raw.get("Constant") is not True
            ),
        )


def _modifier_socket_value(modifier, socket, value):
    interface_values = getattr(getattr(modifier, "properties", None), "inputs", None)
    if interface_values is not None and hasattr(interface_values, socket.identifier):
        socket_value = getattr(interface_values, socket.identifier)
        socket_value.value = value
        return socket_value.path_from_id("value")
    modifier[socket.identifier] = value
    return modifier.path_from_id(f'["{socket.identifier}"]')


def _geometry_nodes_controller(name: str, collection, source_collection):
    mesh = bpy.data.meshes.new(f"{name} Geometry")
    controller = bpy.data.objects.new(name, mesh)
    collection.objects.link(controller)
    modifier = controller.modifiers.new(name="Mooblender", type="NODES")
    node_group = bpy.data.node_groups.new(f"{name} Controls", "GeometryNodeTree")
    modifier.node_group = node_group

    output_socket = node_group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )
    realize_socket = node_group.interface.new_socket(
        name="Realize Instances",
        description=(
            "Convert the nested source hierarchy to a mesh; required for "
            "material overrides"
        ),
        in_out="INPUT",
        socket_type="NodeSocketBool",
    )
    _make_socket_single_value(realize_socket)
    realize_socket.default_value = False
    nodes = node_group.nodes
    links = node_group.links
    collection_info = nodes.new("GeometryNodeCollectionInfo")
    collection_info.label = "Nested Source Hierarchy"
    collection_info.inputs["Collection"].default_value = source_collection
    collection_info.inputs["Separate Children"].default_value = False
    collection_info.inputs["Reset Children"].default_value = False
    realize = nodes.new("GeometryNodeRealizeInstances")
    realize.label = "Optional Realization"
    geometry_switch = nodes.new("GeometryNodeSwitch")
    geometry_switch.input_type = "GEOMETRY"
    geometry_switch.label = "Keep Instances / Realize"
    group_input = nodes.new("NodeGroupInput")
    output = nodes.new("NodeGroupOutput")
    output.is_active_output = True
    links.new(collection_info.outputs["Instances"], realize.inputs["Geometry"])
    links.new(collection_info.outputs["Instances"], geometry_switch.inputs["False"])
    links.new(realize.outputs["Geometry"], geometry_switch.inputs["True"])
    links.new(group_input.outputs[realize_socket.name], geometry_switch.inputs["Switch"])
    links.new(geometry_switch.outputs["Output"], output.inputs[output_socket.name])
    node_group.interface_update(bpy.context)
    _modifier_socket_value(modifier, realize_socket, False)
    controller["mooblender_instances_realized_by_default"] = False
    return (
        controller,
        modifier,
        group_input,
        realize,
        geometry_switch,
        realize_socket,
    )


def _make_socket_single_value(socket) -> None:
    socket.structure_type = "SINGLE"


def _group_input_output(group_input, socket):
    """Resolve an interface socket by identifier, allowing names in other panels."""
    return next(
        output for output in group_input.outputs if output.identifier == socket.identifier
    )


def _keep_modifier_input_active(node_group, group_input, socket) -> None:
    value_sink = node_group.nodes.new("ShaderNodeMath")
    value_sink.operation = "MULTIPLY"
    value_sink.hide = True
    value_sink.label = "Modifier input driver"
    value_sink.inputs[1].default_value = 0.0
    node_group.links.new(_group_input_output(group_input, socket), value_sink.inputs[0])


def _add_dimension_controls(
    dimension_nodes: list[dict[str, Any]],
    *,
    controller,
    modifier,
    group_input,
    panel,
) -> int:
    if not dimension_nodes:
        return 0

    node_group = modifier.node_group
    used_names = {
        item.name for item in node_group.interface.items_tree if item.parent == panel
    }
    defaults = []
    controls = 0
    for data in dimension_nodes:
        label = str(data["label"])
        target = data["object"]
        for dimension in data["dimensions"]:
            base = f"{label}: {dimension.name}" if label else dimension.name
            name = base
            suffix = 2
            while name in used_names:
                name = f"{base} ({suffix})"
                suffix += 1
            used_names.add(name)
            socket = node_group.interface.new_socket(
                name=name,
                in_out="INPUT",
                socket_type="NodeSocketFloat",
                parent=panel,
            )
            _make_socket_single_value(socket)
            socket.subtype = "DISTANCE"
            socket.default_value = dimension.default * 0.001
            socket.min_value = dimension.minimum * 0.001
            socket.max_value = dimension.maximum * 0.001
            socket.description = (
                f"Mooble range: {dimension.minimum:g}–{dimension.maximum:g} mm"
            )
            defaults.append((socket, dimension.default * 0.001, target, dimension.axis))
            controls += 1

    node_group.interface_update(bpy.context)
    for socket, value, target, axis in defaults:
        _keep_modifier_input_active(node_group, group_input, socket)
        data_path = _modifier_socket_value(modifier, socket, value)
        _add_dimension_driver(target, axis, controller, data_path, value)
    node_group.interface_update(bpy.context)
    if controls:
        controller["mooblender_dimension_control_count"] = controls
    return controls


def _add_visibility_controls(
    option_nodes: list[dict[str, Any]],
    *,
    controller,
    modifier,
    group_input,
    panel,
) -> int:
    """Expose independently selectable aggregates as single-value switches."""
    if not option_nodes:
        return 0
    node_group = modifier.node_group
    used_names = {
        item.name for item in node_group.interface.items_tree if item.parent == panel
    }
    controls = 0
    for data in option_nodes:
        name = _unique_interface_name(str(data["label"]), used_names)
        socket = node_group.interface.new_socket(
            name=name,
            in_out="INPUT",
            socket_type="NodeSocketBool",
            parent=panel,
        )
        _make_socket_single_value(socket)
        socket.default_value = True
        socket.description = f"Show or hide {data['label']}"
        node_group.interface_update(bpy.context)
        _keep_modifier_input_active(node_group, group_input, socket)
        data_path = _modifier_socket_value(modifier, socket, True)
        _add_visibility_driver(
            data["object"],
            controller,
            data_path,
            data["default_scale"],
        )
        controls += 1
    node_group.interface_update(bpy.context)
    controller["mooblender_option_control_count"] = controls
    return controls


def _add_mirror_control(
    package: PContentPackage,
    *,
    hierarchy_root,
    controller,
    modifier,
    group_input,
    panel,
) -> bool:
    """Create a whole-model X mirror control when source metadata permits it."""
    if not can_mirror(package.properties):
        return False
    socket = modifier.node_group.interface.new_socket(
        name="Reverse",
        in_out="INPUT",
        socket_type="NodeSocketBool",
        parent=panel,
    )
    _make_socket_single_value(socket)
    socket.default_value = False
    socket.description = "Mirror the complete model while preserving its footprint"
    modifier.node_group.interface_update(bpy.context)
    _keep_modifier_input_active(modifier.node_group, group_input, socket)
    data_path = _modifier_socket_value(modifier, socket, False)
    limits = package.properties.get("Limits", {})
    limits = limits if isinstance(limits, dict) else {}
    minimum = limits.get("Min", {})
    maximum = limits.get("Max", {})
    minimum = minimum if isinstance(minimum, dict) else {}
    maximum = maximum if isinstance(maximum, dict) else {}
    width = property_dimensions(package.properties)[0]
    mirror_offset = (
        evaluate_expression(minimum.get("X"), default=0.0)
        + evaluate_expression(maximum.get("X"), default=width)
    ) * 0.001
    _add_mirror_drivers(hierarchy_root, controller, data_path, mirror_offset)
    controller["mooblender_can_mirror"] = True
    return True


def _model_groups(package: PContentPackage):
    groups: dict[tuple[int, str], dict[str, object]] = {}
    stack = [package]
    visited: set[int] = set()
    while stack:
        current = stack.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        models = current.properties.get("Models", [])
        if isinstance(models, list):
            for model in models:
                if not isinstance(model, dict):
                    continue
                group_id = str(model.get("ModelDefinitionId") or model.get("Id") or "")
                if not group_id:
                    continue
                group = groups.setdefault(
                    (id(current), group_id),
                    {
                        "name": str(model.get("ModelDefinitionName") or group_id),
                        "options": [],
                        "materials": {},
                        "scope": _entity_code(current),
                    },
                )
                option_id = str(model.get("Id") or model.get("Name") or "")
                options = group["options"]
                if isinstance(options, list) and not any(
                    isinstance(item, dict) and item.get("id") == option_id
                    for item in options
                ):
                    components = model.get("Components", [])
                    assignments = {
                        str(component.get("LayerId")): str(component.get("MaterialId"))
                        for component in components
                        if isinstance(component, dict)
                        and component.get("LayerId")
                        and component.get("MaterialId")
                    } if isinstance(components, list) else {}
                    options.append(
                        {
                            "id": option_id,
                            "name": str(model.get("Name") or option_id),
                            "assignments": assignments,
                        }
                    )
                materials = group["materials"]
                if isinstance(materials, dict):
                    materials.update(current.resolved_materials)
        stack.extend(item.package for item in current.resolved_aggregates)
    return groups


def _create_remote_materials(groups, cache):
    result = {}
    for group in groups.values():
        scope = int(group.get("scope", 0))
        materials = group.get("materials", {})
        if not isinstance(materials, dict):
            continue
        for material_id, package in materials.items():
            key = (scope, material_id)
            if key in result or not isinstance(package, PContentPackage):
                continue
            material = _remote_material(material_id, package, cache)
            if material is not None:
                result[key] = material
    return result


def _menu_option_names(options: list[dict[str, object]]) -> list[str]:
    names: list[str] = []
    counts: dict[str, int] = {}
    for index, option in enumerate(options):
        base = str(option.get("name") or option.get("id") or f"Style {index + 1}")
        count = counts.get(base, 0) + 1
        counts[base] = count
        names.append(base if count == 1 else f"{base} ({count})")
    return names


def _modifier_menu_value(modifier, socket, name: str, index: int) -> None:
    interface_values = getattr(getattr(modifier, "properties", None), "inputs", None)
    if interface_values is not None and hasattr(interface_values, socket.identifier):
        getattr(interface_values, socket.identifier).value = name
        return
    try:
        items = modifier.id_properties_ui(socket.identifier).as_dict().get("items", ())
        value = next(item[-1] for item in items if item[0] == name)
    except (KeyError, StopIteration, TypeError):
        value = index
    modifier[socket.identifier] = value


def _material_bundles(groups) -> dict[tuple[str, tuple[str, ...]], list[dict]]:
    """Consolidate package scopes that expose the same named style menu."""
    bundles: dict[tuple[str, tuple[str, ...]], list[dict]] = {}
    for group in groups.values():
        options = group.get("options")
        if not isinstance(options, list) or len(options) < 2:
            continue
        option_names = tuple(_menu_option_names(options))
        group_name = str(group.get("name") or "Material")
        bundles.setdefault((group_name, option_names), []).append(group)
    return bundles


def _finish_part_name(group_name: str, fallback: str) -> str:
    """Turn generic finish-definition names into concise part labels."""
    words = group_name.strip().split()
    if words and words[0].casefold() == "acabamento":
        words.pop(0)
    if words and words[-1].casefold() == "finish":
        words.pop()
    return " ".join(words) or fallback


def _material_applications(bundled_groups, materials):
    """Keep only layers for which every menu option resolved a material."""
    applications = []
    for group in bundled_groups:
        options = group["options"]
        scope = int(group.get("scope", 0))
        layers = sorted(
            {
                layer
                for option in options
                if isinstance(option, dict)
                for layer in option.get("assignments", {})
            }
        )
        usable_layers = [
            layer
            for layer in layers
            if all(
                isinstance(option, dict)
                and materials.get((scope, option.get("assignments", {}).get(layer)))
                is not None
                for option in options
            )
        ]
        if usable_layers:
            applications.append((scope, options, usable_layers))
    return applications


def _unique_interface_name(base: str, used_names: set[str]) -> str:
    name = base
    suffix = 2
    while name in used_names:
        name = f"{base} ({suffix})"
        suffix += 1
    used_names.add(name)
    return name


def _create_style_menu(node_group, group_input, socket, option_names):
    """Create the menu-to-index conversion shared by all matching layers."""
    socket_name = socket.name
    option_output = _group_input_output(group_input, socket)
    style_switch = node_group.nodes.new("GeometryNodeMenuSwitch")
    style_switch.data_type = "INT"
    style_switch.enum_items.clear()
    for index, name in enumerate(option_names):
        style_switch.enum_items.new(name)
        style_switch.inputs[index + 1].default_value = index
    socket.from_socket(style_switch, style_switch.inputs["Menu"])
    # `from_socket` copies the source name ("Menu"), so restore the stable UI
    # name after copying its enum definition.
    socket.name = socket_name
    node_group.links.new(option_output, style_switch.inputs["Menu"])
    return style_switch


def _material_selection(node_group, scope: int, layer: str):
    """Select faces by the stable layer and source-package attributes."""
    nodes = node_group.nodes
    links = node_group.links
    named_layer = nodes.new("GeometryNodeInputNamedAttribute")
    named_layer.data_type = "INT"
    named_layer.inputs["Name"].default_value = "mooblender_layer"
    compare_layer = nodes.new("FunctionNodeCompare")
    compare_layer.data_type = "INT"
    compare_layer.operation = "EQUAL"
    compare_layer.inputs["B"].default_value = (
        zlib.crc32(layer.casefold().encode("utf-8")) & 0x7FFFFFFF
    )
    named_entity = nodes.new("GeometryNodeInputNamedAttribute")
    named_entity.data_type = "INT"
    named_entity.inputs["Name"].default_value = "mooblender_entity"
    compare_entity = nodes.new("FunctionNodeCompare")
    compare_entity.data_type = "INT"
    compare_entity.operation = "EQUAL"
    compare_entity.inputs["B"].default_value = scope
    selection = nodes.new("FunctionNodeBooleanMath")
    selection.operation = "AND"
    links.new(named_layer.outputs["Attribute"], compare_layer.inputs["A"])
    links.new(named_entity.outputs["Attribute"], compare_entity.inputs["A"])
    links.new(compare_layer.outputs["Result"], selection.inputs[0])
    links.new(compare_entity.outputs["Result"], selection.inputs[1])
    return selection.outputs["Boolean"]


def _material_index_switch(node_group, style_index, scope, layer, options, materials):
    """Map one style index to the resolved material for a package layer."""
    material_switch = node_group.nodes.new("GeometryNodeIndexSwitch")
    material_switch.data_type = "MATERIAL"
    while len(material_switch.index_switch_items) < len(options):
        material_switch.index_switch_items.new()
    while len(material_switch.index_switch_items) > len(options):
        material_switch.index_switch_items.remove(material_switch.index_switch_items[-1])
    for index, option in enumerate(options):
        material_id = option["assignments"][layer]
        material_switch.inputs[index + 1].default_value = materials[(scope, material_id)]
    node_group.links.new(style_index, material_switch.inputs["Index"])
    return material_switch.outputs["Output"]


def _apply_materials(node_group, geometry, style_index, applications, materials):
    """Append Set Material nodes for every package scope and compatible layer."""
    for scope, options, layers in applications:
        for layer in layers:
            selection = _material_selection(node_group, scope, layer)
            material = _material_index_switch(
                node_group, style_index, scope, layer, options, materials
            )
            set_material = node_group.nodes.new("GeometryNodeSetMaterial")
            node_group.links.new(selection, set_material.inputs["Selection"])
            node_group.links.new(material, set_material.inputs["Material"])
            node_group.links.new(geometry, set_material.inputs["Geometry"])
            geometry = set_material.outputs["Geometry"]
    return geometry


def _add_material_options(
    package: PContentPackage,
    *,
    controller,
    modifier,
    group_input,
    realize,
    geometry_switch,
    material_cache: dict[tuple[int, int], bpy.types.Material],
) -> int:
    groups = _model_groups(package)
    materials = _create_remote_materials(groups, material_cache)
    if not materials:
        return 0
    node_group = modifier.node_group
    links = node_group.links
    realized_geometry = geometry_switch.inputs["True"]
    for link in list(realized_geometry.links):
        node_group.links.remove(link)
    entries = []
    for (group_name, option_names), bundled_groups in _material_bundles(groups).items():
        applications = _material_applications(bundled_groups, materials)
        if applications:
            entries.append((group_name, option_names, applications))
    if not entries:
        return 0

    finish_panel = node_group.interface.new_panel(
        name="Finish",
        description="Material styles available for each model part",
        default_closed=False,
    )
    geometry = realize.outputs["Geometry"]
    menu_defaults = []
    used_names: set[str] = set()
    for group_name, option_names, applications in entries:
        socket_name = _unique_interface_name(
            _finish_part_name(group_name, controller.name),
            used_names,
        )
        socket = node_group.interface.new_socket(
            name=socket_name,
            in_out="INPUT",
            socket_type="NodeSocketMenu",
            parent=finish_panel,
        )
        _make_socket_single_value(socket)
        socket.description = " / ".join(option_names)
        style_switch = _create_style_menu(node_group, group_input, socket, option_names)
        geometry = _apply_materials(
            node_group,
            geometry,
            style_switch.outputs["Output"],
            applications,
            materials,
        )
        socket.default_value = option_names[0]
        menu_defaults.append((socket, option_names[0], 0))
    links.new(geometry, realized_geometry)
    node_group.interface_update(bpy.context)
    for socket, name, index in menu_defaults:
        _modifier_menu_value(modifier, socket, name, index)
    node_group.interface_update(bpy.context)
    if menu_defaults:
        controller["mooblender_material_option_count"] = len(menu_defaults)
    return len(menu_defaults)


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
    source_collection = bpy.data.collections.new(f"{name} Source")
    (
        root,
        geometry_modifier,
        group_input,
        realize,
        geometry_switch,
        realize_socket,
    ) = _geometry_nodes_controller(
        name,
        destination,
        source_collection,
    )
    hierarchy_root = bpy.data.objects.new(f"{name} Hierarchy", None)
    hierarchy_root.empty_display_type = "CUBE"
    source_collection.objects.link(hierarchy_root)
    target_collection = source_collection
    control_name_counts: dict[str, int] = {}
    opening_panel = None

    def opening_control(
        service: dict[str, object],
        fallback: str,
    ) -> tuple[str, str]:
        nonlocal opening_panel
        if opening_panel is None:
            opening_panel = geometry_modifier.node_group.interface.new_panel(
                name="Doors and Drawers",
                description="Independent opening controls for movable components",
                default_closed=False,
            )
        base = control_name(service, fallback)
        count = control_name_counts.get(base, 0) + 1
        control_name_counts[base] = count
        name = base if count == 1 else f"{base} ({count})"
        socket = geometry_modifier.node_group.interface.new_socket(
            name=name,
            in_out="INPUT",
            socket_type="NodeSocketFloat",
            parent=opening_panel,
        )
        _make_socket_single_value(socket)
        socket.default_value = 0.0
        socket.min_value = 0.0
        socket.max_value = 1.0
        socket.description = f"Open {base}"
        geometry_modifier.node_group.interface_update(bpy.context)
        _keep_modifier_input_active(
            geometry_modifier.node_group,
            group_input,
            socket,
        )
        return _modifier_socket_value(geometry_modifier, socket, 0.0), name

    aggregate_nodes: dict[tuple[int, ...], dict[str, Any]] = {}
    dimension_nodes: list[dict[str, Any]] = []
    option_nodes: list[dict[str, Any]] = []
    cache: dict[int, dict[str, list[bpy.types.Mesh]]] = {}
    material_cache: dict[tuple[int, int], bpy.types.Material] = {}
    if package is not None:
        _build_package_tree(
            package,
            parent=hierarchy_root,
            collection=target_collection,
            source_id=source_id,
            cache=cache,
            material_cache=material_cache,
            aggregate_nodes=aggregate_nodes,
            dimension_nodes=dimension_nodes,
            option_nodes=option_nodes,
            convert_tris_to_quads=convert_tris_to_quads,
        )
        _add_material_options(
            package,
            controller=root,
            modifier=geometry_modifier,
            group_input=group_input,
            realize=realize,
            geometry_switch=geometry_switch,
            material_cache=material_cache,
        )
        has_mirror = can_mirror(package.properties)
        options_panel = (
            geometry_modifier.node_group.interface.new_panel(
                name="Options",
                description="Optional components included with this model",
                default_closed=False,
            )
            if option_nodes or has_mirror
            else None
        )
        _add_visibility_controls(
            option_nodes,
            controller=root,
            modifier=geometry_modifier,
            group_input=group_input,
            panel=options_panel,
        )
        _add_mirror_control(
            package,
            hierarchy_root=hierarchy_root,
            controller=root,
            modifier=geometry_modifier,
            group_input=group_input,
            panel=options_panel,
        )
        open_services = 0
        controlled_paths: set[tuple[int, ...]] = set()
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
                controller=root,
                opening_control=opening_control,
                aggregate_nodes=aggregate_nodes,
                controlled_paths=controlled_paths,
            )
            stack.extend(
                (item.package, prefix + (item.index,))
                for item in current.resolved_aggregates
            )
        if open_services:
            root["mooblender_open_service_count"] = open_services
        parameters_panel = (
            geometry_modifier.node_group.interface.new_panel(
                name="Parameters",
                description="Configurable dimensions and other model parameters",
                default_closed=False,
            )
            if dimension_nodes
            else None
        )
        _add_dimension_controls(
            dimension_nodes,
            controller=root,
            modifier=geometry_modifier,
            group_input=group_input,
            panel=parameters_panel,
        )
    elif document is not None:
        _document_root(
            document,
            None,
            parent=hierarchy_root,
            collection=target_collection,
            source_id=source_id,
            cache=cache,
            material_cache=material_cache,
            convert_tris_to_quads=convert_tris_to_quads,
        )
    source_collection["mooblender_node_source"] = True
    root["promob_version"] = document.version if document is not None else 0
    if source_id:
        root["mooble_item_id"] = source_id
    root["mooblender_convert_tris_to_quads"] = convert_tris_to_quads
    root["mooblender_realize_instances_socket"] = realize_socket.identifier
    return root
