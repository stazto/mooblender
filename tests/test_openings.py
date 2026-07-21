from __future__ import annotations

import math
import unittest

from mooblender.model.openings import door_motion, service_name


class OpeningTests(unittest.TestCase):
    def test_service_name_matches_mooble_pt_br_name(self):
        service = {
            "Description": "Left",
            "Localizations": [
                {"Id": "en-us", "Name": "Left"},
                {"Id": "pt-br", "Name": "Esq"},
            ],
        }

        self.assertEqual(service_name(service, "Door"), "Esq")

    def test_service_name_falls_back_to_description_then_component(self):
        self.assertEqual(service_name({"Description": "Gaveta"}, "Part"), "Gaveta")
        self.assertEqual(service_name({}, "Part"), "Part")

    def test_mirrored_pair_uses_opposite_world_hinges_and_opens_outward(self):
        service = {
            "X": "@($I$?-$W$+($D$/2):$W$-$D$/2)",
            "Y": "-$D$/2",
            "Max": "90",
            "Invert": "@($INVERTED$?0:1)",
        }

        left_pivot, left_angle = door_motion(
            service,
            (381.0, 15.0, 395.0),
            inverted=True,
        )
        right_pivot, right_angle = door_motion(
            service,
            (381.0, 15.0, 395.0),
            inverted=False,
        )

        self.assertEqual(left_pivot, (373.5, -7.5, 0.0))
        self.assertEqual(right_pivot, (373.5, -7.5, 0.0))
        self.assertAlmostEqual(left_angle, math.pi / 2)
        self.assertAlmostEqual(right_angle, math.pi / 2)
        left_hinge_world = 0.399 - left_pivot[0] * 0.001
        right_hinge_world = 0.401 + right_pivot[0] * 0.001
        self.assertAlmostEqual(left_hinge_world, 0.0255)
        self.assertAlmostEqual(right_hinge_world, 0.7745)
        self.assertAlmostEqual(left_hinge_world + right_hinge_world, 0.8)
        self.assertLess(-left_pivot[0] * math.sin(left_angle), 0.0)
        self.assertLess(-right_pivot[0] * math.sin(right_angle), 0.0)


if __name__ == "__main__":
    unittest.main()
