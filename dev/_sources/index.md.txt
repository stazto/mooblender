# Mooblender

Mooblender is a free, open-source Blender extension for bringing supported
[Promob](https://promob.com/) assets into a familiar 3D workflow. You can import
local PMob and PContent files or browse a synchronized copy of the public
[Mooble](https://www.mooble.com/br/) catalog without leaving Blender.

The extension is intended for artists, interior designers, visualization teams,
and technical users who need to reuse authorized furniture and interior assets
in Blender. It translates supported geometry, materials, hierarchy, and product
configuration into Blender data. Each import adds one clean scene object driven
by Geometry Nodes instead of filling the Outliner with helper objects.

```{important}
Mooblender is an independent community project. It is not affiliated with,
endorsed by, sponsored by, or maintained by Mooble, Promob, 2020 Spaces,
Cyncly, or their related companies. Those names and trademarks belong to their
respective owners.
```

## What you can do

- Import supported `.pmob` geometry files and `.pcontent` packages.
- Select which regional Mooble catalog and departments to synchronize.
- Browse categories, search names and descriptions, and filter by manufacturer
  or brand collection using the downloaded catalog snapshot.
- Download only the previews and models you actually view or import.
- Adjust supported finishes, optional parts, doors, drawers, and editable
  dimensions through the imported object's Geometry Nodes modifier.
- Keep the Blender scene tidy: source geometry stays unlinked while one
  controller object appears in the active collection.

The online manual is published as
[stable](https://dantedex.github.io/mooblender/stable/),
[latest](https://dantedex.github.io/mooblender/latest/), and
[development](https://dantedex.github.io/mooblender/dev/) channels. Released
manuals also remain available at versioned `/vN.N.N/` URLs.

Mooblender does not reproduce the full Mooble planner or Promob application. It
focuses on catalog discovery and faithful asset transfer into Blender. It also
does not bypass accounts, licenses, regional availability, or service access
rules.

## A typical workflow

1. [Install the extension](installation.md) in Blender 4.5 LTS or 5.2 LTS.
2. Open the **Mooble** tab in the 3D View sidebar.
3. Choose a source country, category language, and the departments you need.
4. Select **Sync Catalog** and let the complete local index finish downloading.
5. Browse or search locally, then import an item. Previews and model packages
   download on demand and are cached for reuse.
6. Select the imported object and use its Geometry Nodes modifier to adjust the
   controls supplied by that package.

If you already have a supported local file, use
**File → Import → Promob Model** instead of synchronizing the catalog.

## Understand the names

[Mooble](https://www.mooble.com/br/) is an online environment-planning platform
for creating and decorating rooms with real products. [Promob](https://promob.com/)
is a family of software solutions for the furniture industry and is presented
by its official site as **Promob | A Cyncly Company**. Mooblender is the
independent bridge that reads supported data from those ecosystems and builds a
usable Blender object.

Read [Mooble, Promob, and credits](credits.md) for their stated purposes,
corporate context, official pages, trademark credit, and the project's
independence disclaimer.

## Compatibility at a glance

| Area | Current support |
| --- | --- |
| Blender | 4.5 LTS and 5.2 LTS |
| Local files | `.pmob` and `.pcontent` |
| Catalog | Explicit Mooble synchronization, then offline browsing and search |
| Result | One scene-linked Geometry Nodes controller object |
| Runtime | Python only; no Promob or .NET runtime required |

```{toctree}
:maxdepth: 2
:caption: User documentation

about
credits
installation
user-guide
troubleshooting
```

```{toctree}
:maxdepth: 2
:caption: Developer documentation

development
mooble
formats/index
```

```{note}
Catalog assets are not licensed by Mooblender. Download and use only files and
models that you are authorized to access, and follow the applicable service and
asset terms.
```
