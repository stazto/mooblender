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


def _remove_import(controller) -> None:
    modifier = controller.modifiers.get("Mooblender")
    node_groups = {modifier.node_group} if modifier and modifier.node_group else set()
    source_collections = {
        node.inputs["Collection"].default_value
        for node_group in node_groups
        for node in node_group.nodes
        if node.bl_idname == "GeometryNodeCollectionInfo"
        and node.inputs["Collection"].default_value is not None
    }
    objects = {controller}
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
    for source_collection in source_collections:
        bpy.data.collections.remove(source_collection)
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
    controller = None
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

        seam_source = Mesh(
            vertices=[
                (0.0, 0.0, 0.0),
                (100.0, 0.0, 0.0),
                (100.0, 100.0, 0.0),
                (0.0, 0.0, 0.0),
                (100.0, 100.0, 0.0),
                (0.0, 100.0, 0.0),
            ],
            indices=[0, 1, 2, 3, 4, 5],
            normals=[(0.0, 0.0, 1.0)] * 6,
            texture_coordinates=[
                (0.0, 0.0),
                (1.0, 0.0),
                (1.0, 1.0),
                (0.25, 0.0),
                (0.75, 1.0),
                (0.0, 1.0),
            ],
            smooth_groups=[[0, 3], [2, 4]],
        )
        seam_document = PmobDocument(
            name="UV seam topology",
            primitive=Primitive(
                name="UV seam",
                kind=PrimitiveType.LAYER,
                layer_ref="Seam",
            ),
            layers=[SceneLayer(name="Seam", meshes=[seam_source])],
        )
        seam_controller = build_document(
            seam_document,
            bpy.context,
            collection_name="UV seam topology",
        )
        seam_collection = _geometry_source_collection(seam_controller)
        seam_mesh = next(obj.data for obj in seam_collection.all_objects if obj.type == "MESH")
        if len(seam_mesh.vertices) != 4:
            raise AssertionError("UV-seam vertices were not compacted")
        if seam_mesh.get("mooblender_welded_vertex_count") != 2:
            raise AssertionError("mesh does not report its compacted vertex count")
        if not seam_mesh.has_custom_normals or not all(
            polygon.use_smooth for polygon in seam_mesh.polygons
        ):
            raise AssertionError("PMob normals were not applied as smooth corner normals")
        seam_uvs = seam_mesh.uv_layers[0].data
        if tuple(seam_uvs[0].uv) != (0.0, 0.0) or tuple(seam_uvs[3].uv) != (0.25, 0.0):
            raise AssertionError("welding discarded distinct UV coordinates at a seam")
        _remove_import(seam_controller)

        source = Mesh(
            vertices=[(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 120.0, 0.0)],
            indices=[0, 1, 2],
            texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            material_id=0,
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
            materials=[Material(name="Near black", color=(5, 5, 5, 255))],
        )
        collection_count = len(bpy.data.collections)
        static_controller = build_document(
            document,
            bpy.context,
            collection_name="Static model",
        )
        static_source = _geometry_source_collection(static_controller)
        if tuple(static_controller.users_collection) != (bpy.context.collection,):
            raise AssertionError("import did not link its object to the active collection")
        if len(bpy.data.collections) != collection_count + 1:
            raise AssertionError("single-object import created a visible import collection")
        static_modifier = static_controller.modifiers["Mooblender"]
        if any(
            item.socket_type == "NodeSocketFloat"
            for item in static_modifier.node_group.interface.items_tree
        ):
            raise AssertionError("static model received an unnecessary opening control")
        static_object = next(obj for obj in static_source.all_objects if obj.type == "MESH")
        static_material = static_object.data.materials[0]
        if any(abs(value - 5 / 255) > 1e-6 for value in static_material.diffuse_color[:3]):
            raise AssertionError("PMob RGBA color channels were interpreted in the wrong order")
        duplicate_controller = build_document(
            document,
            bpy.context,
            collection_name="Static model duplicate",
        )
        duplicate_source = _geometry_source_collection(duplicate_controller)
        duplicate_object = next(
            obj for obj in duplicate_source.all_objects if obj.type == "MESH"
        )
        if duplicate_object.data.materials[0] is not static_material:
            raise AssertionError("an exactly equal existing material was not reused")
        _remove_import(duplicate_controller)
        static_material.roughness = 0.25
        changed_controller = build_document(
            document,
            bpy.context,
            collection_name="Static model after material edit",
        )
        changed_source = _geometry_source_collection(changed_controller)
        changed_object = next(
            obj for obj in changed_source.all_objects if obj.type == "MESH"
        )
        if changed_object.data.materials[0] is static_material:
            raise AssertionError("a user-modified material was incorrectly reused")
        _remove_import(changed_controller)
        _remove_import(static_controller)

        oriented_part = PContentPackage(
            document=PmobDocument(
                name="Oriented part",
                version=2,
                layers=[
                    SceneLayer(
                        name="Oriented",
                        meshes=[
                            Mesh(
                                vertices=[
                                    (0.0, 0.0, 0.0),
                                    (0.0, 10.0, 0.0),
                                    (0.0, 0.0, 100.0),
                                ],
                                indices=[0, 1, 2],
                            )
                        ],
                    )
                ],
                materials=[Material(name="Oriented", color=(12, 34, 56, 255))],
            ),
            properties={
                "Dimension": {"Width": 10, "Depth": 10, "Height": 100},
                "DrawingDimension": {"Width": 10, "Depth": 10, "Height": 100},
            },
        )
        orientation_package = PContentPackage(
            document=None,
            properties={
                "Dimension": {"Width": 500, "Depth": 400, "Height": 300},
                "Aggregates": [
                    {
                        "Description": "Visible oriented part",
                        "Dimension": {"Width": 10, "Depth": 10, "Height": 100},
                        "Position": {"X": 100, "Y": 0, "Z": 0, "Rotation": 180},
                        "Normal": {"X": -1, "Y": 0, "Z": 0},
                        "VisibleCondition": "$PH$>=300",
                    },
                    {
                        "Description": "Hidden alternate part",
                        "Dimension": {"Width": 10, "Depth": 10, "Height": 100},
                        "Position": {"X": 400, "Y": 0, "Z": 0},
                        "VisibleCondition": "$PH$<100",
                    },
                ],
            },
            resolved_aggregates=[
                ResolvedAggregate(index=0, specification_id="visible", package=oriented_part),
                ResolvedAggregate(index=1, specification_id="hidden", package=oriented_part),
            ],
        )
        orientation_controller = build_document(
            orientation_package,
            bpy.context,
            collection_name="Aggregate metadata",
        )
        bpy.context.view_layer.update()
        orientation_source = _geometry_source_collection(orientation_controller)
        orientation_meshes = [
            obj for obj in orientation_source.all_objects if obj.type == "MESH"
        ]
        if len(orientation_meshes) != 1:
            raise AssertionError("aggregate VisibleCondition did not hide its alternate")
        orientation_points = [
            orientation_meshes[0].matrix_world @ vertex.co
            for vertex in orientation_meshes[0].data.vertices
        ]
        orientation_extents = tuple(
            max(point[axis] for point in orientation_points)
            - min(point[axis] for point in orientation_points)
            for axis in range(3)
        )
        if tuple(round(value, 3) for value in orientation_extents) != (0.1, 0.01, 0.0):
            raise AssertionError("aggregate Normal did not orient the child geometry")
        _remove_import(orientation_controller)

        root_material = PContentPackage(
            document=PmobDocument(
                name="Root Finish",
                materials=[
                    Material(
                        name="Root Finish",
                        color=(64, 128, 255, 255),
                        metallic=0.25,
                        roughness=0.75,
                        diffuse_texture="compatibility.png",
                        mapping_type=1,
                        mapping_scale=(1000.0, 2000.0),
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
                    ),
                    Primitive(
                        name="Fixed Handle",
                        kind=PrimitiveType.LAYER,
                        layer_ref="Handle",
                    ),
                    Primitive(
                        name="Fixed Top Trim",
                        kind=PrimitiveType.LAYER,
                        layer_ref="Top Trim",
                    ),
                ],
            ),
            layers=[
                SceneLayer(
                    name="Compatibility",
                    meshes=[
                        Mesh(
                            vertices=[
                                (10.0, 0.0, 0.0),
                                (100.0, 0.0, 0.0),
                                (10.0, 90.0, 0.0),
                            ],
                            indices=source.indices,
                            texture_coordinates=source.texture_coordinates,
                            material_id=-1,
                        )
                    ],
                ),
                SceneLayer(
                    name="Handle",
                    meshes=[
                        Mesh(
                            vertices=[
                                (0.0, 0.0, 0.0),
                                (10.0, 0.0, 0.0),
                                (0.0, 100.0, 0.0),
                            ],
                            indices=[0, 1, 2],
                            material_id=-1,
                        )
                    ],
                ),
                SceneLayer(
                    name="Top Trim",
                    meshes=[
                        Mesh(
                            vertices=[
                                (0.0, 90.0, 0.0),
                                (100.0, 90.0, 0.0),
                                (0.0, 100.0, 0.0),
                            ],
                            indices=[0, 1, 2],
                            material_id=-1,
                        )
                    ],
                ),
            ],
        )
        child_a = PContentPackage(
            document=PmobDocument(
                name="Child A",
                materials=[
                    Material(
                        name="Child A",
                        color=(255, 0, 0, 255),
                        mapping_type=1,
                        mapping_scale=(1000.0, 1000.0),
                    )
                ],
            )
        )
        child_b = PContentPackage(
            document=PmobDocument(
                name="Child B",
                materials=[
                    Material(
                        name="Child B",
                        color=(0, 0, 255, 255),
                        mapping_type=1,
                        mapping_scale=(1000.0, 1000.0),
                    )
                ],
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
                            {"LayerId": "Compatibility", "MaterialId": "child-a"},
                            {
                                "LayerId": "Handle",
                                "MaterialId": "child-a",
                                "Edit": False,
                            },
                            {
                                "LayerId": "Top Trim",
                                "MaterialId": "child-a",
                                "Edit": False,
                            },
                        ],
                    },
                    {
                        "Id": "child-b",
                        "Name": "Child B",
                        "ModelDefinitionId": "child-finish",
                        "ModelDefinitionName": "Child finish",
                        "Components": [
                            {"LayerId": "Compatibility", "MaterialId": "child-b"},
                            {
                                "LayerId": "Handle",
                                "MaterialId": "child-b",
                                "Edit": False,
                            },
                            {
                                "LayerId": "Top Trim",
                                "MaterialId": "child-b",
                                "Edit": False,
                            },
                        ],
                    },
                    {
                        "Id": "child-a-copy",
                        "Name": "Child A",
                        "ModelDefinitionId": "child-finish-copy",
                        "ModelDefinitionName": "Child finish",
                        "Components": [
                            {"LayerId": "Compatibility", "MaterialId": "child-a"},
                            {
                                "LayerId": "Handle",
                                "MaterialId": "child-a",
                                "Edit": False,
                            },
                            {
                                "LayerId": "Top Trim",
                                "MaterialId": "child-a",
                                "Edit": False,
                            },
                        ],
                    },
                    {
                        "Id": "child-b-copy",
                        "Name": "Child B",
                        "ModelDefinitionId": "child-finish-copy",
                        "ModelDefinitionName": "Child finish",
                        "Components": [
                            {"LayerId": "Compatibility", "MaterialId": "child-b"},
                            {
                                "LayerId": "Handle",
                                "MaterialId": "child-b",
                                "Edit": False,
                            },
                            {
                                "LayerId": "Top Trim",
                                "MaterialId": "child-b",
                                "Edit": False,
                            },
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
                    },
                    {
                        "Type": "Drawer",
                        "AggregatePath": [0, 1],
                        "Max": "50",
                        "Description": "Alternate nested front",
                        "Localizations": [
                            {"Id": "pt-br", "Name": "Frente interna alternativa"}
                        ],
                    },
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
                        "Constant": True,
                        "Dimension": {"Width": 200, "Depth": 200, "Height": 1},
                        "Position": {"X": 300, "Y": "-$PD$", "Z": 0},
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
                    },
                    {
                        "Type": "Drawer",
                        "AggregatePath": [0, 1],
                        "Max": "100",
                        "Description": "Alternate child front",
                        "Localizations": [
                            {"Id": "pt-br", "Name": "Frente externa alternativa"}
                        ],
                    },
                ],
            },
            resolved_aggregates=[
                ResolvedAggregate(index=0, specification_id="child", package=child)
            ],
            resolved_materials={"root-finish": root_material},
        )
        collection_count = len(bpy.data.collections)
        controller = build_document(
            package,
            bpy.context,
        )
        bpy.context.view_layer.update()
        source_collection = _geometry_source_collection(controller)
        if tuple(controller.users_collection) != (bpy.context.collection,):
            raise AssertionError("Geometry Nodes import did not create one scene object")
        if len(bpy.data.collections) != collection_count + 1:
            raise AssertionError("Geometry Nodes import created a visible import collection")
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
        static_uvs = obj.data.uv_layers.active.data
        static_uv_extents = tuple(
            max(loop.uv[axis] for loop in static_uvs)
            - min(loop.uv[axis] for loop in static_uvs)
            for axis in range(2)
        )
        if tuple(round(value, 3) for value in static_uv_extents) != (1.0, 1.2):
            raise AssertionError(
                "cubic UVs do not represent final physical dimensions: "
                f"{static_uv_extents}"
            )
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
        mapping_node = next(
            node for node in obj.data.materials[0].node_tree.nodes if node.type == "MAPPING"
        )
        coordinate_node = next(
            node
            for node in obj.data.materials[0].node_tree.nodes
            if node.type == "TEX_COORD"
        )
        coordinate_outputs = {
            link.from_socket.name
            for link in obj.data.materials[0].node_tree.links
            if link.from_node == coordinate_node
        }
        if (
            image_nodes[0].projection != "FLAT"
            or tuple(mapping_node.inputs["Scale"].default_value) != (1.0, 0.5, 1.0)
            or coordinate_outputs != {"UV"}
        ):
            raise AssertionError("material did not use its physical UV mapping")
        modifier = controller.modifiers.get("Mooblender")
        evaluated = controller.evaluated_get(bpy.context.evaluated_depsgraph_get())
        evaluated_mesh = evaluated.to_mesh()
        if modifier is None or len(evaluated_mesh.polygons) != 5:
            raise AssertionError("single-object Geometry Nodes import is not producing geometry")
        child_placement = next(
            obj
            for obj in source_collection.all_objects
            if obj.get("promob_aggregate_index") == 0 and obj.name == "Child"
        )
        if round(child_placement.location.y, 3) != -1.0:
            raise AssertionError("aggregate expressions did not use the logical parent size")
        handle = next(
            obj
            for obj in source_collection.all_objects
            if obj.type == "MESH" and obj.get("promob_layer") == "Handle"
        )
        handle_points = [handle.matrix_world @ vertex.co for vertex in handle.data.vertices]
        handle_width = max(point.x for point in handle_points) - min(
            point.x for point in handle_points
        )
        if round(handle_width, 3) != 0.01:
            raise AssertionError("fixed-size handle stretched with its constant parent")
        child_panel = next(
            obj
            for obj in source_collection.all_objects
            if obj.type == "MESH" and obj.parent.name == "Child Compatibility"
        )
        panel_points = [
            child_panel.matrix_world @ vertex.co for vertex in child_panel.data.vertices
        ]
        panel_width = max(point.x for point in panel_points) - min(
            point.x for point in panel_points
        )
        if round(panel_width, 3) != 0.19:
            raise AssertionError("panel did not stretch around its fixed-size hardware")
        panel_height = max(point.y for point in panel_points) - min(
            point.y for point in panel_points
        )
        if round(panel_height, 3) != 0.19:
            raise AssertionError("panel did not stretch up to its fixed high-side trim")
        top_trim = next(
            obj
            for obj in source_collection.all_objects
            if obj.type == "MESH" and obj.get("promob_layer") == "Top Trim"
        )
        trim_points = [
            top_trim.matrix_world @ vertex.co for vertex in top_trim.data.vertices
        ]
        trim_bounds = (
            min(point.y for point in trim_points),
            max(point.y for point in trim_points),
        )
        if tuple(round(value, 3) for value in trim_bounds) != (-0.81, -0.8):
            raise AssertionError("fixed high-side trim moved away from the resized edge")
        if not child_panel.data.uv_layers or all(
            loop.uv.length_squared == 0.0
            for loop in child_panel.data.uv_layers.active.data
        ):
            raise AssertionError("a resized panel without source UVs was not box projected")
        panel_uvs = child_panel.data.uv_layers.active.data
        panel_u_extent = max(loop.uv.x for loop in panel_uvs) - min(
            loop.uv.x for loop in panel_uvs
        )
        if round(panel_u_extent, 3) != 0.19:
            raise AssertionError(
                "generated panel UVs do not follow its resized dimensions: "
                f"{panel_u_extent}"
            )
        interface_items = modifier.node_group.interface.items_tree
        interface_names = [item.name for item in interface_items]
        if len(interface_names) != len(set(interface_names)):
            raise AssertionError(f"duplicate node interface entries: {interface_names}")
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
        }
        if set(control_sockets) != expected_controls:
            raise AssertionError(
                f"unexpected component/dimension controls: {set(control_sockets)}"
            )
        if any(socket.structure_type != "SINGLE" for socket in control_sockets.values()):
            raise AssertionError("modifier float controls are fields instead of single values")
        group_input = next(
            node
            for node in modifier.node_group.nodes
            if node.bl_idname == "NodeGroupInput"
        )
        if any(
            not group_input.outputs[socket.name].is_linked
            for socket in control_sockets.values()
        ):
            raise AssertionError("modifier controls are disconnected and appear disabled")
        for name in ("Gaveta externa", "Gaveta interna"):
            socket = control_sockets[name]
            if socket.min_value != 0.0 or socket.max_value != 1.0:
                raise AssertionError(f"opening range is invalid for {name}")
        dimension_ranges = {
            "Largura": (1.0, 0.1, 2.0),
            "Profundidade": (1.0, 0.05, 2.0),
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
        finish_socket = next(
            item
            for item in modifier.node_group.interface.items_tree
            if item.name == "Finish: Child finish"
        )
        if finish_socket.socket_type != "NodeSocketMenu":
            raise AssertionError("finish control is not a named menu")
        if finish_socket.structure_type != "SINGLE":
            raise AssertionError("finish control is a field instead of a single value")
        if sum(item.name == "Finish: Child finish" for item in interface_items) != 1:
            raise AssertionError("identical material controls were not consolidated")
        menu_switch = next(
            node
            for node in modifier.node_group.nodes
            if node.bl_idname == "GeometryNodeMenuSwitch"
        )
        if [item.name for item in menu_switch.enum_items] != ["Child A", "Child B"]:
            raise AssertionError("finish menu does not expose source style names")
        if sum(
            node.bl_idname == "GeometryNodeMenuSwitch"
            for node in modifier.node_group.nodes
        ) != 1:
            raise AssertionError("identical material groups created duplicate menu nodes")
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
        if controller is not None and controller.name in bpy.data.objects:
            _remove_import(controller)
        if registered:
            mooblender.unregister()


if __name__ == "__main__":
    main()
