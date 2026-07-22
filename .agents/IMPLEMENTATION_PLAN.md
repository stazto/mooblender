# Implementation plan

This plan turns the product goals into independently verifiable milestones.
The status labels describe the first `v0.1.0` development target.

## Architecture and delivery principles

The system has three inputs—local files, PContent packages, and downloaded
Mooble resources—and one shared path into Blender:

```text
PMob ────────────────┐
PContent ─> PMob ────┼─> neutral scene model ─> Blender scene builder
Mooble ─> PContent ──┘
```

File parsing, catalog transport, and the neutral scene model remain importable
without `bpy`. Blender owns only registration, UI state, operators, previews,
and datablock creation. All network operations are explicit user actions and
honor Blender's Online Access setting.

## Milestone 0 — Project foundation (complete)

Deliverables:

- Blender 4.5 extension manifest and lazy package entry point.
- Packages for `formats`, `model`, `mooble`, and `blender`.
- Public project, architecture, evidence, and test guidance.
- CPython unit-test entry point with no Blender dependency.
- Deterministic, standard-library-only Blender extension ZIP builder.
- GitHub Actions coverage for Ruff, the supported Python matrix, packaging,
  artifact upload, and one isolated live Mooble health check.

Exit evidence: Ruff and offline test discovery pass from the repository root;
two consecutive builds have the same SHA-256 digest; the opt-in Mooble health
test reaches the observed public catalog endpoint.

## Milestone 1 — Preserve the existing importer capability (implemented baseline)

Deliverables:

- Rewrite the recursive PMob record reader in Python with explicit little
  endian fields, absolute offsets, recursion/count limits, and cycle checks.
- Decode UTF-16LE names, version, layers, meshes, indices, UVs, materials,
  primitives, and animation records into typed neutral objects.
- Validate triangle indices, vector widths, matrices, and material scalars.
- Read PContent as ZIP without extracting it to disk; reject unsafe paths,
  excessive sizes, suspicious compression ratios, missing models, and ambiguous
  multiple-model packages.
- Decode both plain JSON and the observed .NET BinaryWriter string wrapper used
  by `properties.json`.
- Create Blender collections, meshes, UV layers, material slots, and provenance
  custom properties.

Remaining exit work:

- Validate multiple independent PMob versions and mesh source types.
- Import custom normals and smoothing groups correctly on supported Blender
  versions.
- Map PMob animation transforms to actions.

## Milestone 2 — Mooble collection browser (implemented baseline)

Interaction target, inspired by the open-source IKEA Browser extension:

- 3D View sidebar panel;
- search plus explicit catalog synchronization;
- compact thumbnail cards with model, brand, and collection names;
- one-click download/import;
- on-disk thumbnail/model cache; and
- a clear offline-mode message when Blender disables network access.

Mooble-specific additions:

- hierarchical category navigation using Explorer tag URLs;
- back navigation and paged **Load More** results;
- region, partnership, page size, API URL preferences, and persistent sidebar
  checkboxes for each observed top-level catalog department;
- flexible mapping of tags, specifications, details, and content links; and
- HTTPS/host validation and bounded downloads.

Implemented follow-up work:

- Timer-backed catalog, thumbnail, model, and local aggregate work runs off the
  UI thread; Blender data is touched only by completion callbacks.
- Search and empty-query reset run locally with bounded result cards and local
  **Load More**; thumbnails and models remain on-demand.
- Explorer first-page and root-level continuation response shapes are parsed
  independently; completion must reach the selected category's reported unique
  item count before the index can replace its previous cache.
- Indexed `Brand.Name` values populate a local manufacturer menu that combines
  with text search and requires no catalog request.
- Manufacturer filtering retains the active category. A dependent Brand
  Collection menu exposes only `Collection.Name` values available for the
  selected manufacturer in that category, and composes with the text query.
- Catalog access is now explicit and local-first: **Sync Catalog** crawls the
  complete trees of every enabled top-level department and writes deduplicated
  items plus category membership into a temporary SQLite snapshot, atomically
  publishing it only on success. A synthetic local root combines global search
  with department-preserving navigation.
- A bounded live sync of the two smallest non-furniture departments,
  Lareiras/Churrasqueiras and Plantas, persisted both roots and all 41 reported
  unique items in one snapshot.
- Independent department and category downloads run in a bounded four-worker
  pool with serialized progress reporting and a single SQLite writer. The same
  41-item live sample took 4.35 seconds with one worker and 2.37 seconds with
  four configured workers; per-category continuation pages remain ordered.
- Startup, search, manufacturer filtering, category navigation, Back, and Load
  More perform no catalog requests. The previous snapshot remains usable while
  a new sync reports page/category progress in the background.
- Cached thumbnail paths are restored before scheduling work; only materialized
  uncached cards are requested, queued stale batches are cancelled when
  possible, and newly visible work is not trapped behind one old batch.
