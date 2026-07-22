"""Build the Geometry Nodes graph used by an imported Mooble model.

This module is the only place that knows how the add-on's procedural Blender
graph is assembled.  The scene builder supplies neutral meshes, a lightweight
transform hierarchy, and customization metadata.  The functions below turn
that input into one controller object whose modifier owns every user-facing
control.

Keeping graph construction here makes the boundary deliberate:

* :mod:`scene_builder` resolves Promob packages and component relationships;
* :mod:`mesh_builder` creates source mesh datablocks;
* this module converts those results into Geometry Nodes.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import Any

import bpy
from mathutils import Matrix

from ..formats.pcontent import PContentPackage
from ..model.customization import can_mirror
from ..model.dimensions import property_dimensions
from ..model.expressions import evaluate_expression
from .mesh_builder import TransformNode, _entity_code, _remote_material

# This private face attribute records whether the static transform chain has a
# negative determinant.  It lets the final graph correct winding after a model
# or one of its components is mirrored.
_TRANSFORM_PARITY_ATTRIBUTE = "mooblender_transform_parity"


@dataclass(frozen=True, slots=True)
class DrivenChannel:
    """Describe one transform component controlled by a modifier socket.

    Geometry Nodes computes the component as ``offset + factor * socket``.
    Every current opening, dimension, visibility, and reversal control can be
    represented by this small affine expression.
    """

    socket: Any
    offset: float = 0.0
    factor: float = 1.0


# A target is either a temporary TransformNode or a source mesh object.  Each
# target maps (channel name, XYZ axis) to its modifier-driven expression.
TransformControls = dict[object, dict[tuple[str, int], DrivenChannel]]


@dataclass(frozen=True, slots=True)
class ControllerNodes:
    """Named references to the stable nodes created for one import."""

    controller: bpy.types.Object
    modifier: bpy.types.Modifier
    group_input: Any
    source_geometry: Any
    geometry_to_instance: Any
    realize_socket: Any


def record_transform_control(
    controls: TransformControls,
    target: object,
    channel: str,
    axis: int,
    socket: Any,
    *,
    offset: float = 0.0,
    factor: float = 1.0,
) -> None:
    """Record a socket-driven transform channel for graph compilation."""
    controls.setdefault(target, {})[(channel, axis)] = DrivenChannel(
        socket=socket,
        offset=offset,
        factor=factor,
    )


def set_modifier_value(modifier, socket, value):
    """Set a Geometry Nodes modifier input across Blender API generations.

    Blender 5 exposes typed interface values through ``modifier.properties``;
    Blender 4.5 stores the same values as modifier ID properties.  Returning
    the data path keeps this helper useful to callers that need animation or
    drivers, even though current Mooblender transforms stay inside the graph.
    """
    interface_values = getattr(getattr(modifier, "properties", None), "inputs", None)
    if interface_values is not None and hasattr(interface_values, socket.identifier):
        socket_value = getattr(interface_values, socket.identifier)
        socket_value.value = value
        return socket_value.path_from_id("value")
    modifier[socket.identifier] = value
    return modifier.path_from_id(f'["{socket.identifier}"]')


def make_socket_single_value(socket) -> None:
    """Mark a modifier input as one value instead of a geometry field."""
    socket.structure_type = "SINGLE"


def create_controller(name: str, collection) -> ControllerNodes:
    """Create the controller object and the fixed skeleton of its node graph."""
    # The controller's own mesh stays empty.  All visible geometry comes from
    # the modifier, which lets the scene contain exactly one linked object.
    controller_mesh = bpy.data.meshes.new(f"{name} Geometry")
    controller = bpy.data.objects.new(name, controller_mesh)
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
        description="Convert the transformed model instance to editable mesh geometry",
        in_out="INPUT",
        socket_type="NodeSocketBool",
    )
    make_socket_single_value(realize_socket)
    realize_socket.default_value = False

    nodes = node_group.nodes
    links = node_group.links
    source_geometry = nodes.new("GeometryNodeJoinGeometry")
    source_geometry.label = "Transformed Source Meshes"
    geometry_to_instance = nodes.new("GeometryNodeGeometryToInstance")
    geometry_to_instance.label = "Materialized Model Instance"
    realize = nodes.new("GeometryNodeRealizeInstances")
    realize.label = "Optional Realization"
    geometry_switch = nodes.new("GeometryNodeSwitch")
    geometry_switch.input_type = "GEOMETRY"
    geometry_switch.label = "Keep Instances / Realize"
    group_input = nodes.new("NodeGroupInput")
    group_output = nodes.new("NodeGroupOutput")
    group_output.is_active_output = True

    # Source branches are joined as real mesh geometry so face materials and
    # winding can be corrected once.  The result is wrapped back into one model
    # instance; the top-level switch optionally realizes only that instance.
    links.new(
        source_geometry.outputs["Geometry"],
        geometry_to_instance.inputs["Geometry"],
    )
    links.new(geometry_to_instance.outputs["Instances"], realize.inputs["Geometry"])
    links.new(geometry_to_instance.outputs["Instances"], geometry_switch.inputs["False"])
    links.new(realize.outputs["Geometry"], geometry_switch.inputs["True"])
    links.new(group_input.outputs[realize_socket.name], geometry_switch.inputs["Switch"])
    links.new(geometry_switch.outputs["Output"], group_output.inputs[output_socket.name])

    node_group.interface_update(bpy.context)
    set_modifier_value(modifier, realize_socket, False)
    controller["mooblender_instances_realized_by_default"] = False
    return ControllerNodes(
        controller=controller,
        modifier=modifier,
        group_input=group_input,
        source_geometry=source_geometry,
        geometry_to_instance=geometry_to_instance,
        realize_socket=realize_socket,
    )


def group_input_output(group_input, interface_socket):
    """Find a Group Input output by stable interface identifier.

    Display names can repeat in different panels (for example, a Tampo finish
    and a Tampo visibility option), so names are not safe lookup keys.
    """
    return next(
        output
        for output in group_input.outputs
        if output.identifier == interface_socket.identifier
    )


def _rotation_euler(transform_object) -> tuple[float, float, float]:
    """Return a transform's rotation as XYZ Euler radians for a node socket."""
    if transform_object.rotation_mode == "QUATERNION":
        return tuple(transform_object.rotation_quaternion.to_euler("XYZ"))
    if transform_object.rotation_mode == "AXIS_ANGLE":
        return tuple(transform_object.matrix_basis.to_euler("XYZ"))
    return tuple(transform_object.rotation_euler)


