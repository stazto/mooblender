# PMob format notes

Status: partially implemented. Claims here reflect tested parser behavior; axis
and semantic questions remain explicitly open.

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

## Inferred semantics

- Geometry values appear to use millimetres; the scene adapter currently uses
  a `0.001` conversion to metres.
- Mesh indices are interpreted as consecutive triangles.
- Texture coordinates are interpreted as one UV per vertex.

These interpretations need broader fixtures, especially asymmetric geometry,
before being promoted to confirmed format guarantees.

## Unknown or incomplete

- coordinate axes and handedness;
- matrix row/column convention and hierarchy multiplication order;
- meaning and topology rules for every mesh source type;
- smoothing-group encoding;
- line-index semantics;
- texture resolution rules outside PContent;
- animation time units/interpolation; and
- compatibility across PMob producer versions.