- Geometry Nodes imports link only their controller object to the scene. Source
  meshes and helper empties remain in a node-referenced, scene-unlinked
  collection, preserving procedural behavior without polluting the Outliner.

Remaining exit work:

- Add catalog-sync cancellation, retry-after support, cache size controls, and
  a clear-cache operator.
- Add a selected-product details panel with dimensions and source URL.
- Preserve category state independently for every Blender window.
- Add schema-change diagnostics that retain a redacted response shape.
- Validate regional and partnership behavior without assuming all catalog
  content is public or redistributable.

## Milestone 3 — Complete PMob scene fidelity (substantial implementation)

Work packages:

1. **Coordinates (implemented):** source row-vector matrices are transposed for
   Blender; translation and vertices are unit-converted while linear root scale
   is preserved. Asymmetric unit and Blender tests cover the convention.
2. **Hierarchy (implemented):** group primitives and layer references retain
   their hierarchy, with shared mesh datablocks for repeated layer geometry.
3. **Materials (implemented baseline):** color, opacity, metallic, roughness,
   embedded diffuse/metallic/normal/transparency textures, UV repetitions, and
   rotation are mapped to Principled nodes.
4. **Geometry (implemented baseline):** decode nested smoothing groups,
   reconstruct absent normals with the observed 45-degree smooth threshold,
   compact UV-seam vertices onto Blender's corner domain, and preserve hard
   normal fans. An opt-in Blender import setting reconstructs compatible planar
   triangle pairs as quads without crossing UV seams, sharp edges, or material
   boundaries. Remaining work is to validate all mesh source types, line-index
   behavior, culling metadata, and degenerate-face policy.
5. **Animation:** validate time units and transform interpolation, then create
   Blender actions and keyframes.
6. **Diagnostics:** produce an import summary listing dropped or approximated
   semantics instead of silently ignoring them.

Exit criteria: golden neutral-model tests and Blender integration fixtures prove
geometry, hierarchy, transforms, materials, and animation independently.

## Milestone 3A — Mooble aggregate fidelity (implemented baseline)

- Resolve properties-only aggregate and material specifications recursively in
  the background, with caching, cycle/depth/entity limits, and package reuse.
- Evaluate the observed numeric dimension, position, visibility, inversion,
  and opening expression subset without executing arbitrary code. Accept both
  short (`PW`, `W`) and long (`PARENTWIDTH`, `WIDTH`) dimension variable names.
  Use current drawing dimensions for parent formula variables without
  conflating them with the measured mesh envelope used for redimensioning.
- Reconstruct doors and drawers with independent, lazily created controls named
  from their Mooble component localization and retain a Door/Drawer prefix when
  the localization is only ordinal or directional. Bind services to exact
  aggregate paths and collapse alternate service records so each movable
  component owns one single-value input and driver.
- Map observed variable `InsertDimension` axes to bounded Geometry Nodes
  distance controls such as Largura and Profundidade, scoped per package
  instance so nested/repeated configurable components remain independent.
  Suppress those controls below a `Constant` aggregate edge.
- Import one visible Geometry Nodes object directly into the active collection;
  keep the node source collection unlinked and create no visible import wrapper.
- Convert multi-option model finish groups into named Geometry Nodes menu inputs
  that assign the resolved material by PMob layer and package scope; apply the
  first option from single- and multi-option groups as the default material.
  Consolidate identical menus shared by package scopes and give distinct option
  sets unique interface names so node input lookup is never ambiguous.
- Convert mirrored opening-service pivots and handedness into the negative-X
  aggregate representation so paired doors retain separate symmetric hinges
  and open outward.
- Orient aggregate local Z from its `Normal` vector, then apply `Rotation`
  around that attachment axis.
- Measure serialized PMob geometry after primitive transforms, redimension only
  that geometry, and leave nested aggregate placement in target coordinates.
  Preserve partial-axis fixed hardware size when a non-editable component layer
  is flattened into resized panel geometry, and stretch the panel from the
  preserved hardware boundary to the target edge.
- Generate target-size-aware physical UVs for every cubic-mapped mesh after its
  PMob primitive transforms and aggregate redimensioning. Convert observed
  material mapping dimensions from millimetres to Blender UV scale so one
  material retains one texel density across components.
- Interpret PMob colors as RGBA and reuse an existing generated material only
  when its source resources and current Blender node state are exactly equal.

