# User guide

## Requirements and installation

Mooblender supports Blender 4.5 LTS and 5.2 LTS. Install the generated
`mooblender-<version>.zip` through Blender's Extensions preferences and enable
the extension. Online catalog actions also require Blender's **Online Access**
setting.

## Catalog workflow

1. Open the **Mooble** tab in the 3D View sidebar.
2. Select the catalog departments that should exist in the local snapshot.
3. Select **Sync Catalog** and keep using the previous snapshot while the new
   one downloads.
4. Browse categories or combine text, manufacturer, and brand-collection
   filters.
5. Select **Import** on a result card.

Synchronization is the only catalog-wide network action. It downloads the full
selected index into a temporary SQLite database and publishes it atomically.
Search, category navigation, Back, and Load More then query only that snapshot.
Thumbnails and models are separate on-demand downloads; cached files are reused.

The department checkboxes cover Móveis, Decor, Construção, Eletros,
Lareiras/Churrasqueiras, Layout, Luzes, Materiais, and Plantas. Only Móveis is
enabled by default. Large furniture snapshots can take several minutes, but
download work remains outside Blender's main thread.

## Local files

Use **File → Import → Promob Model** for `.pmob` and `.pcontent`. The importer
rejects `.content` and `.mob` until those formats have been independently
identified and documented.

**Convert triangles to quads** is optional in both the sidebar and file-import
dialog. It joins only compatible planar triangle pairs and preserves UV seams,
hard edges, material boundaries, and non-planar surface changes.

## Imported object and controls

Each import creates one scene-linked object with a Geometry Nodes modifier. The
source collection and its transform hierarchy stay unlinked from the scene and
remain instanced by default.

Modifier controls are ordered as follows:

1. **Realize Instances** converts the nested hierarchy to mesh geometry when a
   downstream workflow requires it. Non-default material overrides operate on
   this realized branch.
2. The **Finish** panel contains one named style menu per affected part. Menu
   labels contain only the part name, such as **Tampo**, without a redundant
   `Finish:` or `Acabamento` prefix.
3. **Options** contains default-enabled switches for independently selectable
   components such as worktops and baseboards. Models marked as mirrorable also
   receive a **Reverse** switch that mirrors the full hierarchy in place.
4. **Doors and Drawers** contains independent 0–1 controls for movable parts.
5. **Parameters** contains editable insertion dimensions such as **Largura** and
   **Profundidade**, including their source limits.

Controls are single values rather than fields. Numeric or directional component
labels retain their kind, for example **Drawer: 1ª** and **Door: Esq**. Constant
aggregate children do not expose misleading size controls.
Driver-backed inputs also remain connected to the final Geometry Nodes output
through neutral geometry operations. This keeps Blender from drawing active,
editable controls with the disabled gray appearance reserved for unused inputs.

## Geometry and material behavior

The importer preserves PMob transforms and source units, reconstructs smoothing
groups and compatible normal fans, compacts UV-seam duplicate vertices onto
Blender's corner domain, and generates physical UV projection when required.
Fixed hardware remains fixed while supported editable panels stretch around its
boundary. Exactly equal, unmodified materials are reused; edited Blender
materials are left untouched.

The browser stores catalog data, models, and thumbnails in Blender's managed
user-data directory. It stores no credentials and restricts downloads to
configured HTTPS hosts.
