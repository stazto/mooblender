from __future__ import annotations

import unittest
from pathlib import Path


class FixturePolicyTests(unittest.TestCase):
    def test_tests_do_not_commit_binary_fixture_files(self):
        tests_root = Path(__file__).resolve().parent
        allowed_suffixes = {".py", ".md"}
        unexpected = sorted(
            path.relative_to(tests_root).as_posix()
            for path in tests_root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.casefold() not in allowed_suffixes
        )

        self.assertEqual(
            unexpected,
            [],
            "binary fixtures must be generated from bytes in Python test files",
        )


if __name__ == "__main__":
    unittest.main()
