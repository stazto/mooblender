# Development guide

## Local checks

Run the offline CPython suite and lint checks from the repository root:

```bash
python3 -m unittest discover -s tests -v
ruff check .
```

Ruff enforces Python 3.11 syntax, import/style checks, public API docstrings, and
a cyclomatic-complexity ceiling of 15. Tests are exempt from docstring and
complexity rules because their descriptive method names and synthetic fixtures
form the test contract.

CI repeats the offline suite on Python 3.11, 3.12, and 3.13. It also runs the
Blender smoke and named regression suites in official Blender 4.5 and 5.2
binaries. Each binary is cached by operating system, architecture, exact
version, and cache-layout revision.

Binary fixtures are not committed. PMob records, archives, malformed inputs,
and the tiny image fixture are constructed from Python `bytes` and standard
library builders. See [`../tests/README.md`](../tests/README.md) for the model
regression map.

The live catalog health check is isolated from the normal matrix:

```bash
MOOBLENDER_LIVE_TESTS=1 python3 -m unittest tests.test_mooble_live -v
```

## Build and versioning

Build a deterministic extension archive with:

```bash
python3 build_blender_addon.py
```

The result is `dist/mooblender-<version>.zip` with the extension files at the
archive root. Source manifests and Git tags use `MAJOR.MINOR.PATCH` and
`vMAJOR.MINOR.PATCH`; they never contain `-dev`. The builder adds
`-devNNN` from the GitHub Actions run number or local commit count.

To reproduce a tagged development build:

```bash
python3 build_blender_addon.py --git-tag v0.5.1 --dev-build 1
```

Pushing a matching `v*` tag runs CI, publishes the generated ZIP, and creates a
GitHub prerelease.

## Repository layout

```text
mooblender/          # repository root
├── .agents/         # contributor context, architecture, and roadmap
├── .github/         # continuous integration and release workflow
├── docs/            # user, development, protocol, and format documentation
├── mooblender/      # installable Blender extension and Python package
├── tests/           # offline and headless-Blender regression suites
├── build_blender_addon.py
└── pyproject.toml
```

The low-level `formats`, `model`, and `mooble` packages remain importable without
`bpy`. Blender-specific datablock, UI, and runtime code belongs under
`mooblender/blender`.

## Code commentary policy

Public modules and callable units have docstrings that state their contract.
Inline comments are reserved for information the syntax cannot explain well:
workflow phases, cross-thread ownership, safety boundaries, format observations,
coordinate-system decisions, and reasons an apparently simpler implementation
would be incorrect. When behavior changes, update the nearby invariant comment
in the same change; avoid comments that merely translate Python into prose.

The main import path intentionally follows these layers:

1. `mooble` downloads bounded responses and publishes cache files atomically.
2. `formats` validates bytes and creates Blender-independent package data.
3. `model` evaluates expressions, dimensions, openings, and topology.
4. `mesh_builder` creates unlinked source datablocks and transform records.
5. `scene_builder` interprets package relationships and declares controls.
6. `geometry_nodes` compiles everything into the one scene-linked controller.

Current background workers complete steps 1 and 2, including recursive package
resolution. Blender RNA, model-to-mesh conversion, and datablock creation begin
only on the main thread through timer completions.
