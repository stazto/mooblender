"""Named synthetic regressions for catalog models that exposed importer bugs.

The real catalog packages are not redistributable.  These tests retain only the
small metadata, geometry, and expression characteristics that caused each bug.
"""

from __future__ import annotations

import math
import unittest

from mooblender.model.dimensions import (
    configurable_dimensions,
    dimension_variables,
    document_geometry_dimensions,
    property_dimensions,
)
from mooblender.model.expressions import evaluate_expression
from mooblender.model.openings import control_name, door_motion
from mooblender.model.scene import Mesh, PmobDocument, Primitive, SceneLayer
from mooblender.model.topology import prepare_mesh
from mooblender.model.transforms import blender_matrix_rows, transform_point_row_vector


class ReportedModelRegressionTests(unittest.TestCase):
    def test_onix_kitchen_kit_preserves_root_scale_and_millimetre_translation(self):
        """Kit de Cozinha Onix used a 10x PMob root scale, not a unit matrix."""

        root = (
            10.0, 0.0, 0.0, 0.0,
            0.0, 10.0, 0.0, 0.0,
            0.0, 0.0, 10.0, 0.0,
            1000.0, 0.0, 0.0, 1.0,
        )

        self.assertEqual(transform_point_row_vector((100.0, 0.0, 0.0), root), (2000.0, 0.0, 0.0))
        self.assertEqual(blender_matrix_rows(root)[0], (10.0, 0.0, 0.0, 1.0))

    def test_728_pair_has_named_independent_symmetric_outward_door_motions(self):
        service = {
            "Type": "Door",
            "X": "@($INVERTED$?-$WIDTH$+($DEPTH$/2):$WIDTH$-$DEPTH$/2)",
            "Y": "-$DEPTH$/2",
            "Max": "90",
            "Invert": "@($INVERTED$?0:1)",
        }
        left = {**service, "Description": "Esq"}
        right = {**service, "Description": "Dir"}
        dimensions = (381.0, 15.0, 395.0)

        left_pivot, left_angle = door_motion(left, dimensions, inverted=True)
        right_pivot, right_angle = door_motion(right, dimensions, inverted=False)

        self.assertEqual(
            (control_name(left, "Part"), control_name(right, "Part")),
            ("Door: Esq", "Door: Dir"),
        )
        self.assertEqual(left_pivot, right_pivot)
        self.assertAlmostEqual(left_angle, math.pi / 2)
        self.assertAlmostEqual(right_angle, math.pi / 2)
        left_hinge = 0.399 - left_pivot[0] * 0.001
        right_hinge = 0.401 + right_pivot[0] * 0.001
        self.assertAlmostEqual(left_hinge + right_hinge, 0.8)
        self.assertLess(-left_pivot[0] * math.sin(left_angle), 0.0)
        self.assertLess(-right_pivot[0] * math.sin(right_angle), 0.0)

    def test_pe27_exposes_width_and_depth_but_not_fixed_height(self):
        properties = {
            "Dimension": {"Width": 600, "Depth": 150, "Height": 15},
            "InsertDimension": {
                "Min": {"X": 10, "Y": 10, "Z": 15},
                "Max": {"X": 2740, "Y": 1840, "Z": 15},
            },
        }

        controls = configurable_dimensions(properties)

        self.assertEqual(
            [(item.name, item.axis) for item in controls],
            [("Largura", 0), ("Profundidade", 1)],
        )
        self.assertEqual(
            [(item.minimum, item.maximum) for item in controls],
            [(10.0, 2740.0), (10.0, 1840.0)],
        )

    def test_r678_constant_door_metadata_is_distinct_from_variable_dimensions(self):
        """A broad child range must not override a Constant aggregate edge."""

        aggregate = {
            "Description": "Door",
            "Constant": True,
            "Dimension": {"Width": 376.9, "Depth": 17.5, "Height": 105.1},
        }
        child_properties = {
            "Dimension": {"Width": 100, "Depth": 15, "Height": 100},
            "InsertDimension": {
                "Min": {"X": 10, "Y": 15, "Z": 10},
                "Max": {"X": 1000, "Y": 15, "Z": 1000},
            },
        }

        self.assertTrue(aggregate["Constant"])
        self.assertEqual(
            [item.name for item in configurable_dimensions(child_properties)],
            ["Largura", "Altura"],
        )
        self.assertEqual(property_dimensions(aggregate), (376.9, 17.5, 105.1))

    def test_sup01_0003_selects_only_one_drawer_body_variant(self):
        variables = dimension_variables((400.0, 500.0, 878.0), parent=(400.0, 500.0, 878.0))
        alternatives = (
            "$PARENTHEIGHT$>=700",
            "$PARENTHEIGHT$<700",
        )

        selected = [bool(evaluate_expression(condition, variables)) for condition in alternatives]

        self.assertEqual(selected, [True, False])
        self.assertEqual(sum(selected), 1)

    def test_44950_007_positions_drawers_from_drawing_depth_not_mesh_envelope(self):
        drawing_dimensions = (650.0, 570.0, 760.0)
        measured_mesh_depth = 645.0
        variables = dimension_variables(drawing_dimensions, parent=drawing_dimensions)

        drawer_y = evaluate_expression("-$PARENTDEPTH$-28", variables)

        self.assertEqual(drawer_y, -598.0)
        self.assertNotEqual(drawer_y, -measured_mesh_depth - 28.0)

    def test_10122_handle_source_dimensions_include_primitive_transforms(self):
        document = PmobDocument(
            primitive=Primitive(
                matrix=(
                    1.0, 0.0, 0.0, 0.0,
                    0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, 0.0,
                    20.0, 0.0, 50.0, 1.0,
                ),
                children=[Primitive(layer_ref="Handle")],
            ),
            layers=[
                SceneLayer(
                    name="Handle",
                    meshes=[Mesh(vertices=[(0.0, 0.0, 0.0), (100.0, 15.0, 49.0)])],
                )
            ],
        )

        self.assertEqual(document_geometry_dimensions(document), (100.0, 15.0, 49.0))

    def test_4220a_shared_material_components_retain_same_geometry_scale(self):
        """Equivalent panels must measure alike before one shared UV mapping."""

        mesh = Mesh(vertices=[(0.0, 0.0, 0.0), (600.0, 15.0, 400.0)])
        document = PmobDocument(
            primitive=Primitive(
                children=[Primitive(layer_ref="Body"), Primitive(layer_ref="Drawer")]
            ),
            layers=[
                SceneLayer(name="Body", meshes=[mesh]),
                SceneLayer(name="Drawer", meshes=[mesh]),
            ],
        )

        self.assertEqual(document_geometry_dimensions(document), (600.0, 15.0, 400.0))
        repetitions_per_metre = 1000.0 / 150.0
        self.assertAlmostEqual(repetitions_per_metre, 6.666666666666667)

    def test_porta_de_giro_31_resolves_long_parent_dimension_variables(self):
        parent = (980.0, 190.0, 2189.0)
        leaf = (800.0, 80.1, 2100.0)
        variables = dimension_variables(leaf, parent=parent)
        dimensions = property_dimensions(
            {
                "Dimension": {
                    "Width": "$PARENTWIDTH$-180",
                    "Depth": "$DEPTH$",
                    "Height": "$PARENTHEIGHT$-90",
                }
            },
            variables=variables,
            fallback=leaf,
        )

        self.assertEqual(dimensions, (800.0, 80.1, 2099.0))

    def test_porta_de_correr_21_distributes_three_panels_across_frame(self):
        parent = (980.0, 190.0, 2189.0)
        variables = dimension_variables((0.0, 0.0, 0.0), parent=parent)
        width = evaluate_expression("($PARENTWIDTH$+12)/3", variables)
        positions = [
            evaluate_expression(f"{index}*$PARENTWIDTH$/3", variables)
            for index in range(3)
        ]

        self.assertAlmostEqual(width, 330.6666666666667)
        self.assertEqual(positions, [0.0, 326.6666666666667, 653.3333333333334])

    def test_duplicate_vertices_merge_only_when_normal_fans_are_smooth(self):
        angle = math.radians(30.0)
        source = Mesh(
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, math.cos(angle), math.sin(angle)),
            ],
            indices=[0, 1, 2, 3, 4, 5],
        )

        prepared = prepare_mesh(source)

        self.assertEqual(len(prepared.vertices), 4)
        self.assertEqual(prepared.removed_vertex_count, 2)


if __name__ == "__main__":
    unittest.main()
