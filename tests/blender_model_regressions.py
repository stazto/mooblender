"""Named regression tests that require Blender's real Geometry Nodes API."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import bpy
from mathutils import Vector

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import mooblender  # noqa: E402
from mooblender.blender.scene_builder import (  # noqa: E402
    _aggregate_orientation,
    build_document,
)
from mooblender.formats.pcontent import PContentPackage, ResolvedAggregate  # noqa: E402
from mooblender.model.scene import Material, Mesh, PmobDocument, SceneLayer  # noqa: E402
from tests.blender_smoke import (  # noqa: E402
    _geometry_source_collection,
    _modifier_inputs_reaching_output,
    _remove_import,
    _set_modifier_input,
    _source_instance_matrix,
    _source_transform_labels,
)


def _part_package(name: str = "Part") -> PContentPackage:
    return PContentPackage(
        document=PmobDocument(
            name=name,
            layers=[
                SceneLayer(
                    name=name,
                    meshes=[
                        Mesh(
                            vertices=[
                                (0.0, 0.0, 0.0),
                                (100.0, 0.0, 0.0),
                                (0.0, 10.0, 10.0),
                            ],
                            indices=[0, 1, 2],
                            material_id=0,
                        )
                    ],
                )
            ],
            materials=[Material(name="Handle", color=(5, 5, 5, 255))],
        ),
        properties={
            "Dimension": {"Width": 100, "Depth": 10, "Height": 10},
            "DrawingDimension": {"Width": 100, "Depth": 10, "Height": 10},
            "InsertDimension": {
                "Min": {"X": 10, "Y": 10, "Z": 10},
                "Max": {"X": 1000, "Y": 10, "Z": 1000},
            },
        },
    )


def _closed_part_package(name: str = "Closed part") -> PContentPackage:
    package = _part_package(name)
    package.document.layers[0].meshes[0] = Mesh(
        vertices=[
            (0, 0, 0),
            (100, 0, 0),
            (100, 100, 0),
            (0, 100, 0),
            (0, 0, 100),
            (100, 0, 100),
            (100, 100, 100),
            (0, 100, 100),
        ],
        indices=[
            0, 2, 1, 0, 3, 2,
            4, 5, 6, 4, 6, 7,
            0, 1, 5, 0, 5, 4,
            3, 7, 6, 3, 6, 2,
            0, 4, 7, 0, 7, 3,
            1, 2, 6, 1, 6, 5,
        ],
        material_id=0,
    )
    return package


def _signed_volume(controller) -> float:
    evaluated = controller.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    volume = sum(
        mesh.vertices[polygon.vertices[0]].co.dot(
            mesh.vertices[polygon.vertices[1]].co.cross(
                mesh.vertices[polygon.vertices[2]].co
            )
        )
        / 6.0
        for polygon in mesh.polygons
    )
    evaluated.to_mesh_clear()
    return volume


class BlenderReportedModelRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mooblender.register()

    @classmethod
    def tearDownClass(cls):
        mooblender.unregister()

    def setUp(self):
        self.controllers = []

    def tearDown(self):
        for controller in reversed(self.controllers):
            if controller.name in bpy.data.objects:
                _remove_import(controller)

    def _build(self, package: PContentPackage, name: str):
        controller = build_document(package, bpy.context, collection_name=name)
        self.controllers.append(controller)
        bpy.context.view_layer.update()
        return controller

    def test_r678_constant_door_only_exposes_opening_and_keeps_black_handle(self):
        child = _part_package("R678 Handle")
        package = PContentPackage(
            document=None,
            properties={
                "Dimension": {"Width": 600, "Depth": 350, "Height": 700},
                "Aggregates": [
                    {
                        "Description": "Door",
                        "Constant": True,
                        "Dimension": {"Width": 376.9, "Depth": 17.5, "Height": 105.1},
                    }
                ],
                "OpenServices": [
                    {
                        "Type": "Door",
                        "AggregatePath": [0, 0],
                        "Description": "1ª",
                        "X": "$W$-$D$/2",
                        "Y": "-$D$/2",
                        "Max": "90",
                    }
                ],
            },
            resolved_aggregates=[
                ResolvedAggregate(index=0, specification_id="door", package=child)
            ],
        )

        controller = self._build(package, "R678 regression")
        modifier = controller.modifiers["Mooblender"]
        float_sockets = {
            item.name: item
            for item in modifier.node_group.interface.items_tree
            if item.item_type == "SOCKET"
            and item.socket_type == "NodeSocketFloat"
        }

        self.assertEqual(set(float_sockets), {"Door: 1ª"})
        self.assertEqual(float_sockets["Door: 1ª"].structure_type, "SINGLE")
        self.assertEqual(float_sockets["Door: 1ª"].parent.name, "Doors and Drawers")
        source = _geometry_source_collection(controller)
        material = next(
            obj for obj in source.all_objects if obj.type == "MESH"
        ).data.materials[0]
        observed = tuple(round(value, 6) for value in material.diffuse_color[:3])
        self.assertEqual(observed, (round(5 / 255, 6),) * 3)

    def test_c66_mirror_and_inverted_parts_preserve_outward_face_orientation(self):
        child = _closed_part_package("C66 door")
        package = PContentPackage(
            document=None,
            properties={
                "Dimension": {"Width": 200, "Depth": 100, "Height": 100},
                "Limits": {
                    "Min": {"X": 0},
                    "Max": {"X": 200},
                },
                "Attributes": {"CANMIRROR": {"VALUE": "True"}},
                "Aggregates": [
                    {
                        "Description": "Left door",
                        "Dimension": {"Width": 100, "Depth": 100, "Height": 100},
                    },
                    {
                        "Description": "Right door",
                        "Dimension": {"Width": 100, "Depth": 100, "Height": 100},
                        "Position": {"X": 200},
                        "Inverted": True,
                    },
                ],
            },
            resolved_aggregates=[
                ResolvedAggregate(0, "left", child),
                ResolvedAggregate(1, "right", child),
            ],
        )
        controller = self._build(package, "C66 normals")
        modifier = controller.modifiers["Mooblender"]
        sockets = {
            item.name: item
            for item in modifier.node_group.interface.items_tree
            if item.item_type == "SOCKET"
        }
        _set_modifier_input(modifier, sockets["Realize Instances"], True)

        baseline_volume = _signed_volume(controller)
        self.assertGreater(baseline_volume, 0.0)
        _set_modifier_input(modifier, sockets["Reverse"], True)
        reversed_volume = _signed_volume(controller)
        self.assertGreater(reversed_volume, 0.0)
        self.assertAlmostEqual(reversed_volume, baseline_volume, places=6)

    def test_c67_imports_selected_door_and_exposes_optional_components(self):
        door_p1 = _part_package("C67 Door P1")
        door_p2 = _part_package("C67 Door P2")
        top = _part_package("C67 Top")
        baseboard = _part_package("C67 Baseboard")
        package = PContentPackage(
            document=None,
            properties={
                "Dimension": {"Width": 790, "Depth": 790, "Height": 820},
                "Limits": {
                    "Min": {"X": 0, "Y": -790, "Z": 0},
                    "Max": {"X": 790, "Y": 0, "Z": 820},
                },
                "Attributes": {"CANMIRROR": {"VALUE": "True"}},
                "Models": [
                    {
                        "Id": "coz_bal|plain",
                        "ModelDefinitionId": "coz_bal",
                        "Informations": {"TIPO": "P2"},
                    },
                    {
                        "Id": "coz_bal|mixed",
                        "ModelDefinitionId": "coz_bal",
                        "Informations": {"TIPO": "P1"},
                    },
                ],
                "References": {"C67": {"ModelsId": ["coz_bal|mixed"]}},
                "Aggregates": [
                    {
                        "Description": "Porta",
                        "Concurrent": True,
                        "Constant": True,
                        "VisibleCondition": '@Coz_bal(TIPO)@ == "P1"',
                        "Dimension": {"Width": 400, "Depth": 15, "Height": 625},
                    },
                    {"Description": "Tampo", "Concurrent": True, "Coupled": True},
                    {"Description": "Rodapé", "Concurrent": True},
                    {
                        "Description": "Porta Inferior",
                        "Concurrent": True,
                        "Constant": True,
                        "VisibleCondition": '@Coz_bal(TIPO)@ == "P2"',
                        "Dimension": {"Width": 400, "Depth": 15, "Height": 625},
                    },
                ],
                "OpenServices": [
                    {
                        "Type": "Door",
                        "AggregatePath": [0, 0],
                        "Description": "Porta",
                        "X": "$D$/2",
                        "Y": "-$D$/2",
                        "Max": "90",
                    },
                    {
                        "Type": "Door",
                        "AggregatePath": [3, 0],
                        "Description": "Porta Inferior",
                        "X": "$D$/2",
                        "Y": "-$D$/2",
                        "Max": "90",
                    },
                ],
            },
            resolved_aggregates=[
                ResolvedAggregate(0, "door-p1", door_p1),
                ResolvedAggregate(1, "top", top),
                ResolvedAggregate(2, "baseboard", baseboard),
                ResolvedAggregate(3, "door-p2", door_p2),
            ],
        )

        controller = self._build(package, "C67 regression")
        modifier = controller.modifiers["Mooblender"]
        interface = modifier.node_group.interface.items_tree
        option_sockets = {
            item.name: item
            for item in interface
            if item.item_type == "SOCKET"
            and item.socket_type == "NodeSocketBool"
            and item.parent is not None
            and item.parent.name == "Options"
        }
        opening_sockets = {
            item.name
            for item in interface
            if item.item_type == "SOCKET"
            and item.socket_type == "NodeSocketFloat"
            and item.parent is not None
            and item.parent.name == "Doors and Drawers"
        }
        source = _geometry_source_collection(controller)
        source_meshes = list(source.all_objects)
        transformed_parts = {
            label
            for obj in source_meshes
            for label in _source_transform_labels(controller, obj)
        }

        self.assertEqual(set(option_sockets), {"Tampo", "Rodapé", "Reverse"})
        self.assertTrue(
            all(socket.structure_type == "SINGLE" for socket in option_sockets.values())
        )
        self.assertEqual(opening_sockets, {"Porta"})
        self.assertTrue(
            all(
                any(label.startswith(part) for label in transformed_parts)
                for part in ("Porta", "Tampo", "Rodapé")
            )
        )
        self.assertFalse(
            any(label.startswith("Porta Inferior") for label in transformed_parts)
        )
        self.assertTrue(all(obj.type == "MESH" for obj in source_meshes))
        self.assertEqual(controller["mooblender_option_control_count"], 2)
        self.assertEqual(controller["mooblender_open_service_count"], 1)
        active_inputs = _modifier_inputs_reaching_output(modifier.node_group)
        self.assertTrue(
            {socket.identifier for socket in option_sockets.values()} <= active_inputs
        )

        _set_modifier_input(modifier, option_sockets["Rodapé"], False)
        baseboard_mesh = next(
            obj
            for obj in source_meshes
            if "Rodapé" in _source_transform_labels(controller, obj)
        )
        self.assertEqual(
            tuple(
                round(value, 6)
                for value in _source_instance_matrix(
                    controller, baseboard_mesh
                ).to_scale()
            ),
            (0, 0, 0),
        )
        _set_modifier_input(modifier, option_sockets["Rodapé"], True)
        self.assertEqual(
            tuple(
                round(value, 6)
                for value in _source_instance_matrix(
                    controller, baseboard_mesh
                ).to_scale()
            ),
            (1, 1, 1),
        )

        door_mesh = next(
            obj
            for obj in source_meshes
            if any(
                label.startswith("Porta")
                for label in _source_transform_labels(controller, obj)
            )
        )
        baseline_matrix = _source_instance_matrix(controller, door_mesh)
        baseline_points = [baseline_matrix @ vertex.co for vertex in door_mesh.data.vertices]
        _set_modifier_input(modifier, option_sockets["Reverse"], True)
        reverse_matrix = _source_instance_matrix(controller, door_mesh)
        reversed_points = [reverse_matrix @ vertex.co for vertex in door_mesh.data.vertices]
        for baseline, reversed_point in zip(
            baseline_points, reversed_points, strict=True
        ):
            self.assertAlmostEqual(reversed_point.x, 0.79 - baseline.x)
            self.assertAlmostEqual(reversed_point.y, baseline.y)
            self.assertAlmostEqual(reversed_point.z, baseline.z)

    def test_modifier_keeps_nested_instances_until_top_option_realizes_them(self):
        controller = self._build(_part_package("Instance hierarchy"), "Instances")
        modifier = controller.modifiers["Mooblender"]
        interface_items = modifier.node_group.interface.items_tree
        realize_socket = next(
            item for item in interface_items if item.name == "Realize Instances"
        )
        source_join = next(
            node
            for node in modifier.node_group.nodes
            if node.bl_idname == "GeometryNodeJoinGeometry"
            and node.label == "Transformed Source Meshes"
        )

        self.assertFalse(realize_socket.default_value)
        self.assertGreaterEqual(len(source_join.inputs["Geometry"].links), 1)
        self.assertFalse(
            any(obj.type == "EMPTY" for obj in _geometry_source_collection(controller).all_objects)
        )
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        instances = [
            item
            for item in depsgraph.object_instances
            if item.is_instance
            and item.parent is not None
            and item.parent.original == controller
        ]
        self.assertEqual(
            len(instances),
            len(_geometry_source_collection(controller).all_objects),
        )
        evaluated = controller.evaluated_get(depsgraph)
        self.assertEqual(len(evaluated.to_mesh().polygons), 0)
        evaluated.to_mesh_clear()

        _set_modifier_input(modifier, realize_socket, True)

        evaluated = controller.evaluated_get(bpy.context.evaluated_depsgraph_get())
        self.assertEqual(len(evaluated.to_mesh().polygons), 1)
        evaluated.to_mesh_clear()

    def test_ela_2_opposing_side_normals_keep_both_carriages_above_anchor(self):
        part = _part_package("Lift carriage")
        package = PContentPackage(
            document=None,
            properties={
                "Dimension": {"Width": 300, "Depth": 100, "Height": 800},
                "Aggregates": [
                    {
                        "Description": "Left carriage",
                        "Dimension": {"Width": 100, "Depth": 10, "Height": 10},
                        "Position": {"X": -100, "Rotation": 180},
                        "Normal": {"X": -1, "Y": 0, "Z": 0},
                    },
                    {
                        "Description": "Right carriage",
                        "Dimension": {"Width": 100, "Depth": 10, "Height": 10},
                        "Position": {"X": 100, "Rotation": 180},
                        "Normal": {"X": 1, "Y": 0, "Z": 0},
                    },
                ],
            },
            resolved_aggregates=[
                ResolvedAggregate(index=0, specification_id="left", package=part),
                ResolvedAggregate(index=1, specification_id="right", package=part),
            ],
        )

        controller = self._build(package, "ELA-2 regression")
        source = _geometry_source_collection(controller)
        bounds = []
        for obj in (item for item in source.all_objects if item.type == "MESH"):
            points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
            bounds.append((min(point.z for point in points), max(point.z for point in points)))

        self.assertEqual(len(bounds), 2)
        self.assertTrue(all(minimum >= -1e-6 for minimum, _maximum in bounds))
        self.assertAlmostEqual(bounds[0][0], bounds[1][0])
        self.assertAlmostEqual(bounds[0][1], bounds[1][1])

    def test_10122_side_normal_rotation_keeps_local_front_height_positive(self):
        for normal in (Vector((-1.0, 0.0, 0.0)), Vector((1.0, 0.0, 0.0))):
            orientation = _aggregate_orientation(normal, math.pi)
            vertical = orientation @ Vector((1.0, 0.0, 0.0))
            self.assertGreater(vertical.z, 0.999999)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(BlenderReportedModelRegressions)
    )
    if not result.wasSuccessful():
        raise SystemExit(1)
