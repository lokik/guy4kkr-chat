"""Regression coverage for terminal shutdown and unsaved-work handling."""
from __future__ import annotations

import signal

from ase import Atoms
from PyQt6.QtWidgets import QApplication, QMessageBox

from ase2sprkkr_gui.gui.application.console_interrupt import ConsoleInterrupt
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.flows import files as file_flows
from ase2sprkkr_gui.main import GuiApplication


def test_console_interrupt_wakes_qt_once_and_restores_handler(capfd):
    app = QApplication.instance()
    previous_handler = signal.getsignal(signal.SIGINT)
    received = []
    interrupt = ConsoleInterrupt(lambda: received.append(True), parent=app)
    try:
        assert signal.getsignal(signal.SIGINT) != previous_handler
        interrupt._mark_interrupt(signal.SIGINT, None)
        message = capfd.readouterr().err
        assert "Ctrl+C: shutdown requested" in message
        assert "Hit CTRL+C again to force terminate" in message
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


def test_second_ctrl_c_force_exits_while_first_handler_is_running(monkeypatch):
    import pytest
    from ase2sprkkr_gui.gui.application import console_interrupt as bridge

    app = QApplication.instance() or QApplication([])
    events = []

    def forced_exit(code):
        events.append(("forced", code))
        raise SystemExit(code)

    monkeypatch.setattr(bridge.os, "_exit", forced_exit)
    clock = [10.0]
    monkeypatch.setattr(bridge, "monotonic", lambda: clock[0])
    interrupt = None

    def shutdown():
        events.append("shutdown")
        clock[0] = 10.2
        interrupt._mark_interrupt(signal.SIGINT, None)  # Accidental repeat.
        clock[0] = 10.51
        interrupt._mark_interrupt(signal.SIGINT, None)  # Deliberate force.

    interrupt = ConsoleInterrupt(shutdown, parent=app)
    try:
        interrupt._mark_interrupt(signal.SIGINT, None)
        with pytest.raises(SystemExit) as exc:
            interrupt._on_readable()
        assert exc.value.code == 130
        assert events == ["shutdown", ("forced", 130)]
    finally:
        interrupt.close()


def test_second_ctrl_c_force_exits_before_qt_consumes_first(monkeypatch):
    import pytest
    from ase2sprkkr_gui.gui.application import console_interrupt as bridge

    app = QApplication.instance() or QApplication([])
    called = []
    clock = [0.0]
    monkeypatch.setattr(bridge, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        bridge.os, "_exit",
        lambda code: (_ for _ in ()).throw(SystemExit(code)),
    )
    interrupt = ConsoleInterrupt(lambda: called.append(True), parent=app)
    try:
        interrupt._mark_interrupt(signal.SIGINT, None)
        clock[0] = 0.49
        interrupt._mark_interrupt(signal.SIGINT, None)  # Ignored.
        clock[0] = 0.51
        with pytest.raises(SystemExit, match="130"):
            interrupt._mark_interrupt(signal.SIGINT, None)
        assert not called
    finally:
        interrupt.close()


def test_late_ctrl_c_resets_force_window_during_modal_shutdown(monkeypatch):
    from ase2sprkkr_gui.gui.application import console_interrupt as bridge

    app = QApplication.instance() or QApplication([])
    clock = [10.0]
    events = []
    monkeypatch.setattr(bridge, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        bridge.os, "_exit",
        lambda code: (_ for _ in ()).throw(AssertionError(f"forced exit: {code}")),
    )

    interrupt = None

    def shutdown():
        events.append("shutdown")
        clock[0] = 13.1
        interrupt._mark_interrupt(signal.SIGINT, None)
        assert interrupt._first_interrupt_at == 13.1
        clock[0] = 13.3
        interrupt._mark_interrupt(signal.SIGINT, None)
        # Even in an in-progress modal shutdown, repeated Ctrl+C must not
        # recursively invoke the callback or unexpectedly terminate.
        assert events == ["shutdown"]

    interrupt = ConsoleInterrupt(shutdown, parent=app)
    try:
        interrupt._mark_interrupt(signal.SIGINT, None)
        interrupt._on_readable()
        assert events == ["shutdown"]
    finally:
        interrupt.close()


def test_rearmed_force_window_still_allows_deliberate_second_ctrl_c(monkeypatch):
    import pytest
    from ase2sprkkr_gui.gui.application import console_interrupt as bridge

    app = QApplication.instance() or QApplication([])
    clock = [10.0]
    events = []
    monkeypatch.setattr(bridge, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        bridge.os, "_exit",
        lambda code: (_ for _ in ()).throw(SystemExit(code)),
    )

    interrupt = None

    def shutdown():
        events.append("shutdown")
        clock[0] = 13.1
        interrupt._mark_interrupt(signal.SIGINT, None)  # Late: re-arm.
        clock[0] = 13.7
        interrupt._mark_interrupt(signal.SIGINT, None)  # Force within new window.

    interrupt = ConsoleInterrupt(shutdown, parent=app)
    try:
        interrupt._mark_interrupt(signal.SIGINT, None)
        with pytest.raises(SystemExit) as exc:
            interrupt._on_readable()
        assert exc.value.code == 130
        assert events == ["shutdown"]
    finally:
        interrupt.close()


def test_ctrl_c_after_cancelled_shutdown_starts_fresh_request(monkeypatch):
    from ase2sprkkr_gui.gui.application import console_interrupt as bridge

    app = QApplication.instance() or QApplication([])
    clock = [1.0]
    monkeypatch.setattr(bridge, "monotonic", lambda: clock[0])
    calls = []
    monkeypatch.setattr(
        bridge.os, "_exit",
        lambda code: (_ for _ in ()).throw(AssertionError(f"forced exit: {code}")),
    )
    interrupt = ConsoleInterrupt(lambda: calls.append("requested"), parent=app)
    try:
        interrupt._mark_interrupt(signal.SIGINT, None)
        clock[0] = 1.12
        interrupt._mark_interrupt(signal.SIGINT, None)
        interrupt._on_readable()  # The user cancels the save prompt.
        assert calls == ["requested"]
        clock[0] = 5.0
        interrupt._mark_interrupt(signal.SIGINT, None)
        interrupt._on_readable()
        assert calls == ["requested", "requested"]
    finally:
        interrupt.close()
