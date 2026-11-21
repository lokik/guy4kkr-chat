"""Task chooser for custom SPR-KKR input and calculation workflows."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ase2sprkkr import InputParameters
from ase2sprkkr.sprkkr.executables import task_system_error
from ase2sprkkr.sprkkr.sprkkr_atoms import system_kind_for_atoms
from ase2sprkkr_gui.gui.input_parameters.task_preferences import (
    supported_task_names, effective_preferred, task_ui_name, native_task_names,
)
from ase2sprkkr_gui.gui.misc.icons import task_icon
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QAbstractItemView,
)


@dataclass(frozen=True)
class TaskChoice:
    name: str
    experimental: bool
    applicable: str
    info: str
    reason: str = ""
    details: str = ""
    preferred: bool = False
    supported: bool = False


def applicability(task: Any, system_kind: str | None) -> tuple[str, str]:
    """Present the backend's geometry support in the chooser."""
    if system_kind is None:
        return "Unknown", "No structure is loaded."
    error = task_system_error(task, system_kind)
    return ("No", error) if error else ("Yes", "The task supports this structure.")


def task_choices(
    atoms: Any = None, *, preferred: tuple[str, ...] | None = None,
) -> tuple[TaskChoice, ...]:
    """Discover registered native tasks, including experimental tasks."""
    kind = system_kind_for_atoms(atoms)
    supported = set(supported_task_names())
    preferred_names = set(effective_preferred(None) if preferred is None else preferred)
    rows = []
    seen = set()
    registry = InputParameters.task_registry
    registered = set(registry.names())
    for name in sorted(registered):
        display_name = task_ui_name(name)
        if display_name in seen:
            continue
        seen.add(display_name)
        variants = tuple(
            registry[variant] for variant in native_task_names(display_name)
            if variant in registered
        )
        task = variants[0]
        outcomes = tuple(applicability(variant, kind) for variant in variants)
        status, reason = next(
            (item for item in outcomes if item[0] == "Yes"), outcomes[0]
        )
        try:
            definition = InputParameters.input_parameters_registry.definition_for_task(task)
            # Backend info is the short summary; description is detailed help.
            info = getattr(definition, "info", None)
            details = getattr(definition, "description", None)
            if callable(info):
                info = info()
            if callable(details):
                details = details()
            if not isinstance(info, str):
                info = ""
            if not isinstance(details, str):
                details = ""
        except (AttributeError, KeyError, ValueError):
            info, details = "", ""
        if not info.strip() and details.strip():
            # Only a short lead sentence when no dedicated summary exists.
            info = " ".join(details.split()).split(". ", 1)[0].rstrip(".") + "."
        rows.append(TaskChoice(
            display_name, all(variant.experimental for variant in variants), status,
            " ".join(info.split()) or f"SPR-KKR {task.executable} calculation",
            reason, details.strip(),
            display_name in preferred_names,
            display_name in supported,
        ))
    return tuple(rows)


def order_choices(
    rows: tuple[TaskChoice, ...] | list[TaskChoice],
    *,
    primary: str | None = None,
    descending: bool = False,
    has_structure: bool = True,
) -> list[TaskChoice]:
    """Stable multi-column sort: possible, preferred, supported, nonexperimental, name."""
    default = (
        ("applicable", "preferred", "supported", "experimental", "name")
        if has_structure else
        ("preferred", "supported", "experimental", "name")
    )
    keys = ((primary,) + tuple(key for key in default if key != primary)
            if primary in (*default, "info") else default)

    def value(row: TaskChoice, key: str):
        if key == "applicable":
            return {"Yes": 0, "No": 1, "Unknown": 2}.get(row.applicable, 3)
        if key in ("preferred", "supported"):
            return 0 if getattr(row, key) else 1
        if key == "experimental":
            # Reverse numeric order: secondary sorting and the first
            # Experimental click both put non-experimental tasks first.
            return 0 if row.experimental else 1
        return getattr(row, key).casefold()

    ordered = list(rows)
    for key in reversed(keys[1:]):
        ordered.sort(
            key=lambda row, k=key: value(row, k),
            reverse=key == "experimental",
        )
    reverse_first = descending if primary in keys else keys[0] == "experimental"
    ordered.sort(key=lambda row: value(row, keys[0]), reverse=reverse_first)
    return ordered


