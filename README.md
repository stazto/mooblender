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

The extension targets Blender 4.2 or newer. Build an installable, reproducible
ZIP from the repository root:

```bash
python3 build_blender_addon.py
```

The archive is written to `dist/mooblender-<version>.zip`. It contains the
contents of the inner `mooblender/` extension directory at its root, as Blender
expects.

## Versioning and releases

Development versions use `MAJOR.MINOR.PATCH-devNNN`, where `NNN` is a
zero-padded sequence number. Release tags add a `v` prefix, for example
`v0.1.0-dev001`.

Git tags are authoritative for release builds. Pushing a matching `v*` tag runs
the complete CI suite, injects the tag version into the packaged Blender
manifest, and creates a GitHub Release with the ZIP attached. `-devNNN` tags
create prereleases; plain `vMAJOR.MINOR.PATCH` tags create stable releases.

To reproduce a tagged build locally:

```bash
python3 build_blender_addon.py --git-tag v0.1.0-dev001
```

After enabling it:

1. Open the **Promob** tab in the 3D View sidebar.
2. Enable Blender's **Online Access** setting when using Mooble.
3. Select **Refresh**, browse a collection or search, then select **Import**.
4. For local files, use **File → Import → Promob Model**.

The browser talks only to configured HTTPS Mooble hosts and caches selected
models and thumbnails in Blender's user data directory. It does not store
credentials or bypass access controls.

## Development

Run the Blender-independent suite from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

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
