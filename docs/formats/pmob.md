# PMob format notes

Status: implemented for the observed public Mooble samples, with remaining
unknowns listed below.

## Confirmed structure

PMob is a little-endian recursive record tree. The file itself is the root PMob
record; there is no separate magic signature.

Each record begins with:

| Offset | Width | Meaning |
| ---: | ---: | --- |
| 0 | 4 | signed payload byte count |
| 4 | 4 | signed child count |
| 8 | 8 × count | child entries: signed type ID, absolute file offset |
| after table | payload count | record payload |

Child records may appear elsewhere in the file and are addressed by absolute
offset. Integers and IEEE-754 single-precision floats are little-endian. Names
and texture strings are UTF-16LE. Matrices contain 16 floats (64 bytes).

Implemented record families include document name/version, primitive hierarchy,
animation times/transforms, layers, mesh lists, vertices, triangle indices,
normals, UV coordinates, line indices, smoothing groups, material IDs, and the
known material properties from type IDs `0x1a` through `0x38`.

Material color payloads are four bytes in RGBA order. This matches the
decompiled serializer (`Color.FromArgb(buffer[3], buffer[0], buffer[1],
buffer[2])`) and observed near-black handle payloads such as `(5, 5, 5, 255)`.

## Confirmed transform convention

The decompiled `Mooble.Math3D` implementation and asymmetric Blender tests agree
on the following behavior:

- matrices are serialized as 16 row-major floats;
- points are row vectors (`point * matrix`);
- translation occupies `M41`, `M42`, and `M43`;
- local-to-world composition is `local * parent`; and
- transposing each matrix produces Blender's equivalent column-vector local
  matrix and standard `parent @ local` hierarchy.

Translation and mesh coordinates are converted with `0.001` at the Blender
boundary. The linear matrix is not unit-scaled. Three sampled product PMobs use
a root scale of 10 over centimetre-like raw vertex values; preserving that root
scale produces their advertised metre dimensions. Ignoring it makes those
models exactly ten times too small.

Layer primitives reference shared layer geometry by name. The Blender adapter
creates each mesh datablock once and instances it at every primitive reference.

## Confirmed and inferred geometry semantics

- The composed PMob coordinate space is millimetres and uses Z as up in the
  tested catalog products.
- Mesh indices are interpreted as consecutive triangles.
- Texture coordinates are interpreted as one UV per vertex.

Some observed meshes, including the 728 door panels, contain no serialized UV
coordinates. Other cubic-mapped meshes contain UVs for their original size but
are redimensioned by their parent aggregate. Their material metadata identifies
cubic mapping and gives a physical texture width and height in millimetres.
Mooblender therefore cube-projects every cubic-mapped mesh after its primitive
transforms and target-size correction, stores final physical coordinates in
metres as a Blender UV map, and converts the physical texture dimensions to UV
scale. This gives every use of the same material the same texel density even
when one component was resized. Serialized UVs remain authoritative for
non-cubic mappings. The numeric mapping types are supported from observed files
and the decompiled mapping conversion: `0` fixed, `1` cubic, and `2` planar;
spherical variants remain unverified.

Observed PContent packages embed the diffuse, metallic, and transparency image
members named by or derived from PMob materials. `SPECULAR_TEXTURE` points to
the sampled `_METALLIC` image, so the adapter connects it to Principled
Metallic. `_TRANSPARENT` is derived from a `_DIFFUSE` name and connected to
Principled Alpha. These channel-name rules remain an observed Mooble packaging
convention rather than a guarantee for every PMob producer.

These interpretations need broader fixtures, especially asymmetric geometry,
before being promoted to confirmed format guarantees.

## Unknown or incomplete

- meaning and topology rules for every mesh source type;
- smoothing-group encoding;
- line-index semantics;
- texture resolution rules outside PContent;
- animation time units/interpolation; and
- compatibility across PMob producer versions.
