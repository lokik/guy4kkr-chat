"""Binding adapters for reusable parameter controls."""
from __future__ import annotations

from ase2sprkkr.common.grammar_types import Energy

from ase2sprkkr_gui.gui.input_parameters.energy import (
    EnergyState,
    bound_energy_state,
    convert_energy,
    reference_selectable,
    set_bound_energy,
)
from ase2sprkkr_gui.gui.widgets.input_parameters.energy import EnergyEditor
from ase2sprkkr_gui.gui.widgets.input_parameters.relativistic_scaling import (
    RelativisticScalingEditor,
)


class EnergyParameterEditor(EnergyEditor):
    """Adapt one explicitly energy-presented field to the generic widget."""

    def __init__(self, binding, placement, atoms=None, parent=None):
        del atoms

        def state():
            field = binding.read()
            source = field.value
            if isinstance(source, (list, tuple)) and len(source) == 2:
                value, unit = source
            else:
                value, unit = source, "Ry"
            if hasattr(value, "to_value"):
                value, unit = value.to_value("Ry"), "Ry"
            return EnergyState(
                None if value is None else float(value),
                str(unit),
                explicit=field.explicit is not False,
            )

        def apply(value, unit, _relative):
            if value is None:
                converted = None
            elif isinstance(binding.value_type, Energy):
                converted = (value, unit)
            else:
                converted = convert_energy(value, unit, "Ry")
            binding.set_value(converted)

        super().__init__(
            state,
            apply,
            parent,
            with_reference=False,
            minimum=placement.minimum if placement.minimum is not None else -1e9,
        )


class BoundEnergyParameterEditor(EnergyEditor):
    """Bind the shared absolute/relative energy widget to paired options."""

    def __init__(self, binding, placement, atoms=None, parent=None):
        del atoms
        self.binding = binding
        self.placement = placement
        name = placement.path[-1]

        def apply(value, unit, relative):
            binding.mutate(
                lambda parameters: set_bound_energy(parameters, name, value, unit, relative),
                path=placement.path,
                text=f"Change {placement.label.rstrip(':')}",
            )

        super().__init__(
            lambda: bound_energy_state(binding.parameters, name),
            apply,
            parent,
            reference_selectable=lambda: reference_selectable(
                binding.parameters, name
            ),
        )

class RelativisticScalingParameterEditor(RelativisticScalingEditor):
    """Adapt the shared per-type scaling table to a guided field placement."""

    # The number of orbital columns follows SITES.NL as well as the edited path.
    dependencies = (("SITES", "NL"),)

    def __init__(self, binding, placement, atoms=None, parent=None):
        self.placement = placement
        super().__init__(binding, placement, atoms=atoms, parent=parent)

    def focus_for_history(self, _path, index) -> None:
        if self.table.rowCount():
            self.table.setCurrentCell(min(index or 0, self.table.rowCount() - 1), 0)
        super().focus_for_history(_path, index)