def _affine_control_output(node_group, group_input, driven: DrivenChannel):
    """Build the minimal math nodes for one affine control expression."""
    output = group_input_output(group_input, driven.socket)
    if driven.factor != 1.0:
        multiply = node_group.nodes.new("ShaderNodeMath")
        multiply.operation = "MULTIPLY"
        multiply.inputs[1].default_value = driven.factor
        multiply.hide = True
        node_group.links.new(output, multiply.inputs[0])
        output = multiply.outputs[0]
    if driven.offset:
        add = node_group.nodes.new("ShaderNodeMath")
        add.operation = "ADD"
        add.inputs[1].default_value = driven.offset
        add.hide = True
        node_group.links.new(output, add.inputs[0])
        output = add.outputs[0]
    return output


def _transform_chain(
    mesh_object,
    hierarchy_root: TransformNode,
    object_parents: dict[bpy.types.Object, TransformNode],
) -> list[object]:
    """Return local transforms from one mesh leaf up to the hierarchy root."""
    chain: list[object] = []
    current: object | None = mesh_object
    while current is not None:
        chain.append(current)
        if current == hierarchy_root:
            break
        current = (
            object_parents.get(current)
            if current == mesh_object
            else current.parent
        )
    if not chain or chain[-1] != hierarchy_root:
        raise ValueError(f"source mesh {mesh_object.name!r} is outside the import hierarchy")
    return chain


