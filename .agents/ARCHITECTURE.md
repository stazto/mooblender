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
