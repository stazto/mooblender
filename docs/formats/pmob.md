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

The smoothing-group payload is a sequence of little-endian lists. Each list is
encoded as a signed 32-bit vertex count followed by that many signed 32-bit
vertex indices. A negative count, truncated list, or index outside the mesh's
vertex array is invalid. The decompiled PMob writer confirms that these are
vertex-index groups rather than conventional per-face smoothing-group numbers.

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

The observed PMob producer duplicates a position when two face corners require
different UV coordinates, then places the duplicate indices in one smoothing
group. Its mesh conversion also uses a 45-degree maximum angle when deciding
whether coincident vertices belong to one smooth surface while building this
topology. Normal generation
accumulates triangle normals at each vertex and averages the members of each
smoothing group. These behaviors are confirmed by the decompiled serializer
and mesh implementation; a cached 212-package corpus confirms that the files
commonly omit serialized normals and rely on these topology rules.

Blender stores UV coordinates and custom normals on face corners, so Mooblender
can weld coincident smooth vertices without discarding UV seams. It groups
positions within the producer's `1e-5` source-unit tolerance and keeps UVs on
the face-corner domain. Complete serialized normals take precedence. Without
them, explicit smoothing groups are authoritative, including coincident pairs
omitted to retain hard edges. The observed 45-degree threshold is used only when
both normals and groups are absent. It then writes the generated
normal to every face corner and enables smooth polygon shading. On the sampled
corpus this safely removes UV-seam duplicates while retaining all triangle
corners and their UV coordinates.

PMob still stores mesh faces as triangles. As an optional Blender-side import
step, Mooblender can reconstruct nearly coplanar triangle pairs as quads. The
join compares UVs, sharp/seam flags, vertex colors, and materials, and uses a
one-degree face-angle limit plus a 45-degree shape limit. This is an editable
topology convenience, not a PMob format semantic, so it is disabled by default.

Some observed meshes, including the 728 door panels, contain no serialized UV
coordinates. Other cubic-mapped meshes contain UVs for their original size but
are redimensioned by their parent aggregate. Their material metadata identifies
cubic mapping and gives a physical texture width and height in millimetres.
Mooblender therefore cube-projects every cubic-mapped mesh after its primitive
transforms and target-size correction, stores final physical coordinates in
metres as a Blender UV map, and converts the physical texture dimensions to UV
scale. This gives every use of the same material the same texel density even
when one component was resized. Serialized UVs remain authoritative for
non-cubic mappings. Planar/fixed `MAPPING_SCALE` values are direct normalized UV
scales (commonly `1×1`), not millimetre dimensions. The numeric mapping types
are supported from observed files and the decompiled mapping conversion: `0`
fixed, `1` cubic, and `2` planar; spherical variants remain unverified.

Observed PContent packages embed the diffuse, metallic, and transparency image
members named by or derived from PMob materials. `SPECULAR_TEXTURE` points to
the sampled `_METALLIC` image, so the adapter connects it to Principled
Metallic. The diffuse image's own Alpha is multiplied by serialized material
opacity. When present, `_TRANSPARENT` is derived from a `_DIFFUSE` name and
multiplied as an additional mask. These channel-name rules remain an observed
Mooble packaging convention rather than a guarantee for every PMob producer.

The `REFRACTION_FACTOR` material record is retained as a first-class neutral
field. In the sampled catalog, ordinary materials use `1.0`, while glass and
transparent acrylic consistently use approximately `1.4`. Values above `1.0`
are therefore interpreted as optical IOR and identify refractive materials;
values at or below `1.0` do not, because the corpus also contains non-glass
finishes with a factor of `0.5`.

Eevee physical transmission depends on a scene-level ray-tracing setting. With
the default setting, thick catalog glass shells become dark reflective solids
and hide decals behind them. Mooblender therefore retains the IOR on Principled
but uses alpha blending as a render-setting-independent fallback. Refractive
opacity is capped at `0.35` only when the source value would be more opaque, and
overlapping transparent surfaces are disabled to avoid opacity accumulation.
The fallback tint multiplies material RGB by PMob ambient intensity, retaining
the observed smoked appearance of PE12A's white RGB with ambient `0.0`.

`SPECULAR_POWER` is a normalized reflection level rather than a conventional
unbounded shininess exponent. This is confirmed by the version-zero reader,
which derives it from the average serialized specular RGB value. It maps to
Principled Specular IOR Level; preserving a glass value of `0.0` avoids the
strong dielectric reflection produced by Blender's default `0.5`.

These interpretations need broader fixtures, especially asymmetric geometry,
before being promoted to confirmed format guarantees.

## Unknown or incomplete

- meaning and topology rules for every mesh source type;
- line-index semantics;
- texture resolution rules outside PContent;
- animation time units/interpolation; and
- compatibility across PMob producer versions.
