"""Application settings dialog composing independent tab pages."""
from __future__ import annotations

from typing import Any

from ruamel.yaml.error import YAMLError

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
from ase2sprkkr_gui.gui.input_parameters.task_preferences import default_preferred_task_names
from ase2sprkkr_gui.gui.widgets.settings.preferred_tasks import PreferredTasksPage
from ase2sprkkr_gui.gui.widgets.settings.run_configurations import RunConfigurationsPage
from ase2sprkkr_gui.gui.widgets.settings.general import GeneralSettingsPage
from ase2sprkkr_gui.gui.widgets.settings.ase2sprkkr import Ase2sprkkrSettingsPage


class SettingsDialog(QDialog):
    """Edit application-wide preferences and persistent execution profiles."""

    def __init__(
        self,
        settings: ApplicationSettings,
        parent: QWidget | None = None,
        *,
        profile_store: ExecutionProfileStore | None = None,
        ase_configuration: Any | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(1050, 700)
        self._settings = settings

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)

        self.general_page = GeneralSettingsPage(settings, self.tabs)
        if profile_store is None:
            profile_store = ExecutionProfileStore(ase_configuration)
        self.run_configurations_page = RunConfigurationsPage(
            self.tabs, store=profile_store
        )
        self.tabs.addTab(self.general_page, "General")
        self.preferred_tasks_page = PreferredTasksPage(settings, self.tabs)
        self.tabs.addTab(self.preferred_tasks_page, "Preferred tasks")
        self.tabs.addTab(self.run_configurations_page, "Run configurations")
        configuration = (
            ase_configuration if ase_configuration is not None
            else profile_store.configuration if isinstance(
                profile_store, ExecutionProfileStore
            ) else None
        )
        self.ase2sprkkr_page = Ase2sprkkrSettingsPage(
            self.tabs, configuration=configuration
        )
        self.tabs.addTab(self.ase2sprkkr_page, "Ase2sprkkr")

        self.viewer = self.general_page.viewer
        self.atom_size_slider = self.general_page.atom_size_slider
        self.atom_size_percent = self.general_page.atom_size_percent
        self.atom_relative_sizes = self.general_page.atom_relative_sizes
        self.atom_potential_radii = self.general_page.atom_potential_radii
        self.viewer_warning = self.general_page.viewer_warning
        self.dataset_default_mode = self.general_page.dataset_default_mode
        self.share_python_shell_history = (
            self.general_page.share_python_shell_history
        )
        self.show_embedded_cluster_hint = self.general_page.show_embedded_cluster_hint

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.about_button = buttons.addButton(
            "About…", QDialogButtonBox.ButtonRole.HelpRole
        )
        self.about_button.setObjectName("settingsAboutButton")
        self.about_button.clicked.connect(self._show_about)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _show_about(self) -> None:
        """A small informational action, without adding a global menu bar."""
        QMessageBox.about(
            self,
            "About Ase2sprkkr",
            "Ase2sprkkr\n\n"
            "A graphical interface for creating, loading and editing atomic "
            "structures and preparing SPR-KKR calculations, built on ASE.",
        )

    def accept(self) -> None:  # type: ignore[override]
        try:
            self.ase2sprkkr_page.changes()  # Validate before writing settings.
        except ValueError as exc:
            QMessageBox.critical(self, "Invalid ase2sprkkr configuration", str(exc))
            return
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
        previous_appearance = (
            self._settings.atom_size_percent,
            self._settings.atom_relative_sizes,
            self._settings.atom_potential_radii,
        )
        previous_viewer = self._settings.viewer
        previous_dataset_mode = self._settings.dataset_default_mode
        previous_share_history = self._settings.share_python_shell_history
        previous_hint = self._settings.show_embedded_cluster_hint
        previous_preferred = self._settings.preferred_tasks
        previous_supported = self._settings.preferred_supported_snapshot
        self._settings.viewer = self.viewer.currentText()
        self._settings.atom_size_percent = self.atom_size_percent.value()
        self._settings.atom_relative_sizes = self.atom_relative_sizes.isChecked()
        self._settings.atom_potential_radii = self.atom_potential_radii.isChecked()
        self._settings.dataset_default_mode = str(
            self.dataset_default_mode.currentData()
        )
        self._settings.share_python_shell_history = (
            self.share_python_shell_history.isChecked()
        )
        self._settings.show_embedded_cluster_hint = (
            self.show_embedded_cluster_hint.isChecked()
        )
        selection = self.preferred_tasks_page.preference_override()
        self._settings.preferred_tasks = selection
        self._settings.preferred_supported_snapshot = (
            default_preferred_task_names() if selection is not None else None
        )
        if not self._settings.save():
            self._settings.viewer = previous_viewer
            (
                self._settings.atom_size_percent,
                self._settings.atom_relative_sizes,
                self._settings.atom_potential_radii,
            ) = previous_appearance
            self._settings.dataset_default_mode = previous_dataset_mode
            self._settings.share_python_shell_history = previous_share_history
            self._settings.show_embedded_cluster_hint = previous_hint
            self._settings.preferred_tasks = previous_preferred
            self._settings.preferred_supported_snapshot = previous_supported
            QMessageBox.critical(
                self,
                "Cannot Save Settings",
                f"Could not write settings to:\n{self._settings.path}",
            )
            return
        try:
            self.run_configurations_page.save()
        except (OSError, TypeError, ValueError, YAMLError) as exc:
            QMessageBox.critical(self, "Cannot Save Run Configurations", str(exc))
            return
        try:
            self.ase2sprkkr_page.save()
        except (OSError, TypeError, ValueError, YAMLError) as exc:
            QMessageBox.critical(self, "Cannot save ase2sprkkr configuration", str(exc))
            return
        super().accept()


def edit_settings(
    settings: ApplicationSettings,
    parent: QWidget | None = None,
    *, initial_tab: str | None = None,
) -> bool:
    """Open application settings, optionally with a requested tab selected."""
    dialog = SettingsDialog(settings, parent)
    if initial_tab is not None:
        for index in range(dialog.tabs.count()):
            if dialog.tabs.tabText(index) == initial_tab:
                dialog.tabs.setCurrentIndex(index)
                break
    return dialog.exec() == QDialog.DialogCode.Accepted
