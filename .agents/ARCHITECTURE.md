# Architecture direction

The codebase should use a layered design so format logic remains independent of
Blender and remote services.

## Current boundaries

```text
mooblender/                  # Public repository root
├── mooblender/             # Installable Blender extension
│   ├── __init__.py         # Extension entry point and registration
│   ├── blender/            # Operators, sidebar, and scene adapter
│   ├── formats/            # Pure-Python readers and file dispatch
│   │   ├── pmob/           # PMob structure and semantic readers
│   │   └── pcontent.py     # Safe PContent container reader
│   ├── mooble/             # HTTP client, downloads, and cache
│   ├── model/              # Blender-independent scene model
│   └── blender_manifest.toml
├── docs/formats/           # Public specifications and unknowns
└── tests/                  # Unit, fixture, and malformed-input tests
```

`.content`, `.mob`, structured diagnostics, and deeper Blender adapters should
be added when a tested behavior needs them; do not create empty packages merely
to mirror a future plan.

## Data flow

```text
local file ──> format reader ──┐
                              ├──> intermediate model ──> Blender adapter
Mooble model ──> client/download ┘

Mooble Explorer ──> explicit background sync ──> atomic SQLite snapshot
                                                     │
                         browser/search/categories <─┘
```

Format readers own byte-level validation and return a shared, Blender-neutral
model. The Blender adapter owns coordinate conversion and datablock creation.
The Mooble client owns HTTP behavior and passes downloaded bytes through the
same format readers as local files.

Geometry Nodes imports expose exactly one scene-linked controller object. The
source mesh and transform hierarchy lives in an unlinked collection referenced
by the controller's Collection Info node. This keeps helper empties out of the
scene Outliner while preserving their datablocks, parenting, drivers, and
procedural controls. Collection-hierarchy mode is no longer exposed: every
import returns one controller linked directly to the active collection, while
the source collection remains an unlinked implementation detail.

Modifier interfaces use single-value sockets for openings, configurable
dimensions, and finish menus. Opening services bind only to an exact resolved
aggregate path, and multiple source records for that path collapse to the one
movable component control. Numeric or directional component names retain a
`Door` or `Drawer` prefix. Material definitions with the same display name and
ordered style names share one menu across package scopes; differing option sets
receive unique interface names. The controller node group has a geometry output
only because source geometry enters through its Collection Info node.
Float inputs also feed hidden zero-effect sink nodes, keeping Blender's modifier
UI controls enabled while their values drive source-hierarchy transforms.

`Constant` aggregate edges suppress the resolved child's insertion controls.
For flattened geometry, explicitly non-editable component layers that occupy
less than half of a resized axis retain their size on that axis. The adjacent
panel stretches from the preserved hardware boundary to the resized outer
edge, rather than reserving a scaled copy of the hardware span. Meshes without
serialized UVs receive a target-size-aware cube projection; physical Promob
texture dimensions then drive the material's UV scale. Generated materials
carry both a source/resource fingerprint and a current node-state fingerprint;
reuse requires both to match, so edited materials are preserved.

Aggregate formulas use current `DrawingDimension` axes before logical
`Dimension` axes; measured geometry is reserved for redimension scaling.
`VisibleCondition` filters the resolved tree, while `Normal` maps local positive
Z to the aggregate attachment normal before its axial `Rotation` is applied.

Catalog HTTP is confined to the explicit **Sync Catalog** operation. Browser
queries never fall back to the network: they read the last complete SQLite
snapshot or report that synchronization is required. Thumbnail and model
downloads remain lazy, independent caches.

## Design rules

- Do not import `bpy` from `formats`, `mooble`, or `model`.
- Model coordinates and units explicitly; apply conversions in one documented
  location.
- Use typed data classes or similarly explicit models at parser boundaries.
- Read binary values with explicit endianness and width.
- Validate lengths, counts, offsets, recursion depth, and archive paths before
  allocating or extracting.
- Preserve source identifiers and unknown metadata when safe so diagnostics can
  explain losses.
- Return structured warnings; reserve exceptions for failures that prevent a
  coherent import.
- Keep HTTP transport injectable so tests can use recorded or synthetic
  responses without contacting the live service.
- Cache only non-sensitive data, use atomic writes, and record enough metadata
  to invalidate stale downloads.
- Keep dependencies minimal and compatible with Blender's bundled Python.

## Testing layers

- Parser unit tests run in normal CPython and use tiny redistributable fixtures.
- Property and malformed-input tests exercise bounds and error paths.
- Golden intermediate-model tests separate parsing correctness from Blender.
- Blender integration tests validate created datablocks and transforms.
- Network tests use a fake transport; optional live tests are explicit and
  require user-provided authorization.
