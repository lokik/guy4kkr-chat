"""General application settings: visualization and SPR-KKR defaults."""
from __future__ import annotations

from math import log

from PyQt6.QtCore import Qt

from ase import Atoms
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QHBoxLayout,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.application.settings import ApplicationSettings
from ase2sprkkr_gui.gui.application.viewers import viewer_unavailability
from ase2sprkkr_gui.gui.plots.atom_sizes import (
    AtomAppearance, MAX_ATOM_SIZE_PERCENT, MIN_ATOM_SIZE_PERCENT, marker_areas,
)


_DATASET_MODE_LABELS = (
    ("empty", "Leave unset (ase2sprkkr automatic)"),
    ("datetime", "Structure + date/time"),
    ("uuid", "Structure + UUID"),
)


def available_viewers() -> tuple[str, ...]:
    """Return viewer names understood by ASE."""
    from ase.visualize.viewers import VIEWERS

    return tuple(sorted(str(name) for name in VIEWERS))



# Symmetric logarithmic endpoints (5% and 2000%) around 100%.
# Numeric editing preserves exact saved percentages between slider ticks.
_LOG_ATOM_SIZE_RANGE = log(MAX_ATOM_SIZE_PERCENT / 100)


def atom_size_from_slider(position: int) -> int:
    """Map [-100, 100] to radius percentages [5, 2000]."""
    return round(100 * (MAX_ATOM_SIZE_PERCENT / 100) ** (position / 100))


def slider_from_atom_size(percent: int) -> int:
    """Approximate the position of a saved/entered radius percentage."""
    return round(100 * log(max(MIN_ATOM_SIZE_PERCENT, min(
        MAX_ATOM_SIZE_PERCENT, percent
    )) / 100) / _LOG_ATOM_SIZE_RANGE)


