"""Viewer availability, settings warnings, and visualisation fallback."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QMessageBox

from guy4ase.gui.application import viewers
from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.dialogs import settings as settings_dialog
from guy4ase.gui.flows import visualization
from guy4ase.gui.widgets.settings import general as general_settings


def _app():
    return QApplication.instance() or QApplication([])


def _controller():
    return SimpleNamespace(atoms=Atoms("Fe", positions=[(0, 0, 0)]))


def test_viewer_availability_uses_registered_ase_cli_command(monkeypatch):
    monkeypatch.setitem(
        viewers.VIEWERS, "missing_executable_test",
        SimpleNamespace(argv=["missing_viewer_executable_test"]),
    )
    monkeypatch.setattr(viewers, "which", lambda executable: None)
    reason = viewers.viewer_unavailability("missing_executable_test")
    assert "missing_viewer_executable_test" in reason
    assert "PATH" in reason

    monkeypatch.setattr(
        viewers, "which", lambda executable: "/usr/bin/missing_viewer_executable_test"
    )
    assert viewers.viewer_unavailability("missing_executable_test") is None


def test_unknown_and_builtin_viewer_availability():
    assert viewers.viewer_unavailability("ase") is None
    assert "not registered" in viewers.viewer_unavailability(
        "this_ase_viewer_does_not_exist"
    )


def test_settings_show_unavailable_viewers_in_red_and_warn_on_selection(
    monkeypatch, tmp_path
):
    app = _app()
    monkeypatch.setattr(
        general_settings, "available_viewers", lambda: ("ase", "missing_test")
    )
    monkeypatch.setattr(
        general_settings,
        "viewer_unavailability",
        lambda name: "Executable missing_test not found" if name == "missing_test" else None,
    )
    settings = ApplicationSettings(tmp_path / "settings.json")
    dialog = settings_dialog.SettingsDialog(settings)
    index = dialog.viewer.findText("missing_test")
    assert index >= 0
    assert dialog.viewer.itemData(index, Qt.ItemDataRole.ForegroundRole) == QColor(
        "#cc3333"
    )
    assert "Executable missing_test" in dialog.viewer.itemData(
        index, Qt.ItemDataRole.ToolTipRole
    )

    dialog.viewer.setCurrentText("missing_test")
    assert "not found" in dialog.viewer_warning.text()
    dialog.viewer.setCurrentText("ase")
    assert dialog.viewer_warning.text() == ""
    dialog.reject()


def test_settings_require_confirmation_for_unavailable_viewer(monkeypatch, tmp_path):
    app = _app()
    monkeypatch.setattr(
        general_settings, "available_viewers", lambda: ("ase", "missing_test")
    )
    monkeypatch.setattr(
        general_settings,
        "viewer_unavailability",
        lambda name: "Viewer executable missing_test is not installed"
        if name == "missing_test" else None,
    )
    preferences = ApplicationSettings(tmp_path / "settings.json")
    dialog = settings_dialog.SettingsDialog(preferences)
    dialog.viewer.setCurrentText("missing_test")
    shown = []
    monkeypatch.setattr(
        settings_dialog.QMessageBox, "warning",
        lambda _parent, title, msg, *_args: (
            shown.append((title, msg)) or QMessageBox.StandardButton.No
        ),
    )
    dialog.accept()
    assert shown and "not installed" in shown[0][1]
    assert preferences.viewer == "ase"
    assert not preferences.path.exists()

    monkeypatch.setattr(
        settings_dialog.QMessageBox, "warning",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    dialog.accept()
    assert preferences.viewer == "missing_test"
    assert preferences.path.exists()


def test_visualize_missing_executable_offers_ase_fallback(monkeypatch):
    app = _app()
    settings = ApplicationSettings()
    settings.viewer = "vmd"
    monkeypatch.setattr(
        visualization, "viewer_unavailability",
        lambda name: "Executable 'vmd' was not found on PATH."
        if name == "vmd" else None,
    )
    calls = []
    monkeypatch.setattr(
        visualization, "ase_view",
        lambda atoms, *, viewer: calls.append((atoms, viewer)),
    )
    messages = []
    monkeypatch.setattr(
        visualization.QMessageBox, "warning",
        lambda _parent, title, message, *_args: (
            messages.append((title, message)) or QMessageBox.StandardButton.Yes
        ),
    )
    assert visualization.visualize_structure(_controller(), settings, None)
    assert [viewer for _, viewer in calls] == ["ase"]
    assert "vmd" in messages[0][1]
    assert "Settings" in messages[0][1]
    assert "PATH" in messages[0][1]


def test_visualize_fallback_declined_does_not_launch(monkeypatch):
    app = _app()
    settings = ApplicationSettings()
    settings.viewer = "vmd"
    monkeypatch.setattr(
        visualization, "viewer_unavailability",
        lambda name: "Not installed" if name == "vmd" else None,
    )
    opened = []
    monkeypatch.setattr(
        visualization, "ase_view",
        lambda atoms, *, viewer: opened.append(viewer),
    )
    monkeypatch.setattr(
        visualization.QMessageBox, "warning",
        lambda *_args: QMessageBox.StandardButton.No,
    )
    assert not visualization.visualize_structure(_controller(), settings, None)
    assert opened == []


def test_visualize_launch_exception_is_visible_and_can_fallback(monkeypatch):
    app = _app()
    settings = ApplicationSettings()
    settings.viewer = "vmd"
    monkeypatch.setattr(visualization, "viewer_unavailability", lambda name: None)
    opened = []

    def fake_view(atoms, *, viewer):
        opened.append(viewer)
        if viewer == "vmd":
            raise OSError("Cannot launch requested viewer")

    monkeypatch.setattr(visualization, "ase_view", fake_view)
    errors = []
    monkeypatch.setattr(
        visualization.QMessageBox, "warning",
        lambda _parent, title, message, *_args: (
            errors.append(message) or QMessageBox.StandardButton.Yes
        ),
    )
    assert visualization.visualize_structure(_controller(), settings, None)
    assert opened == ["vmd", "ase"]
    assert "OSError: Cannot launch requested viewer" in errors[0]


def test_visualize_fallback_failure_is_reported(monkeypatch):
    app = _app()
    settings = ApplicationSettings()
    settings.viewer = "vmd"
    monkeypatch.setattr(
        visualization, "viewer_unavailability",
        lambda name: "vmd is not installed" if name == "vmd" else None,
    )
    monkeypatch.setattr(
        visualization.QMessageBox, "warning",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )

    def failing_ase(atoms, *, viewer):
        raise RuntimeError("Cannot open display")

    monkeypatch.setattr(visualization, "ase_view", failing_ase)
    critical = []
    monkeypatch.setattr(
        visualization.QMessageBox, "critical",
        lambda _parent, title, msg: critical.append((title, msg)),
    )
    assert not visualization.visualize_structure(_controller(), settings, None)
    assert critical and "Cannot open display" in critical[0][1]
