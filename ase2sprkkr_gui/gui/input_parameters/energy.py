"""Energy units and absolute/relative InputParameters mappings."""
from __future__ import annotations

from dataclasses import dataclass

from ase2sprkkr.common.grammar_types import Energy
from ase2sprkkr.input_parameters.definitions._sections import relative_energy_supported


def convert_energy(value, source, target):
    return float((value * Energy.units[source]).to_value(Energy.units[target]))


@dataclass(frozen=True)
class EnergyState:
    """A displayed energy and unit; relative means referenced to Fermi energy."""
    value: float | None
    unit: str
    relative: bool = False
    explicit: bool = True


def bound_energy_state(parameters, name):
    """Read a bound, preferring an explicit relative *EV value over absolute Ry."""
    section = parameters.ENERGY
    relative = section[name + 'EV']()
    if relative is not None:
        return EnergyState(float(relative), 'eV', True, section[name + 'EV'].is_set())
    absolute = section[name]()
    return EnergyState(None if absolute is None else float(absolute), 'Ry', False, section[name].is_set())


def bound_energy_updates(name, value, unit, relative):
    """Build updates selecting one representation and clearing its counterpart.

    The caller must apply the returned mapping atomically. Values are converted
    to the backend's eV (relative) or Ry (absolute), without changing reference.
    """
    absolute_name, relative_name = name, name + 'EV'
    target = relative_name if relative else absolute_name
    return {absolute_name: None, relative_name: None,
            target: None if value is None else convert_energy(value, unit, 'eV' if relative else 'Ry')}


def reference_selectable(parameters, name):
    """Allow supported ranges and permit repairing an imported unsupported reference."""
    return relative_energy_supported(parameters.ENERGY) or bound_energy_state(parameters, name).relative


def set_bound_energy(parameters, name, value, unit, relative):
    """Apply a bound and keep the range on one reference in a single transaction.

    Changing reference reinterprets both bounds without inventing a Fermi
    energy. Clearing a relative range restores the task's default bounds.
    """
    energy = parameters.ENERGY
    if relative and value is not None and not relative_energy_supported(energy):
        raise ValueError('This task supports absolute energy only; a relative range requires both bounds.')
    updates = bound_energy_updates(name, value, unit, relative)
    other = 'EMAX' if name == 'EMIN' else 'EMIN'
    if other in energy and other + 'EV' in energy:
        state = bound_energy_state(parameters, other)
        if value is None and relative:
            updates.update(bound_energy_updates(other, None, unit, relative))
        elif value is not None and state.relative != relative:
            updates.update(bound_energy_updates(other, state.value, state.unit, relative))
    energy.set(updates)
