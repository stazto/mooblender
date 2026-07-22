"""Interpret PContent customization metadata without depending on Blender."""

from __future__ import annotations

from collections.abc import Mapping


def _reference_model_ids(references: object) -> tuple[str, ...]:
    if isinstance(references, Mapping):
        candidates = references.values()
    elif isinstance(references, list):
        candidates = references
    else:
        return ()
    result: list[str] = []
    for reference in candidates:
        if not isinstance(reference, Mapping):
            continue
        model_ids = reference.get("ModelsId", ())
        if isinstance(model_ids, list):
            result.extend(value for value in model_ids if isinstance(value, str))
    return tuple(result)


def selected_model_information(
    properties: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    """Return model-information fields selected by the package reference.

    Promob visibility expressions address these values with tokens such as
    ``@Coz_bal(TIPO)@``. A reference's ``ModelsId`` list is authoritative;
    groups absent from that list fall back to their first declared model.
    """
    models = properties.get("Models", ())
    if not isinstance(models, list):
        return {}
    declared = [model for model in models if isinstance(model, Mapping)]
    selected_ids = {
        value.casefold() for value in _reference_model_ids(properties.get("References"))
    }
    selected: dict[str, dict[str, object]] = {}

    # Populate explicitly selected models first, then supply a deterministic
    # first-option fallback for model groups not recorded by the reference.
    for explicit_only in (True, False):
        for model in declared:
            model_id = str(model.get("Id") or "").casefold()
            if explicit_only != (model_id in selected_ids):
                continue
            definition_id = str(model.get("ModelDefinitionId") or "").casefold()
            information = model.get("Informations", {})
            if definition_id and isinstance(information, Mapping):
                selected.setdefault(
                    definition_id,
                    {str(key).casefold(): value for key, value in information.items()},
                )
    return selected


def is_optional_aggregate(aggregate: Mapping[str, object]) -> bool:
    """Return whether Promob marks an aggregate as independently selectable."""
    return (
        aggregate.get("Concurrent") is True
        and aggregate.get("Constant") is not True
        and aggregate.get("AlwaysVisible") is not True
    )
