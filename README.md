# Mooblender

Mooblender is an early open-source Blender extension for browsing the
Mooble catalog and importing Promob models.

## Current implementation

- Pure-Python, bounds-checked `.pmob` parser.
- Safe in-memory `.pcontent` ZIP reader, including its observed
  BinaryWriter-prefixed `properties.json` member.
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
3. Select **Refresh**, browse a collection or search, then select **Import**.
4. For local files, use **File → Import → Promob Model**.

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

The current scene builder creates geometry, per-vertex UVs, basic materials,
and source metadata. Primitive transforms, hierarchy, texture resolution,
custom normals, smoothing groups, animations, and all `.content`/`.mob`
behavior remain planned work.

## License

The original source in this project is licensed under GPL-3.0-or-later. Promob,
Mooble, and downloaded catalog assets remain the property of their respective
owners; users are responsible for ensuring they may access and use each asset.
