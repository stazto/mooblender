"""Resolve aggregate references in properties-only PContent entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .pcontent import PContentPackage, ResolvedAggregate


class AggregateResolutionError(ValueError):
    """Raised when aggregate references are invalid or exceed safety limits."""


@dataclass(slots=True)
class _ResolutionContext:
    loader: Callable[[str], PContentPackage]
    max_depth: int
    max_entities: int
    memo: dict[str, PContentPackage] = field(default_factory=dict)
    loaded_count: int = 0

    def _load(self, entity_id: str, *, aggregate: bool) -> PContentPackage:
        cached = self.memo.get(entity_id)
        if cached is not None:
            return cached
        self.loaded_count += 1
        if self.loaded_count > self.max_entities:
            raise AggregateResolutionError(
                "PContent aggregate/material count exceeds safety limit"
            )
        loaded = self.loader(entity_id)
        if not isinstance(loaded, PContentPackage):
            kind = "aggregate" if aggregate else "material"
            raise AggregateResolutionError(
                f"{kind} {entity_id} did not resolve to PContent"
            )
        self.memo[entity_id] = loaded
        return loaded

    def _resolve_materials(self, package: PContentPackage) -> None:
        package.resolved_materials.clear()
        models = package.properties.get("Models", [])
        if not isinstance(models, list):
            return
        for model in models:
            components = model.get("Components", []) if isinstance(model, dict) else []
            if not isinstance(components, list):
                continue
            for component in components:
                material_id = (
                    component.get("MaterialId") if isinstance(component, dict) else None
                )
                if isinstance(material_id, str) and material_id:
                    package.resolved_materials[material_id] = self._load(
                        material_id, aggregate=False
                    )

    @staticmethod
    def _specification_id(raw: object) -> str:
        if not isinstance(raw, dict):
            return ""
        specifications = raw.get("Specifications")
        if not isinstance(specifications, list):
            return ""
        return next(
            (value for value in specifications if isinstance(value, str) and value),
            "",
        )

    def visit(
        self,
        package: PContentPackage,
        depth: int,
        ancestors: frozenset[str],
    ) -> None:
        if depth > self.max_depth:
            raise AggregateResolutionError("PContent aggregate depth exceeds safety limit")
        self._resolve_materials(package)
        raw_aggregates = package.properties.get("Aggregates", [])
        if not isinstance(raw_aggregates, list):
            return
        package.resolved_aggregates.clear()
        for index, raw in enumerate(raw_aggregates):
            specification_id = self._specification_id(raw)
            if not specification_id:
                continue
            if specification_id in ancestors:
                raise AggregateResolutionError(
                    f"cyclic PContent aggregate reference: {specification_id}"
                )
            cached = specification_id in self.memo
            child = self._load(specification_id, aggregate=True)
            # A cached package has already had its own tree resolved. Re-visiting
            # it would duplicate remote work and could erase shared results.
            if not cached:
                self.visit(child, depth + 1, ancestors | {specification_id})
            package.resolved_aggregates.append(
                ResolvedAggregate(index, specification_id, child)
            )


def resolve_aggregates(
    package: PContentPackage,
    loader: Callable[[str], PContentPackage],
    *,
    max_depth: int = 12,
    max_entities: int = 256,
) -> PContentPackage:
    """Resolve the first specification and referenced materials recursively."""
    context = _ResolutionContext(loader, max_depth, max_entities)
    context.visit(package, 0, frozenset())
    return package
