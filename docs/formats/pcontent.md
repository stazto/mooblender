# PContent format notes

Status: implemented baseline from public Mooble samples observed on 2026-07-21.

## Confirmed container

`.pcontent` is a ZIP archive. An observed model package contained one `.pmob`
member and `properties.json`.

Despite its name, the observed `properties.json` member was not plain JSON at
byte zero. It used the .NET BinaryWriter string representation: a 7-bit encoded
UTF-8 byte length followed by that many bytes of JSON. The reader also accepts
plain UTF-8 JSON so independently produced packages remain straightforward.

The properties object can describe dimensions, limits, type, models/components,
open services, aggregates, lighting, and other product behavior. These fields
are preserved as JSON but are not all mapped into Blender yet.

## Safety policy

The reader operates in memory and does not extract members. It rejects absolute
or parent-traversal paths, excessive member counts/unpacked sizes, suspicious
compression ratios, missing PMob data, and ambiguous multiple PMob members.

## Not established

`.content` is not treated as an alias for `.pcontent`. Its identity remains
unknown pending independent samples.
