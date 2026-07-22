from __future__ import annotations

import unittest

from mooblender.model.customization import (
    is_optional_aggregate,
    selected_model_information,
)


class CustomizationTests(unittest.TestCase):
    def test_reference_selects_model_information_used_by_visibility_rules(self):
        properties = {
            "Models": [
                {
                    "Id": "finish|plain",
                    "ModelDefinitionId": "finish",
                    "Informations": {"TYPE": "P2"},
                },
                {
                    "Id": "finish|mixed",
                    "ModelDefinitionId": "finish",
                    "Informations": {"TYPE": "P1"},
                },
            ],
            "References": {
                "reference": {"ModelsId": ["finish|mixed"]},
            },
        }

        self.assertEqual(
            selected_model_information(properties),
            {"finish": {"type": "P1"}},
        )

    def test_first_model_is_fallback_when_reference_omits_group(self):
        properties = {
            "Models": [
                {
                    "Id": "handle|black",
                    "ModelDefinitionId": "handle",
                    "Informations": {"SIDE": "LEFT"},
                }
            ]
        }

        self.assertEqual(
            selected_model_information(properties),
            {"handle": {"side": "LEFT"}},
        )

    def test_only_nonconstant_concurrent_aggregates_are_optional(self):
        self.assertTrue(is_optional_aggregate({"Concurrent": True}))
        self.assertFalse(
            is_optional_aggregate({"Concurrent": True, "Constant": True})
        )
        self.assertFalse(
            is_optional_aggregate({"Concurrent": True, "AlwaysVisible": True})
        )
        self.assertFalse(is_optional_aggregate({"Concurrent": False}))


if __name__ == "__main__":
    unittest.main()
