# Mooblender

Mooblender is an early open-source Blender extension for browsing the
Mooble catalog and importing Promob models.

## Current implementation

- Pure-Python, bounds-checked `.pmob` parser.
- Safe in-memory `.pcontent` ZIP reader, including its observed
  BinaryWriter-prefixed `properties.json` member.
- Recursive Mooble aggregate resolution for properties-only furniture packages,
  including selected child specifications and remote finish materials.
- Blender import operator for `.pmob` and `.pcontent`.
- Mooble sidebar with search, hierarchical collection navigation, thumbnails,
  pagination, download caching, and one-click import.
- Blender-independent tests for the PMob, PContent, and Mooble layers.

`.content` and `.mob` appear in the product roadmap but are intentionally
rejected until their formats are identified from reproducible samples.

## Install and use

The extension targets Blender 4.5 or newer. Build an installable, reproducible
ZIP from the repository root:

```bash
python3 build_blender_addon.py
```

The archive is written to `dist/mooblender-<version>.zip`. It contains the
contents of the inner `mooblender/` extension directory at its root, as Blender
expects.

## Versioning and releases

Git tags contain only the target version, using `vMAJOR.MINOR.PATCH`, for
example `v0.1.0`. A `-devNNN` suffix is never placed in a tag or the source
manifest. The build script adds it automatically, using the zero-padded GitHub
Actions run number in CI or the Git commit count locally.

Git tags are authoritative for the target version. Pushing a matching `v*` tag
runs the complete CI suite, builds `MAJOR.MINOR.PATCH-devNNN`, injects that
generated version into the packaged Blender manifest, and creates a GitHub
prerelease with the ZIP attached.

To reproduce a tagged build locally:

```bash
python3 build_blender_addon.py --git-tag v0.1.0 --dev-build 1
```

After enabling it:

1. Open the **Mooble** tab in the 3D View sidebar.
2. Enable Blender's **Online Access** setting when using Mooble.
3. The catalog loads automatically; browse a collection or search, then select
   **Import**.
4. For local files, use **File → Import → Promob Model**.

The default import mode creates one visible object with a Geometry Nodes
modifier. Each recognized door or drawer gets its own 0–1 input, named from its
Mooble component metadata; models without movable components get no opening
inputs. Editable insertion dimensions become distance inputs such as
**Largura** and **Profundidade**, with the source limits preserved. Named
**Finish** menus select the styles exposed by the source model.
Nested editable components receive scoped labels such as
**Prateleira: Largura**, so repeated package instances remain independent.
Default remote finishes are applied before any selection, and finish controls
are scoped to their source package so same-named cabinet and door layers do not
overwrite one another.
Choose **Collection hierarchy** in the extension preferences when individual
Promob primitives and aggregates are more useful than a single object.

The complete catalog metadata index is downloaded through the Explorer pages
and cached on disk; model binaries remain on-demand. At startup, the cached
index appears immediately and one background first-page check compares its
items and category counts. A detected change rebuilds the index atomically.
The first complete build can take several minutes for the currently reported
14,000-plus records, but it does not block Blender's main thread.

Search is case- and accent-insensitive and runs entirely against that local
index. Committing the search field or selecting its magnifier updates the cards;
committing an empty field restores the unfiltered catalog. Only one bounded
result batch becomes UI cards at a time, and **Load More** expands the local
matches without contacting Mooble. Thumbnails are fetched only for those
visible cards. Each card shows a loading symbol until its preview arrives.
During catalog or model operations, the panel remains visible with its controls
disabled and a loading message above it. Blender data is only created on its
main thread.

Every separately visited category also remains in the disk cache. Opening an
already visited category or using **Back** restores that cached page immediately
without a network request.

The browser talks only to configured HTTPS Mooble hosts and caches selected
models and thumbnails in Blender's user data directory. It does not store
credentials or bypass access controls.

## Blender compatibility

Mooblender supports Blender 4.5 LTS and 5.2 LTS. The extension manifest keeps
`blender_version_min = "4.5.0"` and intentionally has no maximum. The add-on
uses the `bl_ext.user_default.mooblender` Blender Extensions identifier.

## Development

Run the Blender-independent suite from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

CI additionally launches the add-on in official Blender 4.5.0 and 5.2.0
binaries. Each smoke test registers the add-on and builds disposable
geometry, UVs, and material datablocks through the real Blender Python API.
Each exact Blender installation is cached separately by operating system,
architecture, version, and cache-layout revision, so later runs skip the large
download and extraction.

The normal suite is entirely offline. An opt-in live check verifies the
observed Mooble catalog endpoint:

```bash
MOOBLENDER_LIVE_TESTS=1 python3 -m unittest tests.test_mooble_live -v
```

See [`.agents/IMPLEMENTATION_PLAN.md`](.agents/IMPLEMENTATION_PLAN.md) for the
phased roadmap and [`docs/mooble.md`](docs/mooble.md) for the observed catalog
protocol.

## Repository structure

```text
mooblender/          # repository root
├── .agents/         # public contributor context and implementation plan
├── .github/         # continuous integration workflow
├── build_blender_addon.py
├── mooblender/      # installable Blender extension and Python package
├── docs/            # format and protocol documentation
├── tests/           # Blender-independent tests
└── pyproject.toml   # development-tool configuration
```

## Status and limitations

The current scene builder preserves PMob primitive hierarchy and transforms,
reuses referenced layer meshes, converts observed units correctly, builds
Principled materials from embedded textures, reconstructs Mooble aggregates,
and exposes supported opening and finish choices through Geometry Nodes.
Observed `InsertDimension` ranges are also exposed as axis-specific Geometry
Nodes controls.
Unverified PMob animation timing, smoothing-group semantics, some mapping
modes, alternative non-default aggregate specifications, and all
`.content`/`.mob` behavior remain planned work.

## License

The original source in this project is licensed under GPL-3.0-or-later. Promob,
Mooble, and downloaded catalog assets remain the property of their respective
owners; users are responsible for ensuring they may access and use each asset.
