from __future__ import annotations

import struct
import unittest
from dataclasses import dataclass, field

from mooblender.formats.pmob.content_types import ContentType
from mooblender.formats.pmob.reader import PmobFormatError, read_pmob


@dataclass
class TestRecord:
    payload: bytes = b""
    children: list[tuple[ContentType, TestRecord]] = field(default_factory=list)


def record(payload: bytes = b"", children=()) -> TestRecord:
    return TestRecord(payload, list(children))


def record_size(node: TestRecord) -> int:
    return 8 + 8 * len(node.children) + len(node.payload) + sum(
        record_size(child) for _kind, child in node.children
    )


def encode_record(node: TestRecord, base_offset: int = 0) -> bytes:
    header_size = 8 + 8 * len(node.children) + len(node.payload)
    offsets = []
    offset = base_offset + header_size
    for _kind, child in node.children:
        offsets.append(offset)
        offset += record_size(child)
    header = struct.pack("<ii", len(node.payload), len(node.children))
    table = b"".join(
        struct.pack("<ii", int(kind), child_offset)
        for (kind, _child), child_offset in zip(node.children, offsets, strict=True)
    )
    children = b"".join(
        encode_record(child, child_offset)
        for (_kind, child), child_offset in zip(node.children, offsets, strict=True)
    )
    return header + table + node.payload + children


def utf16(value: str) -> bytes:
    return value.encode("utf-16-le")


def make_document() -> bytes:
    name = record(utf16("Sample"))
    version = record(struct.pack("<i", 2))
    vertices = record(struct.pack("<9f", 0, 0, 0, 1000, 0, 0, 0, 1000, 0))
    indices = record(struct.pack("<3i", 0, 1, 2))
    uvs = record(struct.pack("<6f", 0, 0, 1, 0, 0, 1))
    smooth_groups = record(struct.pack("<3i", 2, 0, 1))
    material_id = record(struct.pack("<i", 0))
    mesh = record(
        children=(
            (ContentType.MATERIAL_ID, material_id),
            (ContentType.VERTICES, vertices),
            (ContentType.INDICES, indices),
            (ContentType.TEXT_COORDS, uvs),
            (ContentType.SMOOTH_GROUPS, smooth_groups),
        )
    )
    mesh_list = record(children=((ContentType.MESH, mesh),))
    layer_name = record(utf16("Top"))
    layer = record(
        children=((ContentType.NAME, layer_name), (ContentType.MESH_LIST, mesh_list))
    )
    layer_list = record(children=((ContentType.LAYER, layer),))
    material_name = record(utf16("White"))
    color = record(bytes((255, 255, 255, 255)))
    material = record(
        children=((ContentType.NAME, material_name), (ContentType.COLOR, color))
    )
    material_list = record(children=((ContentType.MATERIAL, material),))
    return encode_record(record(
        children=(
            (ContentType.NAME, name),
            (ContentType.VERSION, version),
            (ContentType.LAYER_LIST, layer_list),
            (ContentType.MATERIAL_LIST, material_list),
        )
    ))


class PmobReaderTests(unittest.TestCase):
    def test_reads_document_geometry_and_synthetic_primitive(self):
        document = read_pmob(make_document())

        self.assertEqual(document.name, "Sample")
        self.assertEqual(document.version, 2)
        self.assertEqual(document.layers[0].name, "Top")
        self.assertEqual(document.layers[0].meshes[0].triangle_faces(), [(0, 1, 2)])
        self.assertEqual(document.layers[0].meshes[0].smooth_groups, [[0, 1]])
        self.assertEqual(document.materials[0].name, "White")
        self.assertEqual(document.primitive.children[0].layer_ref, "Top")

    def test_rejects_out_of_range_child_offset(self):
        malformed = struct.pack("<iiii", 0, 1, int(ContentType.NAME), 999)
        with self.assertRaisesRegex(PmobFormatError, "outside the file"):
            read_pmob(malformed)

    def test_rejects_non_triangular_index_list(self):
        indices = record(struct.pack("<2i", 0, 1))
        vertices = record(struct.pack("<6f", 0, 0, 0, 1, 0, 0))
        mesh = record(
            children=((ContentType.VERTICES, vertices), (ContentType.INDICES, indices))
        )
        meshes = record(children=((ContentType.MESH, mesh),))
        layer = record(children=((ContentType.MESH_LIST, meshes),))
        layers = record(children=((ContentType.LAYER, layer),))
        root = encode_record(record(children=((ContentType.LAYER_LIST, layers),)))
        with self.assertRaisesRegex(PmobFormatError, "not divisible by three"):
            read_pmob(root)

    def test_rejects_truncated_smoothing_group(self):
        vertices = record(struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0))
        indices = record(struct.pack("<3i", 0, 1, 2))
        groups = record(struct.pack("<2i", 2, 0))
        mesh = record(children=(
            (ContentType.VERTICES, vertices),
            (ContentType.INDICES, indices),
            (ContentType.SMOOTH_GROUPS, groups),
        ))
        meshes = record(children=((ContentType.MESH, mesh),))
        layer = record(children=((ContentType.MESH_LIST, meshes),))
        layers = record(children=((ContentType.LAYER, layer),))
        root = encode_record(record(children=((ContentType.LAYER_LIST, layers),)))

        with self.assertRaisesRegex(PmobFormatError, "extends past"):
            read_pmob(root)

    def test_rejects_out_of_range_smoothing_group_index(self):
        vertices = record(struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0))
        indices = record(struct.pack("<3i", 0, 1, 2))
        groups = record(struct.pack("<2i", 1, 3))
        mesh = record(children=(
            (ContentType.VERTICES, vertices),
            (ContentType.INDICES, indices),
            (ContentType.SMOOTH_GROUPS, groups),
        ))
        meshes = record(children=((ContentType.MESH, mesh),))
        layer = record(children=((ContentType.MESH_LIST, meshes),))
        layers = record(children=((ContentType.LAYER, layer),))
        root = encode_record(record(children=((ContentType.LAYER_LIST, layers),)))

        with self.assertRaisesRegex(PmobFormatError, "out-of-range"):
            read_pmob(root)


if __name__ == "__main__":
    unittest.main()
