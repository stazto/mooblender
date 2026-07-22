# Validation evidence

This file records reproducible observations behind completed importer
regressions. The executable mapping from each reported model to its synthetic
test is maintained in [`../tests/README.md`](../tests/README.md).

## Aggregate and control behavior

- The 728 cabinet case resolves two independent outward-opening doors, retains
  fixed-size handles while stretching the panels, generates physical UVs for
  panels without source UV records, and keeps cabinet and door finishes scoped.
- PE27 exposes bounded width and depth controls without presenting its fixed
  height as editable. R678 exposes only its opening control and retains a
  near-black handle.
- SUP01.0003 chooses one condition-selected drawer body per front. The 44950/007
  tool cart places drawers from the drawing depth, and the 10122 bed keeps
  side-attached handles inside their drawer fronts.
- C67 resolves its active `TIPO=P1` model information to the matching door and
  exposes independent **Tampo** and **Rodapé** switches without treating its
  constant door as optional. Its `CANMIRROR` flag adds a **Reverse** switch that
  reflects the complete 790 mm footprint in place.
- Porta de Giro 31 and Porta de Correr 21 resolve long-form parent-dimension
  variables. ELA-2 keeps opposing lift carriages consistently oriented above
  their anchors.

## Geometry and materials

- Shared material 2552 in the 4220A/0079K case has the same UV-to-world edge
  ratio on internal body and drawer geometry before its common mapping scale.
- A 212-package topology corpus contained 611,468 serialized vertices and no
  mesh normals. Smoothing-group reconstruction and compatible normal-fan
  compaction reduced it to 319,119 Blender vertices while retaining UV seams
  and hard edges.
- Synthetic Blender fixtures verify custom corner normals, UV-seam retention,
  optional triangle-to-quad conversion, material reuse, single-value modifier
  inputs, non-duplicated Geometry Nodes interface entries, and a directed path
  from every exposed modifier input to the final geometry output. They also
  assert that source meshes have identity object transforms and that importing
  creates no helper empties; all placement and controlled transforms live in
  the Geometry Nodes graph.
- The C66/C69 regressions cover `Coupled` Tampo/Rodapé grouping, positive signed
  volume before and after `Reverse`, finish nodes upstream of the default model
  instance, and concise **Main**/component finish labels.
- An AST architecture regression requires node construction to remain isolated
  in `blender/geometry_nodes.py`; `scene_builder.py` may orchestrate it but may
  not contain Blender node type identifiers. The same test requires docstrings
  on every add-on Python module, class, function, and method.

## Catalog behavior

- Offline tests verify all seven countries shown by the official planner,
  country-specific Explorer URLs, source-label preservation, stable English ID
  translation, and an English-only fallback for unknown future categories.
- Blender smoke tests verify both dropdowns register on 4.5 and 5.2, while
  structural panel tests keep them adjacent to department selection.
- Synthetic Explorer and SQLite tests preserve external W/D/H values, format a
  consistent millimetre label, and verify localized regional product links.
- A bounded live sample of the two smallest observed departments persisted both
  roots and all 41 reported unique items in one snapshot.
- The same sample took 4.35 seconds with one worker and 2.37 seconds with four
  configured workers. Pagination remains ordered within a category and SQLite
  writes remain serialized.
- Cooperative cancellation is tested after a valid response but before its
  category can be persisted. The temporary SQLite file is removed, the prior
  snapshot remains byte-for-byte usable, and Blender returns to idle without
  blocking its main thread.
- Synthetic HTTP 429/503 responses verify bounded `Retry-After` handling for
  both delta-seconds and HTTP dates. Tests inject the sleeper, make no real
  delay, cap hostile values, and confirm retry limits and fresh connections.
- Cache regressions verify oldest-first pruning, nested concurrent protection,
  automatic client eviction, stale-temporary cleanup, and non-following link
  removal. Explicit clearing retains the catalog, external link targets, and
  unknown nested directories. Blender tests cover preferences, operator state,
  preview release, and catalog-preserving user feedback.

Live measurements document observations, not service guarantees. CI assertions
use fake transports and Python-built fixtures; the optional live job checks
only whether the configured public endpoint still responds.

## Documentation

- Sphinx 8.2.3 builds all public user, developer, Mooble, and format pages with
  warnings treated as errors.
- Structural tests keep the rendered manual independent from private agent
  notes, require privacy-aware screenshot instructions, and verify that Pages
  deployment consumes a successful strict documentation build.
- Pages publication is persistent and versioned: every successful `main` build
  replaces only `/dev`, while a published `vN.N.N` release replaces `/latest`,
  `/stable`, and `/vN.N.N`. Synthetic filesystem tests prove that unrelated
  release directories survive both update modes and that tags must match the
  extension manifest.
- The public format references describe reusable format traits and unknowns;
  product-specific regression evidence remains in these internal validation
  notes and executable synthetic tests.
- The landing page and credits page distinguish Mooble's documented platform
  purpose from Promob's documented corporate identity as a Cyncly company.
  Their cited official Mooble, Planner, 2020 Spaces, Promob, and Cyncly links
  all returned HTTP 200 after redirects on 2026-07-22.
- Public targets, the Blender file selector, local dispatch, remote model
  validation, implementation planning, and project-wide agent notes list only
  PMob and PContent. A structural regression prevents retired extension targets
  from returning to documentation, plans, or runtime source.
