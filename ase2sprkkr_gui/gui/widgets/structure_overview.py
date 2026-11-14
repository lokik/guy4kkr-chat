from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon
from PyQt6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.misc.resources import icon_path
from ase2sprkkr_gui.gui.plots.lattice import plot_atoms_preview
from ase2sprkkr_gui.physics.composition import site_composition, structure_formula


class StructureOverviewWidget(QWidget):
    """Present the current structure without owning workspace/application policy."""

    recentStartRequested = pyqtSignal()

    def __init__(
        self,
        *,
        save_action: QAction,
        edit_action: QAction,
        create_structure: Callable[[], None],
        create_from_database: Callable[[], None],
        download_structure: Callable[[], None],
        load_structure: Callable[[], None],
        load_output: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._atoms: Any = None
        self._site_colors: Dict[Any, str] = {}
        self._hovered_atom_index: Optional[int] = None

        layout = QVBoxLayout(self)
        self._stack = QStackedWidget(self)
        layout.addWidget(self._stack, 1)

        self._welcome_widget = self._build_welcome_page(
            create_structure=create_structure,
            create_from_database=create_from_database,
            download_structure=download_structure,
            load_structure=load_structure,
            load_output=load_output,
        )
        self._content_widget = self._build_structure_page(save_action, edit_action)
        self._stack.addWidget(self._welcome_widget)
        self._stack.addWidget(self._content_widget)
        self._stack.setCurrentWidget(self._welcome_widget)

    @property
    def info_text(self) -> str:
        """Return the rendered structure summary."""
        return self.info_label.text()

    @property
    def scf_status_text(self) -> str:
        """Return the rendered SCF status summary."""
        return self.converged_label.text()

    def set_recent_start(
        self,
        *,
        title: str | None,
        tooltip: str = "",
        menu: QMenu | None = None,
    ) -> None:
        """Present or hide the recent-item continuation affordance."""
        visible = title is not None
        self._recent_start_button.setVisible(visible)
        if not visible:
            self._recent_start_button.setMenu(None)
            return
        self._recent_start_button.setText(title)
        self._recent_start_button.setToolTip(tooltip)
        self._recent_start_button.setMenu(menu)

    def set_structure(
        self,
        atoms: Any,
        *,
        scf_status: Optional[str] = None,
        scf_converged: bool = False,
    ) -> None:
        """Render one structure snapshot and its already-resolved presentation status."""
        self._atoms = atoms
        if atoms is None:
            self.clear_structure()
            return

        self._stack.setCurrentWidget(self._content_widget)
        self._update_visualization()
        self._update_lattice_params()
        self._update_positions_table()
        self._update_info_label(scf_status=scf_status, scf_converged=scf_converged)

    def clear_structure(self) -> None:
        self._atoms = None
        self._stack.setCurrentWidget(self._welcome_widget)
        self._site_colors = {}
        self._hovered_atom_index = None
        self.converged_label.setText("")
        for label in self.lattice_labels.values():
            label.setText("–")
        for row in self.lattice_matrix_labels:
            for label in row:
                label.setText("–")
        self.positions_table.setRowCount(0)
        self.info_label.setText(
            "No structure loaded.\n\n"
            "Use Structure menu to create, load, or download a structure."
        )

    def _build_welcome_page(
        self,
        *,
        create_structure: Callable[[], None],
        create_from_database: Callable[[], None],
        download_structure: Callable[[], None],
        load_structure: Callable[[], None],
        load_output: Callable[[], None],
    ) -> QWidget:
        widget = QWidget(self._stack)
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("No Structure Loaded")
        title.setStyleSheet("font-size: 18pt; font-weight: bold; color: #666;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(20)

        subtitle = QLabel("Choose an option to get started:")
        subtitle.setStyleSheet("font-size: 11pt; color: #888;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(30)

        buttons: list[QPushButton] = []

        def add_button(text: str, callback: Callable[[], None]) -> QPushButton:
            button = QPushButton(text)
            button.setMinimumHeight(45)
            button.setStyleSheet("font-size: 11pt; padding: 8px;")
            button.clicked.connect(callback)
            buttons.append(button)
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignCenter)
            layout.addSpacing(15)
            return button

        add_button("Create New Structure", create_structure).setIcon(
            QIcon(str(icon_path("bulk_crystal.png")))
        )
        add_button("Create Structure from Prototype Database", create_from_database).setIcon(
            QIcon(str(icon_path("database.svg")))
        )
        add_button("Download Structure from Online Database", download_structure).setIcon(
            QIcon.fromTheme(
                "download",
                self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown),
            )
        )
        add_button("Load from File...", load_structure).setIcon(
            QIcon.fromTheme(
                "document-open",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            )
        )
        output_button = add_button("Load SPRKKR Output File...", load_output)
        output_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        )

        self._recent_start_button = QToolButton(widget)
        self._recent_start_button.setIcon(
            QIcon.fromTheme(
                "document-open-recent",
                self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView),
            )
        )
        self._recent_start_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._recent_start_button.setMinimumHeight(45)
        self._recent_start_button.setStyleSheet("font-size: 11pt; padding: 8px;")
        self._recent_start_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        self._recent_start_button.clicked.connect(
            lambda _checked=False: self.recentStartRequested.emit()
        )
        self._recent_start_button.hide()
        layout.addWidget(
            self._recent_start_button,
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
        # All welcome actions have one width, including the optional recent-file button.
        # Respect the longest translated/styled label rather than assuming 300px fits.
        button_width = max(300, *(button.sizeHint().width() for button in buttons))
        for button in (*buttons, self._recent_start_button):
            button.setFixedWidth(button_width)
        layout.addStretch(1)
        return widget

    def _build_structure_page(
        self,
        save_action: QAction,
        edit_action: QAction,
    ) -> QWidget:
        widget = QWidget(self._stack)
        content_layout = QVBoxLayout(widget)

        top_row = QWidget(widget)
        top_row_layout = QHBoxLayout(top_row)
        top_row_layout.setContentsMargins(0, 0, 0, 0)

        vis_group = QGroupBox("Structure Visualization")
        vis_layout = QVBoxLayout(vis_group)
        self.fig = Figure(figsize=(6, 6))
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.canvas = FigureCanvas(self.fig)
        vis_layout.addWidget(self.canvas)
        top_row_layout.addWidget(vis_group, 1)

        quick_actions = QGroupBox("Structure actions", top_row)
        quick_layout = QVBoxLayout(quick_actions)
        quick_layout.setContentsMargins(0, 0, 0, 0)
        quick_layout.setSpacing(8)

        save_button = QToolButton(quick_actions)
        save_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        save_button.setDefaultAction(save_action)
        save_button.setMinimumWidth(150)
        quick_layout.addWidget(save_button)

        edit_button = QToolButton(quick_actions)
        edit_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        edit_button.setDefaultAction(edit_action)
        quick_layout.addWidget(edit_button)
        quick_layout.addStretch(1)
        quick_actions.setMaximumWidth(220)
        top_row_layout.addWidget(quick_actions, 0)
        content_layout.addWidget(top_row, 2)

        lattice_group = QGroupBox("Lattice Parameters")
        lattice_layout = QGridLayout(lattice_group)
        self.lattice_labels: Dict[str, QLabel] = {}
        params = ["a", "b", "c", "α", "β", "γ"]
        for i, param in enumerate(params):
            label = QLabel(f"{param}:")
            value = QLabel("–")
            value.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            lattice_layout.addWidget(label, i // 3, (i % 3) * 2)
            lattice_layout.addWidget(value, i // 3, (i % 3) * 2 + 1)
            self.lattice_labels[param] = value

        lattice_layout.addWidget(QLabel("Lattice vectors (Å):"), 2, 0, 1, 6)
        self.lattice_matrix_labels = []
        for i in range(3):
            row_labels = []
            for j in range(3):
                label = QLabel("–")
                label.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                lattice_layout.addWidget(label, 3 + i, j * 2, 1, 2)
                row_labels.append(label)
            self.lattice_matrix_labels.append(row_labels)

        info_group = QGroupBox("Structure Information")
        info_layout = QVBoxLayout(info_group)
        self.converged_label = QLabel("")
        self.converged_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(self.converged_label)
        self.info_label = QLabel(
            "No structure loaded.\n\n"
            "Use Structure menu to create, load, or download a structure."
        )
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        info_layout.addWidget(self.info_label)

        params_row = QWidget()
        params_layout = QHBoxLayout(params_row)
        params_layout.setContentsMargins(0, 0, 0, 0)
        params_layout.addWidget(lattice_group, 1)
        params_layout.addWidget(info_group, 1)
        content_layout.addWidget(params_row, 0)

        positions_group = QGroupBox("Atomic Positions")
        positions_layout = QVBoxLayout(positions_group)
        self.positions_table = QTableWidget(0, 9)
        self.positions_table.setHorizontalHeaderLabels(
            [
                "Site",
                "Element",
                "Color",
                "x (Å)",
                "y (Å)",
                "z (Å)",
                "x (scaled)",
                "y (scaled)",
                "z (scaled)",
            ]
        )
        self.positions_table.horizontalHeader().setStretchLastSection(False)
        self.positions_table.verticalHeader().setVisible(False)
        header = self.positions_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.positions_table.setColumnWidth(0, 80)
        self.positions_table.setColumnWidth(1, 160)
        self.positions_table.setColumnWidth(2, 30)
        self.positions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.positions_table.setMouseTracking(True)
        self.positions_table.viewport().setMouseTracking(True)
        self.positions_table.cellEntered.connect(self._on_positions_table_hovered)
        self.positions_table.viewport().installEventFilter(self)
        positions_layout.addWidget(self.positions_table)
        content_layout.addWidget(positions_group, 1)
        return widget

    def _on_positions_table_hovered(self, row: int, _column: int) -> None:
        if self._atoms is None or row < 0 or row >= len(self._atoms):
            return
        if self._hovered_atom_index == row:
            return
        self._hovered_atom_index = row
        self._update_visualization()

    def eventFilter(self, obj, event):  # type: ignore[override]
        if obj is self.positions_table.viewport() and event.type() == QEvent.Type.Leave:
            if self._hovered_atom_index is not None:
                self._hovered_atom_index = None
                self._update_visualization()
        return super().eventFilter(obj, event)

    def _update_visualization(self) -> None:
        if self._atoms is None:
            return
        self._site_colors = plot_atoms_preview(
            self.ax,
            self._atoms,
            canvas=self.canvas,
            hovered_atom_indices=self._hovered_atom_index,
        )

    def _update_lattice_params(self) -> None:
        if self._atoms is None:
            return
        cell = self._atoms.get_cell()
        lengths = cell.lengths()
        angles = cell.angles()
        self.lattice_labels["a"].setText(f"{lengths[0]:.4f} Å")
        self.lattice_labels["b"].setText(f"{lengths[1]:.4f} Å")
        self.lattice_labels["c"].setText(f"{lengths[2]:.4f} Å")
        self.lattice_labels["α"].setText(f"{angles[0]:.2f}°")
        self.lattice_labels["β"].setText(f"{angles[1]:.2f}°")
        self.lattice_labels["γ"].setText(f"{angles[2]:.2f}°")
        for i in range(3):
            for j in range(3):
                self.lattice_matrix_labels[i][j].setText(f"{cell[i, j]:8.4f}")

    def _update_positions_table(self) -> None:
        if self._atoms is None:
            self.positions_table.setRowCount(0)
            return

        positions = self._atoms.get_positions()
        symbols = self._atoms.get_chemical_symbols()
        arrays = self._atoms.arrays
        empty = [None] * len(symbols)
        kinds = arrays.get("spacegroup_kinds", empty)
        labels = arrays.get("labels", empty)
        self.positions_table.setRowCount(len(positions))
        scaled_positions = self._atoms.get_scaled_positions()
        counter: Dict[str, int] = {}

        for i, (sym, pos, scaled_pos, kind, label) in enumerate(
            zip(symbols, positions, scaled_positions, kinds, labels)
        ):
            if not label:
                counter[sym] = counter.get(sym, 0) + 1
                label = f"{sym}.{counter[sym]}"

            item_site = QTableWidgetItem(label)
            item_comp = QTableWidgetItem(site_composition(self._atoms, i))
            item_color = QTableWidgetItem("")
            item_color.setBackground(QColor(self._site_colors.get(kind, "#1f77b4")))

            self.positions_table.setItem(i, 0, item_site)
            self.positions_table.setItem(i, 1, item_comp)
            self.positions_table.setItem(i, 2, item_color)
            align_num = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            for j in range(3):
                item = QTableWidgetItem(f"{pos[j]:.4f}")
                item.setTextAlignment(align_num)
                self.positions_table.setItem(i, 3 + j, item)
                scaled_item = QTableWidgetItem(f"{scaled_pos[j]:.4f}")
                scaled_item.setTextAlignment(align_num)
                self.positions_table.setItem(i, 6 + j, scaled_item)

    def _update_info_label(
        self,
        *,
        scf_status: Optional[str],
        scf_converged: bool,
    ) -> None:
        if self._atoms is None:
            return
        status_text = ""
        if scf_converged:
            status_text = "SCF Status: CONVERGED"
        elif scf_status and scf_status != "START":
            status_text = f"SCF Status: {scf_status}"
        self.converged_label.setText(status_text)
        self.info_label.setText(
            f"Formula: {structure_formula(self._atoms)}\n"
            f"Number of atoms: {len(self._atoms)}\n"
        )