class _AtomSizeExample(QWidget):
    """Use the identical Matplotlib marker areas as the Guided structure preview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Illustrative C/Au pair, at the BCC Fe reference's nearest-neighbour
        # distance (~2.49 Å for a = 2.87 Å), rounded to 2.5 Å here.
        # These are real Å coordinates, not a claim about a C–Au crystal.
        self._atoms = Atoms("CAu", positions=[(0, 0, 0), (2.5, 0, 0)])
        self.distance_angstrom = self._atoms.get_distance(0, 1)
        self.figure = Figure(figsize=(3.0, 2.2))
        self.canvas = FigureCanvasQTAgg(self.figure)
        # Slightly taller, but compact enough to sit beside the radius options.
        self.canvas.setFixedSize(285, 215)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.axes = self.figure.add_axes((0, 0, 1, 1))
        self.axes.set_axis_off()
        self.markers = None
        self.set_values(100, True)

    def set_values(self, percent: int, relative: bool) -> None:
        # 48 points squared matches the Guided/EmbeddingPreview base area.
        areas = marker_areas(
            self._atoms, 48.0,
            appearance=AtomAppearance(
                size_percent=percent, relative_sizes=relative,
                potential_radii=False,
            ),
        )
        self.axes.clear()
        # Use an Å-scaled view spanning three interatomic distances:
        # the atoms occupy one third of the 285 px canvas (~95 px apart).
        d = self.distance_angstrom
        self.axes.set_xlim(-d, 2 * d)
        self.axes.set_ylim(0, 1)
        self.axes.set_axis_off()
        self.markers = self.axes.scatter(
            self._atoms.positions[:, 0], [0.5, 0.5], s=areas,
            c=["#55595d", "#d8ab36"], edgecolors="#333a42",
            linewidths=0.65,
        )
        self.canvas.draw_idle()


class GeneralSettingsPage(QFrame):
    """Common application options grouped on one settings tab."""

    def __init__(
        self, settings: ApplicationSettings, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.visualization_group = QGroupBox("Visualization", self)
        visualization_form = QFormLayout(self.visualization_group)
        self.viewer = QComboBox(self.visualization_group)
        viewers = available_viewers()
        self.viewer.addItems(viewers)
        if settings.viewer not in viewers:
            self.viewer.addItem(settings.viewer)
        self.viewer.setCurrentText(settings.viewer)
        self.viewer.setToolTip("Viewer launched by the external visualization action")
        for index in range(self.viewer.count()):
            name = self.viewer.itemText(index)
            reason = viewer_unavailability(name)
            if reason:
                self.viewer.setItemData(
                    index, QColor("#cc3333"), Qt.ItemDataRole.ForegroundRole
                )
                self.viewer.setItemData(
                    index, reason, Qt.ItemDataRole.ToolTipRole
                )
        visualization_form.addRow("External structure viewer:", self.viewer)
        self.viewer_warning = QLabel(self.visualization_group)
        self.viewer_warning.setWordWrap(True)
        self.viewer_warning.setStyleSheet("color: #cc3333;")
        visualization_form.addRow("", self.viewer_warning)
        self.viewer.currentTextChanged.connect(self._update_viewer_warning)
        self._update_viewer_warning()
        layout.addWidget(self.visualization_group)

        self.atom_appearance_group = QGroupBox("Atom appearance", self)
        atom_form = QFormLayout(self.atom_appearance_group)
        size_row = QWidget(self.atom_appearance_group)
        size_layout = QHBoxLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        self.atom_size_slider = QSlider(Qt.Orientation.Horizontal, size_row)
        self.atom_size_slider.setRange(-100, 100)
        self.atom_size_slider.setSingleStep(1)
        self.atom_size_slider.setPageStep(10)
        self.atom_size_slider.setToolTip(
            "Logarithmic atom-radius scale: 5% to 2000%, 100% at the center."
        )
        self.atom_size_slider.setValue(
            slider_from_atom_size(settings.atom_size_percent)
        )
        self.atom_size_percent = QSpinBox(size_row)
        self.atom_size_percent.setRange(
            MIN_ATOM_SIZE_PERCENT, MAX_ATOM_SIZE_PERCENT
        )
        self.atom_size_percent.setSuffix("%")
        self.atom_size_percent.setValue(settings.atom_size_percent)
        self.atom_size_percent.setToolTip(
            "Exact atom-radius scale, applied to all internal structure previews."
        )
        size_layout.addWidget(self.atom_size_slider, 1)
        size_layout.addWidget(self.atom_size_percent)
        atom_form.addRow("Atom size:", size_row)
        example_row = QWidget(self.atom_appearance_group)
        example_row_layout = QHBoxLayout(example_row)
        example_row_layout.setContentsMargins(0, 0, 0, 0)
        example_row_layout.setSpacing(20)
        radius_options = QVBoxLayout()
        radius_options.setSpacing(12)
        self.atom_relative_sizes = QCheckBox(
            "Use element-dependent Wigner–Seitz radii", example_row
        )
        self.atom_relative_sizes.setChecked(settings.atom_relative_sizes)
        radius_options.addWidget(self.atom_relative_sizes)
        self.atom_potential_radii = QCheckBox(
            "Use potential radii when available", example_row
        )
        self.atom_potential_radii.setToolTip(
            "Only use RWS from an ITERATING or CONVERGED potential. "
            "START or invalid radii fall back to static values."
        )
        self.atom_potential_radii.setChecked(settings.atom_potential_radii)
        self.atom_potential_radii.setEnabled(self.atom_relative_sizes.isChecked())
        radius_options.addWidget(self.atom_potential_radii)
        radius_options.addStretch(1)
        example_row_layout.addLayout(radius_options)
        self.atom_relative_sizes.toggled.connect(
            self.atom_potential_radii.setEnabled
        )

        example_column = QWidget(example_row)
        example_column_layout = QVBoxLayout(example_column)
        example_column_layout.setContentsMargins(0, 0, 0, 0)
        example_column_layout.setSpacing(3)
        self.atom_size_example = _AtomSizeExample(example_column)
        example_column_layout.addWidget(self.atom_size_example)
        self.atom_example_caption = QLabel(
            f"Example (C / Au) · distance {self.atom_size_example.distance_angstrom:.1f} Å",
            example_column,
        )
        self.atom_example_caption.setToolTip(
            "Illustrative centre-to-centre separation, comparable to the BCC Fe "
            "nearest-neighbour distance for a = 2.87 Å."
        )
        self.atom_example_caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        example_column_layout.addWidget(self.atom_example_caption)
        example_row_layout.addWidget(example_column)
        example_row_layout.addStretch(1)
        atom_form.addRow("", example_row)
        self.atom_size_slider.valueChanged.connect(self._size_slider_changed)
        self.atom_size_percent.valueChanged.connect(self._size_percent_changed)
        self.atom_relative_sizes.toggled.connect(self._update_atom_preview)
        self._update_atom_preview()
        layout.addWidget(self.atom_appearance_group)

        self.sprkkr_group = QGroupBox("SPR-KKR", self)
        sprkkr_form = QFormLayout(self.sprkkr_group)
        self.dataset_default_mode = QComboBox(self.sprkkr_group)
        for value, label in _DATASET_MODE_LABELS:
            self.dataset_default_mode.addItem(label, value)
        index = self.dataset_default_mode.findData(settings.dataset_default_mode)
        self.dataset_default_mode.setCurrentIndex(max(index, 0))
        self.dataset_default_mode.setToolTip(
            "Default DATASET for newly created calculations. An explicit value "
            "entered in the calculation editor always takes precedence."
        )
        sprkkr_form.addRow("Default DATASET:", self.dataset_default_mode)
        layout.addWidget(self.sprkkr_group)

        self.python_shell_group = QGroupBox("Python shell", self)
        shell_form = QFormLayout(self.python_shell_group)
        self.share_python_shell_history = QCheckBox(
            "Share command history with regular Python",
            self.python_shell_group,
        )
        self.share_python_shell_history.setChecked(
            settings.share_python_shell_history
        )
        self.share_python_shell_history.setToolTip(
            "ase2sprkkr always saves its own command history. When enabled, "
            "also load the ordinary Python REPL history and append new "
            "Ase2sprkkr commands to it."
        )
        shell_form.addRow(self.share_python_shell_history)
        layout.addWidget(self.python_shell_group)

        self.guided_group = QGroupBox("Guided workflow", self)
        guided_form = QFormLayout(self.guided_group)
        self.show_embedded_cluster_hint = QCheckBox(
            "Offer Create Embedded Cluster when no structure is loaded",
            self.guided_group,
        )
        self.show_embedded_cluster_hint.setChecked(
            settings.show_embedded_cluster_hint
        )
        self.show_embedded_cluster_hint.setToolTip(
            "Show an introductory action explaining that a periodic host "
            "is required before creating an embedded cluster."
        )
        guided_form.addRow(self.show_embedded_cluster_hint)
        layout.addWidget(self.guided_group)
        layout.addStretch(1)

    def _size_slider_changed(self, position: int) -> None:
        self.atom_size_percent.blockSignals(True)
        self.atom_size_percent.setValue(atom_size_from_slider(position))
        self.atom_size_percent.blockSignals(False)
        self._update_atom_preview()

    def _size_percent_changed(self, percent: int) -> None:
        self.atom_size_slider.blockSignals(True)
        self.atom_size_slider.setValue(slider_from_atom_size(percent))
        self.atom_size_slider.blockSignals(False)
        self._update_atom_preview()

    def _update_atom_preview(self, *_args) -> None:
        self.atom_size_example.set_values(
            self.atom_size_percent.value(), self.atom_relative_sizes.isChecked()
        )

    def selected_viewer_unavailability(self) -> str | None:
        """Return the availability warning for the selected viewer."""
        return viewer_unavailability(self.viewer.currentText())

    def _update_viewer_warning(self) -> None:
        reason = self.selected_viewer_unavailability()
        self.viewer_warning.setText(
            f"Viewer is not available: {reason}" if reason else ""
        )
        self.viewer_warning.setVisible(bool(reason))
