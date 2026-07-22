# Mooblender

Mooblender is an open-source Blender extension for browsing the Mooble catalog
and importing Promob models. It is written entirely in Python and does not
depend on Promob runtime libraries.

The current development target imports `.pmob` and `.pcontent`, resolves
Mooble aggregate packages, and creates one scene-linked object controlled by
Geometry Nodes. `.content` and `.mob` remain research targets until their
formats are identified from reproducible samples.

## Highlights

- Local, bounds-checked PMob and PContent readers.
- Full selected-department catalog synchronization into an atomic SQLite cache.
- Offline category browsing, text search, manufacturer filtering, and
  brand-collection filtering after synchronization.
- On-demand model and thumbnail downloads with persistent caches.
- Geometry Nodes controls for supported finishes, optional components, doors,
  drawers, and editable insertion dimensions.
- Transform, smoothing, hard-edge, UV, material, and aggregate reconstruction
  covered by synthetic regression tests.

## Install

Mooblender supports Blender 4.5 LTS and 5.2 LTS. Build the extension archive
from the repository root:

```bash
python3 build_blender_addon.py
```

Install the generated `dist/mooblender-<version>.zip` through Blender's
Extensions preferences. Enable Blender's **Online Access** setting to use the
Mooble catalog.

## Quick start

1. Open the **Mooble** tab in the 3D View sidebar.
2. Select the catalog departments to retain and choose **Sync Catalog**.
3. Browse or search the local snapshot, then choose **Import** on a model.
4. To import a local file, use **File → Import → Promob Model**.

Synchronization is the only catalog-wide network action. Browsing and search
use the last complete local snapshot; thumbnails and selected models download
only when needed. Each import creates one visible controller object while its
source hierarchy remains in an unlinked collection referenced by Geometry
Nodes.

See the [user guide](docs/user-guide.md) for catalog behavior, import options,
and modifier controls.

## Development

Run the offline tests and quality checks with:

```bash
python3 -m unittest discover -s tests -v
ruff check .
```

CI repeats the offline suite on supported Python versions and runs Blender
integration tests against Blender 4.5 and 5.2. Binary fixtures are not
committed; tests construct PMob records, archives, and images from Python
`bytes` and standard-library builders.

Tags use stable versions such as `v0.1.0`. The build script adds the generated
`-devNNN` suffix to packaged development versions; source manifests and tags
never contain that suffix.

Read the [development guide](docs/development.md), [test coverage map](tests/README.md),
and [documentation index](docs/README.md) for details.

## Status

The PMob and Mooble formats are only implemented where behavior has been
observed and reproduced. Unsupported semantics are documented rather than
guessed. Current format evidence and open questions live in
[`docs/formats/`](docs/formats/) and [`docs/mooble.md`](docs/mooble.md).

## License

Original source in this repository is licensed under GPL-3.0-or-later. Promob,
Mooble, and catalog assets remain the property of their respective owners;
users are responsible for ensuring they may access and use downloaded assets.
