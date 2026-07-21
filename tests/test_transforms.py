from __future__ import annotations

import unittest

from mooblender.model.transforms import blender_matrix_rows, transform_point_row_vector


class TransformTests(unittest.TestCase):
    def test_transposes_source_matrix_and_scales_only_translation(self):
        source = (
            10.0, 2.0, 3.0, 0.0,
            4.0, 20.0, 6.0, 0.0,
            7.0, 8.0, 30.0, 0.0,
            1000.0, 2000.0, 3000.0, 1.0,
        )

        self.assertEqual(
            blender_matrix_rows(source),
            (
                (10.0, 4.0, 7.0, 1.0),
                (2.0, 20.0, 8.0, 2.0),
                (3.0, 6.0, 30.0, 3.0),
                (0.0, 0.0, 0.0, 1.0),
            ),
        )

    def test_source_point_uses_row_vector_translation(self):
        source = (
            2.0, 0.0, 0.0, 0.0,
            0.0, 3.0, 0.0, 0.0,
            0.0, 0.0, 4.0, 0.0,
            10.0, 20.0, 30.0, 1.0,
        )

        self.assertEqual(transform_point_row_vector((1.0, 2.0, 3.0), source), (12.0, 26.0, 42.0))


if __name__ == "__main__":
    unittest.main()
