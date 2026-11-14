"""Qt-independent declarations of specialized expert-tree fields."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ase2sprkkr_gui.gui.input_parameters.bindings import (
    InputParameterPath,
    resolve_option,
)
from ase2sprkkr_gui.gui.input_parameters.specs.schema import FieldPlacement


@dataclass(frozen=True)
class ExpertFieldSpec:
    """Select a registered editor and its expert-tree presentation."""

    editor: str
    small_editor: str | None = None
    label: str | None = None
    related_paths: tuple[InputParameterPath, ...] = ()
    type_label: str | None = None
    minimum: float | int | None = None
    minimum_width: int | None = None

    def placement(
        self,
        path: InputParameterPath,
        default_label: str,
        *,
        editor: str | None = None,
    ) -> FieldPlacement:
        """Create the ordinary editor placement consumed by the registry."""
        return FieldPlacement(
            path,
            self.label or default_label,
            editor=editor or self.editor,
            minimum=self.minimum,
            related_paths=self.related_paths,
        )


EXPERT_FIELDS: Mapping[InputParameterPath, ExpertFieldSpec] = MappingProxyType({
    ('ENERGY', 'EMIN'): ExpertFieldSpec(
        editor='energy_bound',
        label='EMIN / EMINEV',
        related_paths=(('ENERGY', 'EMINEV'),),
        type_label='Energy',
        minimum=-1e9,
        minimum_width=320,
    ),
    ('ENERGY', 'EMAX'): ExpertFieldSpec(
        editor='energy_bound',
        label='EMAX / EMAXEV',
        related_paths=(('ENERGY', 'EMAXEV'),),
        type_label='Energy',
        minimum=-1e9,
        minimum_width=320,
    ),
    ('MODE', 'C'): ExpertFieldSpec(
        editor='scaling',
        small_editor='auto',
        minimum_width=280,
    ),
    ('MODE', 'SOC'): ExpertFieldSpec(
        editor='scaling',
        small_editor='auto',
        minimum_width=280,
    ),
})


def applicable_expert_fields(
    parameters: Any,
) -> dict[InputParameterPath, ExpertFieldSpec]:
    """Return declarations whose primary and related options all exist."""
    result = {}
    for path, spec in EXPERT_FIELDS.items():
        try:
            for candidate in (path, *spec.related_paths):
                resolve_option(parameters, candidate)
        except (AttributeError, KeyError):
            continue
        result[path] = spec
    return result
