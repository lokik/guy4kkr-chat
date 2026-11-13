"""Application settings dialog."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.viewers import viewer_unavailability


def available_viewers() -> tuple[str, ...]:
    """Return viewer names understood by ASE."""
    from ase.visualize.viewers import VIEWERS

    return tuple(sorted(str(name) for name in VIEWERS))


_DATASET_MODE_LABELS = (
    ("empty", "Leave unset (ASE2SPRKKR automatic)"),
    ("datetime", "Structure + date/time"),
    ("uuid", "Structure + UUID"),
)


class SettingsDialog(QDialog):
    """Edit application-wide preferences."""

    def __init__(
        self,
        settings: ApplicationSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._settings = settings

        layout = QVBoxLayout(self)
        visualization = QGroupBox("Visualization", self)
        form = QFormLayout(visualization)

        self.viewer = QComboBox(visualization)
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
        form.addRow("Structure viewer:", self.viewer)
        self.viewer_warning = QLabel(visualization)
        self.viewer_warning.setWordWrap(True)
        self.viewer_warning.setStyleSheet("color: #cc3333;")
        form.addRow("", self.viewer_warning)
        self.viewer.currentTextChanged.connect(self._update_viewer_warning)
        self._update_viewer_warning()
        layout.addWidget(visualization)

        sprkkr = QGroupBox("SPR-KKR", self)
        sprkkr_form = QFormLayout(sprkkr)
        self.dataset_default_mode = QComboBox(sprkkr)
        for value, label in _DATASET_MODE_LABELS:
            self.dataset_default_mode.addItem(label, value)
        index = self.dataset_default_mode.findData(settings.dataset_default_mode)
        self.dataset_default_mode.setCurrentIndex(max(index, 0))
        self.dataset_default_mode.setToolTip(
            "Default DATASET for newly created calculations. An explicit value "
            "entered in the calculation editor always takes precedence."
        )
        sprkkr_form.addRow("Default DATASET:", self.dataset_default_mode)
        layout.addWidget(sprkkr)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_viewer_warning(self) -> None:
        reason = viewer_unavailability(self.viewer.currentText())
        self.viewer_warning.setText(
            f"Viewer is not available: {reason}" if reason else ""
        )
        self.viewer_warning.setVisible(bool(reason))

    def accept(self) -> None:  # type: ignore[override]
        reason = viewer_unavailability(self.viewer.currentText())
        if reason:
            answer = QMessageBox.warning(
                self,
                "Viewer Not Available",
                f"{reason}\n\nThe selected viewer may not work. "
                "Choose another viewer or install it first. "
                "Save this viewer anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        previous_viewer = self._settings.viewer
        previous_dataset_mode = self._settings.dataset_default_mode
        self._settings.viewer = self.viewer.currentText()
        self._settings.dataset_default_mode = str(
            self.dataset_default_mode.currentData()
        )
        if not self._settings.save():
            self._settings.viewer = previous_viewer
            self._settings.dataset_default_mode = previous_dataset_mode
            QMessageBox.critical(
                self,
                "Cannot Save Settings",
                f"Could not write settings to:\n{self._settings.path}",
            )
            return
        super().accept()


def edit_settings(
    settings: ApplicationSettings,
    parent: QWidget | None = None,
) -> bool:
    """Open the application settings dialog."""
    dialog = SettingsDialog(settings, parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