def _attach_transform_node(
    node_group,
    group_input,
    geometry,
    transform_object,
    controls: dict[tuple[str, int], DrivenChannel],
):
    """Append one Transform Geometry node, including its driven XYZ inputs."""
    translation = tuple(transform_object.location)
    rotation = _rotation_euler(transform_object)
    scale = tuple(transform_object.scale)
    if (
        not controls
        and translation == (0.0, 0.0, 0.0)
        and rotation == (0.0, 0.0, 0.0)
        and scale == (1.0, 1.0, 1.0)
    ):
        return geometry

    transform = node_group.nodes.new("GeometryNodeTransform")
    transform.label = transform_object.name
    transform.inputs["Translation"].default_value = translation
    transform.inputs["Rotation"].default_value = rotation
    transform.inputs["Scale"].default_value = scale
    node_group.links.new(geometry, transform.inputs["Geometry"])

    defaults = {
        "translation": translation,
        "rotation": rotation,
        "scale": scale,
    }
    for channel_name, channel_defaults in defaults.items():
        driven_axes = {
            axis: driven
            for (name, axis), driven in controls.items()
            if name == channel_name
        }
        if not driven_axes:
            continue

        # Transform Geometry expects a vector/rotation socket.  Combine XYZ
        # keeps untouched axes at their static values and replaces only the
        # components that have modifier controls.
        combine = node_group.nodes.new("ShaderNodeCombineXYZ")
        combine.hide = True
        for axis, axis_name in enumerate(("X", "Y", "Z")):
            combine.inputs[axis_name].default_value = channel_defaults[axis]
            driven = driven_axes.get(axis)
            if driven is not None:
                node_group.links.new(
                    _affine_control_output(node_group, group_input, driven),
                    combine.inputs[axis_name],
                )
        node_group.links.new(
            combine.outputs["Vector"],
            transform.inputs[channel_name.title()],
        )
    return transform.outputs["Geometry"]


def compile_hierarchy(
    controller_nodes: ControllerNodes,
    source_collection,
    hierarchy_root: TransformNode,
    transform_controls: TransformControls,
    object_parents: dict[bpy.types.Object, TransformNode],
) -> None:
    """Compile build-time transform records into the controller node graph."""
    node_group = controller_nodes.modifier.node_group
    nodes = node_group.nodes
    links = node_group.links
    mesh_objects = [
        obj for obj in source_collection.all_objects if obj.type == "MESH"
    ]

    # Phase 1: create one graph branch per source mesh and replay its complete
    # ancestor chain as Transform Geometry nodes. Shared TransformNode records
    # still compile independently because each leaf needs an explicit dataflow.
    for mesh_object in mesh_objects:
        # Object Info references the unlinked source datablock.  Realizing this
        # leaf internally lets later face-domain material and parity operations
        # work without forcing the public output to be realized.
        object_info = nodes.new("GeometryNodeObjectInfo")
        object_info.label = mesh_object.name
        object_info.transform_space = "ORIGINAL"
        object_info.inputs["Object"].default_value = mesh_object
        object_info.inputs["As Instance"].default_value = True
        leaf_realize = nodes.new("GeometryNodeRealizeInstances")
        leaf_realize.label = "Read Source Mesh"
        links.new(object_info.outputs["Geometry"], leaf_realize.inputs["Geometry"])

        store_parity = nodes.new("GeometryNodeStoreNamedAttribute")
        store_parity.data_type = "BOOLEAN"
        store_parity.domain = "FACE"
        store_parity.inputs["Name"].default_value = _TRANSFORM_PARITY_ATTRIBUTE
        links.new(leaf_realize.outputs["Geometry"], store_parity.inputs["Geometry"])
        geometry = store_parity.outputs["Geometry"]

        # Static mirror parity is accumulated while transforms are attached and
        # stored on faces before all branches join. Dynamic whole-model reversal
        # is combined with this attribute in the next phase.
        negative_determinant = False
        for transform_object in _transform_chain(
            mesh_object,
            hierarchy_root,
            object_parents,
        ):
            scale = tuple(transform_object.scale)
            if scale[0] * scale[1] * scale[2] < 0.0:
                negative_determinant = not negative_determinant
            geometry = _attach_transform_node(
                node_group,
                controller_nodes.group_input,
                geometry,
                transform_object,
                transform_controls.get(transform_object, {}),
            )

        store_parity.inputs["Value"].default_value = negative_determinant
        links.new(geometry, controller_nodes.source_geometry.inputs["Geometry"])

    # Phase 2: correct winding once after branch joining but before the model is
    # wrapped as an instance, so materials and normals behave identically for
    # both realized and non-realized public output.
    _correct_face_orientation(
        node_group,
        controller_nodes.group_input,
        controller_nodes.geometry_to_instance,
        hierarchy_root,
        transform_controls,
    )

    # Phase 3: erase redundant object-space state. Complete placement now lives
    # in Transform Geometry nodes, so the graph is the only authority and hidden
    # object state cannot change the procedural result.
    for mesh_object in mesh_objects:
        mesh_object.parent = None
        mesh_object.matrix_basis = Matrix.Identity(4)
    node_group.interface_update(bpy.context)


