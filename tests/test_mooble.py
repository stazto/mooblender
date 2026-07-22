from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

from mooblender.mooble.client import MoobleClient
from mooblender.mooble.models import CatalogItem


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
        self.assertIn("region=br", url)

    def test_country_changes_catalog_origin_without_changing_department_ids(self):
        client = MoobleClient(region="fr", transport=FakeTransport({}))

        url = client.root_url(category="Moveis")

        self.assertIn("region=fr", url)
        self.assertIn("%21Departamento=Moveis", url)

    def test_catalog_index_can_request_the_maximum_page_size(self):
        client = MoobleClient(page_size=12, transport=FakeTransport({}))

        url = client.root_url(category="Moveis", page_size=48)

        self.assertIn("%24top=48", url)

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

    def test_maps_get_next_root_data_and_links(self):
        payload = {
            "HasMore": True,
            "Links": {"Next": "https://catalog.mooble.com/api/next-page"},
            "Data": [
                {
                    "Id": "continued-1",
                    "Name": "Continued cabinet",
                    "Brand": {"Name": "Kappesberg"},
                    "Links": {},
                }
            ],
        }
        client = MoobleClient(transport=FakeTransport(payload))

        page = client.browse_url("https://catalog.mooble.com/api/continuation")

        self.assertEqual(page.items[0].id, "continued-1")
        self.assertEqual(page.items[0].brand, "Kappesberg")
        self.assertEqual(page.next_url, "https://catalog.mooble.com/api/next-page")

    def test_caches_and_restores_catalog_page(self):
        payload = {
            "Output": {
                "Pin": {"Name": "Departamento", "AvailableTags": {"Data": []}},
                "Specifications": {
                    "Links": {},
                    "Data": [
                        {
                            "Id": "cached-1",
                            "Name": "Cached chair",
                            "Links": {},
                        }
                    ],
                },
            }
        }
        with TemporaryDirectory() as directory:
            client = MoobleClient(cache_dir=directory, transport=FakeTransport(payload))
            page = client.browse(category="Moveis")
            calls_before_restore = list(client.transport.urls)
            restored = client.load_cached_page(page.current_url)

        self.assertEqual(restored, page)
        self.assertEqual(client.transport.urls, calls_before_restore)

    def test_pagination_extends_the_original_catalog_cache(self):
        first_payload = {
            "Output": {
                "Pin": {"Name": "Departamento", "AvailableTags": {"Data": []}},
                "Specifications": {
                    "Links": {"Next": "https://catalog.mooble.com/api/page-2"},
                    "Data": [{"Id": "one", "Name": "One", "Links": {}}],
                },
            }
        }
        second_payload = {
            "Output": {
                "Pin": {"Name": "Departamento", "AvailableTags": {"Data": []}},
                "Specifications": {
                    "Links": {},
                    "Data": [{"Id": "two", "Name": "Two", "Links": {}}],
                },
            }
        }
        with TemporaryDirectory() as directory:
            transport = FakeTransport(first_payload)
            client = MoobleClient(cache_dir=directory, transport=transport)
            first = client.browse()
            transport.payload = second_payload
            second = client.browse_url(first.next_url)
            merged = client.extend_cached_page(first.current_url, second)
            transport.payload = first_payload
            revalidated = client.browse()
            calls_before_restore = list(transport.urls)
            restored = client.load_cached_page(first.current_url)

        self.assertEqual([item.id for item in merged.items], ["one", "two"])
        self.assertEqual(revalidated, merged)
        self.assertEqual(restored, merged)
        self.assertEqual(transport.urls, calls_before_restore)

    def test_downloads_aggregate_specification_by_id(self):
        payload = {
            "Id": "door-id",
            "Name": "Door",
            "Links": {"Content": "https://cdn.mooble.com/door.pcontent"},
        }
        with TemporaryDirectory() as directory:
            transport = FakeTransport(payload)
            client = MoobleClient(cache_dir=directory, transport=transport)
            path = client.download_specification("door-id")

            self.assertEqual(path.read_bytes(), b"content")
            self.assertIn("explorer/GetSpec/door-id", " ".join(transport.urls))

    def test_model_details_keep_selected_country_context(self):
        payload = {
            "Id": "model",
            "Links": {"Content": "https://cdn.mooble.com/model.pcontent"},
        }
        transport = FakeTransport(payload)
        client = MoobleClient(region="fr", transport=transport)

        client.details(
            CatalogItem(
                id="model",
                name="Model",
                detail_url="https://catalog.mooble.com/api/explorer/GetSpec/model",
            )
        )

        self.assertTrue(any("region=fr" in url for url in transport.urls))

    def test_cached_thumbnail_is_not_downloaded_again(self):
        item = CatalogItem(
            id="preview-id",
            name="Preview",
            thumbnail_url="https://cdn.mooble.com/preview.png",
        )
        with TemporaryDirectory() as directory:
            transport = FakeTransport({})
            client = MoobleClient(cache_dir=directory, transport=transport)
            first = client.download_thumbnail(item)
            calls_after_first = list(transport.urls)
            second = client.download_thumbnail(item)

        self.assertEqual(first, second)
        self.assertEqual(transport.urls, calls_after_first)

    def test_model_download_prunes_older_entries_to_configured_limit(self):
        payload = {
            "Id": "model",
            "Name": "Model",
            "Links": {"Content": "https://cdn.mooble.com/model.pcontent"},
        }
        with TemporaryDirectory() as directory:
            client = MoobleClient(
                cache_dir=directory,
                model_cache_bytes=1,
                transport=FakeTransport(payload),
            )
            first = client.download_specification("first")
            second = client.download_specification("second")
            remaining = sorted(path.name for path in first.parent.iterdir())

            self.assertFalse(first.exists())
            self.assertTrue(second.exists())
            self.assertEqual(
                remaining,
                sorted((second.name, second.name + ".json")),
            )


if __name__ == "__main__":
    unittest.main()
