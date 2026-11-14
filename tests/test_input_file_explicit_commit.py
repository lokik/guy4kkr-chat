"""Regressions for explicit commits before opening the input-file editor."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.dialogs import expert_input, guided_input
from ase2sprkkr_gui.gui.dialogs.expert_input import InputParametersDialog
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog


def _application():
    return QApplication.instance() or QApplication([])


def test_guided_commits_pending_before_editing_input_file(monkeypatch):
    application = _application()
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    calls = []

    monkeypatch.setattr(dialog, "_commit_pending", lambda: calls.append("commit") or True)
    monkeypatch.setattr(
        guided_input,
        "edit_input_parameters_file",
        lambda session, parent: calls.append(("edit", session, parent)),
    )

    dialog._edit_input_file()

    assert calls == ["commit", ("edit", dialog.session, dialog)]
    dialog.close()
    application.processEvents()


def test_guided_does_not_open_input_file_editor_when_commit_fails(monkeypatch):
    application = _application()
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    opened = []

    monkeypatch.setattr(dialog, "_commit_pending", lambda: False)
    monkeypatch.setattr(
        guided_input,
        "edit_input_parameters_file",
        lambda *_args: opened.append(True),
    )

    dialog._edit_input_file()

    assert not opened
    dialog.close()
    application.processEvents()


def test_expert_commits_pending_before_editing_input_file(monkeypatch):
    application = _application()
    dialog = InputParametersDialog(InputParameters.create("scf"))
    calls = []

    monkeypatch.setattr(
        dialog.tree_editor,
        "commit_pending",
        lambda: calls.append("commit") or True,
    )
    monkeypatch.setattr(
        expert_input,
        "edit_input_parameters_file",
        lambda session, parent: calls.append(("edit", session, parent)),
    )

    dialog._edit_input_file()

    assert calls == ["commit", ("edit", dialog.session, dialog)]
    dialog.close()
    application.processEvents()


def test_expert_does_not_open_input_file_editor_when_commit_fails(monkeypatch):
    application = _application()
    dialog = InputParametersDialog(InputParameters.create("scf"))
    opened = []

    monkeypatch.setattr(dialog.tree_editor, "commit_pending", lambda: False)
    monkeypatch.setattr(
        expert_input,
        "edit_input_parameters_file",
        lambda *_args: opened.append(True),
    )

    dialog._edit_input_file()

    assert not opened
    dialog.close()
    application.processEvents()