def _correct_face_orientation(
    node_group,
    group_input,
    geometry_to_instance,
    hierarchy_root,
    transform_controls: TransformControls,
) -> None:
    """Flip faces whose complete transform has a negative determinant."""
    links = node_group.links
    instance_input = geometry_to_instance.inputs["Geometry"]
    source_link = instance_input.links[0]
    source_output = source_link.from_socket
    links.remove(source_link)

    parity = node_group.nodes.new("GeometryNodeInputNamedAttribute")
    parity.data_type = "BOOLEAN"
    parity.inputs["Name"].default_value = _TRANSFORM_PARITY_ATTRIBUTE
    selection = parity.outputs["Attribute"]

    # Reverse is represented as X scale = 1 - 2 * socket.  XOR with the static
    # parity flips all faces only when the whole-model mirror is enabled.
    reverse = transform_controls.get(hierarchy_root, {}).get(("scale", 0))
    if reverse is not None and reverse.offset == 1.0 and reverse.factor == -2.0:
        xor = node_group.nodes.new("FunctionNodeBooleanMath")
        xor.operation = "XOR"
        links.new(selection, xor.inputs[0])
        links.new(group_input_output(group_input, reverse.socket), xor.inputs[1])
        selection = xor.outputs[0]

    flip_faces = node_group.nodes.new("GeometryNodeFlipFaces")
    flip_faces.label = "Correct Mirrored Face Orientation"
    links.new(source_output, flip_faces.inputs["Mesh"])
    links.new(selection, flip_faces.inputs["Selection"])
    links.new(flip_faces.outputs["Mesh"], instance_input)


def add_dimension_controls(
    dimension_nodes: list[dict[str, Any]],
    *,
    controller_nodes: ControllerNodes,
    panel,
    transform_controls: TransformControls,
) -> int:
    """Expose configurable package dimensions as bounded distance inputs."""
    if not dimension_nodes:
        return 0

    modifier = controller_nodes.modifier
    node_group = modifier.node_group
    used_names = {
        item.name for item in node_group.interface.items_tree if item.parent == panel
    }
    pending_defaults = []

    for data in dimension_nodes:
        label = str(data["label"])
        target = data["object"]
        for dimension in data["dimensions"]:
            base_name = f"{label}: {dimension.name}" if label else dimension.name
            socket_name = _unique_interface_name(base_name, used_names)
            socket = node_group.interface.new_socket(
                name=socket_name,
                in_out="INPUT",
                socket_type="NodeSocketFloat",
                parent=panel,
            )
            make_socket_single_value(socket)

            # Promob stores dimension metadata in millimetres.  Blender's
            # distance socket and all generated geometry use metres.
            socket.subtype = "DISTANCE"
            socket.default_value = dimension.default * 0.001
            socket.min_value = dimension.minimum * 0.001
            socket.max_value = dimension.maximum * 0.001
            socket.description = (
                f"Mooble range: {dimension.minimum:g}–{dimension.maximum:g} mm"
            )
            pending_defaults.append(
                (socket, dimension.default * 0.001, target, dimension.axis)
            )

    # Interface sockets must be materialized before Blender exposes modifier
    # storage for their initial values.
    node_group.interface_update(bpy.context)
    for socket, default_value, target, axis in pending_defaults:
        set_modifier_value(modifier, socket, default_value)
        record_transform_control(
            transform_controls,
            target,
            "scale",
            axis,
            socket,
            factor=1.0 / default_value,
        )
    node_group.interface_update(bpy.context)

    count = len(pending_defaults)
    if count:
        controller_nodes.controller["mooblender_dimension_control_count"] = count
    return count


