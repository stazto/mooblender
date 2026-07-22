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
dimensions. Some packages serialize the equivalent long names
`$PARENTWIDTH$`, `$PARENTDEPTH$`, `$PARENTHEIGHT$`, `$WIDTH$`, `$DEPTH$`, and
`$HEIGHT$`; both vocabularies refer to the same values. Open-service expressions
additionally use C-style ternaries inside an `@(...)` wrapper. Aggregate
`VisibleCondition` records use numeric comparisons and Boolean operators. Some
also compare model information through tokens such as
`@Coz_bal(TIPO)@ == "P1"`. The selected model comes from the current
`References.ModelsId` entry, with the first declared model as a fallback for an
unreferenced group. Mooblender evaluates only this small grammar; it does not
execute Python or arbitrary source text. It omits an aggregate when a supported
visibility expression is false, but retains geometry when an unfamiliar token
cannot be resolved instead of silently deleting every alternative.

`Dimension`, `DrawingDimension`, and the serialized PMob geometry are distinct.
`Dimension` supplies logical/default values when an aggregate omits an axis.
Parent expressions use the current aggregate target dimensions. At the root,
each axis uses `DrawingDimension` when present, then `Dimension`, and only then
the measured geometry. This matters because the observed 728 has a logical 600
mm width but a current drawing width of 800 mm, while the observed tool cart has
a 570 mm drawing depth despite a 645 mm geometry envelope. For geometry scaling,
Mooblender separately measures PMob vertices after their primitive transforms;
`DrawingDimension`, `GeometryBoundingBox`, and logical dimensions are
progressively weaker fallbacks when no renderable PMob is present.

Redimension scale applies only to the child package's own PMob geometry. Nested
aggregate positions are already expressed in the redimensioned child's target
coordinate system and must not inherit that scale a second time. Inversion is
kept on the aggregate placement so it mirrors both geometry and nested parts.
An aggregate `Normal` vector orients its local positive Z axis. Because a normal
alone does not determine roll, Mooblender projects global negative Z into the
attachment plane as the zero-rotation local X reference, then applies
`Rotation` around the normal. This keeps side-mounted pairs with `(-1, 0, 0)`
and `(1, 0, 0)` symmetric instead of giving them opposite vertical roll.
Ignoring `Normal` leaves components on the wrong plane; the observed 10122 bed
uses `(-1, 0, 0)` to lay its long drawer handles horizontally, while ELA-2 uses
opposing X normals for its two lifting carriages.

`OpenServices.AggregatePath` alternates aggregate-container and selected-option
indices. Doors supply a pivot and maximum angle; drawers supply maximum travel.
The single-object import gives every valid movable component its own 0–1
Geometry Nodes input, preferring its `pt-br` localization and then its source
description. If that name does not already identify the component type, the
input retains the source `Door` or `Drawer` prefix, for example `Drawer: 1ª`.
It creates these controls lazily, so entities without a valid door or drawer
expose no opening input.

Observed resizable entities use `InsertDimension.Min` and
`InsertDimension.Max` to describe editable insertion ranges. The public API
serializes axes as X/Y/Z, while the decompiled domain model calls the same
values Width/Depth/Height. An editable 15 mm shelf observed on 2026-07-21 had a
600 × 150 × 15 mm default, X limits of 10–2740 mm, Y limits of 10–1840 mm, and
fixed Z. Mooblender consequently exposes **Largura** and **Profundidade** as
meter-based Blender distance inputs and scales only their corresponding axes;
an axis with no variable range gets no control.
An aggregate with `Constant: true` fixes its resolved child in the parent,
even when that reusable child specification publishes broad insertion limits.
Those child limits are therefore not user controls. This distinction is
observed in `Aéreo de Canto Reto (R678)` and its fixed door package.
Controls belong to the concrete package instance. A root entity uses the plain
dimension name, while nested entities use a component-qualified name such as
`Prateleira: Largura`; changing one nested control scales that entity subtree
without changing a sibling instance.

An aggregate marked `Concurrent: true` is independently selectable unless it
is also `Constant` or `AlwaysVisible`. Every resolved selectable aggregate gets
a default-enabled Boolean control in the Geometry Nodes **Options** panel. The
control keeps the source hierarchy intact and drives only that aggregate
instance's visibility. In the observed C67 package, **Tampo** and **Rodapé**
therefore receive separate controls, while the constant door does not.

Some fixed hardware is flattened into the same PMob document as a resizable
panel. In the observed 728 door, `Models.Components` marks `PUXADOR` with
`Edit: false`; its geometry spans the door width but only a small fraction of
the resized height. Mooblender keeps that small non-editable component fixed on
the partial axis. It preserves the nearest outer boundary and overlap beside
that hardware, whether the hardware is on the low or high side, then stretches
the panel's remaining span to the requested aggregate size. In the cached 728
sample this keeps each handle about 30 mm high while each door panel extends
about 370 mm vertically. This is an evidence-based fallback for packages that
do not place hardware in a separate constant aggregate.

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
