from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mooblender.formats import UnsupportedPromobFormat, load_path


class FormatDispatchTests(unittest.TestCase):
    def test_unknown_extension_is_not_guessed_from_file_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "model.zip"
            path.write_bytes(b"synthetic bytes")

            with self.assertRaisesRegex(
                UnsupportedPromobFormat,
                "unsupported extension: .zip",
            ):
                load_path(path)


if __name__ == "__main__":
    unittest.main()