def add_visibility_controls(
    option_nodes: list[dict[str, Any]],
    *,
    controller_nodes: ControllerNodes,
    panel,
    transform_controls: TransformControls,
) -> int:
    """Expose optional components as grouped, single-value Boolean inputs."""
    if not option_nodes:
        return 0

    modifier = controller_nodes.modifier
    node_group = modifier.node_group
    used_names = {
        item.name for item in node_group.interface.items_tree if item.parent == panel
    }

    # Coupled products often describe one baseboard as several aggregate
    # segments.  Grouping by the displayed component name gives the user one
    # switch that controls the complete logical part.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for data in option_nodes:
        grouped.setdefault(str(data["label"]), []).append(data)

    for label, components in grouped.items():
        socket = node_group.interface.new_socket(
            name=_unique_interface_name(label, used_names),
            in_out="INPUT",
            socket_type="NodeSocketBool",
            parent=panel,
        )
        make_socket_single_value(socket)
        socket.default_value = True
        socket.description = f"Show or hide {label}"
        node_group.interface_update(bpy.context)
        set_modifier_value(modifier, socket, True)

        # Visibility is represented as the component's original scale
        # multiplied by the Boolean socket (False = zero scale).
        for data in components:
            for axis, scale in enumerate(data["default_scale"]):
                record_transform_control(
                    transform_controls,
                    data["object"],
                    "scale",
                    axis,
                    socket,
                    factor=scale,
                )

    node_group.interface_update(bpy.context)
    count = len(grouped)
    controller_nodes.controller["mooblender_option_control_count"] = count
    return count


def add_mirror_control(
    package: PContentPackage,
    *,
    hierarchy_root: TransformNode,
    controller_nodes: ControllerNodes,
    panel,
    transform_controls: TransformControls,
) -> bool:
    """Add whole-model reversal when Promob marks the package as mirrorable."""
    if not can_mirror(package.properties):
        return False

    modifier = controller_nodes.modifier
    socket = modifier.node_group.interface.new_socket(
        name="Reverse",
        in_out="INPUT",
        socket_type="NodeSocketBool",
        parent=panel,
    )
    make_socket_single_value(socket)
    socket.default_value = False
    socket.description = "Mirror the complete model while preserving its footprint"
    modifier.node_group.interface_update(bpy.context)
    set_modifier_value(modifier, socket, False)

    # Mirroring around X=0 would move a positive-width model into negative X.
    # Translating by min+max reflects around the source footprint midpoint.
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

    record_transform_control(
        transform_controls,
        hierarchy_root,
        "scale",
        0,
        socket,
        offset=1.0,
        factor=-2.0,
    )
    record_transform_control(
        transform_controls,
        hierarchy_root,
        "translation",
        0,
        socket,
        factor=mirror_offset,
    )
    controller_nodes.controller["mooblender_can_mirror"] = True
    return True


def _model_groups(package: PContentPackage):
    """Collect finish definitions and material packages from the package tree."""
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
                        # Entity scope prevents a same-named child layer from
                        # receiving the root package's material selection.
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
                    assignments = (
                        {
                            str(component.get("LayerId")): str(
                                component.get("MaterialId")
                            )
                            for component in components
                            if isinstance(component, dict)
                            and component.get("LayerId")
                            and component.get("MaterialId")
                        }
                        if isinstance(components, list)
                        else {}
                    )
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
    """Create or reuse every material referenced by a finish group."""
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
    """Return stable, unique display names for a finish menu's options."""
    names: list[str] = []
    counts: dict[str, int] = {}
    for index, option in enumerate(options):
        base = str(option.get("name") or option.get("id") or f"Style {index + 1}")
        count = counts.get(base, 0) + 1
        counts[base] = count
        names.append(base if count == 1 else f"{base} ({count})")
    return names


def _set_modifier_menu_value(modifier, socket, name: str, index: int) -> None:
    """Initialize a menu socket using the API available in this Blender version."""
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


def finish_part_name(group_name: str, fallback: str = "Main") -> str:
    """Turn generic finish-definition names into concise part labels."""
    words = group_name.strip().split()
    if words and words[0].casefold() == "acabamento":
        words.pop(0)
    if words and words[-1].casefold() == "finish":
        words.pop()
    return " ".join(words) or fallback


