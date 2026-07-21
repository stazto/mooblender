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

## Category loading strategy

Category pages are loaded lazily. The observed root furniture category reports
more than 14,000 models and exposes its immediate children, while selecting a
child makes another Explorer request that can expose an additional category
level. Recursively fetching the entire tree on startup would therefore add many
requests to the catalog API without improving the first visible result.

Mooblender parses the complete category metadata returned by each requested
page, creates its cards immediately, and then fetches the card thumbnails as a
separate background batch. Category branches are requested only when opened.

Requested catalog pages are cached on disk. On add-on startup, the initial page
is restored from that cache before a background revalidation request. The
observed service does not return `ETag` or `Last-Modified` validators and marks
responses `no-cache`, so Mooblender compares a fingerprint of the parsed live
page with the displayed cached page. Existing cards and previews are replaced
only when that fingerprint changes.

Fetching a specification detail URL can add `Links.Content`. Publicly visible
shape records observed during development linked to HTTPS CDN `.pcontent`
resources. The add-on downloads only after the user selects **Import**, validates
the HTTPS host and size, caches the response, and passes it through the same
PContent reader used for local files.

## Browser interaction

The sidebar borrows the compact workflow of the open-source
[IKEA Browser](https://github.com/shish/blender-ikea-browser/): search, thumbnail
cards, metadata, cache, and one-click import. Mooble additionally requires a
hierarchical collection list, back navigation, and server pagination.

## Compatibility policy

- Network actions require Blender Online Access.
- API URL and regional values are preferences because deployments may differ.
- Returned URLs are treated as untrusted input and restricted to known HTTPS
  hosts.
- No credentials or browser cookies are copied or stored.
- Authorization failures are reported; the add-on does not attempt to bypass
  them.
- Parser and Blender code do not depend on the service remaining available.
