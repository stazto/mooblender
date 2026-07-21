from __future__ import annotations

import unittest

from mooblender.mooble.models import CatalogItem
from mooblender.mooble.search import filter_catalog_items


class CatalogSearchTests(unittest.TestCase):
    def setUp(self):
        self.items = (
            CatalogItem(
                id="shelf",
                name="Prateleira Editável 15mm",
                brand="Móveis Arte Cas",
                collection="Cozinha",
            ),
            CatalogItem(
                id="cabinet",
                name="Armário Geladeira 80cm",
                description="Duas portas",
                brand="CHF Móveis",
                collection="Ônix",
            ),
        )

    def test_empty_query_restores_every_item(self):
        self.assertEqual(filter_catalog_items(self.items, "  "), self.items)

    def test_matching_is_case_and_accent_insensitive(self):
        self.assertEqual(
            [item.id for item in filter_catalog_items(self.items, "MOVEIS onix")],
            ["cabinet"],
        )

    def test_every_term_must_match_visible_metadata(self):
        self.assertEqual(
            [item.id for item in filter_catalog_items(self.items, "armario portas")],
            ["cabinet"],
        )


if __name__ == "__main__":
    unittest.main()
