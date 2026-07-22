# Test fixtures and capability coverage

The test suite contains no copied catalog packages. Synthetic PMob records, ZIP
members, images, malformed inputs, and package metadata are assembled in Python
from byte strings and standard-library builders. `test_fixture_policy.py`
enforces this rule in the normal CI matrix.

Regression names in Python may retain the original report identifier for
traceability, but this public map documents the behavior being protected rather
than individual catalog products.

| Capability or invariant | CPython coverage | Blender coverage |
| --- | --- | --- |
| Recursive PMob records, offsets, bounds, strings, matrices, and malformed input | `test_pmob.py` | registration/import smoke |
| Root transforms, unit conversion, hierarchy, and instancing | model and transform suites | `blender_smoke.py` and model regressions |
| UV seams, smooth fans, hard boundaries, custom normals, and safe vertex compaction | topology and PMob suites | mesh shading regressions |
| Optional triangle-to-quad conversion without losing seams or materials | topology suite | smoke scene topology checks |
| Physical cubic UV density and generated UVs after resizing | dimensions/material suites | physical UV checks |
| Material alpha, refractive fallback, specular strength, textures, and exact reuse | PMob/material suites | generated shader checks |
| Recursive PContent aggregation, cycle/depth limits, conditions, and package reuse | aggregate/expression suites | resolved scene checks |
| Logical, drawing, measured, parent, and editable dimensions | `test_dimensions.py` | modifier parameter checks |
| Constant children, optional/coupled components, and model-selected variants | customization suite | Geometry Nodes option checks |
| Door and drawer pivots, travel, inversion, naming, and independent values | opening/model suites | animated modifier checks |
| Stable side-normal orientation and nested aggregate placement | transform/model suites | asymmetric placement checks |
| One linked controller, unlinked source meshes, no helper empties, and node-only transforms | architecture/model suites | outliner and node-graph checks |
| Concise finish menus, per-component scope, instanced assignment, and realization | customization suite | modifier/material checks |
| Full local catalog, atomic replacement, parallel downloads, and cancellation | `test_catalog_store.py` | asynchronous operator smoke |
| Country selection, English category labels, and snapshot identity | catalog localization/store suites | preference and panel checks |
| Local search, category navigation, manufacturer and collection filters | search/store suites | interactive state checks |
| Card dimensions, regional product URLs, and on-demand thumbnails | Mooble/client/store suites | card property and layout checks |
| Cache size limits, recency, active-path protection, and safe cleanup | cache/transport suites | preview and operator cleanup checks |
| Retry limits, `Retry-After`, host validation, and atomic downloads | transport/client suites | offline-state checks |
| Deterministic archive versioning and fixture policy | build/policy suites | extension installation layout |

The opt-in live test checks only whether the public
[Mooble](https://www.mooble.com/br/) catalog endpoint still responds. It runs
once outside the normal Python matrix and is not a source of binary fixtures or
product-specific assertions.
