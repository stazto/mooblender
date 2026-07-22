# Mooble catalog integration

[Mooble](https://www.mooble.com/br/) is the online environment-planning platform
whose public catalog is used by this integration. Status: observed public
web-service behavior. Endpoints and schemas are not a vendor compatibility
guarantee and can change independently of Mooblender.

## Explorer request

The current integration uses an Explorer v2 GET request below
`https://catalog.mooble.com/api/explorer/v2` with parameters including:

- `client=mooble`;
- `internal=Item`;
- `pin=Departamento`;
- `!Departamento=<department-id>`;
- `region=<country-code>`;
- optional `partnership` and `search`; and
- `$top=<page-size>`.

Supported country codes are `br`, `us`, `ca`, `es`, `ar`, `cn`, and `fr`.
Region controls model availability and server localization. Department IDs are
treated as opaque service identifiers and are not translated.

The configured departments cover Furniture, Decor, Openings, Appliances,
Fireplaces / Grills, Layout, Lights, Materials, and Plants.

## Explorer response

Initial responses expose:

- `Output.Pin.AvailableTags.Data` for the category tree;
- `Output.Specifications.Data` for product summaries; and
- `Output.Specifications.Links.Next` for continuation.

Observed continuation responses can place `Data`, `Links`, and `HasMore` at the
response root. Both shapes normalize into the same `CatalogPage` model.

Category records provide stable IDs, display names, navigation URLs, hierarchy
levels, selection state, and reported item counts. Product summaries can provide
ID, name, description, brand, collection, thumbnail, detail URL, type, and
external millimetre dimensions under `Properties.Dimension`.

The card information link uses the synchronized country and item ID. Public
routes are localized: `produto` for Brazil, `producto` for Spain and Argentina,
and `product` for the other supported countries.

## Complete catalog synchronization

**Sync Catalog** is the only catalog-wide network operation. It:

1. resolves each selected department root;
2. follows its category hierarchy and continuation pages;
3. normalizes product summaries and category memberships;
4. writes a temporary SQLite database;
5. validates safety limits and advertised category counts; and
6. atomically replaces the previous snapshot.

Independent categories use a bounded worker pool. Continuation pages within one
category remain sequential because each response supplies the next URL. Only the
synchronization coordinator writes SQLite, so parallel HTTP completion cannot
mutate the database concurrently.

Cancellation is cooperative at bounded request boundaries. A cancellation,
schema error, incomplete category, or worker failure removes the temporary file
and leaves the prior snapshot untouched.

The snapshot records source country, category-label language, enabled
departments, source URLs, schema version, and synchronization time. A snapshot
whose country or language differs from current preferences is not opened until
the user synchronizes again.

## Offline-first browser

Startup, category navigation, Back, search, manufacturer filtering, brand
collection filtering, and Load More read only the SQLite snapshot. They never
fall back to Explorer requests.

Search splits whitespace-separated terms and matches them case- and
accent-insensitively against name, description, brand, collection, and ID. An
empty query restores the current category. Manufacturer and collection filters
combine with every text term.

The panel materializes a preference-sized result window. **Load More** expands
that local window. Opening a previously unseen category is still a database read
because synchronization stores the complete selected hierarchy.

## On-demand downloads

Catalog synchronization does not download every preview or model:

- only visible cards request missing thumbnails;
- preview failures do not block model import;
- **Import** resolves the selected detail record and downloads its PContent only
  when not cached; and
- aggregate child specifications reuse downloads by specification ID.

Detail requests retain the snapshot region. Returned URLs are validated against
trusted HTTPS hosts and bounded response sizes before use. Package resolution
runs in a worker; Blender datablock creation begins later on the main thread.

## Cache behavior

The Blender-managed cache contains:

- `catalog.sqlite3` for the atomic searchable snapshot;
- `models/` for downloaded packages and safe metadata sidecars; and
- `thumbnails/` for on-demand previews.

Models and previews use separate size targets. Cache hits refresh recency, and
completed writes prune the oldest inactive files in their own allow-listed
group. Active paths cannot be pruned or cleared. **Clear Downloads** removes
models and thumbnails after confirmation but retains `catalog.sqlite3`.

## Resilience and privacy

- Network actions honor Blender Online Access.
- Responses to HTTP 429 and 503 can retry at most twice with bounded
  `Retry-After` handling.
- Catalog publication and file downloads use same-directory temporary files and
  atomic replacement.
- No credentials, session cookies, or authenticated browser state are stored.
- Authorization failures are reported rather than bypassed.
- Parser and Blender code remain usable for local files when the service is
  unavailable.

## Compatibility boundary

Explorer and detail fields are normalized before reaching Blender code. Service
discovery, catalog persistence, binary downloads, PContent parsing, and scene
construction remain separate layers so a web-service change does not require a
format-parser rewrite.
