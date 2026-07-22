# Development guide

## Repository layout

```text
mooblender/                 repository root
├── .github/workflows/      tests, releases, and documentation deployment
├── docs/                   public user and developer documentation
├── mooblender/             installable Blender extension and Python package
├── tests/                  synthetic CPython and Blender regressions
├── build_blender_addon.py  deterministic extension builder
└── pyproject.toml          Python lint configuration
```

Low-level `formats`, `model`, and `mooble` modules must remain importable without
`bpy`. Blender RNA, UI, datablocks, previews, and node construction belong under
`mooblender/blender`.

## Run code checks

From the repository root:

```bash
python3 -m unittest discover -s tests -v
ruff check .
git diff --check
```

The offline matrix runs on Python 3.11, 3.12, and 3.13. Blender integration runs
against official Blender 4.5 and 5.2 binaries. CI caches each binary by platform,
architecture, exact version, and cache-layout revision.

The live service health check is separate from the normal test matrix:

```bash
MOOBLENDER_LIVE_TESTS=1 python3 -m unittest tests.test_mooble_live -v
```

Tests build PMob records, PContent archives, images, and malformed input from
Python byte strings and standard-library builders. Do not commit proprietary or
binary catalog fixtures. The capability map is maintained in the repository's
[`tests/README.md`](https://github.com/dantedex/mooblender/blob/main/tests/README.md).

## Build the documentation

Create a virtual environment, install the pinned documentation toolchain, and
run Sphinx with warnings treated as errors:

```bash
python3 -m venv .venv-docs
. .venv-docs/bin/activate
python -m pip install --requirement docs/requirements.txt
python -m sphinx -W --keep-going -b html docs docs/_build/html
```

On Unix-like systems, `make -C docs html` is equivalent after dependencies are
installed. On Windows, run `docs\make.bat html`. Open
`docs/_build/html/index.html` to inspect the site.

Use the optional external-link checker when network access is available:

```bash
python -m sphinx -W --keep-going -b linkcheck docs docs/_build/linkcheck
```

Sphinx uses MyST-Parser so the source remains readable Markdown. `conf.py` reads
the version from `blender_manifest.toml`; documentation and add-on versions
cannot silently diverge.

## Add screenshots

Screenshot comments in the user documentation specify the intended filename,
UI state, crop, and privacy constraints. Add PNG files under
`docs/_static/screenshots/`, then replace the nearby comment with a MyST figure:

````markdown
```{figure} _static/screenshots/example.png
:alt: Concise description of the visible Blender controls
:width: 100%

Optional caption.
```
````

Use Blender's default theme unless a UI behavior specifically depends on a
theme. Never include personal paths, usernames, credentials, private catalog
content, or unrelated desktop areas.

## GitHub Pages

`.github/workflows/docs.yml` builds every documentation pull request with
warnings as errors. A push to `main` that changes the documentation builds and
uploads the HTML artifact, then deploys it through the protected
`github-pages` environment.

Repository administrators must select **GitHub Actions** once under
**Settings → Pages → Build and deployment → Source**. The workflow uses the
official `configure-pages`, `upload-pages-artifact`, and `deploy-pages` actions.

## Build and version the extension

Create a deterministic extension ZIP:

```bash
python3 build_blender_addon.py
```

Source manifests and Git tags use `MAJOR.MINOR.PATCH` and
`vMAJOR.MINOR.PATCH`; neither contains `-dev`. The builder adds `-devNNN` from
the GitHub Actions run number or local Git commit count.

To reproduce a tagged development build:

```bash
python3 build_blender_addon.py --git-tag v0.5.1 --dev-build 1
```

Pushing a `v*` tag runs the complete CI suite, publishes the ZIP artifact, and
creates a GitHub prerelease.

## Runtime workflow

1. `mooble` downloads bounded responses and publishes cache files atomically.
2. `formats` validates bytes and creates Blender-independent package data.
3. `model` evaluates expressions, dimensions, openings, and topology.
4. `mesh_builder` creates unlinked source datablocks and transform records.
5. `scene_builder` interprets package relationships and declares controls.
6. `geometry_nodes` compiles the result into one scene-linked controller.

Network, archive parsing, and recursive package resolution run outside Blender's
main thread. Blender RNA and datablock creation begin only in timer completions
on the main thread.

## Documentation policy

Public documentation describes user tasks, developer contracts, format traits,
security boundaries, and supported behavior. Product-specific regression
evidence, private investigation history, and implementation planning do not
belong in the rendered manual.

Every public Python module and callable has a docstring. Inline comments should
explain workflow phases, ownership, safety boundaries, coordinate conventions,
or why a simpler-looking implementation would be incorrect—not restate syntax.
