"""Resolve aggregate references in properties-only PContent entities."""

from __future__ import annotations

from collections.abc import Callable

from .pcontent import PContentPackage, ResolvedAggregate


class AggregateResolutionError(ValueError):
    pass


def resolve_aggregates(
    package: PContentPackage,
    loader: Callable[[str], PContentPackage],
    *,
    max_depth: int = 12,
    max_entities: int = 256,
) -> PContentPackage:
    """Resolve the first/default specification of every aggregate recursively."""

    memo: dict[str, PContentPackage] = {}
    loaded_count = 0

    def visit(current: PContentPackage, depth: int, ancestors: frozenset[str]) -> None:
        nonlocal loaded_count
        if depth > max_depth:
            raise AggregateResolutionError("PContent aggregate depth exceeds safety limit")
        current.resolved_materials.clear()
        models = current.properties.get("Models", [])
        if isinstance(models, list):
            for model in models:
                if not isinstance(model, dict):
                    continue
                components = model.get("Components", [])
                if not isinstance(components, list):
                    continue
                for component in components:
                    if not isinstance(component, dict):
                        continue
                    material_id = component.get("MaterialId")
                    if not isinstance(material_id, str) or not material_id:
                        continue
                    material_package = memo.get(material_id)
                    if material_package is None:
                        loaded_count += 1
                        if loaded_count > max_entities:
                            raise AggregateResolutionError(
                                "PContent aggregate/material count exceeds safety limit"
                            )
                        material_package = loader(material_id)
                        memo[material_id] = material_package
                    current.resolved_materials[material_id] = material_package

        raw_aggregates = current.properties.get("Aggregates", [])
        if not isinstance(raw_aggregates, list):
            return
        current.resolved_aggregates.clear()
        for index, raw in enumerate(raw_aggregates):
            if not isinstance(raw, dict):
                continue
            specifications = raw.get("Specifications")
            if not isinstance(specifications, list):
                continue
            specification_id = next(
                (value for value in specifications if isinstance(value, str) and value),
                "",
            )
            if not specification_id:
                continue
            if specification_id in ancestors:
                raise AggregateResolutionError(
                    f"cyclic PContent aggregate reference: {specification_id}"
                )
            child = memo.get(specification_id)
            if child is None:
                loaded_count += 1
                if loaded_count > max_entities:
                    raise AggregateResolutionError(
                        "PContent aggregate count exceeds safety limit"
                    )
                child = loader(specification_id)
                if not isinstance(child, PContentPackage):
                    raise AggregateResolutionError(
                        f"aggregate {specification_id} did not resolve to PContent"
                    )
                memo[specification_id] = child
                visit(child, depth + 1, ancestors | {specification_id})
            current.resolved_aggregates.append(
                ResolvedAggregate(
                    index=index,
                    specification_id=specification_id,
                    package=child,
                )
            )

    visit(package, 0, frozenset())
    return package
