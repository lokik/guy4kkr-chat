"""Regression coverage for terminal shutdown and unsaved-work handling."""
from __future__ import annotations

import signal

from ase import Atoms
from PyQt6.QtWidgets import QApplication, QMessageBox

from guy4ase.gui.application.console_interrupt import ConsoleInterrupt
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import files as file_flows
from guy4ase.main import GuiApplication


def test_console_interrupt_wakes_qt_once_and_restores_handler():
    app = QApplication.instance()
    previous_handler = signal.getsignal(signal.SIGINT)
    received = []
    interrupt = ConsoleInterrupt(lambda: received.append(True), parent=app)
    try:
        assert signal.getsignal(signal.SIGINT) != previous_handler
        interrupt._mark_interrupt(signal.SIGINT, None)
        interrupt._writer.send(bytes([2]))
        app.processEvents()
        assert received == [True]
        app.processEvents()
        assert received == [True]
    finally:
        interrupt.close()
        interrupt.close()
    assert signal.getsignal(signal.SIGINT) == previous_handler


def test_saved_revisions_are_not_marked_clean_after_new_edit():
    controller = WorkspaceController()
    controller.replace_structure(Atoms("Fe"))
    initial = controller.structure_generation
    assert controller.has_unsaved_structure
    assert controller.mark_structure_saved(initial)
    assert not controller.has_unsaved_structure

    controller.replace_structure(Atoms("Cu"))
    assert controller.has_unsaved_structure
    assert not controller.mark_structure_saved(initial)
    assert controller.has_unsaved_structure

    controller.replace_input_parameters(object())
    initial_input = controller.input_parameters_generation
    assert controller.has_unsaved_input_parameters
    assert controller.mark_input_parameters_saved(initial_input)
    assert not controller.has_unsaved_input_parameters
    controller.replace_input_parameters(object())
    assert controller.has_unsaved_input_parameters


def test_exit_without_edits_does_not_prompt(tmp_path, monkeypatch):
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    def fail_prompt(*_args):
        raise AssertionError("unexpected prompt")
    monkeypatch.setattr(QMessageBox, "question", fail_prompt)
    assert gui.request_exit()


def test_cancelled_exit_preserves_workspace(tmp_path, monkeypatch):
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    atoms = Atoms("Fe")
    gui.controller.replace_structure(atoms)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Cancel
    )
    assert not gui.request_exit()
    assert gui.controller.atoms is atoms
    assert gui.controller.has_unsaved_structure


def test_discard_exits_without_saving(tmp_path, monkeypatch):
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    gui.controller.replace_structure(Atoms("Fe"))
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Discard
    )
    assert gui.request_exit()
    assert gui.controller.has_unsaved_structure


def test_save_exit_uses_both_existing_file_flows(tmp_path, monkeypatch):
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    gui.controller.replace_structure(Atoms("Fe"))
    gui.controller.replace_input_parameters(object())
    writes = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Save
    )

    def save_structure(controller, _recent, _parent):
        writes.append("structure")
        return controller.mark_structure_saved(controller.structure_generation)

    def save_input(controller, _recent, _parent):
        writes.append("input")
        return controller.mark_input_parameters_saved(controller.input_parameters_generation)

    monkeypatch.setattr(file_flows, "save_structure", save_structure)
    monkeypatch.setattr(file_flows, "save_input_parameters", save_input)
    assert gui.request_exit()
    assert writes == ["structure", "input"]
    assert not gui.controller.has_unsaved_structure
    assert not gui.controller.has_unsaved_input_parameters


def test_cancelling_save_aborts_exit(tmp_path, monkeypatch):
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    gui.controller.replace_structure(Atoms("Fe"))
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Save
    )
    monkeypatch.setattr(file_flows, "save_structure", lambda *_args: False)
    assert not gui.request_exit()
    assert gui.controller.has_unsaved_structure


def test_loaded_structure_exits_without_save_prompt(tmp_path, monkeypatch):
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    file_path = tmp_path / "Fe.cif"
    monkeypatch.setattr(
        file_flows, "ase_read",
        lambda _path: Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
    )
    assert file_flows.load_structure(
        gui.controller, gui.recent_files, file_path, None
    )
    assert not gui.controller.has_unsaved_structure

    def unexpected_prompt(*_args):
        raise AssertionError("loading a structure must not prompt on exit")

    monkeypatch.setattr(QMessageBox, "question", unexpected_prompt)
    assert gui.request_exit()
