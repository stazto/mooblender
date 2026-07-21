# Project brief

## Mission

Create Mooblender, an open-source Blender add-on implemented in Python for
working with Promob assets.

## Product goals

- Import `.pmob` files.
- Import `.content` files.
- Import `.mob` files.
- Let users browse or resolve models dynamically from the Mooble platform at
  `https://planner.mooble.com` and download models they are authorized to use.
- Publish accurate, reproducible documentation for every supported file format.

## Core constraints

- Runtime implementation is Python and Blender's Python API.
- The add-on must not depend on .NET, Wine, proprietary executables, or vendor
  libraries.
- Parsing and service logic must be testable outside Blender wherever possible.
- Credentials and authenticated session material must never be committed.
- Remote access must respect user authorization, service terms, rate limits,
  and server errors.
- Unknown or unsupported data must be surfaced clearly; compatibility must not
  be guessed from file extensions alone.

## Acceptance criteria

- The add-on registers and its core scene builder works on Blender 4.5 LTS and
  Blender 5.2 LTS.

An imported asset should preserve all supported information, including:

- object names and hierarchy;
- coordinate system, units, and transforms;
- mesh topology, UVs, normals, and smoothing;
- material assignments and texture references;
- instancing and reusable geometry; and
- animation data when present and understood.

Each supported format must have public documentation, representative
redistributable fixtures, parser tests, malformed-input tests, and a list of
known unknowns. Mooble integration must provide understandable errors for
offline, unauthorized, missing, changed, and rate-limited responses.

## Non-goals unless scope changes

- Reimplementing the Promob application.
- Circumventing authentication, licensing, or access controls.
- Shipping proprietary binaries or non-redistributable catalog content.
- Making Blender APIs a dependency of the low-level file parsers.
