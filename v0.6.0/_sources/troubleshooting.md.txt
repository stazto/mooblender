# Troubleshooting

## Sync Catalog is disabled

Enable **Allow Online Access** under **Edit → Preferences → System → Network**.
The button remains disabled while Blender is offline.

## The panel asks me to synchronize again

Country, category language, and catalog schema are part of the snapshot
identity. Run **Sync Catalog** after changing those settings or installing a
version that updates the catalog schema.

## Synchronization takes a long time

Large department selections can take several minutes. Progress below the button
should continue to update. You can select **Cancel Sync** without damaging the
previous catalog. Selecting fewer departments reduces the amount of work.

## Search returns fewer items than expected

Search applies inside the current category and combines with Manufacturer and
Brand Collection. Select **Back** until you reach the catalog root, reset both
filters to their **All** options, clear the search field, and press {kbd}`Enter`.
If the catalog source is outdated, synchronize it again.

## A preview is missing

Previews are downloaded only for visible cards. Wait briefly, check Blender
Online Access, and verify the network connection. A missing preview does not
prevent model import.

## The info icon opens a missing page

The icon uses the synchronized country and item identifier. The website may not
publish a page for every item or may remove an item after your last sync. Run a
new synchronization before reporting a broken mapping.

## Import is slow

The first import may download a model and its referenced components. Later
imports reuse cached packages. Download progress appears above search while
Blender remains responsive.

## The imported object has no control I expected

Controls are created only when the package provides supported metadata. Fixed
parts do not receive size controls, and models without valid opening services do
not receive door or drawer controls. This prevents inactive gray inputs.

## I need editable mesh geometry

Enable **Realize Instances** in the imported object's Geometry Nodes modifier.
For local mesh editing, you may also need to apply the modifier on a duplicate.
Keep the original controller object if you want to preserve configurable inputs.

## Materials or transparency look different between renderers

The importer maps supported PMob material traits to Blender's Principled shader.
Renderer color management, lighting, and transmission settings can still change
the final appearance. Verify the material in a neutral lit scene before editing
its generated node tree.

## Clear only downloaded files

Use **Clear Downloads** in the [Mooble](https://www.mooble.com/br/) panel. It
removes models and previews but keeps `catalog.sqlite3`. To discard the catalog
too, close Blender and remove the catalog database from the cache directory
shown in the user guide.

## Reporting a problem

Include:

- Mooblender version;
- Blender version and operating system;
- whether the source was local or from the catalog;
- the visible error message;
- the minimum steps needed to reproduce the issue; and
- a legally shareable synthetic or stripped fixture when possible.

Do not publish credentials, private catalog files, or personal filesystem paths.
