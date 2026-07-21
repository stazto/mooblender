from __future__ import annotations

import unittest

from mooblender.formats.aggregates import AggregateResolutionError, resolve_aggregates
from mooblender.formats.pcontent import PContentPackage


class AggregateTests(unittest.TestCase):
    def test_resolves_first_specification_and_nested_children_once(self):
        leaf = PContentPackage(document=None)
        material = PContentPackage(document=None)
        child = PContentPackage(
            document=None,
            properties={
                "Aggregates": [{"Specifications": ["leaf"]}],
                "Models": [
                    {"Components": [{"LayerId": "body", "MaterialId": "material"}]}
                ],
            },
        )
        root = PContentPackage(
            document=None,
            properties={
                "Aggregates": [
                    {"Specifications": ["child", "alternative"]},
                    {"Specifications": ["child"]},
                ]
            },
        )
        calls = []

        def loader(specification_id):
            calls.append(specification_id)
            return {"child": child, "leaf": leaf, "material": material}[specification_id]

        resolve_aggregates(root, loader)

        self.assertEqual(calls, ["child", "material", "leaf"])
        self.assertEqual(
            [item.specification_id for item in root.resolved_aggregates],
            ["child", "child"],
        )
        self.assertEqual(child.resolved_aggregates[0].package, leaf)
        self.assertEqual(child.resolved_materials["material"], material)

    def test_rejects_cycles(self):
        root = PContentPackage(
            document=None,
            properties={"Aggregates": [{"Specifications": ["root"]}]},
        )
        with self.assertRaisesRegex(AggregateResolutionError, "cyclic"):
            resolve_aggregates(root, lambda _specification_id: root)


if __name__ == "__main__":
    unittest.main()
