from __future__ import annotations

import os
import unittest

from mooblender.mooble.client import MoobleClient

LIVE_TESTS_ENABLED = os.environ.get("MOOBLENDER_LIVE_TESTS") == "1"


@unittest.skipUnless(LIVE_TESTS_ENABLED, "set MOOBLENDER_LIVE_TESTS=1 to call Mooble")
class MoobleLiveTests(unittest.TestCase):
    def test_public_catalog_explorer_is_available(self) -> None:
        page = MoobleClient(page_size=1).browse(category="Moveis")

        self.assertEqual(page.pin_name, "Departamento")
        self.assertTrue(page.categories)
        self.assertTrue(page.items)
        self.assertTrue(page.items[0].id)
        self.assertTrue(page.items[0].detail_url.startswith("https://catalog.mooble.com/"))


if __name__ == "__main__":
    unittest.main()
