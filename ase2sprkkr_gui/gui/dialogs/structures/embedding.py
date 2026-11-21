"""Interactive editor for a finite cluster embedded in an infinite SPR-KKR host."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import product

import numpy as np
from PyQt6.QtCore import QEvent, QItemSelection, QItemSelectionModel, Qt, QTimer
from PyQt6.QtGui import QAction, QCursor, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.ase.embedding import (
    EmbeddingDraft,
    HostSite,
    cell_ring_offsets,
    embedding_cell,
    embedding_source,
    fill_cell_hull,
    occupation_label,
)
from ase2sprkkr_gui.gui.dialogs.structures.embedding_history import EmbeddingUndoStack
from ase2sprkkr_gui.gui.plots.lattice import corner_indices
from ase2sprkkr_gui.gui.widgets.structures.embedding_preview import EmbeddingPreview
from ase2sprkkr_gui.gui.plots.atom_sizes import marker_areas
from ase2sprkkr_gui.gui.widgets.structures.host_cell_map import (
    HostCellMap, SELECTED_COLOR, SYMMETRY_APPLY_COLOR, SYMMETRY_PREVIEW_COLOR,
)
from ase2sprkkr_gui.gui.widgets.structures.occupation import OccupationEditor


@dataclass(frozen=True)
class _PendingDisplacement:
    sites: tuple[HostSite, ...]
    vector: np.ndarray
    symmetric: bool
    edit_key: tuple


class BuildEmbeddingDialog(QDialog):
    """Build/edit a cluster without mutating its periodic host."""

    HELP_TEXT = (
        "Select a repeated host cell, then include or modify individual sites. "
        "Only included sites are written to the cluster; the host remains unchanged."
    )

    def __init__(self, atoms, parent: QWidget | None = None, *, embedded=False):
        super().__init__(parent)
        self._embedded = embedded
        self._applied = False
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        host, cluster = embedding_source(atoms)
        self.draft = EmbeddingDraft(host, cluster)
        self.undo_stack = EmbeddingUndoStack(self.draft, self)
        self._occupation_edit_key = None
        self._pending_displacement: _PendingDisplacement | None = None
        self.setWindowTitle("Edit Embedded Cluster" if cluster is not None else "Build Embedded Cluster")
        self.resize(1450, 950)
        self.result_atoms = None
        self._selected_cell = self.draft.center.cell_index[:self.draft.dimension]
        self._selected_site: HostSite | None = self.draft.center
        self._occupation_overwrite_approval = None
        self._selected_sites = {self.draft.center}
        self._site_rows: list[HostSite] = []
        self._site_updating = False
        self._highlighted: set[HostSite] = set()
        self._expansion_mode: str | None = None
        self._expansion_sites: set[HostSite] = set()
        self._expansion_key = None
        self._rendered_sites: list[HostSite] = []
        self._rendered_host_sites: set[HostSite] = set()
        self._local_sites: list[HostSite] = []
        self._global_timer = QTimer(self)
        self._global_timer.setInterval(120)
        self._global_timer.setSingleShot(True)
        self._global_timer.timeout.connect(self._render_global)
        self._local_timer = QTimer(self)
        self._local_timer.setInterval(80)
        self._local_timer.setSingleShot(True)
        self._local_timer.timeout.connect(self._render_local)
        self._displacement_timer = QTimer(self)
        self._displacement_timer.setSingleShot(True)
        self._displacement_timer.setInterval(350)
        self._displacement_timer.timeout.connect(self._apply_pending_displacement)
        self._expansion_timer = QTimer(self)
        self._expansion_timer.setSingleShot(True)
        self._expansion_timer.setInterval(120)
        self._expansion_timer.timeout.connect(self._update_expansion_preview)
        self._build_ui()
        self._refresh_cells()
        self._refresh_sites()
        self._refresh_summary()
        self.undo_stack.stateRestored.connect(self._history_restored)
        self.undo_stack.indexChanged.connect(self._update_history_actions)
        self.occupation.validityChanged.connect(self._occupation_validity_changed)
        self.occupation.add_btn.pressed.connect(self.undo_stack.end_edit)
        self._update_history_actions()
        QApplication.instance().focusChanged.connect(self._expansion_focus_changed)
        QApplication.instance().focusChanged.connect(self._editing_focus_changed)
        QApplication.instance().installEventFilter(self)

    def update_host_geometry(self, host) -> None:
        """Refresh live host coordinates without replacing the Embedded draft."""
        if host is self.draft.geometry_host:
            return
        if self._pending_displacement is not None:
            if self._unfinished_numbers():
                raise ValueError("Finish the pending displacement before updating the host")
            self._commit_pending_displacement()
        self.draft.set_geometry_host(host)
        self.undo_stack.end_edit()
        self._expansion_key = None  # Geometry-dependent radius/shell previews.
        self._expansion_sites.clear()
        self._global_timer.stop()
        self._local_timer.stop()
        self._refresh_cells()
        if self._unfinished_numbers() or self._has_occupation_buffer():
            # Never overwrite invalid, unfinished text in live input controls.
            self._update_symmetry_preview()
            self._refresh_summary()
        else:
            self._refresh_sites()
        self._update_history_actions()
        self._schedule_global_render()
        self._schedule_local_render()
        self._schedule_expansion_preview()

    def _build_ui(self):
        root = QVBoxLayout(self)
        body = QSplitter(Qt.Orientation.Vertical, self)
        body.setChildrenCollapsible(False)
        root.addWidget(body, 1)
        controls = QWidget(body)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        controls_layout.addWidget(splitter, 1)

        left = QGroupBox("Host cells", splitter)
        left_v = QVBoxLayout(left)
        map_row = QHBoxLayout()
        map_controls = QWidget(left)
        map_controls.setMaximumWidth(125)
        map_controls_layout = QVBoxLayout(map_controls)
        map_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.cell_plane = QComboBox()
        for name, axes in (("XY", (0, 1)), ("XZ", (0, 2)), ("YZ", (1, 2))):
            self.cell_plane.addItem(name, axes)
        self.cell_plane.setToolTip("Cartesian projection of the repeated host-cell lattice")
        self.cell_plane.currentIndexChanged.connect(self._plane_changed)
        if self.draft.dimension == 3:
            map_controls_layout.addWidget(QLabel("Projection"))
            map_controls_layout.addWidget(self.cell_plane)
            self.layer_label = QLabel("Layer")
            self.layer = QSpinBox()
            self.layer.setRange(-100000, 100000)
            self.layer.setValue(self._selected_cell[2])
            self.layer.setToolTip("Cell translation perpendicular to the selected lattice plane")
            self.layer.valueChanged.connect(self._layer_changed)
            map_controls_layout.addWidget(self.layer_label)
            map_controls_layout.addWidget(self.layer)
        else:
            self.layer = None
            self.cell_plane.hide()
        map_controls_layout.addWidget(QLabel("WS rings"))
        self.cell_rings = QSpinBox()
        self.cell_rings.setRange(0, 20)
        self.cell_rings.setValue(2)
        self.cell_rings.setToolTip(
            "Each ring adds neighbours sharing a Wigner–Seitz (Voronoi) edge, "
            "using the actual lattice metric. Zero shows only cell (0,0). "
            "Drawn cells remain primitive parallelograms."
        )
        self.cell_rings.valueChanged.connect(self._display_region_changed)
        map_controls_layout.addWidget(self.cell_rings)
        map_controls_layout.addStretch(1)
        map_row.addWidget(map_controls)
        self.cells = HostCellMap(left)
        self.cells.cellSelected.connect(self._cell_changed)
        map_row.addWidget(self.cells, 1)
        left_v.addLayout(map_row, 1)
        self.symmetric = QCheckBox("Apply actions to symmetry-equivalent sites")
        self.symmetric.setChecked(True)
        self.symmetric.setToolTip(
            "Include, Exclude, occupation and displacement affect all "
            "symmetry-equivalent host sites when checked. When unchecked, "
            "only the selected sites are edited."
        )
        self.symmetric.toggled.connect(self._symmetry_changed)
        left_v.addWidget(self.symmetric)
        self.symmetry_info = QLabel()
        self.symmetry_info.setWordWrap(True)
        left_v.addWidget(self.symmetry_info)
        splitter.addWidget(left)

        # The expansion controls belong to the two editing columns, while
        # the cell map extends to the bottom of their combined height.
        details_panel = QWidget(splitter)
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(0, 0, 0, 0)
        # The centre and expansion settings apply to the whole cluster.
        # Show the centre heading and its value on one line, with the action
        # for choosing a new centre next to the per-cell site selection.
        self.centre_label = QLabel(details_panel)
        self.centre_label.setTextFormat(Qt.TextFormat.RichText)
        self.centre_label.setWordWrap(False)
        details_layout.addWidget(self.centre_label)
        options = QGroupBox(details_panel)
        options_layout = QVBoxLayout(options)
        opt_row = QHBoxLayout()
        options_layout.addLayout(opt_row)
        opt_row.addWidget(QLabel("Radius (Å):"))
        self.radius = QDoubleSpinBox()
        self.radius.setRange(0, 1000)
        self.radius.setDecimals(2)
        self.radius.setValue(5.0)
        self.radius.valueChanged.connect(self._schedule_expansion_preview)
        opt_row.addWidget(self.radius)
        self.add_radius_button = QPushButton("Include within radius")
        self.add_radius_button.clicked.connect(self._add_radius)
        opt_row.addWidget(self.add_radius_button)
        opt_row.addWidget(QLabel("Coordination shells:"))
        self.shells = QSpinBox()
        self.shells.setRange(0, 50)
        self.shells.setValue(1)
        self.shells.valueChanged.connect(self._schedule_expansion_preview)
        opt_row.addWidget(self.shells)
        self.add_shells_button = QPushButton("Include shells")
        self.add_shells_button.clicked.connect(self._add_shells)
        opt_row.addWidget(self.add_shells_button)
        opt_row.addStretch(1)
        self.expansion_info = QLabel()
        self.expansion_info.setWordWrap(True)
        self.expansion_info.hide()
        options_layout.addWidget(self.expansion_info)
        details_layout.addWidget(options)

        details_splitter = QSplitter(Qt.Orientation.Horizontal, details_panel)
        details_splitter.setChildrenCollapsible(False)
        details_layout.addWidget(details_splitter, 1)

        site_group = QGroupBox("Sites in selected cell", details_splitter)
        site_layout = QVBoxLayout(site_group)
        site_header = QHBoxLayout()
        self.cell_label = QLabel()
        site_header.addWidget(self.cell_label)
        site_header.addStretch(1)
        self.centre_button = QPushButton("Use selected site as cluster centre", site_group)
        self.centre_button.setToolTip(
            "Set the host site used for symmetry and radius/shell expansion"
        )
        self.centre_button.clicked.connect(self._set_centre)
        site_header.addWidget(self.centre_button)
        site_layout.addLayout(site_header)
        self.sites = QTableWidget(site_group)
        self.sites.setColumnCount(4)
        self.sites.setHorizontalHeaderLabels(
            ["Site", "Host occupation", "Cluster occupation", "Included"]
        )
        self.sites.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sites.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sites.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sites.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.sites.horizontalHeader().setStretchLastSection(True)
        self.sites.itemSelectionChanged.connect(self._site_changed)
        self.sites.currentCellChanged.connect(self._current_site_changed)
        site_layout.addWidget(self.sites, 1)
        site_actions = QHBoxLayout()
        self.include_button = QPushButton("Include")
        self.include_button.clicked.connect(self._include)
        site_actions.addWidget(self.include_button)
        self.exclude_button = QPushButton("Exclude")
        self.exclude_button.clicked.connect(self._exclude)
        site_actions.addWidget(self.exclude_button)
        site_layout.addLayout(site_actions)
        details_splitter.addWidget(site_group)

        right = QGroupBox("Site editing", details_splitter)
        right_v = QVBoxLayout(right)

        occupation_group = QGroupBox("Occupation", right)
        occupation_layout = QVBoxLayout(occupation_group)
        self.occupation_info = QLabel()
        self.occupation_info.setWordWrap(True)
        occupation_layout.addWidget(self.occupation_info)
        self.occupation_group = occupation_group
        right_v.addWidget(occupation_group)
        self.occupation = OccupationEditor(
            occupation_group, require_full=True, allow_duplicates=False
        )
        # An incomplete mixture stays in this control. Once its fractions
        # are valid, publish the edit to the cluster without another button.
        self.occupation.occupationEdited.connect(self._occupation_edited)
        self.occupation.restore_btn.clicked.disconnect(self.occupation.restore_initial)
        self.occupation.restore_btn.clicked.connect(self._restore_occupation)
        occupation_layout.addWidget(self.occupation)

        displacement_group = QGroupBox("Displacement from host position (Å)", right)
        displacement_layout = QVBoxLayout(displacement_group)
        self.displacement_info = QLabel()
        self.displacement_info.setWordWrap(True)
        displacement_layout.addWidget(self.displacement_info)
        displacement_row = QFormLayout()
        self.deltas = []
        for label in ("x", "y", "z"):
            spin = QDoubleSpinBox()
            spin.setDecimals(5)
            spin.setRange(-100.0, 100.0)
            spin.setSingleStep(0.01)
            self.deltas.append(spin)
            spin.valueChanged.connect(self._schedule_displacement)
            spin.editingFinished.connect(self._finish_displacement_edit)
            displacement_row.addRow(label, spin)
        displacement_layout.addLayout(displacement_row)
        self.displacement_group = displacement_group
        right_v.addWidget(displacement_group)
        right_v.addStretch(1)
        details_splitter.addWidget(right)
        details_splitter.setSizes([510, 500])
        splitter.addWidget(details_panel)
        splitter.setSizes([490, 870])

        preview_splitter = QSplitter(Qt.Orientation.Horizontal, self)

        local_group = QGroupBox(
            "Selected cell · click a site to edit" if self.draft.dimension == 3
            else "Selected cell: transition region · click a site to edit", preview_splitter
        )
        local_layout = QVBoxLayout(local_group)
        self.local_info = QLabel()
        local_layout.addWidget(self.local_info)
        self.local_preview = EmbeddingPreview(selectable=True)
        self.local_preview.pointSelected.connect(self._select_local_site)
        local_layout.addWidget(self.local_preview, 1)
        preview_splitter.addWidget(local_group)

        global_group = QGroupBox("Host structure / embedded cluster · view only", preview_splitter)
        global_layout = QVBoxLayout(global_group)
        self.preview_info = QLabel()
        global_layout.addWidget(self.preview_info)
        self.global_scope = QComboBox()
        self.global_scope.addItem("Whole structure", "whole")
        if self.draft.dimension == 3:
            self.global_scope.addItem("Current layer", "layer")
        else:
            self.global_scope.addItem("Transition region", "layer")
        self.global_scope.currentIndexChanged.connect(self._schedule_global_render)
        self.global_scope.setToolTip("Scope of the host structure shown in this preview")
        self.global_preview = EmbeddingPreview(
            controls_on_right=True, controls_header=self.global_scope,
            show_bulk_opacity=True,
        )
        global_layout.addWidget(self.global_preview, 1)
        preview_splitter.addWidget(global_group)
        preview_splitter.setSizes([650, 650])
        # Bold section headings without changing the font of child controls.
        self.setStyleSheet("QGroupBox::title { font-weight: bold; }")
        body.addWidget(preview_splitter)
        body.setSizes([350, 450])

        atom_hint = (
            "Fill:\n"
            "Blue — included in cluster\n"
            "Orange — modified site\n"
            "Green — expansion preview\n"
            "Gray — host site\n"
            "Rings:\n"
            "Bright orange — selected site\n"
            "Dark orange — symmetry-related site (actions enabled)\n"
            "Purple — symmetry preview (actions disabled)"
        )
        self._plot_hints = {
            self.cells.canvas: (
                "Fill:\n"
                "Blue — cell containing included sites\n"
                "Orange — cell containing modified sites\n"
                "Gray — other host cell\n"
                "Borders:\n"
                "Bright orange — selected cell\n"
                "Dark orange — symmetry-related cell (actions enabled)\n"
                "Purple — symmetry preview (actions disabled)"
            ),
            self.local_preview.canvas: atom_hint,
            self.global_preview.canvas: atom_hint,
        }
        self._plot_hint_target = None
        self._plot_hint_timer = QTimer(self)
        self._plot_hint_timer.setInterval(900)
        self._plot_hint_timer.setSingleShot(True)
        self._plot_hint_timer.timeout.connect(self._show_plot_hint)

        self.summary = QLabel()
        root.addWidget(self.summary)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        history_buttons = []
        for name, key, slot in (("undo", QKeySequence.StandardKey.Undo, self._undo),
                                ("redo", QKeySequence.StandardKey.Redo, self._redo)):
            action = QAction(name.title(), self)
            action.setShortcuts(QKeySequence.keyBindings(key))
            action.triggered.connect(slot)
            self.addAction(action)
            setattr(self, name + "_action", action)
            button = QToolButton(self)
            button.setDefaultAction(action)
            setattr(self, name + "_button", button)
            history_buttons.append(button)
            footer.addWidget(button)
        standard_buttons = [
            self.buttons.button(QDialogButtonBox.StandardButton.Ok),
            self.buttons.button(QDialogButtonBox.StandardButton.Cancel),
        ]
        width = max(button.sizeHint().width() for button in history_buttons + standard_buttons)
        for button in history_buttons + standard_buttons:
            button.setFixedWidth(width)
        if self._embedded:
            footer.addStretch(1)
        else:
            self.hint = QLabel(self.HELP_TEXT, self)
            self.hint.setWordWrap(True)
            footer.addWidget(self.hint, 1)
        footer.addWidget(self.buttons)
        if self._embedded:
            # The parent Structure Editor owns Apply / Cancel. Undo and redo
            # remain local to the embedded-site editing draft.
            self.buttons.hide()
        root.addLayout(footer)

    def _show_plot_hint(self):
        target = self._plot_hint_target
        if target is not None and target.underMouse():
            QToolTip.showText(QCursor.pos(), self._plot_hints[target], target)

    def _edit_key(self, field):
        return self.undo_stack.edit_key((field, frozenset(self._selected_sites),
                                         self.symmetric.isChecked(), self.draft.center))

    def _record_edit(self, text, operation, *, edit_key=None, preserve_occupation=False):
        if self.undo_stack.apply(operation, text, merge_key=edit_key):
            self._changed(preserve_occupation=preserve_occupation)
        self._update_history_actions()

    def _edit_control(self, widget):
        if widget is None:
            return None
        controls = list(self.deltas)
        controls.extend(control for row in self.occupation.rows
                        for control in (row["elem"], row["occ"], row["pick"], row["del"]))
        for control in controls:
            if widget is control or control.isAncestorOf(widget):
                return control
        return None

    def _editing_focus_changed(self, old, new):
        if self._edit_control(old) is not self._edit_control(new):
            self._apply_pending_displacement()
            self.undo_stack.end_edit()

    def eventFilter(self, obj, event):
        if obj in self._plot_hints:
            if event.type() == QEvent.Type.Enter:
                self._plot_hint_target = obj
                self._plot_hint_timer.start()
            elif (event.type() in (
                QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel
            ) and self._plot_hint_target is obj):
                self._plot_hint_timer.stop()
                self._plot_hint_target = None
                QToolTip.hideText()
        # Child line edits otherwise consume Ctrl+Z as a character-level undo.
        # Keep shortcuts scoped to this dialog, excluding separate modal windows.
        if (event.type() == QEvent.Type.KeyRelease
                and isinstance(obj, QWidget) and obj.window() is self):
            self._update_history_actions()
        if (event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress)
                and isinstance(obj, QWidget) and obj.window() is self):
            for key, action in ((QKeySequence.StandardKey.Undo, self.undo_action),
                                (QKeySequence.StandardKey.Redo, self.redo_action)):
                if event.matches(key):
                    if event.type() == QEvent.Type.KeyPress:
                        self._update_history_actions()
                        action.trigger()
                    event.accept()
                    return True
            if (event.type() == QEvent.Type.KeyPress
                    and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
                control = self._edit_control(obj)
                if control is not None:
                    if isinstance(control, QDoubleSpinBox):
                        control.interpretText()
                    self._finish_displacement_edit()
                    event.accept()
                    return True
        return super().eventFilter(obj, event)

    def _update_history_actions(self, *_):
        dirty = self._has_occupation_buffer() or bool(self._unfinished_numbers())
        pending = self._pending_displacement is not None
        self.undo_action.setEnabled(self.undo_stack.canUndo() or dirty or pending)
        self.redo_action.setEnabled(self.undo_stack.canRedo() and not dirty and not pending)
        for action, text, key in ((self.undo_action, self.undo_stack.undoText(), "Undo"),
                                  (self.redo_action, self.undo_stack.redoText(), "Redo")):
            shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            action.setToolTip(f"{key} {text} ({shortcut})" if text else f"{key} ({shortcut})")

    def _has_occupation_buffer(self):
        return (not self.occupation.is_valid()
                or any(not entry.symbol.strip() for entry in self.occupation.entries))

    def _unfinished_numbers(self):
        controls = self.deltas + [row["occ"] for row in self.occupation.rows]
        return [spin for spin in controls if not spin.hasAcceptableInput()]

    def _prepare_history_navigation(self):
        try:
            self._commit_pending_displacement()
        except (ValueError, TypeError, IndexError):
            # Undo cancels an invalid pending vector without undoing an older,
            # unrelated command or letting a timer reapply the invalid edit.
            self._display_site()
            self.undo_stack.end_edit()
            self._update_history_actions()
            return False
        return True

    def _undo(self):
        unfinished = self._has_occupation_buffer()
        edit_key = self._occupation_edit_key
        numbers = self._unfinished_numbers()
        if numbers:
            unfinished = True
            field = "displacement" if numbers[0] in self.deltas else "occupation"
            edit_key = self._edit_key(field)
        if not self._prepare_history_navigation():
            return
        undo_edit = not unfinished or self.undo_stack.last_edit_matches(edit_key)
        self._display_site()
        if undo_edit:
            self.undo_stack.undo()
        self.undo_stack.end_edit()
        self._update_history_actions()

    def _redo(self):
        if self._prepare_history_navigation():
            self._display_site()
            self.undo_stack.redo()
            self.undo_stack.end_edit()
            self._update_history_actions()

    def _history_restored(self):
        self._displacement_timer.stop()
        self._pending_displacement = None
        self._occupation_overwrite_approval = None
        self._changed()

    def _guard(self, operation):
        try:
            return operation()
        except (ValueError, TypeError, IndexError) as exc:
            QMessageBox.warning(self, "Embedded Cluster", str(exc))
            return None

    def _display_region_changed(self, *_):
        self._refresh_cells()
        # The cell map and the context must show the same viewport immediately.
        # Detail geometry is independent of its size and needs no redraw here.
        self._global_timer.stop()
        self._render_global()

    def _plane_axes(self):
        return tuple(self.cell_plane.currentData()) if self.draft.dimension == 3 else (0, 1)

    def _fixed_axis(self):
        return next(i for i in range(3) if i not in self._plane_axes())

    def _plane_changed(self, *_):
        fixed = self._fixed_axis()
        self.layer.blockSignals(True)
        self.layer.setValue(self._selected_cell[fixed])
        self.layer.blockSignals(False)
        self.global_scope.setItemData(
            1, "Host cells in the currently selected lattice layer",
            Qt.ItemDataRole.ToolTipRole,
        )
        self._display_region_changed()

    def _layer_changed(self, value):
        fixed = self._fixed_axis()
        if (
            self._selected_site is not None
            and not self.occupation.is_valid()
            and self._selected_cell[fixed] != value
        ):
            self.layer.blockSignals(True)
            self.layer.setValue(self._selected_cell[fixed])
            self.layer.blockSignals(False)
            return
        self._apply_pending_displacement()
        self.undo_stack.end_edit()
        cell = list(self._selected_cell)
        cell[fixed] = value
        self._selected_cell = tuple(cell)
        self._refresh_cells()
        self._refresh_sites()

    def _cell_index(self, x, y):
        cell = [0] * self.draft.dimension
        for axis, value in zip(self._plane_axes(), (x, y)):
            cell[axis] = value
        if self.layer is not None:
            cell[self._fixed_axis()] = self.layer.value()
        return tuple(cell)

    def _cell_offsets(self):
        atoms = getattr(self.draft.geometry_host, "atoms", self.draft.geometry_host)
        return cell_ring_offsets(np.asarray(atoms.cell)[list(self._plane_axes())],
                                 self.cell_rings.value())

    def _visible_cells(self, *, whole=False):
        cells = [self._cell_index(x, y) for x, y in self._cell_offsets()]
        if whole and self.layer is not None:
            fixed = self._fixed_axis()
            count = min(2 * self.cell_rings.value() + 1, 5)
            start = self.layer.value() - count // 2
            cells = [tuple(value if i == fixed else cell[i] for i in range(3))
                     for cell in cells for value in range(start, start + count)]
        return cells

    def _refresh_cells(self, *_):
        origin, cell = embedding_cell(self.draft.geometry_host)
        axes = self._plane_axes()
        if self.draft.dimension == 2:
            first = cell[0] / np.linalg.norm(cell[0])
            normal = np.cross(cell[0], cell[1])
            normal /= np.linalg.norm(normal)
            projection = np.column_stack((first, np.cross(normal, first)))
            axis_labels = ("along a1", "in-plane transverse")
        else:
            projection = np.eye(3)[:, axes]
            axis_labels = tuple("xyz"[i] for i in axes)
        dimension = self.draft.dimension
        counts = Counter(site.cell_index[:dimension] for site in self.draft.entries)
        modified = {site.cell_index[:dimension] for site in self.draft.entries
                    if self._is_modified(site)}
        equivalents = {site.cell_index[:dimension] for site in self._highlighted}
        self.cells.set_cells(
            self._visible_cells(), cell=cell, origin=origin, axes=axes,
            projection=projection, axis_labels=axis_labels,
            selected=self._selected_cell, counts=counts,
            modified=modified, equivalents=equivalents,
            apply_equivalents=self.symmetric.isChecked(),
        )

    def _is_modified(self, site):
        entry = self.draft.entries.get(site)
        if entry is None:
            return False
        return (entry.occupation != site.occupation(self.draft.geometry_host)
                or np.linalg.norm(entry.displacement) > 1e-8)

    def _cell_changed(self, cell):
        self._apply_pending_displacement()
        if (
            tuple(cell) != self._selected_cell
            and self._selected_site is not None
            and not self.occupation.is_valid()
        ):
            return
        self.undo_stack.end_edit()
        # Cell-map offsets may contain NumPy scalars; keep UI identities and
        # their tuple representations as ordinary Python integers.
        self._selected_cell = tuple(int(index) for index in cell)
        self._selected_site = None
        self._selected_sites.clear()
        self._occupation_overwrite_approval = None
        self._refresh_cells()
        self._refresh_sites()

    def _refresh_sites(self, *, preserve_occupation=False):
        self._site_updating = True
        self.sites.blockSignals(True)
        self._site_rows = list(self.draft.cell_sites(self._selected_cell))
        self.cell_label.setText("Cell " + str(self._selected_cell))
        self.sites.setRowCount(len(self._site_rows))
        for row, site in enumerate(self._site_rows):
            entry = self.draft.entries.get(site)
            name = f"#{site.original_site + 1}"
            if len(site.cell_index) > self.draft.dimension:
                name += f" · N5={site.cell_index}"
            labels = (
                name,
                occupation_label(site.occupation(self.draft.geometry_host)),
                occupation_label(entry.occupation) if entry else "—",
                "Yes" if entry else "No",
            )
            for col, label in enumerate(labels):
                self.sites.setItem(row, col, QTableWidgetItem(label))
        self._selected_sites.intersection_update(self._site_rows)
        if self._site_rows:
            if not self._selected_sites:
                self._selected_sites = {self._selected_site if self._selected_site in self._site_rows
                                        else self._site_rows[0]}
            if self._selected_site not in self._selected_sites:
                self._selected_site = next(s for s in self._site_rows if s in self._selected_sites)
        else:
            self._selected_site = None
        self._restore_table_selection()
        self.sites.blockSignals(False)
        self._site_updating = False
        self._display_site(preserve_occupation=preserve_occupation)
        self._update_symmetry_preview()
        self._refresh_summary()

    def _restore_table_selection(self):
        selection = QItemSelection()
        model = self.sites.model()
        for row, site in enumerate(self._site_rows):
            if site in self._selected_sites:
                selection.select(model.index(row, 0), model.index(row, 3))
        self.sites.selectionModel().select(
            selection, QItemSelectionModel.SelectionFlag.ClearAndSelect
        )
        if self._selected_site in self._site_rows:
            self.sites.setCurrentCell(self._site_rows.index(self._selected_site), 0,
                                     QItemSelectionModel.SelectionFlag.NoUpdate)

    def _site_changed(self):
        if self._site_updating:
            return
        selected = {self._site_rows[index.row()]
                    for index in self.sites.selectionModel().selectedRows()}
        added = selected - self._selected_sites
        row = self.sites.currentRow()
        current = self._site_rows[row] if 0 <= row < len(self._site_rows) else None
        if current in added or (not added and current in selected):
            next_site = current
        elif added:
            next_site = next(s for s in self._site_rows if s in added)
        else:
            next_site = next((s for s in self._site_rows if s in selected), None)
        self._apply_pending_displacement()
        if selected != self._selected_sites and not self.occupation.is_valid():
            self.sites.blockSignals(True)
            self._restore_table_selection()
            self.sites.blockSignals(False)
            return
        if selected != self._selected_sites:
            self.undo_stack.end_edit()
        self._selected_sites, self._selected_site = selected, next_site
        self._occupation_overwrite_approval = None
        self._display_site()
        self._update_symmetry_preview()

    def _current_site_changed(self, row, _column, *_):
        if self._site_updating or not 0 <= row < len(self._site_rows):
            return
        site = self._site_rows[row]
        if site not in self._selected_sites or site == self._selected_site:
            return
        self._apply_pending_displacement()
        if not self.occupation.is_valid():
            self.sites.blockSignals(True)
            self._restore_table_selection()
            self.sites.blockSignals(False)
            return
        self.undo_stack.end_edit()
        self._selected_site = site
        self._display_site()
        self._schedule_local_render()

    def _display_site(self, *, preserve_occupation=False):
        site = self._selected_site
        self.occupation_group.setEnabled(site is not None)
        self.displacement_group.setEnabled(site is not None)
        self.centre_button.setEnabled(len(self._selected_sites) == 1)
        if site is None:
            self.occupation_info.show()
            self.displacement_info.show()
            self.occupation_info.setText("Select one or more sites")
            self.displacement_info.setText("Select one or more sites")
            return
        occupations = [self.draft.entries[s].occupation if s in self.draft.entries
                       else s.occupation(self.draft.geometry_host) for s in self._selected_sites]
        displacements = [
            self.draft.display_displacement(
                self.draft.entries[s].displacement if s in self.draft.entries
                else np.zeros(3)
            ) for s in self._selected_sites
        ]
        count = len(self._selected_sites)
        common = all(value == occupations[0] for value in occupations)
        self.occupation_info.setVisible(not common)
        self.occupation_info.setText(
            f"{count} selected site(s)" + ("" if common else
            f" · Different occupations; showing #{site.original_site + 1}. Edits apply to all.")
        )
        common = all(np.array_equal(value, displacements[0]) for value in displacements)
        self.displacement_info.setVisible(not common)
        self.displacement_info.setText(
            f"{count} selected site(s)" + ("" if common else
            f" · Different vectors; showing #{site.original_site + 1}. Edits apply to all.")
        )
        entry = self.draft.entries.get(site)
        if not preserve_occupation:
            self._occupation_edit_key = None
            self.occupation.set_occupation(
                entry.occupation if entry else site.occupation(self.draft.geometry_host)
            )
            # The host occupation is the original value even when starting
            # a brand-new embedded cluster. Restore handles every target's
            # own host occupation when several sites are selected.
            self.occupation.set_initial_occupation(site.occupation(self.draft.geometry_host))
        values = self.draft.display_displacement(
            entry.displacement if entry else (0, 0, 0)
        )
        for spin, value in zip(self.deltas, values):
            spin.blockSignals(True)
            spin.setValue(float(value))
            spin.blockSignals(False)

    def _targets(self):
        if not self._selected_sites:
            raise ValueError("Select one or more host sites first")
        return self.draft.targets(self._selected_sites, symmetric=self.symmetric.isChecked())

    def _symmetry_changed(self, *_):
        self._apply_pending_displacement()
        self.undo_stack.end_edit()
        self._occupation_overwrite_approval = None
        self._update_symmetry_preview()

    def _update_symmetry_preview(self, *_):
        self._highlighted.clear()
        try:
            self._highlighted.update(self.draft.equivalents(self._selected_sites))
            targets = self._highlighted if self.symmetric.isChecked() else self._selected_sites
        except (ValueError, IndexError) as exc:
            self.symmetry_info.setText(f"Symmetry unavailable: {exc}")
        else:
            self.symmetry_info.setText(
                f"{len(self._selected_sites)} selected · {len(self._highlighted)} symmetry-related · "
                f"{len(targets)} affected by actions"
            )
        self._refresh_cells()
        self._schedule_global_render()
        self._schedule_local_render()

    def _confirm_occupation_overwrite(self, occupations):
        # Editing the selected site is intentional. Only overwriting independent
        # modifications of *other* symmetry-equivalent sites needs approval.
        conflicts = []
        for site, occupation in occupations.items():
            if site in self._selected_sites:
                continue
            entry = self.draft.entries.get(site)
            if entry is None:
                continue
            if entry.occupation != occupation and self._is_modified(site):
                conflicts.append(site)
        if not conflicts:
            return True
        key = (frozenset(self._selected_sites), frozenset(occupations))
        if key == self._occupation_overwrite_approval:
            return True
        response = QMessageBox.question(
            self, "Replace previous edits?",
            f"{len(conflicts)} other site(s) already have a modification. "
            "Apply this occupation to them too?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if response == QMessageBox.StandardButton.Yes:
            self._occupation_overwrite_approval = key
            return True
        return False

    def _include(self):
        self._apply_pending_displacement()
        def action():
            targets = self._targets()
            self._record_edit("Include sites", lambda: self.draft.include(targets))
        self._guard(action)

    def _exclude(self):
        self._apply_pending_displacement()
        def action():
            targets = self._targets()
            self._record_edit("Exclude sites", lambda: self.draft.exclude(targets))
        self._guard(action)

    def _set_centre(self):
        self._apply_pending_displacement()
        def action():
            if len(self._selected_sites) != 1:
                raise ValueError("Select exactly one site for the symmetry centre")
            self._record_edit("Change centre", lambda: self.draft.set_center(self._selected_site))
        self._guard(action)

    def _occupation_edited(self):
        # Keystrokes during a mixed-occupation edit can have an incomplete
        # total. Keep them local, but never commit a partial physical state.
        if self._selected_site is not None:
            self._occupation_edit_key = self._edit_key("occupation")
            if self.occupation.is_valid():
                self._assign_occupation()
        self._update_history_actions()

    def _occupation_validity_changed(self, _valid):
        if self._has_occupation_buffer():
            self._occupation_edit_key = self._edit_key("occupation")
        self._update_history_actions()

    def _assign_occupation(self):
        self._apply_pending_displacement()
        def action():
            occupation = self.occupation.occupation()
            targets = self._targets()
            if all(
                site in self.draft.entries
                and self.draft.entries[site].occupation == occupation
                for site in targets
            ):
                return
            if not self._confirm_occupation_overwrite({site: occupation for site in targets}):
                # A rejected multi-site overwrite must not leave controls
                # displaying an occupation different from the model.
                self._display_site()
                return
            # Do not replace the live row controls while the user is typing.
            self._record_edit(
                "Edit occupation", lambda: self.draft.set_occupation(targets, occupation),
                edit_key=self._occupation_edit_key, preserve_occupation=True,
            )
        self._guard(action)

    def _restore_occupation(self):
        self._apply_pending_displacement()
        def action():
            targets = self._targets()
            occupations = {site: site.occupation(self.draft.geometry_host) for site in targets}
            if not self._confirm_occupation_overwrite(occupations):
                return
            self._record_edit("Restore occupations", lambda: self.draft.reset_occupation(targets))
        self._guard(action)

    def _schedule_displacement(self, *_):
        if self._selected_site is not None:
            self._pending_displacement = _PendingDisplacement(
                tuple(self._selected_sites), np.array([spin.value() for spin in self.deltas]),
                self.symmetric.isChecked(), self._edit_key("displacement"),
            )
            self._displacement_timer.start()
            self._update_history_actions()

    def _finish_displacement_edit(self):
        self._apply_pending_displacement()
        self.undo_stack.end_edit()

    def _apply_pending_displacement(self):
        if self._guard(self._commit_pending_displacement) is None:
            self._display_site()
            self._update_history_actions()

    def _commit_pending_displacement(self):
        self._displacement_timer.stop()
        pending, self._pending_displacement = self._pending_displacement, None
        if pending is not None:
            if not pending.symmetric and all(
                np.allclose(
                    self.draft.display_displacement(
                        self.draft.entries[site].displacement
                        if site in self.draft.entries else np.zeros(3)
                    ),
                    pending.vector, atol=1e-10, rtol=0,
                )
                for site in pending.sites
            ):
                self._update_history_actions()
                return True
            self._record_edit(
                "Edit displacement",
                lambda: self.draft.set_displacement(
                    pending.sites, pending.vector, symmetric=pending.symmetric,
                ),
                edit_key=pending.edit_key, preserve_occupation=True,
            )
        return True

    def _add_radius(self):
        self._apply_pending_displacement()
        self._guard(lambda: self._record_edit(
            "Expand by radius", lambda: self.draft.add_radius(self.radius.value()),
        ))

    def _add_shells(self):
        self._apply_pending_displacement()
        self._guard(lambda: self._record_edit(
            "Expand by shells", lambda: self.draft.add_shells(self.shells.value()),
        ))

    def _expansion_focus_changed(self, _old, widget):
        mode = None
        for name, controls in (("radius", (self.radius, self.add_radius_button)),
                               ("shells", (self.shells, self.add_shells_button))):
            if widget is not None and any(
                widget is control or control.isAncestorOf(widget) for control in controls
            ):
                mode = name
                break
        if mode == self._expansion_mode:
            return
        self._expansion_mode = mode
        self._expansion_key = None
        self._expansion_sites.clear()
        self.expansion_info.setVisible(mode is not None)
        self._expansion_timer.stop()
        if mode is not None:
            self.expansion_info.setText("Updating expansion preview…")
            self._schedule_expansion_preview()
        self._schedule_local_render()
        self._schedule_global_render()

    def _schedule_expansion_preview(self, *_):
        if self._expansion_mode is not None:
            self._expansion_timer.start()

    def _update_expansion_preview(self):
        """Preview exactly the expansion selection without creating entries.

        Geometry is cached while its mode, value and physical centre stay the
        same; edits to occupations or inclusion only change the displayed count.
        Preview errors stay inline instead of opening dialogs while typing.
        """
        if self._expansion_mode is None:
            return
        radius = self._expansion_mode == "radius"
        value = self.radius.value() if radius else self.shells.value()
        key = (self._expansion_mode, value, self.draft.center)
        try:
            if key != self._expansion_key:
                sites = (self.draft.sites_within_radius(value) if radius
                         else self.draft.sites_within_shells(value))
                self._expansion_sites = set(sites)
                self._expansion_key = key
        except (ValueError, TypeError, IndexError) as exc:
            self._expansion_sites.clear()
            self._expansion_key = None
            self.expansion_info.setText(f"Cannot preview expansion: {exc}")
        else:
            new = len(self._expansion_sites - self.draft.entries.keys())
            name = "Radius" if radius else "Coordination-shell"
            self.expansion_info.setText(
                f"{name} preview: {len(self._expansion_sites)} sites; "
                f"{new} new sites shown in green. Click Add to include them."
            )
        self._schedule_local_render()
        self._schedule_global_render()

    def _changed(self, *, preserve_occupation=False):
        self._refresh_sites(preserve_occupation=preserve_occupation)
        self._refresh_summary()
        self._schedule_global_render()
        self._schedule_local_render()
        self._schedule_expansion_preview()

    def _refresh_summary(self):
        center = self.draft.center
        self.centre_label.setText(
            f"<b>Cluster centre:</b> Host site #{center.original_site + 1} "
            f"in cell {center.cell_index}"
        )
        included = len(self.draft.entries)
        changed = sum(self._is_modified(site) for site in self.draft.entries)
        has_host_pot = hasattr(self.draft.host, "LATTICE")
        suffix = "" if has_host_pot else (
            "  •  No host POTFIL: cluster geometry can be built but native "
            "CLUPOT calculations require a host potential."
        )
        self.summary.setText(f"{included} cluster sites; {changed} modified{suffix}")

    def _schedule_global_render(self, *_):
        self._global_timer.start()

    def _schedule_local_render(self, *_):
        self._local_timer.start()

    def _render(self):
        """Render both views synchronously (also useful for GUI regression tests)."""
        self._render_local()
        self._render_global()

    def _site_style(self, site, *, local=False):
        if self._is_modified(site):
            color, size = "#d88c49", 65
        elif site in self.draft.entries:
            color, size = "#4b92cf", 55
        elif site in self._expansion_sites:
            color, size = "#69b88e", 45 if local else 30
        else:
            color, size = "#a6aeb6", 23 if local else 12
        if site in self._selected_sites:
            return color, max(size, 72), SELECTED_COLOR, 2.4
        if site in self._highlighted:
            ring = (SYMMETRY_APPLY_COLOR if self.symmetric.isChecked()
                    else SYMMETRY_PREVIEW_COLOR)
            return color, max(size, 30), ring, 1.8
        if site in self._expansion_sites and site not in self.draft.entries:
            # Keep pending additions visible through the surrounding host,
            # using the preview widget's foreground outline layer.
            return color, size, "#329466", 1.6
        return color, size, "#515961", .4

    def _selected_cell_corners(self):
        """Reference cell outline, with no leads or vacuum in the 2D detail."""
        origin, cell = embedding_cell(self.draft.geometry_host)
        atoms = getattr(self.draft.geometry_host, "atoms", self.draft.geometry_host)
        shift = np.asarray(self._selected_cell) @ np.asarray(atoms.cell)[:self.draft.dimension]
        return corner_indices.T @ cell + origin + shift

    def _draw_sites(self, preview, sites, *, detail=False):
        points, colors, sizes, outlines, widths = [], [], [], [], []
        host = self.draft.geometry_host
        atoms = getattr(host, 'atoms', host)
        potential = host if hasattr(host, 'SCF_INFO') else None
        factors = marker_areas(atoms, 1.0, potential=potential)
        for site in sites:
            entry = self.draft.entries.get(site)
            displacement = (
                self.draft.display_displacement(entry.displacement)
                if entry is not None else 0
            )
            points.append(site.position(self.draft.geometry_host) + displacement)
            color, size, outline, width = self._site_style(site, local=detail)
            colors.append(color)
            sizes.append(size * factors[site.original_site])
            outlines.append(outline)
            widths.append(width)
        # Fade host context, not cluster atoms or editing highlights.
        bulk_mask = None if detail else [
            site not in self.draft.entries
            and site != self._selected_site
            and site not in self._selected_sites
            and site not in self._highlighted
            and site not in self._expansion_sites
            for site in sites
        ]
        preview.set_points(
            points, colors, sizes, cell_corners=self._selected_cell_corners(),
            labels=[f"#{site.original_site + 1}" for site in sites] if detail else (),
            label_index=(sites.index(self._selected_site)
                         if detail and self._selected_site in sites else None),
            outlines=outlines, widths=widths, bulk_mask=bulk_mask,
        )

    def _host_context_sites(self, *, allowed_only=False):
        """Finite viewport of the infinite host, independent of cluster size.

        The in-plane cell grid controls how many periodic replicas are shown.
        For a bulk host we show a bounded stack of translated cells as well.
        Native 2D lead sites are visible in the whole-structure view but are
        excluded from the transition-region view and the editable cell.
        """
        host_atoms = getattr(self.draft.geometry_host, "atoms", self.draft.geometry_host)
        indices = (
            sorted(self.draft.allowed) if allowed_only
            else range(len(host_atoms))
        )
        return tuple(HostSite(i, cell) for cell in self._visible_cells(whole=True) for i in indices)

    def _render_local(self):
        """Detail and site table always refer to the same selected cell.

        In 2D this is the complete transition region of one in-plane cell,
        including every atomic height, without semi-infinite lead sites.
        """
        self._local_sites = list(self.draft.cell_sites(self._selected_cell))
        self._draw_sites(self.local_preview, self._local_sites, detail=True)
        region = "Transition region" if self.draft.dimension == 2 else "Host cell"
        self.local_info.setText(
            f"{region} {self._selected_cell} · {len(self._local_sites)} sites"
        )

    def _render_global(self):
        """Show complete displayed host context and every cluster site."""
        host_context = set(self._host_context_sites())
        overlay = set(self.draft.entries) | self._highlighted | self._expansion_sites
        if self._selected_site is not None:
            overlay.add(self._selected_site)
        if self.global_scope.currentData() == "layer":
            if self.draft.dimension == 2:
                # Keep every height of the transition region across cells,
                # excluding semi-infinite lead sites from this context view.
                host_context = set(
                    self._host_context_sites(allowed_only=True)
                )
            else:
                fixed = self._fixed_axis()
                host_context = {
                    site for site in host_context
                    if site.cell_index[fixed] == self.layer.value()
                }
                overlay = {
                    site for site in overlay
                    if site.cell_index[fixed] == self.layer.value()
                }
        # A symmetry orbit can extend beyond the navigation box (especially
        # for a sheared 2D basis). Show host surroundings there too, rather
        # than drawing isolated highlighted atoms outside the finite host.
        context_cells = {site.cell_index for site in host_context}
        missing = {site.cell_index for site in overlay} - context_cells
        axes = self._plane_axes()
        extra_cells = set()
        for cell in missing:
            for x, y in product((-1, 0, 1), repeat=2):
                neighbour = list(cell)
                neighbour[axes[0]] += x
                neighbour[axes[1]] += y
                extra_cells.add(tuple(neighbour))
        atoms = getattr(self.draft.geometry_host, "atoms", self.draft.geometry_host)
        indices = (sorted(self.draft.allowed)
                   if self.draft.dimension == 2 and self.global_scope.currentData() == "layer"
                   else range(len(atoms)))
        host_context.update(HostSite(i, cell) for cell in extra_cells for i in indices)
        if self.draft.dimension == 2 and missing:
            regular_cells = {site.cell_index for site in host_context if len(site.cell_index) == 2}
            host_context.update(HostSite(i, cell)
                                for cell in fill_cell_hull(regular_cells) for i in indices)
        self._rendered_host_sites = host_context
        self._rendered_sites = sorted(host_context | overlay)
        self._draw_sites(self.global_preview, self._rendered_sites)
        included_shown = sum(
            site in self.draft.entries for site in self._rendered_sites
        )
        self.preview_info.setText(
            f"Host: {len(host_context)} · "
            f"Cluster: {included_shown}/{len(self.draft.entries)} · "
            f"Symmetry: {len(self._highlighted)} · "
            f"Displayed: {len(self._rendered_sites)}"
        )

    def _select_local_site(self, index):
        """Apply a preview selection through the same controls as the table."""
        if not 0 <= index < len(self._local_sites):
            return
        site = self._local_sites[index]
        if site.original_site not in self.draft.allowed:
            return
        if (
            site != self._selected_site
            and self._selected_site is not None
            and not self.occupation.is_valid()
        ):
            return
        self._apply_pending_displacement()
        self.undo_stack.end_edit()
        self._selected_site = site
        self._selected_sites = {site}
        self._occupation_overwrite_approval = None
        self._refresh_sites()

    def _accept(self):
        self._applied = False
        self._apply_pending_displacement()
        def action():
            if self._selected_site is not None and not self.occupation.is_valid():
                raise ValueError(
                    "Finish or restore the incomplete occupation before accepting."
                )
            radial_reset = self.draft.would_discard_radial_data()
            if radial_reset:
                choice = QMessageBox.warning(
                    self, "Existing Radial Data",
                    "The edited cluster cannot reuse a complete set of "
                    "compatible radial potentials, charges and moments as its "
                    "initial density. Native CLUPOT requires all radial data "
                    "for an ITERATING restart; this edit will instead create "
                    "a START structure without the incomplete data. "
                    "The original cluster will not be modified. Continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if choice != QMessageBox.StandardButton.Yes:
                    return
            self.result_atoms = (
                self.draft.original_cluster
                if self.draft.is_unchanged()
                else self.draft.to_atoms(allow_radial_reset=radial_reset)
            )
            self._applied = True
            if not self._embedded:
                self.accept()
        self._guard(action)

    def has_unapplied_changes(self) -> bool:
        """Include both changed cluster data and unfinished input controls."""
        return (
            not self.draft.is_unchanged()
            or self._pending_displacement is not None
            or bool(self._unfinished_numbers())
            or (self._selected_site is not None and self._has_occupation_buffer())
        )

    def finalize_embedded(self) -> bool:
        """Validate and export the draft only at the outer Apply Structure."""
        if not self._embedded:
            raise RuntimeError("finalize_embedded is for inline editors")
        if (self._unfinished_numbers()
                or (self._selected_site is not None
                    and self._has_occupation_buffer())):
            QMessageBox.warning(
                self, "Incomplete Cluster Edit",
                "Finish or restore incomplete site occupations and displacements "
                "before applying the structure.",
            )
            return False
        self._accept()
        return self._applied

    def closeEvent(self, event):
        # This editor installs application-wide listeners; an inline tab can
        # be replaced several times in a single structure editing session.
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
            for slot in (self._expansion_focus_changed, self._editing_focus_changed):
                try:
                    app.focusChanged.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        super().closeEvent(event)


def select_build_embedding_structure(atoms, parent: QWidget | None = None):
    """Return new embedded atoms, or None if editing was cancelled."""
    dialog = BuildEmbeddingDialog(atoms, parent)
    return dialog.result_atoms if dialog.exec() == QDialog.DialogCode.Accepted else None
