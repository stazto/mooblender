# Architecture direction

The codebase should use a layered design so format logic remains independent of
Blender and remote services.

## Current boundaries

```text
mooblender/                  # Public repository root
├── mooblender/             # Installable Blender extension
│   ├── __init__.py         # Extension entry point and registration
│   ├── blender/            # UI, runtime, and Blender adapters
│   │   ├── scene_builder.py # Aggregate interpretation and import orchestration
│   │   ├── geometry_nodes.py # Node graph, controls, transforms, and finishes
│   │   ├── mesh_builder.py # Mesh, topology, UV, and primitive construction
│   │   └── materials.py    # Images, node materials, and material reuse
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
Within that adapter, `scene_builder` interprets aggregate metadata and
orchestrates one import, `geometry_nodes` exclusively constructs the procedural
graph and modifier interface, `mesh_builder` creates geometry and build-time
transform records, and `materials` owns image and shader datablocks. UI
operators schedule work but do not implement format semantics.
The Mooble client owns HTTP behavior and passes downloaded bytes through the
same format readers as local files.

Geometry Nodes imports expose exactly one scene-linked controller object.
Source mesh objects live in an unlinked collection with identity object
transforms and are referenced individually by Object Info nodes. Lightweight
Python records represent the source hierarchy only while importing;
`scene_builder` passes that interpreted hierarchy to `geometry_nodes`, which
compiles each ordered local transform into Transform Geometry nodes and then
discards those records. Static placement, opening pivots,
dimensions, optional-part visibility, and whole-model reversal therefore run
inside the node group. No helper empty datablocks or transform drivers are
created. An explicit top-level **Realize Instances** input selects the realized
branch when downstream mesh operations need it. Source instances are realized
internally before face materials and mirrored-winding correction, then wrapped
as one model instance; both public branches therefore share finishes and
correct normals.

Modifier interfaces place **Realize Instances** first, followed by a **Finish**
panel whose menu labels name only the affected part, an **Options** panel for selectable aggregate components, a
**Doors and Drawers** panel, and a **Parameters** panel for configurable sizes.
All controls use single-value sockets. Opening services
bind only to an exact resolved
aggregate path, and multiple source records for that path collapse to the one
movable component control. Numeric or directional component names retain a
`Door` or `Drawer` prefix. Material definitions with the same display name and
ordered style names share one menu across package scopes; differing option sets
receive unique interface names. Every exposed control has a directed path
through its actual transform or material operation to the group output, so
Blender keeps the modifier input active instead of graying it as unused.
Generic root finish groups use **Main**, while component metadata supplies names
such as **Tampo**. Repeated `Coupled` components share one Options socket.

Before Blender datablock creation, the neutral topology adapter reconstructs
normal fans for PMob meshes that omit normals. It honors nested smoothing
groups and the producer's observed 45-degree smooth-angle threshold, then welds
only coincident vertices in the same normal fan. UVs and normals remain on the
face-corner domain, so UV seams do not require duplicate Blender vertices and
hard edges remain split.

The Blender adapter may then perform an opt-in triangle-to-quad pass before
face attributes and custom normals are finalized. It joins only nearly planar,
shape-compatible pairs and compares seams, sharp edges, UVs, colors, and
materials. The neutral format model remains triangulated and Blender-neutral.

`Constant` aggregate edges suppress the resolved child's insertion controls.
For flattened geometry, explicitly non-editable component layers that occupy
less than half of a resized axis retain their size on that axis. The adjacent
panel stretches from the preserved hardware boundary to the resized outer
edge, rather than reserving a scaled copy of the hardware span. Every
cubic-mapped mesh receives a projection from its final physical geometry,
including PMob primitive transforms and aggregate redimensioning; physical
Promob texture dimensions then drive the material's UV scale. This standardizes
texel density between resized and unresized users of one material. Generated
materials carry both a source/resource fingerprint and a current node-state
fingerprint; reuse requires both to match, so edited materials are preserved.

Aggregate formulas use current `DrawingDimension` axes before logical
`Dimension` axes; measured geometry is reserved for redimension scaling.
`VisibleCondition` filters the resolved tree, while `Normal` maps local positive
Z to the aggregate attachment normal before its axial `Rotation` is applied.
The remaining roll is fixed by projecting global negative Z into the attachment
plane, rather than using an ambiguous shortest-arc quaternion; opposing side
normals therefore preserve a consistent vertical direction.

Catalog HTTP is confined to the explicit **Sync Catalog** operation. Browser
queries never fall back to the network: they read the last complete SQLite
snapshot or report that synchronization is required. Thumbnail and model
downloads remain lazy, independent caches. The sync scope is a hardcoded set of
observed top-level department identifiers exposed as sidebar checkboxes. A
country enum selects the Explorer `region`; an independent language enum either
keeps server category labels or localizes them to English before persistence.
Snapshot metadata records both dimensions so its origin remains visible. Each
enabled department is crawled as a separate root, then attached below one
synthetic local root whose deduplicated item membership supports global search.
Item rows also retain the summary payload's external width, depth, and height;
the card and its read-only information dialog consume only this local metadata.
Catalog HTTP uses a bounded four-worker category pool backed by the transport's
thread-local HTTPS connections. Pagination stays sequential inside each
category, while the synchronization worker remains the only SQLite writer.
Downloaded model and thumbnail groups have separate byte limits and flat,
non-following LRU cleanup. Paths registered by active workers cannot be pruned
or cleared. Explicit cache clearing releases Blender preview handles and removes
only those two groups; the atomic catalog database is a separate durable asset.

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
