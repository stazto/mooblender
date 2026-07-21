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

- Blender 4.2 extension manifest and lazy package entry point.
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
- Resolve coordinate handedness and matrix convention, then apply primitive
  hierarchy and transforms.
- Import custom normals and smoothing groups correctly on supported Blender
  versions.
- Resolve textures relative to packages and create Principled BSDF node trees.
- Map PMob animation transforms to actions.

## Milestone 2 — Mooble collection browser (implemented baseline)

Interaction target, inspired by the open-source IKEA Browser extension:

- 3D View sidebar panel;
- search plus explicit refresh;
- compact thumbnail cards with model, brand, and collection names;
- one-click download/import;
- on-disk thumbnail/model cache; and
- a clear offline-mode message when Blender disables network access.

Mooble-specific additions:

- hierarchical category navigation using Explorer tag URLs;
- back navigation and paged **Load More** results;
- region, partnership, start category, page size, and API URL preferences;
- flexible mapping of tags, specifications, details, and content links; and
- HTTPS/host validation and bounded downloads.

Remaining exit work:

- Move HTTP and image work off the UI thread using a Blender timer-backed job
  queue; never touch Blender data from worker threads.
- Add cancellation, progress, retry-after support, ETag/Last-Modified cache
  validation, cache size controls, and a clear-cache operator.
- Add a selected-product details panel with dimensions and source URL.
- Preserve search/category state per Blender window and avoid reloading
  thumbnails already held in previews.
- Add schema-change diagnostics that retain a redacted response shape.
- Validate regional and partnership behavior without assuming all catalog
  content is public or redistributable.

## Milestone 3 — Complete PMob scene fidelity

Work packages:

1. **Coordinates:** establish source axes, handedness, matrix storage order,
   multiplication order, and millimetre conversion with asymmetric fixtures.
2. **Hierarchy:** instantiate group primitives and layer references, preserving
   reuse without duplicating mesh datablocks unnecessarily.
3. **Materials:** map color, opacity, metallic, roughness, reflection, emission,
   texture channels, mapping mode, scale, repetitions, and rotation.
4. **Geometry:** validate all mesh source types; apply normals, smoothing,
   line-index behavior, culling metadata, and degenerate-face policy.
5. **Animation:** validate time units and transform interpolation, then create
   Blender actions and keyframes.
6. **Diagnostics:** produce an import summary listing dropped or approximated
   semantics instead of silently ignoring them.

Exit criteria: golden neutral-model tests and Blender integration fixtures prove
geometry, hierarchy, transforms, materials, and animation independently.

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

- Blender 4.2+ and Python 3.11+ are declared as the supported baseline.
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

- Add type checking and headless Blender integration tests to CI.
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

1. Add a small fixture writer to generate more asymmetric PMob cases.
2. Validate coordinate/matrix behavior in Blender and implement primitive
   hierarchy.
3. Add texture-member discovery to PContent and build material node trees.
4. Introduce the timer/job queue before expanding the live browser UI.
5. Obtain `.content` and `.mob` samples and begin independent identification.
