"""Safe in-memory reader for the observed PContent ZIP container.

The archive is validated as a whole before any member is decoded. Members are
never extracted to disk: the PMob payload, properties, and texture resources
remain bytes owned by the returned package, which also becomes the root of the
later aggregate-resolution tree.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePosixPath

from ..model.scene import PmobDocument
from .pmob.reader import read_pmob


class PContentFormatError(ValueError):
    """Raised when a PContent archive violates its format or safety limits."""


@dataclass(slots=True)
class PContentPackage:
    """Parsed PContent document, metadata, resources, and resolved references."""

    document: PmobDocument | None
    properties: dict[str, object] = field(default_factory=dict)
    pmob_member: str = ""
    members: tuple[str, ...] = ()
    resources: dict[str, bytes] = field(default_factory=dict)
    resolved_aggregates: list[ResolvedAggregate] = field(default_factory=list)
    resolved_materials: dict[str, PContentPackage] = field(default_factory=dict)

    def resource(self, name: str | None) -> bytes | None:
        """Return an embedded resource by full path or case-insensitive name."""
        if not name:
            return None
        normalized = name.replace("\\", "/").casefold()
        direct = self.resources.get(normalized)
        if direct is not None:
            return direct
        basename = PurePosixPath(normalized).name
        return next(
            (
                data
                for member, data in self.resources.items()
                if PurePosixPath(member).name == basename
            ),
            None,
        )


@dataclass(slots=True)
class ResolvedAggregate:
    """One selected aggregate specification attached to its source index."""

    index: int
    specification_id: str
    package: PContentPackage


def _decode_7bit_length(data: bytes) -> tuple[int, int]:
    """Decode .NET BinaryWriter's bounded seven-bit string length prefix."""
    value = 0
    shift = 0
    for index, byte in enumerate(data[:5]):
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index + 1
        shift += 7
    raise PContentFormatError("invalid BinaryWriter string length prefix")


def decode_properties(data: bytes) -> dict[str, object]:
    """Decode properties.json, including the observed BinaryWriter wrapper."""
    if not data:
        return {}
    if data.lstrip().startswith((b"{", b"[")):
        payload = data
    else:
        length, prefix_size = _decode_7bit_length(data)
        end = prefix_size + length
        if end > len(data):
            raise PContentFormatError("properties string extends past end of member")
        payload = data[prefix_size:end]
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PContentFormatError(f"invalid properties JSON: {error}") from error
    if not isinstance(value, dict):
        raise PContentFormatError("properties root must be a JSON object")
    return value


def _safe_member(info: zipfile.ZipInfo) -> bool:
    """Reject absolute and parent-traversing ZIP member paths."""
    path = PurePosixPath(info.filename.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts


def read_pcontent(
    data: bytes,
    *,
    max_members: int = 512,
    max_uncompressed_bytes: int = 256 * 1024 * 1024,
    max_ratio: int = 200,
) -> PContentPackage:
    """Parse a bounded PContent ZIP entirely in memory."""
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except (zipfile.BadZipFile, OSError) as error:
        raise PContentFormatError(f"invalid PContent ZIP: {error}") from error

    with archive:
        infos = archive.infolist()
        # Validate paths and expansion cost before calling ``archive.read`` on
        # any member. This ordering prevents a malformed archive from consuming
        # unbounded memory or using extraction-like traversal semantics.
        if len(infos) > max_members:
            raise PContentFormatError("PContent member count exceeds safety limit")
        total_size = sum(info.file_size for info in infos)
        if total_size > max_uncompressed_bytes:
            raise PContentFormatError("PContent unpacked size exceeds safety limit")
        for info in infos:
            if not _safe_member(info):
                raise PContentFormatError(f"unsafe archive member path: {info.filename}")
            if info.file_size and info.compress_size == 0:
                raise PContentFormatError("invalid compressed member size")
            if info.compress_size and info.file_size / info.compress_size > max_ratio:
                raise PContentFormatError("PContent compression ratio exceeds safety limit")

        # A normal package contains one geometric PMob plus optional metadata.
        # Properties-only packages are valid because aggregates and material
        # specifications can reference their geometry elsewhere.
        pmob_infos = [
            info for info in infos
            if not info.is_dir() and PurePosixPath(info.filename).suffix.lower() == ".pmob"
        ]
        if len(pmob_infos) > 1:
            raise PContentFormatError("PContent contains multiple PMob models")

        pmob_info = pmob_infos[0] if pmob_infos else None
        document = read_pmob(archive.read(pmob_info)) if pmob_info is not None else None
        properties_info = next(
            (
                info for info in infos
                if PurePosixPath(info.filename).name.lower() == "properties.json"
            ),
            None,
        )
        properties = (
            decode_properties(archive.read(properties_info))
            if properties_info is not None
            else {}
        )
        if document is None and properties_info is None:
            raise PContentFormatError("PContent contains neither a PMob model nor properties")
        image_suffixes = {".bmp", ".jpeg", ".jpg", ".png", ".tga", ".tif", ".tiff", ".webp"}
        # Retain only image types consumed by the material builder. Unknown
        # archive members remain listed for diagnostics but are not duplicated
        # in memory.
        resources = {
            info.filename.replace("\\", "/").casefold(): archive.read(info)
            for info in infos
            if not info.is_dir()
            and PurePosixPath(info.filename).suffix.lower() in image_suffixes
        }
        return PContentPackage(
            document=document,
            properties=properties,
            pmob_member=pmob_info.filename if pmob_info is not None else "",
            members=tuple(info.filename for info in infos),
            resources=resources,
        )
