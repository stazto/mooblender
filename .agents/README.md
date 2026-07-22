# Mooblender agent guide

This directory contains contributor context for the public `mooblender`
project at `https://github.com/dantedex/mooblender`.

- `PROJECT.md` defines the product scope and acceptance criteria.
- `ARCHITECTURE.md` defines the intended Python package boundaries.
- `IMPLEMENTATION_PLAN.md` tracks the phased implementation and validation plan.
- `VALIDATION.md` records reproducible evidence behind completed regressions.
- `FORMAT_RESEARCH.md` defines how file-format and service behavior are
  documented.

Keep this guidance current as implementation decisions are made. Statements
about unverified formats or service behavior must be labeled as hypotheses,
not facts.

The rendered `docs/` site is exclusively public user and developer
documentation. Keep agent workflow, product-specific investigation evidence,
roadmap state, and private implementation context here in `.agents/`. When a
trait becomes public, rewrite it as a general behavior or format contract rather
than copying model-specific research notes into the manual.
