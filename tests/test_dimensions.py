from __future__ import annotations

import unittest

from mooblender.model.dimensions import (
    bounding_box_dimensions,
    configurable_dimensions,
    document_geometry_dimensions,
    property_dimensions,
    serialized_geometry_dimensions,
)
from mooblender.model.scene import Mesh, PmobDocument, Primitive, SceneLayer


class DimensionTests(unittest.TestCase):
    def test_insert_dimension_exposes_only_axes_with_a_variable_range(self):
        properties = {
            "Dimension": {"Width": "600", "Depth": "150", "Height": "15"},
            "InsertDimension": {
                "Min": {"X": 10.0, "Y": 10.0, "Z": 0.0},
                "Max": {"X": 2740.0, "Y": 1840.0, "Z": 0.0},
            },
        }

        dimensions = configurable_dimensions(properties)

        self.assertEqual([value.name for value in dimensions], ["Largura", "Profundidade"])
        self.assertEqual(
            [
                (value.axis, value.default, value.minimum, value.maximum)
                for value in dimensions
            ],
            [(0, 600.0, 10.0, 2740.0), (1, 150.0, 10.0, 1840.0)],
        )

    def test_insert_dimension_accepts_domain_width_depth_names(self):
        properties = {
            "Dimension": {"Width": 600, "Depth": 150, "Height": 15},
            "InsertDimension": {
                "Min": {"Width": 100, "Depth": 100, "Height": 15},
                "Max": {"Width": 1200, "Depth": 100, "Height": 15},
            },
        }

        self.assertEqual(
            [
                (value.name, value.minimum, value.maximum)
                for value in configurable_dimensions(properties)
            ],
            [("Largura", 100.0, 1200.0)],
        )

    def test_drawing_dimension_describes_serialized_geometry(self):
        properties = {
            "Dimension": {"Width": "100", "Depth": "15", "Height": "100"},
            "DrawingDimension": {
                "Width": "376.9",
                "Depth": "17.5",
                "Height": "105.1",
            },
        }

        self.assertEqual(property_dimensions(properties), (100.0, 15.0, 100.0))
        self.assertEqual(
            serialized_geometry_dimensions(properties),
            (376.9, 17.5, 105.1),
        )

    def test_bounding_box_fills_missing_drawing_axes(self):
        properties = {
            "DrawingDimension": {"Width": "50", "Depth": None, "Height": None},
            "GeometryBoundingBox": {
                "Min": {"X": 0, "Y": -20, "Z": 10},
                "Max": {"X": 50, "Y": 0, "Z": 110},
            },
        }

        self.assertEqual(bounding_box_dimensions(properties), (50.0, 20.0, 100.0))
        self.assertEqual(
            serialized_geometry_dimensions(properties),
            (50.0, 20.0, 100.0),
        )

    def test_aggregate_expressions_use_parent_and_child_dimensions(self):
        raw = {"Dimension": {"Width": "($PW$/2)-19", "Height": "395"}}

        self.assertEqual(
            property_dimensions(
                raw,
                variables={"PW": 800, "W": 100, "D": 15, "H": 100},
                fallback=(100.0, 15.0, 100.0),
            ),
            (381.0, 15.0, 395.0),
        )

    def test_document_geometry_includes_primitive_transforms(self):
        document = PmobDocument(
            primitive=Primitive(
                matrix=(
                    2.0, 0.0, 0.0, 0.0,
                    0.0, 3.0, 0.0, 0.0,
                    0.0, 0.0, 4.0, 0.0,
                    100.0, 200.0, 300.0, 1.0,
                ),
                children=[Primitive(layer_ref="Panel")],
            ),
            layers=[
                SceneLayer(
                    name="Panel",
                    meshes=[
                        Mesh(
                            vertices=[
                                (0.0, 0.0, 0.0),
                                (50.0, 20.0, 10.0),
                            ]
                        )
                    ],
                )
            ],
        )

        self.assertEqual(document_geometry_dimensions(document), (100.0, 60.0, 40.0))
        self.assertEqual(
            serialized_geometry_dimensions(
                {"DrawingDimension": {"Width": 50, "Depth": 50, "Height": 50}},
                document=document,
            ),
            (100.0, 60.0, 40.0),
        )


if __name__ == "__main__":
    unittest.main()
