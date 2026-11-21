"""Shared task selection policy, independent of Qt widgets.

Supported means that the GUI has a dedicated editor; possible means that
the backend permits the current structure. These are separate properties.
"""
from __future__ import annotations

from typing import Collection

from ase2sprkkr import InputParameters
from ase2sprkkr.sprkkr.executables import task_system_error

from ase2sprkkr_gui.gui.input_parameters.tasks import guided_task_definitions


# A multi-backend Guided definition can expose one presentation alias.
# BSF is one such family: its existing 'bsf' alias covers BSFEK and BSFKK.
# Derive GUI identities from that definition, not a parallel task registry.
_FAMILY_BACKENDS = {
    definition.aliases[0].upper(): tuple(
        name.upper() for name in definition.backend_tasks
    )
    for definition in guided_task_definitions()
    if len(definition.backend_tasks) > 1 and definition.aliases
}
_NATIVE_FAMILIES = {
    backend: display
    for display, backends in _FAMILY_BACKENDS.items()
    for backend in backends
}


def task_ui_name(name: str) -> str:
    """Canonical GUI identity; the backend task names remain untouched."""
    name = str(name).upper()
    return _NATIVE_FAMILIES.get(name, name)


def native_task_names(name: str) -> tuple[str, ...]:
    """Native variants for a single displayed task, preserving declared order."""
    display = task_ui_name(name)
    return _FAMILY_BACKENDS.get(display, (display,))


def native_task_name(name: str) -> str:
    """Concrete backend identity when creating a new grouped task input."""
    return native_task_names(name)[0]



def supported_task_names() -> tuple[str, ...]:
    """Registered native task names with a GUI-defined editor, alphabetically."""
    available = set(InputParameters.task_registry.names())
    return tuple(sorted({
        task_ui_name(name)
        for definition in guided_task_definitions()
        for name in definition.backend_tasks
        if name.upper() in available
    }))


def default_preferred_task_names() -> tuple[str, ...]:
    """GUI task shortcuts; SCF is always managed by the convergence workflow."""
    return tuple(name for name in supported_task_names() if name != "SCF")


def all_task_names() -> tuple[str, ...]:
    return tuple(sorted({
        task_ui_name(name) for name in InputParameters.task_registry.names()
    }))


def effective_preferred(
    selected: tuple[str, ...] | None,
    supported_at_save: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Follow supported defaults, or retain an explicit ordered preference.

    Newly supported tasks are offered to the user rather than silently added.
    The saved supported set is a baseline for detecting additions, not a
    second configuration of task support.
    """
    if selected is None:
        return default_preferred_task_names()
    available = set(all_task_names())
    result = list(dict.fromkeys(
        task_ui_name(name) for name in selected
        if task_ui_name(name) in available and task_ui_name(name) != "SCF"
    ))
    return tuple(result)


def applicable_task_names(system_kind: str | None) -> tuple[str, ...]:
    """Native applicability only; readiness to run is evaluated elsewhere."""
    if system_kind is None:
        return ()
    registry = InputParameters.task_registry
    available = set(registry.names())
    return tuple(
        name for name in all_task_names()
        if any(
            variant in available
            and task_system_error(registry[variant], system_kind) is None
            for variant in native_task_names(name)
        )
    )


def displayed_tasks(
    system_kind: str | None,
    preferred: tuple[str, ...],
    *,
    maximum_fallback: int = 8,
    eligible: Collection[str] | None = None,
) -> tuple[str, ...]:
    """First nonempty group: preferred, guided, ordinary, experimental.

    Preferred order is user-defined; fallback groups are alphabetical. Too
    many tasks in a fallback group suppress cards, not the Custom task action.
    ``eligible`` enforces workflow readiness before preferred/fallback grouping.
    """
    possible = set(applicable_task_names(system_kind))
    if eligible is not None:
        possible.intersection_update(eligible)
    if not possible:
        return ()
    chosen = tuple(name for name in preferred if name in possible)
    if chosen:
        return chosen
    supported = set(supported_task_names())
    registered = InputParameters.task_registry
    for candidates in (
        sorted(possible & supported),
        sorted(
            name for name in possible
            if not registered[native_task_name(name)].experimental
        ),
        sorted(possible),
    ):
        if candidates:
            return tuple(candidates) if len(candidates) <= maximum_fallback else ()
    return ()
