# PContent format reference

Status: implemented baseline for supported package, aggregate, material, and
image traits.

## Container

`.pcontent` is a ZIP archive. Supported packages appear in three forms:

- a renderable entity with one `.pmob`, embedded images, and `properties.json`;
- a material package with one material-only PMob; or
- a properties-only aggregate whose geometry comes from referenced child
  specifications.

The observed `properties.json` member can use the .NET BinaryWriter string
representation: a 7-bit encoded UTF-8 byte length followed by JSON bytes. The
reader also accepts plain UTF-8 JSON for independently produced packages.

## Properties and referenced packages

The properties object can describe logical dimensions, drawing dimensions,
limits, models, components, open services, aggregate children, lighting, and
material choices.

An aggregate can contain a list of specification UUIDs and expressions for
dimensions, position, rotation, and visibility. Mooblender selects the declared
default, resolves its public detail record, and recursively loads PContent with
depth, entity, and cycle limits. Repeated specification IDs reuse parsed package
data and mesh datablocks.

The supported expression grammar includes:

- `$PW$`, `$PD$`, `$PH$` for parent width, depth, and height;
- `$W$`, `$D$`, `$H$` for child dimensions;
- equivalent long names such as `$PARENTWIDTH$` and `$WIDTH$`;
- arithmetic and numeric comparisons;
- Boolean operators;
- C-style ternaries inside `@(...)`; and
- model-information tokens such as `@Component(TYPE)@`.

The evaluator implements only this bounded grammar. It does not execute Python
or arbitrary source text. A supported false visibility expression omits the
aggregate; an unresolved unfamiliar token retains geometry rather than silently
removing alternatives.

## Dimensions and placement

`Dimension`, `DrawingDimension`, and measured PMob geometry are separate:

- `Dimension` supplies logical/default values and child-expression variables.
- `DrawingDimension` describes the authored drawing coordinate extent.
- measured geometry is calculated after primitive transforms.
- `GeometryBoundingBox` is a fallback when renderable geometry is absent.

At a root, each axis prefers drawing dimension, then logical dimension, then
measured geometry. A child target derives from aggregate expressions and its own
defaults. Geometry resizing applies only to that child's PMob geometry; nested
aggregate positions already use the resized coordinate system and must not
receive the scale a second time.

An aggregate `Normal` orients local positive Z. A normal does not determine
roll, so Mooblender projects global negative Z into the attachment plane as a
stable local X reference and applies `Rotation` around the normal. Opposing side
normals therefore keep a consistent vertical direction. Inversion stays on the
aggregate placement so it affects geometry and descendants together.

## Editable and fixed dimensions

`InsertDimension.Min` and `InsertDimension.Max` define editable axis ranges.
API records use X/Y/Z while domain names can use Width/Depth/Height. An axis is
exposed as a Blender distance input only when its range varies and the current
default lies inside that range.

An aggregate marked `Constant: true` fixes its child even if that reusable child
publishes broad insertion limits. Fixed axes and constant children do not create
misleading controls. Controls belong to concrete package instances, so changing
one nested part does not resize a sibling instance.

Some packages flatten fixed hardware into the same PMob as an editable panel.
When component metadata marks that region non-editable, Mooblender preserves the
nearest boundary and hardware span while stretching the remaining panel region.
This behavior is a package fallback; separate constant aggregates remain the
preferred representation.

## Doors, drawers, options, and reversal

`OpenServices.AggregatePath` alternates aggregate-container and selected-option
indices. A door supplies a pivot and maximum angle; a drawer supplies maximum
travel. Each valid movable instance receives its own 0–1 Geometry Nodes value,
using localized component names when available.

Controls are created lazily. A package without a valid movement service receives
no inactive door or drawer input.

Aggregates marked `Concurrent` or `Coupled` can become default-enabled options
unless they are constant or always visible. Repeated coupled components with the
same description share one switch. The `CANMIRROR` attribute adds a **Reverse**
control that reflects the complete X footprint around its reported limits.
Face-winding parity is corrected for component inversion and whole-object
reversal so visible normals remain outward.

## Finishes

`Models` groups map PMob layer IDs to material specification UUIDs.
Multi-option groups become named **Finish** menus. The first option is the
default, including single-option groups and meshes with no local material ID.

Selections are scoped by package identity and layer ID because parent and child
packages can reuse layer names while having independent finishes. A model-wide
group is labeled **Main**; available component descriptions are retained.

## Safety policy

The reader operates in memory and does not extract archive paths. It rejects:

- absolute paths and parent traversal;
- excessive member counts or unpacked size;
- suspicious compression ratios;
- packages containing neither PMob nor properties;
- ambiguous multiple PMob members; and
- unsafe or unsupported embedded-image names.

Images are loaded through a private temporary file, packed into the Blender
datablock, and the temporary file is removed immediately.
