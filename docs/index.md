# Mooblender documentation

Mooblender is an open-source Blender extension that imports supported Promob
files and provides an offline-first browser for the Mooble model catalog. It
turns each imported asset into one clean scene object driven by Geometry Nodes,
with supported finishes, movable parts, options, and editable dimensions exposed
as modifier controls.

Use this manual to install the extension, synchronize a catalog, import files,
configure caches, understand supported behavior, or contribute to development.

```{toctree}
:maxdepth: 2
:caption: Get started

about
installation
user-guide
troubleshooting
```

```{toctree}
:maxdepth: 2
:caption: Developer documentation

development
mooble
formats/index
```

## At a glance

- **Supported Blender versions:** 4.5 LTS and 5.2 LTS.
- **Local import:** `.pmob` and `.pcontent`.
- **Catalog workflow:** explicit synchronization followed by local browsing and
  search.
- **Scene result:** one linked controller object; source geometry remains
  unlinked and is consumed by Geometry Nodes.
- **Runtime:** Python only; no Promob or .NET runtime is required.

```{important}
Mooblender does not grant licenses to catalog assets. Use only files and models
that you are authorized to access.
```
