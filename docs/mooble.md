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

## Catalog indexing and category strategy

The observed root furniture category reports more than 14,000 models. Mooblender
follows its server-provided pagination links in a background worker with a
48-item request size, 2,048-page limit, 100,000-item limit, and pagination-cycle
check. It stores summary metadata only; thumbnails and model PContent are not
part of this full index download.

The complete root index replaces the previous cache atomically only after every
page succeeds. On startup, the old index is displayed immediately. A background
request checks the first live page, including category records and their model
counts. If that prefix differs, the complete index is rebuilt; otherwise the
single check request is sufficient. This is a practical change detector because
the observed service does not return `ETag` or `Last-Modified` validators and
marks responses `no-cache`.

Search never sends the query to the Explorer API. It matches all whitespace-
separated terms, case- and accent-insensitively, against cached name,
description, brand, collection, and ID fields. Empty search restores the full
index. The sidebar materializes only a preference-sized window of results;
**Load More** expands that local window, and only visible cards request
thumbnails.

Category branches remain available for navigation and are requested only when
opened. Category and Back navigation are cache-first after the initial visit.
Those pages are separate from the root search index.

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
hierarchical collection list, back navigation, and server pagination.
The search field is debounced locally while editing; committing it with Enter
or selecting the magnifier therefore always displays only matching cached
objects, including the empty-query reset case.

## Compatibility policy

- Network actions require Blender Online Access.
- API URL and regional values are preferences because deployments may differ.
- Returned URLs are treated as untrusted input and restricted to known HTTPS
  hosts.
- No credentials or browser cookies are copied or stored.
- Authorization failures are reported; the add-on does not attempt to bypass
  them.
- Parser and Blender code do not depend on the service remaining available.
