from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.physics.structure_database import (
    StructurePrototype,
    load_structure_database,
)


class StructureDatabaseDialog(QDialog):
    """Select a crystallographic prototype from the bundled XBand database."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Create Structure from Prototype Database")
        self.resize(900, 600)
        self._prototypes = load_structure_database()

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Select a structure prototype. Lattice parameters, free Wyckoff "
            "coordinates, and chemical elements are specified in the next steps."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText(
            "Search structure type, Pearson symbol, material, or space group…"
        )
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._populate_table)
        layout.addWidget(self.search_edit)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(
            [
                "Description",
                "Structure type",
                "Pearson",
                "Space group",
                "Wyckoff sites",
            ]
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self._accept_selection())
        layout.addWidget(self.table, 1)

        self.details_label = QLabel(self)
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.details_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.buttons.accepted.connect(self._accept_selection)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        layout.addWidget(self.buttons)

        self._populate_table()

    @property
    def selected_prototype(self) -> Optional[StructurePrototype]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    @staticmethod
    def _display_structure_type(prototype: StructurePrototype) -> str:
        structure_type = prototype.structure_type
        return "Unknown" if structure_type in {"", "???"} else structure_type

    def _populate_table(self) -> None:
        query = self.search_edit.text().strip().casefold()
        rows = [
            prototype
            for prototype in self._prototypes
            if not query or query in prototype.search_text
        ]

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row, prototype in enumerate(rows):
            description_item = QTableWidgetItem(prototype.description)
            description_item.setData(Qt.ItemDataRole.UserRole, prototype)
            self.table.setItem(row, 0, description_item)

            display_type = self._display_structure_type(prototype)
            type_item = QTableWidgetItem(display_type)
            if display_type == "Unknown":
                type_item.setToolTip(
                    "No structure type is specified in the XBand database."
                )
            self.table.setItem(row, 1, type_item)
            self.table.setItem(row, 2, QTableWidgetItem(prototype.pearson_symbol))

            space_group_item = QTableWidgetItem()
            space_group_item.setData(
                Qt.ItemDataRole.DisplayRole, prototype.space_group
            )
            space_group_item.setToolTip(prototype.international_symbol)
            self.table.setItem(row, 3, space_group_item)
            self.table.setItem(row, 4, QTableWidgetItem(prototype.site_summary))
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.AscendingOrder)

        if rows:
            self.table.selectRow(0)
            self._selection_changed()
        else:
            self.details_label.setText("No matching structure prototypes.")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def _selection_changed(self) -> None:
        prototype = self.selected_prototype
        enabled = prototype is not None
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(enabled)
        if prototype is None:
            self.details_label.clear()
            return

        setting_note = (
            " The rhombohedral definition will be represented by its equivalent "
            "conventional hexagonal cell."
            if prototype.is_rhombohedral_setting
            else ""
        )
        identity = " ".join(
            value
            for value in (
                self._display_structure_type(prototype),
                prototype.pearson_symbol,
                prototype.description,
            )
            if value
        )
        self.details_label.setText(
            f"{identity}\n"
            f"Space group {prototype.space_group}: "
            f"{prototype.international_symbol} "
            f"({prototype.schoenflies_symbol}); "
            f"sites: {prototype.site_summary}.{setting_note}"
        )

    def _accept_selection(self) -> None:
        if self.selected_prototype is not None:
            self.accept()


def select_structure_prototype(
    parent: Optional[QWidget] = None,
) -> Optional[StructurePrototype]:
    dialog = StructureDatabaseDialog(parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.selected_prototype
    return None
