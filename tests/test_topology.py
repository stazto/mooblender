from __future__ import annotations

import math
import unittest

from mooblender.model.scene import Mesh
from mooblender.model.topology import prepare_mesh


class TopologyTests(unittest.TestCase):
    def test_welds_uv_seams_but_keeps_corner_uvs(self):
        source = Mesh(
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (0.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
                (0.0, 1.0, 0.0),
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

        topology = prepare_mesh(source)

        self.assertEqual(len(topology.vertices), 4)
        self.assertEqual(topology.removed_vertex_count, 2)
        self.assertEqual(topology.faces, [(0, 1, 2), (0, 2, 3)])
        self.assertEqual(topology.loop_uvs, source.texture_coordinates)

    def test_preserves_duplicate_positions_at_hard_edges(self):
        source = Mesh(
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
            ],
            indices=[0, 1, 2, 3, 4, 5],
        )

        topology = prepare_mesh(source)

        self.assertEqual(len(topology.vertices), 6)
        self.assertEqual(topology.removed_vertex_count, 0)
        self.assertEqual(topology.faces, [(0, 1, 2), (3, 4, 5)])

    def test_welds_generated_normal_fans_below_observed_smooth_angle(self):
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

        topology = prepare_mesh(source)

        self.assertEqual(len(topology.vertices), 4)
        self.assertEqual(topology.faces, [(0, 1, 2), (0, 1, 3)])
        self.assertAlmostEqual(topology.loop_normals[0][1], -math.sin(angle / 2.0))
        self.assertAlmostEqual(topology.loop_normals[0][2], math.cos(angle / 2.0))

    def test_serialized_normals_remain_authoritative(self):
        source = Mesh(
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (1.0, 1.0, 0.0),
            ],
            indices=[0, 1, 2, 3, 4, 5],
            normals=[(0.0, 0.0, 1.0)] * 3 + [(0.0, 1.0, 0.0)] * 3,
            smooth_groups=[[0, 3], [1, 4]],
        )

        topology = prepare_mesh(source)

        self.assertEqual(len(topology.vertices), 6)
        self.assertEqual(topology.loop_normals, source.normals)

    def test_explicit_groups_preserve_omitted_hard_edges(self):
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
            # Only the first coincident pair is explicitly smooth. Although the
            # faces meet below 45 degrees, the second pair must stay a hard edge.
            smooth_groups=[[0, 3]],
        )

        topology = prepare_mesh(source)

        self.assertEqual(len(topology.vertices), 5)
        self.assertEqual(topology.removed_vertex_count, 1)
        self.assertEqual(topology.faces, [(0, 1, 2), (0, 3, 4)])

    def test_generates_continuous_normals_for_smoothing_groups(self):
        source = Mesh(
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 0.0),
                (0.0, 0.0, 1.0),
                (1.0, 0.0, 0.0),
            ],
            indices=[0, 1, 2, 3, 4, 5],
            smooth_groups=[[0, 3], [1, 5]],
        )

        topology = prepare_mesh(source)

        expected = math.sqrt(0.5)
        self.assertEqual(len(topology.vertices), 4)
        self.assertEqual(topology.faces, [(0, 1, 2), (0, 3, 1)])
        for loop_index in (0, 1, 3, 5):
            self.assertAlmostEqual(topology.loop_normals[loop_index][1], expected)
            self.assertAlmostEqual(topology.loop_normals[loop_index][2], expected)


if __name__ == "__main__":
    unittest.main()
