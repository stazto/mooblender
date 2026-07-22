# User guide

## Open the Mooble browser

1. Switch to the **3D View**.
2. Press {kbd}`N` or use **View → Sidebar**.
3. Select the **Mooble** tab.

<!-- SCREENSHOT: Add _static/screenshots/mooble-sidebar-overview.png here.
Capture the full Mooble tab after a successful sync. Annotate Catalog content,
Sync Catalog, search/filters, one result card, Import, and the info icon. Use a
catalog item that is safe to show publicly. -->

The panel is arranged from catalog setup at the top to result cards at the
bottom. Messages are shown beside the operation they describe: catalog status
below **Sync Catalog**, and selected-model download status above search.

## Choose what the catalog contains

Before the first synchronization, configure the **Catalog content** box:

**Source country**
: Chooses the regional Mooble catalog. Brazil, United States, Canada, Spain,
  Argentina, China, and France are supported. It changes model availability,
  not only labels.

**Category names**
: **Source language** keeps names returned by the selected catalog. **English**
  stores a consistent translated category tree while preserving the same items.

**Department checkboxes**
: Choose Furniture, Decor, Openings, Appliances, Fireplaces / Grills, Layout,
  Lights, Materials, and Plants. Furniture is the only default selection.

These options define the next complete local snapshot. Changing country,
language, or department selection requires another synchronization.

## Synchronize the catalog

1. Enable Blender Online Access.
2. Select at least one department.
3. Select **Sync Catalog**.
4. Follow progress directly below the button.

<!-- SCREENSHOT: Add _static/screenshots/catalog-sync-progress.png here. Capture
an active synchronization with the warning, current category, page, record, and
category counts readable. Do not capture browser developer tools. -->

A full synchronization can take several minutes. Mooblender downloads category
pages in the background, writes a temporary SQLite database, validates the
result, and replaces the previous snapshot only after completion. **Cancel
Sync** stops at a safe network boundary and preserves the previous snapshot.

Catalog synchronization does not download every thumbnail or model. It stores
the searchable metadata and category relationships. Preview images appear later
for visible cards, and a model downloads only when you import it.

## Browse and search

After synchronization, all browsing controls query the local snapshot:

- Select a category under **Collections** to enter it.
- Select **Back** to return to the previous category.
- Enter one or more words in search. Press {kbd}`Enter` or select the magnifier
  to apply the query; an empty query restores the current category.
- Use **Manufacturer** to limit results to one brand.
- Use **Brand Collection** to limit the selected manufacturer's collections.
- Select **Load More** when additional local matches are available.

<!-- SCREENSHOT: Add _static/screenshots/catalog-search-filters.png here. Show a
search term, a selected manufacturer, a selected brand collection, the local
match count, Back, and Load More where possible. -->

Search ignores case and accents and matches item name, description, brand,
collection, and identifier. Filters combine: a card must satisfy the search and
both selected menus.

## Read and import a card

Each result card can contain:

- an on-demand preview;
- model name, manufacturer, and brand collection;
- external dimensions in `W × D × H` millimetres;
- an **info** icon that opens the matching regional page on `www.mooble.com`;
- an **Import** button.

Select **Import** to download the model if necessary and build it in the current
scene. Blender remains responsive during the download. Reimporting a cached
model skips the network transfer.

<!-- SCREENSHOT: Add _static/screenshots/model-download-status.png here. Capture
the local object-download message above search while the existing cards remain
visible and disabled. -->

## Import a local file

1. Open **File → Import → Promob Model**.
2. Choose a `.pmob` or `.pcontent` file.
3. In the file browser's options region, decide whether to enable
   **Convert triangles to quads**.
4. Select **Import Promob Model**.

<!-- SCREENSHOT: Add _static/screenshots/local-file-import.png here. Capture the
File Browser with a safe synthetic filename and the Convert triangles to quads
option visible. Do not show personal directories. -->

Triangle-to-quad conversion is disabled by default. It joins only compatible
planar triangle pairs and preserves material boundaries, UV seams, sharp edges,
and meaningful surface changes.

`.content` and `.mob` are not currently supported. Mooblender reports them as
unsupported instead of assuming they use the PMob or PContent layout.

## Work with the imported object

An import creates one visible object in the active scene. Select it and open
the **Modifiers** tab in the Properties editor (wrench icon). The Geometry Nodes
modifier exposes only controls supported by that package:

**Realize Instances**
: Converts the final model instance to realized mesh geometry when an editing or
  export workflow requires it. Leave it disabled for lighter scenes.

**Finish**
: Provides named style menus for the whole model (**Main**) or individual parts.
  Material overrides work before and after realization.

**Options**
: Shows switches for optional or coupled components. Mirrorable packages add a
  **Reverse** switch that reflects the complete footprint and preserves normals.

**Doors and Drawers**
: Provides a separate 0–1 value for each movable component. `0` is closed and
  `1` is fully open.

**Parameters**
: Shows editable insertion dimensions with the limits supplied by the package.
  Fixed dimensions are deliberately omitted.

<!-- SCREENSHOT: Add _static/screenshots/geometry-nodes-controls.png here.
Capture one imported object in the Outliner and its expanded Geometry Nodes
modifier with Realize Instances plus Finish, Options, Doors and Drawers, and
Parameters panels where available. Avoid product-specific annotations. -->

Source meshes are not linked into the scene or shown as helper empties. Geometry
Nodes references those internal datablocks and evaluates hierarchy, placement,
visibility, resizing, movement, reversal, and finish selection.

## Configure preferences

Open **Edit → Preferences → Add-ons**, search for **Mooblender**, and expand its
preferences.

<!-- SCREENSHOT: Add _static/screenshots/addon-preferences.png here. Capture the
expanded Mooblender preferences with all settings visible. Ensure Catalog API
and Partnership contain only their defaults and no private values. -->

| Setting | Purpose | Recommended use |
| --- | --- | --- |
| Catalog API | Base URL for the public catalog service | Keep the default unless maintaining a compatible deployment |
| Source country | Regional catalog used for synchronization and product links | Choose the catalog you are authorized to use |
| Category names | Source-language or English category labels | Choose before synchronization |
| Partnership | Optional service-specific partnership identifier | Leave empty unless your deployment supplies one |
| Page size | Number of local matches materialized at once | Increase for more cards; decrease for a lighter panel |
| Convert triangles to quads | Default for catalog and local imports | Leave off unless editable quad topology is needed |
| Model cache limit | Target disk space for downloaded models | Default: 2048 MiB |
| Thumbnail cache limit | Target disk space for previews | Default: 512 MiB |

## Manage downloads and cache

**Clear Downloads** asks for confirmation and removes cached models and
thumbnails. It keeps the synchronized catalog, so search and navigation remain
available. Active downloads are protected from cleanup.

The cache is stored below Blender's version-specific user-data directory:

- Linux: `~/.config/blender/<version>/datafiles/mooblender/cache/`
- Windows: `%APPDATA%\Blender Foundation\Blender\<version>\datafiles\mooblender\cache\`
- macOS: `~/Library/Application Support/Blender/<version>/datafiles/mooblender/cache/`

The directory contains `catalog.sqlite3`, `models/`, and `thumbnails/`. Blender
4.5 and Blender 5.2 use separate version-specific caches.

## Network and privacy

Mooblender stores no credentials or browser cookies. Catalog and asset requests
are restricted to configured HTTPS hosts. The info icon opens a normal browser
page; the destination website then applies its own privacy policy and access
rules. Clearing downloads does not clear browser data.
