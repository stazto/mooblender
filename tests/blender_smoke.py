"""Headless registration and scene-building smoke test for supported Blender LTS releases."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import bpy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import mooblender  # noqa: E402
from mooblender.blender import operators  # noqa: E402
from mooblender.blender.panels import PROMOB_PT_browser  # noqa: E402
from mooblender.blender.scene_builder import build_document  # noqa: E402
from mooblender.formats.pcontent import PContentPackage, ResolvedAggregate  # noqa: E402
from mooblender.model.scene import (  # noqa: E402
    Material,
    Mesh,
    PmobDocument,
    Primitive,
    PrimitiveType,
    SceneLayer,
)
from mooblender.mooble.models import CatalogItem, CatalogPage  # noqa: E402


def _set_modifier_input(modifier, socket, value) -> None:
    interface_inputs = getattr(getattr(modifier, "properties", None), "inputs", None)
    if interface_inputs is not None and hasattr(interface_inputs, socket.identifier):
        getattr(interface_inputs, socket.identifier).value = value
    else:
        modifier[socket.identifier] = value
    modifier.node_group.interface_update(bpy.context)
    modifier.id_data.update_tag(refresh={"OBJECT"})
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()


def _remove_collection(collection) -> None:
    source_collections = set()
    node_groups = set()
    for obj in collection.all_objects:
        for modifier in obj.modifiers:
            if modifier.type != "NODES" or modifier.node_group is None:
                continue
            node_groups.add(modifier.node_group)
            source_collections.update(
                node.inputs["Collection"].default_value
                for node in modifier.node_group.nodes
                if node.bl_idname == "GeometryNodeCollectionInfo"
                and node.inputs["Collection"].default_value is not None
            )
    objects = set(collection.all_objects)
    for source_collection in source_collections:
        objects.update(source_collection.all_objects)
    meshes = {obj.data for obj in objects if obj.type == "MESH"}
    materials = {
        material
        for mesh in meshes
        for material in mesh.materials
        if material is not None
    }
    for obj in objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in meshes:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for child_collection in list(collection.children):
        bpy.data.collections.remove(child_collection)
    for source_collection in source_collections:
        bpy.data.collections.remove(source_collection)
    bpy.data.collections.remove(collection)
    for node_group in node_groups:
        if node_group.users == 0:
            bpy.data.node_groups.remove(node_group)
    for material in materials:
        if material.users == 0:
            bpy.data.materials.remove(material)


def _geometry_source_collection(controller):
    modifier = controller.modifiers.get("Mooblender")
    if modifier is None or modifier.node_group is None:
        raise AssertionError("Geometry Nodes controller has no Mooblender node group")
    source = next(
        (
            node.inputs["Collection"].default_value
            for node in modifier.node_group.nodes
            if node.bl_idname == "GeometryNodeCollectionInfo"
        ),
        None,
    )
    if source is None:
        raise AssertionError("Mooblender node group has no source collection")
    return source


def main() -> None:
    collection = None
    registered = False
    try:
        mooblender.register()
        registered = True
        if PROMOB_PT_browser.bl_category != "Mooble":
            raise AssertionError("Mooblender panel is not in the Mooble sidebar tab")
        if not getattr(PROMOB_PT_browser, "is_registered", False):
            raise AssertionError("Mooblender panel did not register")
        if not hasattr(bpy.types.WindowManager, "promob_browser"):
            raise AssertionError("Mooblender browser state did not register")
        state = bpy.context.window_manager.promob_browser
        if state.is_loading or state.is_syncing:
            raise AssertionError("Mooblender browser started in a loading state")

        class LocalStore:
            def __init__(self):
                self.calls = []
                self.root = CatalogPage(
                    items=(
                        CatalogItem(
                            id="onix",
                            name="Armário Ônix",
                            brand="CHF Móveis",
                            collection="Ônix",
                        ),
                        *tuple(
                            CatalogItem(id=f"item-{index}", name=f"Item {index}")
                            for index in range(12)
                        ),
                    ),
                    current_url="https://catalog.mooble.com/index",
                )
                self.kitchen = CatalogPage(
                    items=(
                        CatalogItem(
                            id="onix",
                            name="Armário Ônix",
                            brand="CHF Móveis",
                            collection="Ônix",
                        ),
                    ),
                    current_url="https://catalog.mooble.com/kitchen",
                )
                self.cached = CatalogPage(
                    items=(CatalogItem(id="cached", name="Cached model"),),
                    current_url="https://catalog.mooble.com/cached",
                )

            def exists(self):
                return True

            def root_url(self):
                return self.root.current_url

            def page(self, url=""):
                self.calls.append(url)
                target = url or self.root.current_url
                return {
                    self.root.current_url: self.root,
                    self.kitchen.current_url: self.kitchen,
                    self.cached.current_url: self.cached,
                }.get(target)

        local_store = LocalStore()
        original_store_factory = operators._catalog_store
        operators._catalog_store = lambda: local_store
        operators._CATALOG_INDEXES.clear()
        try:
            state.history_json = json.dumps(["https://catalog.mooble.com/cached"])
            if bpy.ops.promob.catalog_back() != {"FINISHED"}:
                raise AssertionError("cached catalog back navigation did not finish")
        finally:
            operators._catalog_store = original_store_factory
        if (
            local_store.calls != ["https://catalog.mooble.com/cached"]
            or state.current_url != "https://catalog.mooble.com/cached"
            or state.items[0].item_id != "cached"
            or state.is_loading
        ):
            raise AssertionError("back navigation did not restore only the cached catalog")

        state.current_url = local_store.root.current_url
        operators._catalog_store = lambda: local_store
        operators._CATALOG_INDEXES.clear()
        try:
            state.query = "moveis onix"
            if bpy.ops.promob.catalog_search() != {"FINISHED"}:
                raise AssertionError("local catalog search did not finish")
            if [item.item_id for item in state.items] != ["onix"]:
                raise AssertionError("local catalog search did not show only matches")
            state.query = ""
            if bpy.ops.promob.catalog_search() != {"FINISHED"}:
                raise AssertionError("empty local catalog search did not finish")
            if len(state.items) != 12 or state.local_result_total != 13:
                raise AssertionError("empty local search did not restore a bounded index")
            state.current_url = local_store.kitchen.current_url
            state.history_json = json.dumps([local_store.root.current_url])
            state.manufacturer = "CHF Móveis"
            if bpy.ops.promob.catalog_search() != {"FINISHED"}:
                raise AssertionError("manufacturer filter did not finish")
            if [item.item_id for item in state.items] != ["onix"]:
                raise AssertionError("manufacturer filter did not show only its brand")
            if (
                state.current_url != local_store.kitchen.current_url
                or json.loads(state.history_json) != [local_store.root.current_url]
            ):
                raise AssertionError("manufacturer filter discarded the active category")
            state.collection_filter = "Ônix"
            if bpy.ops.promob.catalog_search() != {"FINISHED"}:
                raise AssertionError("brand collection filter did not finish")
            if [item.item_id for item in state.items] != ["onix"]:
                raise AssertionError("brand collection filter did not show its models")
            state.query = "item"
            if bpy.ops.promob.catalog_search() != {"FINISHED"} or state.items:
                raise AssertionError("manufacturer and text filters were not combined")
            state.query = ""
            state.manufacturer = "__ALL_MANUFACTURERS__"
            state.collection_filter = "__ALL_COLLECTIONS__"
            if bpy.ops.promob.catalog_back() != {"FINISHED"}:
                raise AssertionError("category Back did not restore the cached root")
            if bpy.ops.promob.catalog_load_more() != {"FINISHED"}:
                raise AssertionError("local catalog Load More did not finish")
            if len(state.items) != 13:
                raise AssertionError("local Load More contacted no API but added no results")
        finally:
            operators._catalog_store = original_store_factory

        source = Mesh(
            vertices=[(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 100.0, 0.0)],
            indices=[0, 1, 2],
            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            material_id=-1,
        )
        document = PmobDocument(
            name="Mooblender LTS Smoke Test",
            version=2,
            primitive=Primitive(
                name="Scaled Root",
                kind=PrimitiveType.GROUP,
                matrix=(
                    10.0, 0.0, 0.0, 0.0,
                    0.0, 10.0, 0.0, 0.0,
                    0.0, 0.0, 10.0, 0.0,
                    1000.0, 0.0, 0.0, 1.0,
                ),
                children=[
                    Primitive(
                        name="Compatibility",
                        kind=PrimitiveType.LAYER,
                        layer_ref="Compatibility",
                    )
                ],
            ),
            layers=[SceneLayer(name="Compatibility", meshes=[source])],
            materials=[],
        )
        static_collection = build_document(
            document,
            bpy.context,
            collection_name="Static model",
            structure_mode="GEOMETRY_NODES",
        )
        static_controller = bpy.data.objects[static_collection["promob_root_object"]]
        static_source = _geometry_source_collection(static_controller)
        if tuple(static_collection.all_objects) != (static_controller,):
            raise AssertionError("Geometry Nodes import linked helper objects to the scene")
        if static_source.name in static_collection.children:
            raise AssertionError("Geometry Nodes source collection is visible in the scene")
        static_modifier = static_controller.modifiers["Mooblender"]
        if any(
            item.socket_type == "NodeSocketFloat"
            for item in static_modifier.node_group.interface.items_tree
        ):
            raise AssertionError("static model received an unnecessary opening control")
        _remove_collection(static_collection)
        root_material = PContentPackage(
            document=PmobDocument(
                name="Root Finish",
                materials=[
                    Material(
                        name="Root Finish",
                        color=(255, 64, 128, 255),
                        metallic=0.25,
                        roughness=0.75,
                        diffuse_texture="compatibility.png",
                    )
                ],
            ),
            resources={
                "compatibility.png": base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
                    "2mP8/x8AAusB9Y9Z4GgAAAAASUVORK5CYII="
                )
            },
        )
        child_document = PmobDocument(
            name="Child",
            version=2,
            primitive=Primitive(
                name="Child Root",
                kind=PrimitiveType.GROUP,
                children=[
                    Primitive(
                        name="Child Compatibility",
                        kind=PrimitiveType.LAYER,
                        layer_ref="Compatibility",
                    )
                ],
            ),
            layers=[
                SceneLayer(
                    name="Compatibility",
                    meshes=[
                        Mesh(
                            vertices=source.vertices,
                            indices=source.indices,
                            material_id=-1,
                        )
                    ],
                )
            ],
        )
        child_a = PContentPackage(
            document=PmobDocument(
                name="Child A",
                materials=[Material(name="Child A", color=(255, 255, 0, 0))],
            )
        )
        child_b = PContentPackage(
            document=PmobDocument(
                name="Child B",
                materials=[Material(name="Child B", color=(255, 0, 0, 255))],
            )
        )
        nested = PContentPackage(
            document=PmobDocument(
                name="Nested",
                version=2,
                layers=[
                    SceneLayer(
                        name="Nested",
                        meshes=[
                            Mesh(
                                vertices=[
                                    (0.0, 0.0, 0.0),
                                    (10.0, 0.0, 0.0),
                                    (0.0, 10.0, 0.0),
                                ],
                                indices=[0, 1, 2],
                            )
                        ],
                    )
                ],
                materials=[Material(name="Nested")],
            ),
            properties={
                "Dimension": {"Width": 10, "Depth": 10, "Height": 1},
                "DrawingDimension": {"Width": 10, "Depth": 10, "Height": 1},
                "InsertDimension": {
                    "Min": {"X": 5, "Y": 10, "Z": 0},
                    "Max": {"X": 30, "Y": 10, "Z": 0},
                },
            },
        )
        child = PContentPackage(
            document=child_document,
            properties={
                "Dimension": {"Width": 100, "Depth": 100, "Height": 1},
                "DrawingDimension": {"Width": 100, "Depth": 100, "Height": 1},
                "Models": [
                    {
                        "Id": "child-a",
                        "Name": "Child A",
                        "ModelDefinitionId": "child-finish",
                        "ModelDefinitionName": "Child finish",
                        "Components": [
                            {"LayerId": "Compatibility", "MaterialId": "child-a"}
                        ],
                    },
                    {
                        "Id": "child-b",
                        "Name": "Child B",
                        "ModelDefinitionId": "child-finish",
                        "ModelDefinitionName": "Child finish",
                        "Components": [
                            {"LayerId": "Compatibility", "MaterialId": "child-b"}
                        ],
                    },
                ],
                "Aggregates": [
                    {
                        "Description": "Nested",
                        "Dimension": {"Width": 10, "Depth": 10, "Height": 1},
                        "Position": {"X": 150, "Y": 0, "Z": 0},
                    }
                ],
                "OpenServices": [
                    {
                        "Type": "Drawer",
                        "AggregatePath": [0, 0],
                        "Max": "50",
                        "Description": "Nested drawer",
                        "Localizations": [
                            {"Id": "pt-br", "Name": "Gaveta interna"}
                        ],
                    }
                ],
            },
            resolved_aggregates=[
                ResolvedAggregate(index=0, specification_id="nested", package=nested)
            ],
            resolved_materials={"child-a": child_a, "child-b": child_b},
        )
        package = PContentPackage(
            document=document,
            properties={
                "Dimension": {"Width": 1000, "Depth": 1000, "Height": 1},
                "DrawingDimension": {"Width": 1000, "Depth": 1000, "Height": 1},
                "InsertDimension": {
                    "Min": {"X": 100, "Y": 50, "Z": 0},
                    "Max": {"X": 2000, "Y": 2000, "Z": 0},
                },
                "Models": [
                    {
                        "Id": "root-finish",
                        "ModelDefinitionId": "root-finish-group",
                        "Components": [
                            {"LayerId": "Compatibility", "MaterialId": "root-finish"}
                        ],
                    }
                ],
                "Aggregates": [
                    {
                        "Description": "Child",
                        "Dimension": {"Width": 200, "Depth": 100, "Height": 1},
                        "Position": {"X": 300, "Y": 0, "Z": 0},
                    }
                ],
                "OpenServices": [
                    {
                        "Type": "Drawer",
                        "AggregatePath": [0, 0],
                        "Max": "100",
                        "Description": "Child drawer",
                        "Localizations": [
                            {"Id": "pt-br", "Name": "Gaveta externa"}
                        ],
                    }
                ],
            },
            resolved_aggregates=[
                ResolvedAggregate(index=0, specification_id="child", package=child)
            ],
            resolved_materials={"root-finish": root_material},
        )
        collection = build_document(
            package,
            bpy.context,
            structure_mode="GEOMETRY_NODES",
        )
        bpy.context.view_layer.update()
        controller = bpy.data.objects[collection["promob_root_object"]]
        source_collection = _geometry_source_collection(controller)
        if tuple(collection.all_objects) != (controller,):
            raise AssertionError("Geometry Nodes import did not create one scene object")
        if source_collection.name in collection.children:
            raise AssertionError("Geometry Nodes helpers are still linked to the scene")
        if any(
            tuple(obj.users_collection) != (source_collection,)
            for obj in source_collection.all_objects
        ):
            raise AssertionError("Geometry Nodes helper is linked outside its node source")
        obj = next(
            obj
            for obj in source_collection.all_objects
            if obj.type == "MESH"
        )
        if len(obj.data.vertices) != 3 or len(obj.data.polygons) != 1:
            raise AssertionError("scene builder produced invalid triangle geometry")
        if len(obj.data.uv_layers) != 1 or len(obj.data.materials) != 1:
            raise AssertionError("scene builder did not preserve UVs and material assignment")
        world_vertex = obj.matrix_world @ obj.data.vertices[1].co
        if tuple(round(value, 5) for value in world_vertex) != (2.0, 0.0, 0.0):
            raise AssertionError("scene builder did not apply PMob units and root transform")
        image_nodes = [
            node
            for node in obj.data.materials[0].node_tree.nodes
            if node.type == "TEX_IMAGE"
        ]
        if len(image_nodes) != 1 or image_nodes[0].image.packed_file is None:
            raise AssertionError("scene builder did not load and pack an embedded texture")
        modifier = controller.modifiers.get("Mooblender")
        evaluated = controller.evaluated_get(bpy.context.evaluated_depsgraph_get())
        evaluated_mesh = evaluated.to_mesh()
        if modifier is None or len(evaluated_mesh.polygons) != 3:
            raise AssertionError("single-object Geometry Nodes import is not producing geometry")
        interface_items = modifier.node_group.interface.items_tree
        if any(item.name == "Open Ratio" for item in interface_items):
            raise AssertionError("legacy shared Open Ratio control is still exposed")
        control_sockets = {
            item.name: item
            for item in interface_items
            if item.socket_type == "NodeSocketFloat"
        }
        expected_controls = {
            "Gaveta externa",
            "Gaveta interna",
            "Largura",
            "Profundidade",
            "Nested: Largura",
        }
        if set(control_sockets) != expected_controls:
            raise AssertionError(
                f"unexpected component/dimension controls: {set(control_sockets)}"
            )
        for name in ("Gaveta externa", "Gaveta interna"):
            socket = control_sockets[name]
            if socket.min_value != 0.0 or socket.max_value != 1.0:
                raise AssertionError(f"opening range is invalid for {name}")
        dimension_ranges = {
            "Largura": (1.0, 0.1, 2.0),
            "Profundidade": (1.0, 0.05, 2.0),
            "Nested: Largura": (0.01, 0.005, 0.03),
        }
        for name, expected in dimension_ranges.items():
            socket = control_sockets[name]
            observed = (socket.default_value, socket.min_value, socket.max_value)
            if socket.subtype != "DISTANCE" or any(
                abs(value - target) > 1e-6
                for value, target in zip(observed, expected, strict=True)
            ):
                raise AssertionError(f"dimension range is invalid for {name}: {observed}")
        motions = {
            obj.get("mooblender_open_service"): obj
            for obj in source_collection.all_objects
            if obj.get("mooblender_open_service")
        }
        _set_modifier_input(modifier, control_sockets["Gaveta externa"], 1.0)
        external_y = motions["Gaveta externa"].evaluated_get(
            bpy.context.evaluated_depsgraph_get()
        ).location.y
        internal_y = motions["Gaveta interna"].evaluated_get(
            bpy.context.evaluated_depsgraph_get()
        ).location.y
        if round(external_y, 3) != -0.1 or round(internal_y, 3) != 0.0:
            raise AssertionError("one opening control moved more than its own component")
        _set_modifier_input(modifier, control_sockets["Gaveta externa"], 0.0)
        _set_modifier_input(modifier, control_sockets["Gaveta interna"], 1.0)
        external_y = motions["Gaveta externa"].evaluated_get(
            bpy.context.evaluated_depsgraph_get()
        ).location.y
        internal_y = motions["Gaveta interna"].evaluated_get(
            bpy.context.evaluated_depsgraph_get()
        ).location.y
        if round(external_y, 3) != 0.0 or round(internal_y, 3) != -0.05:
            raise AssertionError("nested opening control is not independent")
        _set_modifier_input(modifier, control_sockets["Gaveta interna"], 0.0)

        baseline_mesh = controller.evaluated_get(
            bpy.context.evaluated_depsgraph_get()
        ).to_mesh()
        base_x = max(vertex.co.x for vertex in baseline_mesh.vertices) - min(
            vertex.co.x for vertex in baseline_mesh.vertices
        )
        base_y = max(vertex.co.y for vertex in baseline_mesh.vertices) - min(
            vertex.co.y for vertex in baseline_mesh.vertices
        )
        _set_modifier_input(modifier, control_sockets["Largura"], 2.0)
        resized = controller.evaluated_get(
            bpy.context.evaluated_depsgraph_get()
        ).to_mesh()
        resized_x = max(vertex.co.x for vertex in resized.vertices) - min(
            vertex.co.x for vertex in resized.vertices
        )
        resized_y = max(vertex.co.y for vertex in resized.vertices) - min(
            vertex.co.y for vertex in resized.vertices
        )
        if round(resized_x / base_x, 3) != 2.0 or round(resized_y / base_y, 3) != 1.0:
            raise AssertionError("Largura did not resize only the X axis")
        _set_modifier_input(modifier, control_sockets["Largura"], 1.0)
        _set_modifier_input(modifier, control_sockets["Profundidade"], 2.0)
        resized = controller.evaluated_get(
            bpy.context.evaluated_depsgraph_get()
        ).to_mesh()
        resized_x = max(vertex.co.x for vertex in resized.vertices) - min(
            vertex.co.x for vertex in resized.vertices
        )
        resized_y = max(vertex.co.y for vertex in resized.vertices) - min(
            vertex.co.y for vertex in resized.vertices
        )
        if round(resized_x / base_x, 3) != 1.0 or round(resized_y / base_y, 3) != 2.0:
            raise AssertionError("Profundidade did not resize only the Y axis")
        _set_modifier_input(modifier, control_sockets["Profundidade"], 1.0)
        evaluated_mesh = controller.evaluated_get(
            bpy.context.evaluated_depsgraph_get()
        ).to_mesh()
        used_materials = {
            evaluated_mesh.materials[polygon.material_index].name
            for polygon in evaluated_mesh.polygons
        }
        if used_materials != {"Root Finish", "Child A", "Nested"}:
            raise AssertionError(
                f"default model materials were not assigned: {used_materials}"
            )
        nested_index = next(
            index
            for index, material in enumerate(evaluated_mesh.materials)
            if material.name == "Nested"
        )
        nested_polygon = next(
            polygon
            for polygon in evaluated_mesh.polygons
            if polygon.material_index == nested_index
        )
        nested_center_x = sum(
            evaluated_mesh.vertices[index].co.x for index in nested_polygon.vertices
        ) / len(nested_polygon.vertices)
        if round(nested_center_x, 3) != 0.453:
            raise AssertionError(
                "nested aggregate position inherited geometry redimension scale: "
                f"{nested_center_x}"
            )
        nested_width = max(
            evaluated_mesh.vertices[index].co.x for index in nested_polygon.vertices
        ) - min(
            evaluated_mesh.vertices[index].co.x for index in nested_polygon.vertices
        )
        _set_modifier_input(modifier, control_sockets["Nested: Largura"], 0.02)
        resized_nested_mesh = controller.evaluated_get(
            bpy.context.evaluated_depsgraph_get()
        ).to_mesh()
        nested_index = next(
            index
            for index, material in enumerate(resized_nested_mesh.materials)
            if material.name == "Nested"
        )
        resized_nested_polygon = next(
            polygon
            for polygon in resized_nested_mesh.polygons
            if polygon.material_index == nested_index
        )
        resized_nested_width = max(
            resized_nested_mesh.vertices[index].co.x
            for index in resized_nested_polygon.vertices
        ) - min(
            resized_nested_mesh.vertices[index].co.x
            for index in resized_nested_polygon.vertices
        )
        if round(resized_nested_width / nested_width, 3) != 2.0:
            raise AssertionError("nested Largura did not resize its own package instance")
        _set_modifier_input(modifier, control_sockets["Nested: Largura"], 0.01)
        finish_socket = next(
            item
            for item in modifier.node_group.interface.items_tree
            if item.name == "Finish: Child finish"
        )
        if finish_socket.socket_type != "NodeSocketMenu":
            raise AssertionError("finish control is not a named menu")
        menu_switch = next(
            node
            for node in modifier.node_group.nodes
            if node.bl_idname == "GeometryNodeMenuSwitch"
        )
        if [item.name for item in menu_switch.enum_items] != ["Child A", "Child B"]:
            raise AssertionError("finish menu does not expose source style names")
        interface_inputs = getattr(getattr(modifier, "properties", None), "inputs", None)
        if interface_inputs is not None and hasattr(interface_inputs, finish_socket.identifier):
            _set_modifier_input(modifier, finish_socket, "Child B")
        else:
            items = modifier.id_properties_ui(
                finish_socket.identifier
            ).as_dict()["items"]
            modifier[finish_socket.identifier] = next(
                item[-1] for item in items if item[0] == "Child B"
            )
            modifier.node_group.interface_update(bpy.context)
            controller.update_tag(refresh={"OBJECT"})
            bpy.context.view_layer.update()
            bpy.context.evaluated_depsgraph_get().update()
        evaluated = controller.evaluated_get(bpy.context.evaluated_depsgraph_get())
        switched_mesh = evaluated.to_mesh()
        switched_materials = {
            switched_mesh.materials[polygon.material_index].name
            for polygon in switched_mesh.polygons
        }
        if switched_materials != {"Root Finish", "Child B", "Nested"}:
            raise AssertionError(
                "a child finish changed a same-named layer outside its package: "
                f"{switched_materials}"
            )
        print(f"Mooblender smoke test passed on Blender {bpy.app.version_string}")
    finally:
        if collection is not None:
            _remove_collection(collection)
        if registered:
            mooblender.unregister()


if __name__ == "__main__":
    main()