def _material_applications(bundled_groups, materials):
    """Return layers whose every menu option resolved to a real material."""
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
    """Reserve a unique display name within one interface panel."""
    name = base
    suffix = 2
    while name in used_names:
        name = f"{base} ({suffix})"
        suffix += 1
    used_names.add(name)
    return name


def _create_style_menu(node_group, group_input, socket, option_names):
    """Create the menu-to-integer conversion used by material switches."""
    socket_name = socket.name
    option_output = group_input_output(group_input, socket)
    style_switch = node_group.nodes.new("GeometryNodeMenuSwitch")
    style_switch.data_type = "INT"
    style_switch.enum_items.clear()
    for index, name in enumerate(option_names):
        style_switch.enum_items.new(name)
        style_switch.inputs[index + 1].default_value = index

    # from_socket copies the enum definition required by Blender, but it also
    # copies the generic source name "Menu".  Restore our component label.
    socket.from_socket(style_switch, style_switch.inputs["Menu"])
    socket.name = socket_name
    node_group.links.new(option_output, style_switch.inputs["Menu"])
    return style_switch


def _material_selection(node_group, scope: int, layer: str):
    """Build the face selection for one package scope and PMob layer."""
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
    """Map one selected style index to the material for a specific layer."""
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
    """Append Set Material nodes for every compatible package layer."""
    for scope, options, layers in applications:
        for layer in layers:
            selection = _material_selection(node_group, scope, layer)
            material = _material_index_switch(
                node_group,
                style_index,
                scope,
                layer,
                options,
                materials,
            )
            set_material = node_group.nodes.new("GeometryNodeSetMaterial")
            node_group.links.new(selection, set_material.inputs["Selection"])
            node_group.links.new(material, set_material.inputs["Material"])
            node_group.links.new(geometry, set_material.inputs["Geometry"])
            geometry = set_material.outputs["Geometry"]
    return geometry


def add_material_options(
    package: PContentPackage,
    *,
    controller_nodes: ControllerNodes,
    material_cache: dict[tuple[int, int], bpy.types.Material],
) -> int:
    """Add named finish menus and apply their materials before instancing."""
    groups = _model_groups(package)
    materials = _create_remote_materials(groups, material_cache)
    if not materials:
        return 0

    entries = []
    for (group_name, option_names), bundled_groups in _material_bundles(groups).items():
        applications = _material_applications(bundled_groups, materials)
        if applications:
            entries.append((group_name, option_names, applications))
    if not entries:
        return 0

    modifier = controller_nodes.modifier
    node_group = modifier.node_group
    links = node_group.links
    instance_geometry = controller_nodes.geometry_to_instance.inputs["Geometry"]
    source_output = instance_geometry.links[0].from_socket
    for link in list(instance_geometry.links):
        links.remove(link)

    finish_panel = node_group.interface.new_panel(
        name="Finish",
        description="Material styles available for each model part",
        default_closed=False,
    )
    geometry = source_output
    menu_defaults = []
    used_names: set[str] = set()

    for group_name, option_names, applications in entries:
        socket = node_group.interface.new_socket(
            name=_unique_interface_name(finish_part_name(group_name), used_names),
            in_out="INPUT",
            socket_type="NodeSocketMenu",
            parent=finish_panel,
        )
        make_socket_single_value(socket)
        socket.description = " / ".join(option_names)
        style_switch = _create_style_menu(
            node_group,
            controller_nodes.group_input,
            socket,
            option_names,
        )
        geometry = _apply_materials(
            node_group,
            geometry,
            style_switch.outputs["Output"],
            applications,
            materials,
        )
        socket.default_value = option_names[0]
        menu_defaults.append((socket, option_names[0], 0))

    # Set Material must run before Geometry to Instance so the default
    # non-realized output and the optional realized output share finishes.
    links.new(geometry, instance_geometry)
    node_group.interface_update(bpy.context)
    for socket, name, index in menu_defaults:
        _set_modifier_menu_value(modifier, socket, name, index)
    node_group.interface_update(bpy.context)
    controller_nodes.controller["mooblender_material_option_count"] = len(
        menu_defaults
    )
    return len(menu_defaults)
