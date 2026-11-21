"""Guided input file actions use isolated sessions, not workspace documents."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

from ase import Atoms
from ase2sprkkr import InputParameters
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.dialogs import guided_input as gui_input
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.flows import input_parameters as input_flows


def _dialog(**kwargs):
    app = QApplication.instance() or QApplication([])
    return app, GuidedInputParametersDialog(
        "scf", InputParameters.create("scf"), **kwargs
    )


def test_undo_redo_are_in_top_right_header_not_footer():
    _app, dialog = _dialog()
    layout = dialog.layout()
    top = layout.itemAt(0).layout()
    footer = layout.itemAt(layout.count() - 1).layout()
    assert top.indexOf(dialog.undo_button) >= 0
    assert top.indexOf(dialog.redo_button) >= 0
    assert top.indexOf(dialog.undo_button) < top.indexOf(dialog.redo_button)
    assert footer.indexOf(dialog.undo_button) == -1
    assert footer.indexOf(dialog.redo_button) == -1
    assert dialog.save_input_button.text() == "Save Input…"
    dialog.close()


def test_page_focus_has_no_native_tail_and_keeps_selected_border():
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    app, dialog = _dialog()
    dialog.show()
    app.processEvents()
    first, second = dialog.spec.pages[:2]
    first_label = dialog._navigation[first.id].label
    second_label = dialog._navigation[second.id].label

    # The original selected tile styling must NOT be changed.
    assert "border: 3px solid" in first_label.styleSheet()
    assert "border: 1px solid" in second_label.styleSheet()
    stylesheet = dialog.navigation.styleSheet()
    assert "outline: 0" in stylesheet
    assert "QListWidget::item:selected, QListWidget::item:hover" in stylesheet
    assert "background: transparent" in stylesheet

    rect = dialog.navigation.visualItemRect(dialog._navigation[second.id].item)
    QTest.mouseClick(dialog.navigation.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert dialog.navigation.currentRow() == 1
    assert dialog.pages.currentIndex() == 1
    assert "border: 3px solid" in second_label.styleSheet()
    assert "border: 1px solid" in first_label.styleSheet()

    dialog.navigation.setFocus()
    QTest.keyClick(dialog.navigation, Qt.Key.Key_Up)
    assert dialog.navigation.currentRow() == 0
    assert dialog.pages.currentIndex() == 0
    assert "border: 3px solid" in first_label.styleSheet()
    dialog.close()


def test_page_navigation_is_below_pages_and_run_controls_share_file_action_row():
    _app, dialog = _dialog()
    root = dialog.layout()
    body = next(
        root.itemAt(i).layout() for i in range(root.count())
        if root.itemAt(i).layout() is not None
        and any(
            root.itemAt(i).layout().itemAt(j).widget() is dialog.pages
            for j in range(root.itemAt(i).layout().count())
        )
    )
    nav_column = body.itemAt(0).layout()
    assert nav_column.itemAt(0).widget() is dialog.navigation
    page_buttons = nav_column.itemAt(nav_column.count() - 1).layout()
    assert page_buttons.indexOf(dialog.previous_button) >= 0
    assert page_buttons.indexOf(dialog.next_button) >= 0

    actions = root.itemAt(root.count() - 1).layout()
    labels = ["Load input…", "Save Input…", "Presets…",
              "Edit input file…", "Expert settings…", "Cancel", "Calculate"]
    buttons = [actions.itemAt(i).widget() for i in range(actions.count())
               if actions.itemAt(i).widget() is not None]
    assert [button.text() for button in buttons] == labels
    assert all(not button.icon().isNull() for button in buttons)
    assert not dialog.previous_button.icon().isNull()
    assert not dialog.next_button.icon().isNull()

    assert not dialog.previous_button.isEnabled()
    dialog.next_button.click()
    assert dialog.navigation.currentRow() == 1
    assert dialog.previous_button.isEnabled()
    dialog.previous_button.click()
    assert dialog.navigation.currentRow() == 0
    dialog.close()


def test_save_commits_current_draft_without_accepting_or_mutating_source(monkeypatch):
    _app, dialog = _dialog()
    source = dialog.session.working_parameters
    original = source.SCF.NITER()
    saved = []
    monkeypatch.setattr(
        gui_input, "choose_and_save_input_parameters",
        lambda params, parent, **_options: saved.append((params, parent)) or True,
    )
    assert dialog.session.set_value(("SCF", "NITER"), 314)
    dialog.save_input_button.click()
    assert len(saved) == 1
    params, parent = saved[0]
    assert parent is dialog
    assert params is not dialog.session.working_parameters
    assert params.SCF.NITER() == 314
    assert dialog.result() == 0
    assert source.SCF.NITER() == original
    dialog.close()


def test_save_input_uses_native_serializer_and_cancel_is_noop(monkeypatch, tmp_path):
    parameters = InputParameters.create("scf")
    directory = tmp_path / "calculations" / "run"
    directory.mkdir(parents=True)
    parameters.CONTROL.POTFIL = str(directory / "input.pot")
    path = tmp_path / "test.inp"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        input_flows.QFileDialog, "getSaveFileName",
        lambda *_args, **_kwargs: (str(path), ""),
    )
    atoms = Atoms("Fe", cell=(3, 3, 3), pbc=(True, True, False))
    assert input_flows.choose_and_save_input_parameters(
        parameters, None, atoms=atoms, directory=directory,
    )
    saved = path.read_text()
    assert "POTFIL=input.pot" in saved
    assert "NKTAB2D" in saved
    assert "KKRMODE=TB" in saved
    monkeypatch.setattr(
        input_flows.QFileDialog, "getSaveFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    assert not input_flows.choose_and_save_input_parameters(parameters, None)
    assert path.read_text() == saved


def test_calculate_disabled_with_reason_and_restores_after_session_edit(monkeypatch):
    # Isolate contextual availability from native validity of an empty model.
    monkeypatch.setattr(gui_input, "validate_setup", lambda _params: None)
    _app, dialog = _dialog(
        calculation_unavailable_reason=lambda p: (
            "This input needs an existing converged potential"
            if p.SCF.NITER() != 314 else None
        ),
    )
    assert not dialog.calculate_button.isEnabled()
    assert "converged potential" in dialog.calculate_button.toolTip()
    assert dialog.save_input_button.isEnabled()
    assert dialog.session.set_value(("SCF", "NITER"), 314)
    assert dialog.calculate_button.isEnabled()
    assert "Run a calculation" in dialog.calculate_button.toolTip()
    dialog.close()


def test_calculate_invalid_input_is_disabled_without_disabling_save(monkeypatch):
    from ase2sprkkr_gui.gui.input_parameters.validation import InputParametersValidationError

    def fail(_parameters):
        raise InputParametersValidationError("Energy window must be corrected")

    monkeypatch.setattr(gui_input, "validate_setup", fail)
    _app, dialog = _dialog()
    assert not dialog.calculate_button.isEnabled()
    assert "Energy window" in dialog.calculate_button.toolTip()
    assert dialog.save_input_button.isEnabled()
    dialog.close()



def test_explicit_input_save_populates_recent_history(tmp_path, monkeypatch):
    from ase2sprkkr_gui.gui.application.recent_files import RecentFiles

    _app, dialog = _dialog()
    history = RecentFiles(tmp_path / "recent.json")
    dialog.recent_files = history
    target = tmp_path / "saved.inp"
    monkeypatch.setattr(
        input_flows.QFileDialog, "getSaveFileName",
        lambda *_args, **_kwargs: (str(target), ""),
    )
    dialog.save_input_button.click()
    assert target.is_file()
    assert history.paths("input") == (str(target.resolve()),)
    dialog.close()
