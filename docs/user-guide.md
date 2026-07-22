# User guide

## Requirements and installation

Mooblender supports Blender 4.5 LTS and 5.2 LTS. Install the generated
`mooblender-<version>.zip` through Blender's Extensions preferences and enable
the extension. Online catalog actions also require Blender's **Online Access**
setting.

## Catalog workflow

1. Open the **Mooble** tab in the 3D View sidebar.
2. Select the source country, category-name language, and departments that
   should exist in the local snapshot.
3. Select **Sync Catalog** and keep using the previous snapshot while the new
   one downloads.
4. Browse categories or combine text, manufacturer, and brand-collection
   filters.
5. Read the external W/D/H dimensions directly on a card, or select its
   information icon for description, manufacturer, collection, and dimensions.
6. Select **Import** on a result card.

Synchronization is the only catalog-wide network action. It downloads the full
selected index into a temporary SQLite database and publishes it atomically.
Search, category navigation, Back, and Load More then query only that snapshot.
Thumbnails and models are separate on-demand downloads; cached files are reused.
Card dimensions and information come from the SQLite snapshot, so opening the
information dialog never makes a network request.

**Source country** chooses which Mooble catalog supplies the models: Brazil,
United States, Canada, Spain, Argentina, China, or France. **Category names**
can retain the selected country's source language or store a consistent English
view. This changes labels only; it never substitutes models from another
country. English mode uses stable category IDs and an offline taxonomy, so an
unknown future category receives an English placeholder instead of introducing
a source-language word into the same list.

The department checkboxes cover Furniture, Decor, Openings, Appliances,
Fireplaces/Grills, Layout, Lights, Materials, and Plants. Only Furniture is
enabled by default. A complete catalog synchronization can take a very long
time—even many minutes for large department selections, depending on the
service and network. Its progress appears directly below **Sync Catalog**, and
the download work remains outside Blender's main thread. Use **Cancel Sync** to
stop at the next completed network request; the incomplete temporary database
is discarded and the previous cached catalog remains unchanged.

When a selected model is downloading for import, its separate progress message
appears immediately above the search box. Catalog synchronization and model
downloads do not replace the existing browser contents.

## Local files

Use **File → Import → Promob Model** for `.pmob` and `.pcontent`. The importer
rejects `.content` and `.mob` until those formats have been independently
identified and documented.

**Convert triangles to quads** is optional in both the sidebar and file-import
dialog. It joins only compatible planar triangle pairs and preserves UV seams,
hard edges, material boundaries, and non-planar surface changes.

## Imported object and controls

Each import creates one scene-linked object with a Geometry Nodes modifier.
Unlinked source meshes remain instanced by default, while every source,
aggregate, opening, resize, visibility, and reversal transform is evaluated
inside the node group. Imports do not create helper empties.

Modifier controls are ordered as follows:

1. **Realize Instances** converts the transformed model instance to mesh
   geometry when a downstream editing workflow requires it. Finish overrides
   work in both the default instanced branch and the realized branch.
2. The **Finish** panel contains one named style menu per affected part. Menu
   labels contain only the part name, such as **Tampo**, without a redundant
   `Finish:` or `Acabamento` prefix. A model-wide style is named **Main** rather
   than repeating the imported object's full name.
3. **Options** contains default-enabled switches for independently selectable
   or coupled components such as worktops and baseboards. Repeated segments
   with the same component name share one switch. Models marked as mirrorable also
   receive a **Reverse** switch that mirrors the full model in place.
4. **Doors and Drawers** contains independent 0–1 controls for movable parts.
5. **Parameters** contains editable insertion dimensions such as **Largura** and
   **Profundidade**, including their source limits.

Controls are single values rather than fields. Numeric or directional component
labels retain their kind, for example **Drawer: 1ª** and **Door: Esq**. Constant
aggregate children do not expose misleading size controls.
Every editable input connects directly to the transform or material nodes that
produce the final output. Blender therefore displays controls as active instead
of using the disabled gray appearance reserved for unused inputs.

## Geometry and material behavior

The importer preserves PMob transforms and source units, reconstructs smoothing
groups and compatible normal fans, compacts safe UV-seam duplicate vertices
onto Blender's corner domain, and generates physical UV projection when
required. Explicit groups preserve omitted hard edges. When smoothing metadata
is absent, authored vertex splits remain intact because position and face angle
alone cannot reliably distinguish UV seams from disconnected hard boundaries.
Negative-determinant component transforms and whole-model reversal correct face
winding inside Geometry Nodes, so mirroring does not invert visible normals.
Fixed hardware remains fixed while supported editable panels stretch around its
boundary. Exactly equal, unmodified materials are reused; edited Blender
materials are left untouched. PMob glass and acrylic refraction metadata keeps
its IOR and uses an alpha-blended viewport/render fallback that does not require
enabling Eevee ray tracing, including glass whose source opacity is `1.0`.
Serialized specular strength controls dielectric reflection, and embedded
diffuse-image alpha is multiplied by material opacity instead of being discarded.

The browser stores catalog data, models, and thumbnails in Blender's managed
user-data directory. Models and thumbnails have independent limits under the
add-on preferences: 2 GB for models and 512 MB for thumbnails by default.
After a successful download, Mooblender removes the oldest inactive files from
that group until it reaches the configured limit; the model currently being
imported and previews still downloading are protected. A limit is therefore a
target: one active model larger than its configured limit is retained so the
requested import can finish.

Use **Clear Downloads** in the sidebar to remove cached models and thumbnails
after confirmation. This releases loaded preview icons and refreshes visible
cards, but deliberately keeps the synchronized SQLite catalog, current search,
and category navigation. The add-on stores no credentials and restricts
downloads to configured HTTPS hosts.
