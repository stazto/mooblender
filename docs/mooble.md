# Mooble catalog integration

Status: live protocol observation from 2026-07-21. This is not a promise that
the service will retain the same endpoints or schema.

The current Mooble planner loads a public catalog SDK from
`https://catalog.mooble.com`. Its model explorer uses an Explorer v2 GET request
under `/api/explorer/v2` with parameters including:

- `client=mooble`;
- `internal=Item`;
- `pin=Departamento`;
- `!Departamento=<category>`;
- `region=<region>`;
- optional `partnership` and `search`; and
- `$top=<page size>`.

The response contains `Output.Pin.AvailableTags.Data` for hierarchical category
navigation and `Output.Specifications.Data` for product cards. Tag records expose
navigation URLs and counts. Specification summaries expose IDs, names,
descriptions, brands, collections, thumbnail links, dimensions, and detail URLs.
Pagination is supplied as a server-generated `Links.Next` URL.
Initial Explorer responses place product records under
`Output.Specifications.Data`; observed `GetNext/Specs` responses instead place
`Data`, `Links`, and `HasMore` directly at the response root. Both shapes must
be parsed or pagination silently appears empty.

## Catalog synchronization and local queries

The observed root furniture category reports more than 14,000 models. Mooblender
contacts Explorer catalog endpoints only after the user selects **Sync
Catalog**. The background synchronizer follows the root pagination and every
category branch with a 48-item request size, per-category page and cycle limits,
and global category, item, and membership safety limits. Thumbnails and model
PContent are not part of catalog synchronization.

Although observed continuation URLs default to 15 records, their endpoint was
verified to accept 48 and returns the next skip value accordingly. The indexer
normalizes that existing `$top` parameter to 48. It also compares the final
unique-item count with the selected root category's `SpecCount`; an early or
misparsed end aborts the sync instead of publishing a partial index. On
2026-07-21 this check reported 14,310 root furniture items, and a bounded live
`kappesberg` verification returned all 310 reported matches in seven pages.

The API summaries do not expose their department membership directly. The sync
therefore records each category's complete ordered item-ID set while
deduplicating model summaries in a temporary SQLite database. That database
replaces the previous snapshot atomically only after the complete category tree
succeeds. A failed or interrupted synchronization leaves the last usable
snapshot untouched.

Startup opens the SQLite snapshot and makes no catalog request. Category, Back,
search, manufacturer, and pagination actions query the local snapshot only.
The old snapshot remains interactive while a new one synchronizes, with page,
model, and category progress displayed separately from model-import activity.

Search never sends the query to the Explorer API. It matches all whitespace-
separated terms, case- and accent-insensitively, against the complete cached
root catalog's name, description, brand, collection, and ID fields. Empty
search restores the root catalog. A local manufacturer dropdown is derived
from the non-empty `Brand.Name` values in that complete index. Manufacturer
equality is case- and accent-insensitive
and combines with every text term. The sidebar materializes only a preference-
sized window of results; **Load More** expands that local window, and only
visible cards request thumbnails.

Category branches and item memberships are all captured by synchronization.
Opening a category for the first time is therefore the same local database read
as revisiting it and works without Blender Online Access.

Fetching a specification detail URL can add `Links.Content`. Publicly visible
shape records observed during development linked to HTTPS CDN `.pcontent`
resources. The add-on downloads only after the user selects **Import**, validates
the HTTPS host and size, caches the response, and passes it through the same
PContent reader used for local files.

Properties-only products use the same detail endpoint for their aggregate and
material UUIDs: `GET /api/explorer/GetSpec/<uuid>`. The observed response has a
`Type` such as `Shape` or `Material` and an HTTPS `Links.Content` PContent URL.
Responses observed on 2026-07-21 used `Cache-Control: public, max-age=1800`.
Mooblender caches every downloaded child by specification ID and resolves the
tree in its model-download worker, leaving all Blender datablock creation on
the main thread.

## Browser interaction

The sidebar borrows the compact workflow of the open-source
[IKEA Browser](https://github.com/shish/blender-ikea-browser/): search, thumbnail
cards, metadata, cache, and one-click import. Mooble additionally requires a
hierarchical collection list, back navigation, and bounded local result pages.
The search field is debounced locally while editing; committing it with Enter
or selecting the magnifier therefore always displays only matching cached
objects, including the empty-query reset case. **Sync Catalog** is deliberately
explicit; enabling the add-on and starting Blender never triggers a catalog
download.

## Compatibility policy

- Network actions require Blender Online Access.
- API URL and regional values are preferences because deployments may differ.
- Returned URLs are treated as untrusted input and restricted to known HTTPS
  hosts.
- No credentials or browser cookies are copied or stored.
- Authorization failures are reported; the add-on does not attempt to bypass
  them.
- Parser and Blender code do not depend on the service remaining available.
