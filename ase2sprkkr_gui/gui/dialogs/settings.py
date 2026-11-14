"""Application settings dialog composing independent tab pages."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.application.execution_profiles import ExecutionProfileStore
from ase2sprkkr_gui.gui.application.settings import ApplicationSettings
from ase2sprkkr_gui.gui.widgets.settings.run_configurations import RunConfigurationsPage
from ase2sprkkr_gui.gui.widgets.settings.general import GeneralSettingsPage


class SettingsDialog(QDialog):
    """Edit application-wide preferences and persistent execution profiles."""

    def __init__(
        self,
        settings: ApplicationSettings,
        parent: QWidget | None = None,
        *,
        profile_store: ExecutionProfileStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(1050, 700)
        self._settings = settings

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)

        self.general_page = GeneralSettingsPage(settings, self.tabs)
        self.run_configurations_page = RunConfigurationsPage(
            self.tabs, store=profile_store
        )
        self.tabs.addTab(self.general_page, "General")
        self.tabs.addTab(self.run_configurations_page, "Run configurations")

        self.viewer = self.general_page.viewer
        self.viewer_warning = self.general_page.viewer_warning
        self.dataset_default_mode = self.general_page.dataset_default_mode
        self.share_python_shell_history = (
            self.general_page.share_python_shell_history
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:  # type: ignore[override]
        reason = self.general_page.selected_viewer_unavailability()
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
        previous_share_history = self._settings.share_python_shell_history
        self._settings.viewer = self.viewer.currentText()
        self._settings.dataset_default_mode = str(
            self.dataset_default_mode.currentData()
        )
        self._settings.share_python_shell_history = (
            self.share_python_shell_history.isChecked()
        )
        if not self._settings.save():
            self._settings.viewer = previous_viewer
            self._settings.dataset_default_mode = previous_dataset_mode
            self._settings.share_python_shell_history = previous_share_history
            QMessageBox.critical(
                self,
                "Cannot Save Settings",
                f"Could not write settings to:\n{self._settings.path}",
            )
            return
        try:
            self.run_configurations_page.save()
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "Cannot Save Run Configurations", str(exc))
            return
        super().accept()


def edit_settings(
    settings: ApplicationSettings,
    parent: QWidget | None = None,
) -> bool:
    """Open the application settings dialog."""
    dialog = SettingsDialog(settings, parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