Validated evidence: a random six-category corpus contained three standalone
renderable products and three properties-only aggregates. A sampled 2.30 m
tower resolved 11 unique entity packages into 20 aggregate instances, including
four doors, one drawer, and four base/foot instances. It has no unmaterialed
source meshes and evaluates to approximately 0.70 × 0.552 × 2.30 m closed. The
exact `Armário Geladeira 80cm 2 Portas (728)` sample evaluates to 0.80 × 0.330 ×
0.425 m with both doors, independent cabinet/door finishes, and working opening
drivers named `Esq` and `Dir`. The exact `Prateleira Editável 15mm (PE27-15)`
sample exposes bounded Largura and Profundidade controls and resizes each axis
independently. Closed/open bounds, parameter resizing, and finish switching
were checked in Blender 4.5 and 5.2 LTS. The general smoke fixture passes both
releases and covers independent openings, optional controls, configurable
root and nested-instance dimensions, default remote materials, and
same-layer-name finish isolation.
The smoke fixture also rejects duplicate interface entries, verifies all
user-facing inputs are single values rather than fields, consolidates repeated
material definitions, and confirms the controller still evaluates to mesh
geometry after those controls are built.
Cached R678 validation now exposes only its door-opening control and renders its
near-black handle with equal RGB channels. Cached 728 validation keeps both
handles at about 30 mm high, stretches each door panel to about 370 mm, and
generates physically scaled UVs for its source panels, which contain no UV
records.
Cached placement validation also keeps the SUP01.0003 cabinet within its 878 mm
height with one condition-selected drawer body per front, positions the
44950/007 tool-cart drawers from its 570 mm drawing depth rather than its 645 mm
mesh envelope, and orients the 10122 bed's handles inside their 149 mm drawer
fronts.
Cached 4220A/0079K validation gives the internal body and both drawers a
UV-to-world edge ratio of 1.0 before their shared 150 mm material mapping, so
all three use the same 6.6667 texture repetitions per metre.
Cached door validation reconstructs the 800 × 2099 mm leaf and correctly placed
handle inside `Porta de Giro 31`, and distributes all three 330.67 × 2195 mm
panels across the 980 mm frame of `Porta de Correr 21`. These packages use the
long-form parent dimension variables that previously collapsed their panels.
A 212-package cached topology corpus contains 611,468 PMob vertices and no
serialized mesh normals. Nested smoothing groups plus inferred 45-degree
normal fans compact this to 319,119 Blender vertices while preserving triangle
corners, UV seams, and incompatible hard-edge fans. Synthetic unit and Blender
smoke fixtures independently verify smooth-group decoding, seam UV retention,
custom corner normals, and hard-edge separation.

## Milestone 4 — Identify and implement `.content`

Do not alias `.content` to PContent based on its name.

1. Acquire at least two legally usable samples and provenance notes.
2. Record magic bytes, container structure, versions, and relationships.
3. Determine whether it embeds or references PMob, textures, metadata, or other
   resources.
4. Write a bounds-checked parser and malformed-input tests.
5. Convert through the neutral model and document unsupported fields.

Exit criteria: the public format document and fixtures reproduce imports without
vendor runtime dependencies.

## Milestone 5 — Identify and implement `.mob`

Use the same evidence gate as `.content`. Investigate it independently, then
add detection, a parser, neutral-model conversion, tests, and documentation.
Only share code when byte-level evidence demonstrates shared structures.

## Milestone 6 — Packaging and release quality

Implemented foundation:

- Blender 4.5+ and Python 3.11+ are declared as the supported baseline.
- Ruff and offline unit tests run on Python 3.11, 3.12, and 3.13 in CI.
- Network-dependent tests are skipped by default and run once in a dedicated
  Mooble API health-check job.
- `build_blender_addon.py` validates manifest identity/version, rejects
  symlinks, normalizes archive metadata, and packages the inner extension at
  the ZIP root; CI publishes that ZIP without adding a second archive layer.
- Git target tags follow `vMAJOR.MINOR.PATCH` without development suffixes.
  The builder automatically produces `MAJOR.MINOR.PATCH-devNNN`, using the CI
  run number or local Git commit count, injects it into the packaged manifest,
  and publishes tag builds as GitHub prereleases.

Remaining work:

- Add type checking to CI and expand the headless Blender fixture corpus.
- Validate the generated archive with Blender's extension tooling.
- Add user documentation, troubleshooting, privacy notes, and a compatibility
  matrix by format version.
- Review all fixtures and screenshots for redistribution rights.
- Run security tests for archives, offsets/counts, URLs, cache paths, JSON size,
  and decompression limits.

Release exit criteria: a clean Blender profile can install the built archive,
browse a public Mooble collection, import a selected PContent, and import local
supported fixtures with documented results.

## Immediate next implementation sequence

1. Add redistributable aggregate/opening/material fixtures matching the live
   observations without copying catalog assets.
2. Validate PMob animation timing and interpolation, smoothing groups, and all
   observed mesh source types.
3. Add structured import diagnostics for unsupported expressions and semantics.
4. Obtain `.content` and `.mob` samples and begin independent identification.
5. Add cancellation, progress, bounded cache management, and conditional HTTP
   validation where the service supports it.
