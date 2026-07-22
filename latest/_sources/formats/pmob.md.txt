# PMob format reference

Status: implemented for the record families and traits documented below.
Unrecognized records remain unsupported rather than being interpreted by name
or file extension alone.

## Binary structure

PMob is a little-endian recursive record tree. The file itself is the root PMob
record; there is no separate magic signature.

Each record begins with:

| Offset | Width | Meaning |
| ---: | ---: | --- |
| `0` | 4 | Signed payload byte count |
| `4` | 4 | Signed child count |
| `8` | `8 × count` | Child entries: signed type ID and absolute file offset |
| after table | payload count | Record payload |

Child records can appear elsewhere in the file and are addressed by absolute
offset. Integers and IEEE-754 single-precision floats are little-endian. Names
and texture strings are UTF-16LE. A transform matrix contains 16 floats.

Implemented record families include document identity, primitive hierarchy,
animation transforms, layers, meshes, vertices, triangle indices, normals, UV
coordinates, line indices, smoothing groups, material assignments, and observed
material properties in type IDs `0x1a` through `0x38`.

## Transform convention

The serialized convention is:

- 16 row-major floats;
- row-vector points (`point * matrix`);
- translation in `M41`, `M42`, and `M43`;
- local-to-world composition as `local * parent`; and
- Z as the up axis in supported assets.

Transposing each matrix produces Blender's column-vector local matrix and normal
`parent @ local` composition. Translation and mesh coordinates are converted
from millimetres to metres at the Blender boundary. Linear matrix terms are not
unit-scaled, so authored object scale is preserved.

Layer primitives reference geometry by layer name. The Blender adapter creates a
mesh datablock once and instances it for each primitive reference.

## Geometry and smoothing

Mesh indices describe consecutive triangles. Texture coordinates are one UV per
serialized vertex when present.

The smoothing-group payload is a sequence of little-endian lists. Each list is a
signed 32-bit vertex count followed by that many signed 32-bit indices. Negative
counts, truncation, and out-of-range indices are invalid. These are
vertex-membership groups, not conventional per-face smoothing-group numbers.

Producers can duplicate a position when adjacent face corners need different
UVs, then place those indices in one smoothing group. Blender stores UVs and
custom normals on face corners, so the importer can compact compatible smooth
duplicates while retaining UV seams.

The reconstruction priority is:

1. Complete serialized normals.
2. Explicit smoothing groups, including omissions that preserve hard edges.
3. Authored vertex connectivity when neither source is available.

Position and face angle alone are not enough to distinguish a UV seam from a
disconnected hard boundary. The importer therefore does not weld authored
splits merely because their positions are equal. Resulting normals are written
to face corners and compatible polygons use smooth shading.

PMob faces remain triangles. Optional Blender-side triangle-to-quad conversion
joins only compatible, nearly coplanar pairs while checking UVs, materials,
sharp/seam state, vertex colors, and shape quality. This is an editing
convenience, not a PMob semantic, and is disabled by default.

## Texture mapping

Some meshes omit serialized UV coordinates. Others contain UVs for an authored
size but are later resized by package metadata.

For cubic mapping, material metadata supplies physical texture width and height
in millimetres. Mooblender projects after primitive transforms and size
correction, stores physical coordinates in metres on Blender's corner domain,
and derives UV scale from the material dimensions. Reusing a material therefore
retains consistent texel density across differently sized parts.

Serialized UVs remain authoritative for non-cubic mappings. Fixed and planar
`MAPPING_SCALE` values are normalized UV scales, not millimetre dimensions.
Observed numeric mapping types are `0` fixed, `1` cubic, and `2` planar.
Spherical variants are not established.

## Materials

Material color payloads are four bytes in RGBA order. Supported packages can
embed diffuse, metallic, and transparency images named by or derived from PMob
material records.

- The diffuse image Alpha is multiplied by serialized material opacity.
- A separate transparency image is multiplied as an additional mask.
- The observed specular-texture channel maps to Principled Metallic.
- Normalized specular strength maps to Principled Specular IOR Level.
- Refraction factors above `1.0` are treated as optical IOR in supported
  material records.

Blender transmission depends on renderer settings. To keep refractive shells
usable in default viewport and render configurations, Mooblender preserves IOR
and uses bounded alpha blending as a fallback. It avoids accumulating opacity
across overlapping transparent surfaces and retains supported ambient tint.

Exactly equal generated materials are reused. A material edited by the user is
not silently replaced by a later import.

## Safety validation

The reader validates record bounds, child counts, offsets, string lengths,
matrix widths, index ranges, and recursive traversal before consuming payloads.
Malformed data raises a format error rather than producing partial geometry.

## Unknown or incomplete

- semantics for every mesh source type;
- line-index rendering rules;
- texture resolution outside PContent;
- animation time units and interpolation;
- spherical mapping variants; and
- compatibility across all PMob producer versions.
