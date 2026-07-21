from __future__ import annotations

import json
import unittest
import zipfile
from io import BytesIO

from mooblender.formats.pcontent import (
    PContentFormatError,
    decode_properties,
    read_pcontent,
)
from tests.test_pmob import make_document


def encode_7bit(value: int) -> bytes:
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def make_archive(*, member: str = "model.pmob") -> bytes:
    stream = BytesIO()
    properties = json.dumps({"Type": "Entity", "Dimension": {"Width": "1000"}}).encode()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, make_document())
        archive.writestr("properties.json", encode_7bit(len(properties)) + properties)
    return stream.getvalue()


class PContentReaderTests(unittest.TestCase):
    def test_reads_pmob_and_binarywriter_properties(self):
        package = read_pcontent(make_archive())

        self.assertEqual(package.document.name, "Sample")
        self.assertEqual(package.properties["Type"], "Entity")
        self.assertEqual(package.pmob_member, "model.pmob")

    def test_plain_json_properties_are_also_accepted(self):
        self.assertEqual(decode_properties(b'{"Type":"Light"}')["Type"], "Light")

    def test_rejects_traversal_member(self):
        with self.assertRaisesRegex(PContentFormatError, "unsafe archive member"):
            read_pcontent(make_archive(member="../model.pmob"))


if __name__ == "__main__":
    unittest.main()
