"""General application settings: visualization and SPR-KKR defaults."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.viewers import viewer_unavailability


_DATASET_MODE_LABELS = (
    ("empty", "Leave unset (ASE2SPRKKR automatic)"),
    ("datetime", "Structure + date/time"),
    ("uuid", "Structure + UUID"),
)


def available_viewers() -> tuple[str, ...]:
    """Return viewer names understood by ASE."""
    from ase.visualize.viewers import VIEWERS

    return tuple(sorted(str(name) for name in VIEWERS))


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
        self.viewer.setToolTip("ASE viewer used for atomic structures")
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
        visualization_form.addRow("Structure viewer:", self.viewer)
        self.viewer_warning = QLabel(self.visualization_group)
        self.viewer_warning.setWordWrap(True)
        self.viewer_warning.setStyleSheet("color: #cc3333;")
        visualization_form.addRow("", self.viewer_warning)
        self.viewer.currentTextChanged.connect(self._update_viewer_warning)
        self._update_viewer_warning()
        layout.addWidget(self.visualization_group)

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
        layout.addStretch(1)

    def selected_viewer_unavailability(self) -> str | None:
        """Return the availability warning for the selected viewer."""
        return viewer_unavailability(self.viewer.currentText())

    def _update_viewer_warning(self) -> None:
        reason = self.selected_viewer_unavailability()
        self.viewer_warning.setText(
            f"Viewer is not available: {reason}" if reason else ""
        )
        self.viewer_warning.setVisible(bool(reason))
