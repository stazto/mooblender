from __future__ import annotations

import unittest

from mooblender.model.dimensions import (
    bounding_box_dimensions,
    document_geometry_dimensions,
    property_dimensions,
    serialized_geometry_dimensions,
)
from mooblender.model.scene import Mesh, PmobDocument, Primitive, SceneLayer


class DimensionTests(unittest.TestCase):
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
