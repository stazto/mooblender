"""Bounds-checked parser for the recursive PMob record table."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .content_types import ContentType


class PmobStructureError(ValueError):
    pass


@dataclass(slots=True)
class Record:
    type_id: int
    payload: bytes = b""
    children: list[Record] = field(default_factory=list)
    offset: int = 0

    @property
    def known_type(self) -> ContentType | None:
        try:
            return ContentType(self.type_id)
        except ValueError:
            return None


class StructureReader:
    def __init__(
        self,
        data: bytes,
        *,
        max_depth: int = 128,
        max_records: int = 1_000_000,
    ) -> None:
        self.data = data
        self.max_depth = max_depth
        self.max_records = max_records
        self._records_read = 0
        self._active_offsets: set[int] = set()

    def read(self) -> Record:
        if len(self.data) < 8:
            raise PmobStructureError("PMob data is shorter than the root header")
        return self._read_record(0, int(ContentType.PMOB), 0)

    def _read_record(self, offset: int, type_id: int, depth: int) -> Record:
        if depth > self.max_depth:
            raise PmobStructureError("PMob record nesting exceeds the safety limit")
        if offset in self._active_offsets:
            raise PmobStructureError(f"cyclic PMob child offset at {offset}")
        if offset < 0 or offset + 8 > len(self.data):
            raise PmobStructureError(f"record header at {offset} is outside the file")

        self._records_read += 1
        if self._records_read > self.max_records:
            raise PmobStructureError("PMob record count exceeds the safety limit")

        payload_size, child_count = struct.unpack_from("<ii", self.data, offset)
        if payload_size < 0 or child_count < 0:
            raise PmobStructureError(f"negative size/count in record at {offset}")
        table_start = offset + 8
        table_size = child_count * 8
        payload_start = table_start + table_size
        payload_end = payload_start + payload_size
        if payload_end > len(self.data):
            raise PmobStructureError(f"record at {offset} extends past end of file")

        self._active_offsets.add(offset)
        try:
            children: list[Record] = []
            for index in range(child_count):
                entry_offset = table_start + index * 8
                child_type, child_offset = struct.unpack_from(
                    "<ii", self.data, entry_offset
                )
                children.append(
                    self._read_record(child_offset, child_type, depth + 1)
                )
        finally:
            self._active_offsets.remove(offset)

        return Record(
            type_id=type_id,
            payload=self.data[payload_start:payload_end],
            children=children,
            offset=offset,
        )


def read_structure(data: bytes) -> Record:
    return StructureReader(data).read()
