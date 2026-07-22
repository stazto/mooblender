"""Country selection and all-or-nothing category localization regressions."""

from __future__ import annotations

import unittest

from mooblender.mooble.localization import (
    CATALOG_COUNTRIES,
    CATALOG_DEPARTMENTS,
    CATEGORY_LANGUAGE_ENGLISH,
    CATEGORY_LANGUAGE_SOURCE,
    category_display_name,
    english_category_name,
    product_page_url,
)


class CatalogLocalizationTests(unittest.TestCase):
    """Keep catalog origin independent from the language of category labels."""

    def test_official_planner_countries_are_available(self) -> None:
        self.assertEqual(
            [code for code, _name in CATALOG_COUNTRIES],
            ["br", "us", "ca", "es", "ar", "cn", "fr"],
        )

    def test_source_language_keeps_the_server_label(self) -> None:
        self.assertEqual(
            category_display_name("Cozinha", "Cozinha", CATEGORY_LANGUAGE_SOURCE),
            "Cozinha",
        )

    def test_english_uses_stable_ids_before_localized_source_names(self) -> None:
        self.assertEqual(
            category_display_name("Cozinha", "Cocina", CATEGORY_LANGUAGE_ENGLISH),
            "Kitchen",
        )
        self.assertEqual(
            english_category_name("IQaHxYP5z9", "Réfrigérateurs"),
            "Refrigerators",
        )
        self.assertEqual(
            english_category_name("unknown", "Fornos | Microondas"),
            "Ovens / Microwaves",
        )

    def test_unknown_english_category_never_leaks_source_language(self) -> None:
        translated = english_category_name("future-id", "Categoria futura")

        self.assertRegex(translated, r"^Other category \[[0-9A-F]{6}\]$")
        self.assertNotIn("Categoria", translated)

    def test_department_controls_use_one_english_vocabulary(self) -> None:
        labels = [label for _property, _id, label, _default in CATALOG_DEPARTMENTS]

        self.assertEqual(
            labels,
            [
                "Furniture",
                "Decor",
                "Openings",
                "Appliances",
                "Fireplaces / Grills",
                "Layout",
                "Lights",
                "Materials",
                "Plants",
            ],
        )

    def test_product_pages_use_each_country_localized_route(self) -> None:
        expected_segments = {
            "br": "produto",
            "us": "product",
            "ca": "product",
            "es": "producto",
            "ar": "producto",
            "cn": "product",
            "fr": "product",
        }
        for country, segment in expected_segments.items():
            with self.subTest(country=country):
                self.assertEqual(
                    product_page_url(country, "model/id"),
                    f"https://www.mooble.com/{country}/{segment}/model%2Fid",
                )

        self.assertEqual(product_page_url("unsupported", "model"), "")
        self.assertEqual(product_page_url("br", ""), "")


if __name__ == "__main__":
    unittest.main()
