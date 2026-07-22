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
  from every exposed modifier input to the final geometry output.

## Catalog behavior

- A bounded live sample of the two smallest observed departments persisted both
  roots and all 41 reported unique items in one snapshot.
- The same sample took 4.35 seconds with one worker and 2.37 seconds with four
  configured workers. Pagination remains ordered within a category and SQLite
  writes remain serialized.

Live measurements document observations, not service guarantees. CI assertions
use fake transports and Python-built fixtures; the optional live job checks
only whether the configured public endpoint still responds.
