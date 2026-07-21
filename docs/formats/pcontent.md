# PContent format notes

Status: implemented baseline from public Mooble samples observed on 2026-07-21.

## Confirmed container

`.pcontent` is a ZIP archive. Observed packages fall into three useful forms:

- a renderable entity with one `.pmob`, embedded images, and
  `properties.json`;
- a material package with one material-only `.pmob`; and
- a properties-only aggregate whose geometry is supplied by referenced child
  specifications.

Despite its name, the observed `properties.json` member was not plain JSON at
byte zero. It used the .NET BinaryWriter string representation: a 7-bit encoded
UTF-8 byte length followed by that many bytes of JSON. The reader also accepts
plain UTF-8 JSON so independently produced packages remain straightforward.

The properties object can describe dimensions, limits, type, models/components,
open services, aggregates, lighting, and other product behavior. Aggregate
records contain a `Specifications` UUID list plus dimension and position
expressions. The current importer selects the first/default UUID, resolves it
with Mooble `GetSpec`, and recursively loads its PContent with a depth, entity,
and cycle limit. Repeated specifications reuse the same parsed package and mesh
datablocks.

Observed dimension/position expressions use arithmetic variables such as
`$PW$`, `$PD$`, `$PH$` for parent dimensions and `$W$`, `$D$`, `$H$` for child
dimensions. Open-service expressions additionally use C-style ternaries inside
an `@(...)` wrapper. Mooblender evaluates only a small numeric grammar; it does
not execute Python or arbitrary source text.

`Dimension`, `DrawingDimension`, and the serialized PMob geometry are distinct.
`Dimension` supplies logical/default values when an aggregate omits an axis.
Parent expressions use the dimensions of the current, already-redimensioned
entity. For scaling, Mooblender measures the PMob vertices after their primitive
transforms; `DrawingDimension`, `GeometryBoundingBox`, and logical dimensions
are progressively weaker fallbacks when no renderable PMob is present. This is
necessary because observed packages include both a door whose logical width is
100 mm while its serialized geometry is about 377 mm, and parametric fronts
whose metadata bounding box is a 50 mm cube while their PMob primitive
transforms produce the actual panel size.

Redimension scale applies only to the child package's own PMob geometry. Nested
aggregate positions are already expressed in the redimensioned child's target
coordinate system and must not inherit that scale a second time. Inversion is
kept on the aggregate placement so it mirrors both geometry and nested parts.

`OpenServices.AggregatePath` alternates aggregate-container and selected-option
indices. Doors supply a pivot and maximum angle; drawers supply maximum travel.
The single-object import gives every valid movable component its own 0–1
Geometry Nodes input, preferring its `pt-br` localization and then its source
description. It creates these controls lazily, so entities without a valid
door or drawer expose no opening input.

Observed resizable entities use `InsertDimension.Min` and
`InsertDimension.Max` to describe editable insertion ranges. The public API
serializes axes as X/Y/Z, while the decompiled domain model calls the same
values Width/Depth/Height. An editable 15 mm shelf observed on 2026-07-21 had a
600 × 150 × 15 mm default, X limits of 10–2740 mm, Y limits of 10–1840 mm, and
fixed Z. Mooblender consequently exposes **Largura** and **Profundidade** as
meter-based Blender distance inputs and scales only their corresponding axes;
an axis with no variable range gets no control.

`Models` groups map layer IDs to material specification UUIDs. Multi-option
groups become named **Finish** menu inputs whose entries use the source style
names, and select the resolved remote material per face layer.
The first option in every model group is also assigned as the default, including
single-option groups and PMob meshes whose local material ID is `-1`. Finish
selections match both package identity and layer ID, because parent bodies and
child fronts commonly reuse names such as `CORPO_V` but have independent
finishes.

An inverted door's service pivot is expressed in the entity's already-mirrored
coordinates. Because Mooblender represents inversion with a negative-X
aggregate placement, it converts the hinge X and rotation handedness back to
the unmirrored child coordinates. Without that conversion, a mirrored pair can
incorrectly share one hinge and swing inward. The exact 80 cm two-door cabinet
sample verifies distinct symmetric hinges and outward movement.

## Safety policy

The reader operates in memory and does not extract archive paths. It rejects
absolute or parent-traversal paths, excessive member counts/unpacked sizes,
suspicious compression ratios, packages with neither PMob nor properties, and
ambiguous multiple PMob members. Supported embedded images are retained by
safe normalized member name; Blender loads them through a private temporary
file, packs the image datablock, and removes that file immediately.

## Not established

`.content` is not treated as an alias for `.pcontent`. Its identity remains
unknown pending independent samples.
