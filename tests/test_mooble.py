from __future__ import annotations

import unittest

from mooblender.mooble.client import MoobleClient


class FakeTransport:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def validate_url(self, url):
        self.urls.append(url)

    def get_json(self, url, *, max_bytes=0):
        self.urls.append(url)
        return self.payload

    def get_bytes(self, url, *, max_bytes):
        self.urls.append(url)
        return b"content"


class MoobleClientTests(unittest.TestCase):
    def test_builds_current_explorer_v2_query(self):
        client = MoobleClient(transport=FakeTransport({}), page_size=8)
        url = client.root_url(category="Moveis", search="mesa")

        self.assertIn("explorer/v2", url)
        self.assertIn("%21Departamento=Moveis", url)
        self.assertIn("%24top=8", url)
        self.assertIn("search=mesa", url)

    def test_maps_categories_items_and_pagination(self):
        payload = {
            "Output": {
                "Pin": {
                    "Name": "Departamento",
                    "AvailableTags": {
                        "Data": [
                            {
                                "Id": "Cozinha",
                                "Name": "Cozinha",
                                "PinUrl": "https://catalog.mooble.com/api/explorer/x",
                                "Level": 1,
                                "SpecCount": 10,
                            }
                        ]
                    },
                },
                "Specifications": {
                    "Links": {"Next": "https://catalog.mooble.com/api/explorer/next"},
                    "Data": [
                        {
                            "Id": "id-1",
                            "Name": "Cabinet",
                            "Description": "Base cabinet",
                            "Brand": {"Name": "Brand"},
                            "Collection": {"Name": "Kitchen"},
                            "Links": {"ContentImageSmall": "https://cdn.mooble.com/x.png"},
                            "DetailUrl": "https://catalog.mooble.com/api/explorer/GetSpec/id-1",
                            "Type": "Shape",
                        }
                    ],
                },
            }
        }
        client = MoobleClient(transport=FakeTransport(payload))
        page = client.browse()

        self.assertEqual(page.categories[0].name, "Cozinha")
        self.assertEqual(page.items[0].brand, "Brand")
        self.assertEqual(page.items[0].collection, "Kitchen")
        self.assertTrue(page.next_url.endswith("/next"))


if __name__ == "__main__":
    unittest.main()
