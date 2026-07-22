# Format and service research standard

Public documentation is a deliverable, not a by-product. Every implemented
behavior should be traceable to reproducible evidence.

## File-format records

Create one specification per extension under `docs/formats/`. For each format,
record:

- identification bytes and container type;
- byte order, integer widths, floating-point representation, and text encoding;
- header fields, versions, offsets, alignment, and length rules;
- nested record grammar and type identifiers;
- coordinate system, handedness, axes, units, and matrix convention;
- geometry, UV, normal, smoothing, material, texture, hierarchy, and animation
  semantics;
- compression, checksums, encryption, or obfuscation when present;
- relationships to other files or embedded resources;
- malformed-input behavior and safe implementation limits;
- general traits supported by legally usable samples, without naming private or
  incidental catalog products; and
- unknown fields, unsupported versions, and competing hypotheses.

Mark claims as **confirmed**, **inferred**, or **unknown**. Include byte offsets
or minimal hex examples where useful. A field name alone is not proof of its
meaning.

Document PMob records and the PContent container as separate layers. Share code
only when byte-level evidence demonstrates a common structure.

## Mooble service records

Document only behavior observed from the current web application or public
service documentation. Record:

- request purpose, method, URL shape, and required headers;
- authentication and authorization expectations without recording secrets;
- pagination, localization, filters, identifiers, and response schema;
- model/resource URLs and content types;
- caching headers, retries, rate-limit signals, and error responses; and
- the observation date and the test conditions.

Endpoints are versioned observations, not permanent contracts. Keep discovery,
metadata lookup, and binary download separate in code so one can change without
rewriting the others.

## Verification checklist

Before calling a behavior supported:

1. reproduce it with more than one legally usable sample where possible;
2. add a focused fixture and parser/service test;
3. test truncation, invalid sizes, unknown values, and unsupported versions;
4. compare the intermediate model with expected semantic values;
5. verify the Blender result separately; and
6. update the specification and known-unknown list in the same change.
