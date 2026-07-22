# About Mooblender

## What it does

Mooblender brings supported [Promob](https://promob.com/) content into Blender.
It combines a local file importer with a searchable
[Mooble](https://www.mooble.com/br/) catalog browser, persistent downloads, and
Geometry Nodes controls that keep configurable model behavior accessible after
import.

The extension is designed for artists, interior designers, visualization teams,
and technical users who need Promob-originated assets in a standard Blender
workflow without installing proprietary runtime libraries inside Blender.

## Extension-directory description

The following text is intentionally plain and copy-ready for an extension
directory or software catalog listing:

> Browse the Mooble catalog and import supported Promob models directly into
> Blender. Mooblender caches catalog data for fast local search, downloads
> previews and models only when needed, and creates one clean Geometry
> Nodes-controlled object with supported materials, options, doors, drawers,
> and editable dimensions. The extension is open source, written entirely in
> Python, and supports Blender 4.5 LTS and 5.2 LTS. It is an independent
> community project and is not affiliated with Mooble, Promob, or Cyncly.

Short summary:

> Browse Mooble and import supported Promob models as clean, configurable
> Geometry Nodes objects in Blender.

Mooblender is a **Blender extension**, not a GNOME Shell extension. The text
above follows the concise style used by extension marketplaces, but listings
must identify Blender as the host application.

## Design principles

- Catalog synchronization happens only when the user requests it.
- Browsing, navigation, filters, and search use the completed local snapshot.
- Thumbnails and model packages download on demand and are reused from cache.
- Imports add one visible scene object rather than a hierarchy of helper empties.
- Unsupported or unknown format behavior is reported instead of guessed.
- Network requests use HTTPS allow-lists, bounded responses, and no stored
  credentials.

## Current limits

Local import is limited to the documented PMob and PContent traits. Catalog
endpoints are observed web-service behavior rather than a vendor guarantee and
may require maintenance when Mooble changes.

## License and trademarks

Original Mooblender source is licensed under GPL-3.0-or-later. Mooble, Promob,
2020 Spaces, Cyncly, their trademarks, and catalog assets belong to their
respective owners. Mooblender is independent and is not affiliated with,
endorsed by, sponsored by, authorized by, or maintained by those companies.
Users remain responsible for asset licenses, service terms, and authorization.

See [Mooble, Promob, and credits](credits.md) for official links, corporate
context, and the complete independence notice.