class TaskChooserDialog(QDialog):
    """Filterable, sortable task picker; unsupported tasks remain selectable."""

    def __init__(
        self, atoms: Any = None, parent: QWidget | None = None, *, settings=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Choose SPR-KKR task")
        self.resize(880, 560)
        self._has_structure = atoms is not None
        if settings is None:
            settings = getattr(parent, "settings", None)
        preferred = settings.effective_preferred_tasks() if settings is not None else None
        self._records = (
            task_choices(atoms) if preferred is None
            else task_choices(atoms, preferred=preferred)
        )
        self._primary: str | None = None
        self._descending = False
        self.selected_task: str | None = None

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Choose a task. Unsupported tasks can still be edited "
            "and saved; calculation availability is checked separately.", self
        ))
        toolbar = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Filter by name or description…")
        toolbar.addWidget(self.search, 1)
        self.experimental_filter = QComboBox(self)
        self.experimental_filter.addItems(("All tasks", "Experimental", "Non-experimental"))
        toolbar.addWidget(self.experimental_filter)
        self.applicability_filter = None
        if self._has_structure:
            self.applicability_filter = QComboBox(self)
            self.applicability_filter.addItems(("Any applicability", "Yes", "No"))
            toolbar.addWidget(self.applicability_filter)
        root.addLayout(toolbar)

        self._fields = ["icon", "name"]
        if self._has_structure:
            self._fields.append("applicable")
        self._fields.extend(("preferred", "supported", "experimental", "info"))
        self.table = QTableWidget(0, len(self._fields), self)
        self.table.setObjectName("customTaskTable")
        self.table.setHorizontalHeaderLabels([
            {"icon": "", "name": "Name", "experimental": "Experimental",
             "applicable": "Possible", "preferred": "Preferred",
             "supported": "Supported", "info": "Info"}[key]
            for key in self._fields
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setIconSize(QSize(24, 24))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 30)
        header.setSectionResizeMode(self._fields.index("info"), QHeaderView.ResizeMode.Stretch)
        header.setSortIndicatorShown(False)
        header.sectionClicked.connect(self._sort_by_column)
        self.table.cellDoubleClicked.connect(lambda *_args: self._accept_selection())
        root.addWidget(self.table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.search.textChanged.connect(self._refresh)
        self.experimental_filter.currentIndexChanged.connect(self._refresh)
        if self.applicability_filter is not None:
            self.applicability_filter.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def _sort_by_column(self, index: int) -> None:
        field = self._fields[index]
        if field == "icon":
            return
        if self._primary == field:
            self._descending = not self._descending
        else:
            # First click on Experimental: No, then Yes (descending labels).
            self._descending = field == "experimental"
        self._primary = field
        header = self.table.horizontalHeader()
        header.setSortIndicator(
            index, (Qt.SortOrder.DescendingOrder if self._descending
                    else Qt.SortOrder.AscendingOrder)
        )
        header.setSortIndicatorShown(True)
        self._refresh()

    def _refresh(self, *_args) -> None:
        previously = self._selected_name()
        text = self.search.text().casefold().strip()
        experimental = self.experimental_filter.currentIndex()
        applicable = (self.applicability_filter.currentText()
                      if self.applicability_filter is not None else "Any applicability")
        rows = [
            row for row in self._records
            if (not text or text in (row.name + " " + row.info + " " + row.details).casefold())
            and (experimental == 0 or row.experimental == (experimental == 1))
            and (applicable == "Any applicability" or row.applicable == applicable)
        ]
        rows = order_choices(
            rows, primary=self._primary, descending=self._descending,
            has_structure=self._has_structure,
        )
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = {
                "name": row.name, "experimental": "Yes" if row.experimental else "No",
                "applicable": row.applicable, "info": row.info,
                "preferred": "—" if row.name == "SCF" else "Yes" if row.preferred else "No",
                "supported": "Yes" if row.supported else "No",
            }
            for column, key in enumerate(self._fields):
                item = QTableWidgetItem() if key == "icon" else QTableWidgetItem(values[key])
                item.setData(Qt.ItemDataRole.UserRole, row.name)
                item.setToolTip(
                    row.reason if key == "applicable"
                    else "SCF is shown automatically when convergence is required."
                    if key == "preferred" and row.name == "SCF"
                    else (row.details or row.info) if key == "info"
                    else row.info
                )
                if key == "icon":
                    icon = task_icon(row.name)
                    if not icon.isNull():
                        item.setIcon(icon)
                self.table.setItem(index, column, item)
        target = next((i for i, row in enumerate(rows) if row.name == previously), 0)
        if rows:
            self.table.selectRow(target)

    def _selected_name(self) -> str | None:
        row = self.table.currentRow()
        item = self.table.item(row, self._fields.index("name")) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _accept_selection(self) -> None:
        name = self._selected_name()
        if name is None:
            return
        selected = next((row for row in self._records if row.name == name), None)
        if selected is not None and selected.applicable != "Yes" and self._has_structure:
            answer = QMessageBox.warning(
                self, "Task applicability",
                f"{name}: {selected.reason}\n\n"
                "You may edit and save this input even if the calculation is unsupported. "
                "Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.selected_task = name
        self.accept()
