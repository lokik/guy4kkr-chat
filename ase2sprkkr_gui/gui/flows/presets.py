"""Shared preset actions for Guided and Expert input editors."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from PyQt6.QtWidgets import QInputDialog, QMenu, QMessageBox, QWidget

from ase2sprkkr.input_parameters.presets import PresetStore
from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession


def available_presets(
    session: InputParametersSession,
    *,
    compatible_tasks: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """List IPD-wide and task-scoped presets appropriate to this editor."""
    schema = session.working_parameters.definition_name
    names = PresetStore().list(f"input_parameters:{schema}")
    if compatible_tasks is None:
        return names
    allowed = {str(task).upper() for task in compatible_tasks}
    return tuple(
        name for name in names
        if not name.startswith("task:")
        or name.split(":", 1)[1].split(".", 1)[0].upper() in allowed
    )


def preset_labels(identifiers: Iterable[str]) -> dict[str, str]:
    """Use short names when all presets share a scope; qualify differences."""
    parts = {}
    for identifier in identifiers:
        scope, qualified = identifier.split(":", 1)
        owner, name = qualified.split(".", 1)
        parts[identifier] = (scope, owner, name)

    scopes = {scope for scope, _, _ in parts.values()}
    owners = {owner for _, owner, _ in parts.values()}
    distinguish_scopes = len(scopes) > 1
    distinguish_owners = len(owners) > 1

    labels = {}
    for identifier, (scope, owner, name) in parts.items():
        qualifiers = []
        if distinguish_owners:
            qualifiers.append(owner.upper())
        if distinguish_scopes:
            qualifiers.append("task" if scope == "task" else "input parameters")
        labels[identifier] = (
            f"{name} ({' '.join(qualifiers)})" if qualifiers else name
        )
    return labels


def populate_preset_menus(
    replace_menu: QMenu,
    merge_menu: QMenu,
    session: InputParametersSession,
    parent: QWidget | None,
    *,
    on_select: Callable[[str, bool], None],
    compatible_tasks: Iterable[str] | None = None,
) -> None:
    """Populate both menus from one snapshot, disabling inapplicable actions."""
    try:
        names = available_presets(session, compatible_tasks=compatible_tasks)
    except Exception as exc:
        QMessageBox.critical(parent, "Load presets failed", str(exc))
        names = ()

    labels = preset_labels(names)
    current_task = session.working_parameters.task_name
    for clear_first, menu in ((True, replace_menu), (False, merge_menu)):
        menu.clear()
        menu.setToolTipsVisible(True)
        for name in names:
            action = menu.addAction(labels[name])
            action.setData(name)
            if not clear_first and name.startswith("task:"):
                owner = name.split(":", 1)[1].split(".", 1)[0]
                if current_task is not None and owner.upper() != current_task.upper():
                    action.setEnabled(False)
                    action.setToolTip(
                        f"Cannot merge {owner.upper()} settings into "
                        f"{current_task}; use Replace by preset instead."
                    )
                    continue
            action.triggered.connect(
                lambda _checked=False, selected=name, replace=clear_first:
                on_select(selected, replace)
            )
        enabled = any(action.isEnabled() for action in menu.actions())
        menu.setEnabled(enabled)
        menu.menuAction().setEnabled(enabled)


def load_preset(
    session: InputParametersSession,
    parent: QWidget | None,
    *,
    name: str,
    clear_first: bool = True,
    compatible_tasks: Iterable[str] | None = None,
) -> bool:
    """Apply the explicitly selected preset as one undoable action."""
    store = PresetStore()
    allowed = (
        None if compatible_tasks is None
        else {str(task).upper() for task in compatible_tasks}
    )

    def apply(candidate):
        candidate.load_preset(
            name, clear_first=clear_first, store=store,
            required_task=(next(iter(allowed)) if allowed and len(allowed) == 1 else None),
        )
        if allowed is not None and candidate.task_name not in allowed:
            raise ValueError(
                f"Preset selects {candidate.task_name}, expected "
                + "/".join(sorted(allowed))
            )

    try:
        if clear_first:
            candidate = session.result()
            apply(candidate)
            session.replace_parameters(
                candidate, text=f"Replace with preset {name}", source_page="preset",
                preserve_explicit=True,
            )
        else:
            session.mutate(
                apply, text=f"Merge preset {name}", source_page="preset",
                preserve_explicit=True,
            )
    except Exception as exc:
        QMessageBox.critical(parent, "Load preset failed", str(exc))
        return False
    return True


def save_preset(session: InputParametersSession, parent: QWidget | None) -> bool:
    """Save explicit values, choosing task scope automatically where needed.

    Qualified names let users force a particular scope, including in shared
    JXC/DMI schemas where 'jxc' is both an IPD name and a task name.
    """
    store = PresetStore()
    schema = session.working_parameters.definition_name
    task = session.working_parameters.task_name
    name, ok = QInputDialog.getText(
        parent, "Save as preset",
        f"Preset name (or input_parameters:{schema}.name"
        + (f" / task:{task.lower()}.name" if task else "")
        + "):",
    )
    if not ok or not name.strip():
        return False
    name = name.strip()
    try:
        session.result().save_preset(name, store=store)
    except FileExistsError:
        reply = QMessageBox.question(
            parent, "Replace preset?",
            f"A preset named {name!r} already exists in the selected scope. Replace it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        try:
            session.result().save_preset(name, overwrite=True, store=store)
        except Exception as exc:
            QMessageBox.critical(parent, "Save preset failed", str(exc))
            return False
    except Exception as exc:
        QMessageBox.critical(parent, "Save preset failed", str(exc))
        return False
    return True
