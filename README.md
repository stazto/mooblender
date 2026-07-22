# Mooblender

[Documentation](https://dantedex.github.io/mooblender/stable/) ·
[Source](https://github.com/dantedex/mooblender) ·
[License](LICENSE.md)

Mooblender brings supported [Promob](https://promob.com/) content into Blender.
It combines a local file importer with an offline-first
[Mooble](https://www.mooble.com/br/) catalog browser and creates one clean scene
object whose supported finishes, options, movable parts, and dimensions remain
accessible through Geometry Nodes.

> [!IMPORTANT]
> Mooblender is an independent community project. It is not affiliated with,
> endorsed by, sponsored by, authorized by, or maintained by Mooble, Promob,
> 2020 Spaces, Cyncly, or any related company. Their names, trademarks, catalog
> data, images, and models belong to their respective owners.

The extension is open source, written entirely in Python, and does not require
Promob, .NET, Wine, or proprietary runtime libraries inside Blender.

The current development target imports `.pmob` and `.pcontent`, resolves Mooble
aggregate packages, and creates one scene-linked object controlled by Geometry
Nodes.

## Highlights

- Local, bounds-checked PMob and PContent readers.
- Country-selectable, selected-department catalog synchronization into an
  atomic SQLite cache, with source-language or English category labels.
- Offline category browsing, text search, manufacturer filtering, and
  brand-collection filtering after synchronization.
- Cached external dimensions and a regional Mooble information link on every card.
- On-demand model and thumbnail downloads with persistent caches.
- Configurable model/thumbnail cache limits and catalog-preserving cleanup.
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
2. Select the source country, category-name language, and catalog departments
   to retain, then choose **Sync Catalog**.
3. Browse or search the local snapshot, then choose **Import** on a model.
4. To import a local file, use **File → Import → Promob Model**.

Synchronization is the only catalog-wide network action. Browsing and search
use the last complete local snapshot; thumbnails and selected models download
only when needed. Each import creates one visible controller object. Unlinked
source meshes are referenced directly by Geometry Nodes; their complete
transform hierarchy is encoded in the node graph, without helper empties.

> **Note:** A complete catalog synchronization can take a very long time—often
> several minutes for large department selections. Progress remains visible
> below **Sync Catalog**. **Cancel Sync** safely discards incomplete work, and
> the previous cached catalog stays available.

See the [stable documentation](https://dantedex.github.io/mooblender/stable/) for
installation, catalog navigation, configuration, troubleshooting, format
references, and contributor workflows.

## Mooble and Promob

[Mooble](https://www.mooble.com/br/) is an online 3D environment-planning
platform for creating and decorating rooms with real products. Its objective is
to connect room projects with product discovery and, where available, stores or
e-commerce. The interactive application is the
[Mooble Planner](https://planner.mooble.com/br/).

[Promob](https://promob.com/) provides software for the furniture industry,
connecting design, quoting, production, sales, and management. Its official
company page identifies the business as **Promob | A Cyncly Company**. See the
[project credits](https://dantedex.github.io/mooblender/stable/credits.html) for a
longer description, official links, ownership context, and trademark notice.

## Documentation

The manual is built with Sphinx and MyST Markdown:

```bash
python3 -m pip install --requirement docs/requirements.txt
python3 -m sphinx -W --keep-going -b html docs docs/_build/html
```

GitHub Actions validates documentation changes. Every commit or merge into
`main` updates the [development manual](https://dantedex.github.io/mooblender/dev/).
A published release updates `/stable`, `/latest`, and its permanent
`/vN.N.N` URL. Screenshot placement notes are kept as comments beside the
relevant user-guide steps.

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

Tags use stable versions such as `v0.5.1`. The build script adds the generated
`-devNNN` suffix to packaged development versions; source manifests and tags
never contain that suffix.

Read the [development guide](docs/development.md) and
[test coverage map](tests/README.md) for details.

## Status

The PMob and PContent readers and Mooble integration are implemented only where
behavior has been observed and reproduced. Unsupported semantics are documented
rather than guessed. Current format evidence and open questions live in
[`docs/formats/`](docs/formats/) and [`docs/mooble.md`](docs/mooble.md).

## AI Usage

The foundations of this project started more than two years ago just as a
.pcontent mesh importer. With the usage of GPT 5.6 Sol, this project was
extended to include a Mooble catalog browser and Geometry Nodes controller. The
AI was used to assist in code generation, documentation, and testing. The AI
was used to generate code snippets, documentation, and test cases. Until now,
most of the code is still written by AI, with large human interaction, review,
guidance and testing. Now the project enter a new phase with human developer
reviewing, rewriting and improving the code.

## License

Original source in this repository is licensed under GPL-3.0-or-later. Mooble,
Promob, 2020 Spaces, Cyncly, and their related names and trademarks remain the
property of their respective owners. Catalog assets remain the property of
their publishers or licensors; users are responsible for ensuring they may
access and use downloaded assets.
