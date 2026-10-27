"""Regression tests for editing output identifiers at launch."""
from __future__ import annotations

import copy
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from ase import Atoms
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.profiles import ProfileSelectionDialog, RunIdentification
from guy4ase.gui.flows import calculation as calculation_flow


class _Option:
    def __init__(self, value=None):
        self.value = value

    def is_set(self):
        return self.value is not None

    def __call__(self):
        return self.value

    def set(self, value):
        self.value = value


class _Parameters:
    def __init__(self, dataset="original", adsi="SCF"):
        self.CONTROL = SimpleNamespace(DATASET=_Option(dataset), ADSI=_Option(adsi))

    def copy(self, *, copy_values):
        assert copy_values
        return copy.deepcopy(self)


class _Profiles:
    def names(self):
        return []

    def resolved_name(self, _name):
        return None

    def describe(self, _name):
        return "Built-in local profile"


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_run_dialog_edits_both_identifiers_without_mutating_inputs(application, tmp_path):
    parameters = _Parameters()
    dialog = ProfileSelectionDialog(input_parameters=parameters, store=_Profiles(), directory=str(tmp_path))

    assert dialog.dataset_edit.text() == "original"
    assert dialog.adsi_edit.text() == "SCF"
    assert "DATASET" in dialog.dataset_edit.toolTip()
    assert "ADSI" in dialog.adsi_edit.toolTip()

    dialog.dataset_edit.setText("Fe_bcc_02")
    dialog.adsi_edit.setText("relaxed")
    dialog.accept()

    assert dialog.identification() == RunIdentification("Fe_bcc_02", "relaxed")
    assert parameters.CONTROL.DATASET() == "original"
    assert parameters.CONTROL.ADSI() == "SCF"
    dialog.close()


def test_empty_dataset_means_automatic_naming(application, tmp_path):
    dialog = ProfileSelectionDialog(
        input_parameters=_Parameters(), store=_Profiles(), directory=str(tmp_path)
    )
    dialog.dataset_edit.clear()
    dialog.accept()
    assert dialog.identification().dataset is None
    dialog.close()


def test_accepted_run_identification_overrides_only_request(application, monkeypatch, tmp_path):
    parameters = _Parameters()
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=parameters,
            directory=str(tmp_path),
        )
    )
    captured = {}

    class Window:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def show(self):
            pass

        def start(self):
            pass

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(
        calculation_flow,
        "_select_profile",
        lambda _parent, **_kwargs: (
            True, None, RunIdentification("new_dataset", "new_label"), str(tmp_path)
        ),
    )
    monkeypatch.setattr(calculation_flow, "profile_description", lambda _name: None)

    assert calculation_flow.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), object()
    ) is not None
    launched = captured["request"].input_parameters
    assert launched is not parameters
    assert launched.CONTROL.DATASET() == "new_dataset"
    assert launched.CONTROL.ADSI() == "new_label"
    assert controller.input_parameters.CONTROL.DATASET() == "original"
    assert controller.input_parameters.CONTROL.ADSI() == "SCF"


def test_cancelling_run_dialog_leaves_workspace_unchanged(application, monkeypatch, tmp_path):
    parameters = _Parameters()
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=parameters,
            directory=str(tmp_path),
        )
    )
    generation = controller.input_parameters_generation
    monkeypatch.setattr(
        calculation_flow, "_select_profile",
        lambda _parent, **_kwargs: (False, None, None, None),
    )

    assert calculation_flow.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), object()
    ) is None
    assert controller.input_parameters is parameters
    assert controller.input_parameters_generation == generation


def test_execution_dialog_requires_working_directory_and_can_browse(
    application, monkeypatch, tmp_path
):
    from guy4ase.gui.dialogs import profiles

    dialog = ProfileSelectionDialog(
        input_parameters=_Parameters(), store=_Profiles()
    )
    warnings = []
    monkeypatch.setattr(
        profiles.QMessageBox, "warning",
        lambda _dialog, title, message: warnings.append((title, message)),
    )
    dialog.accept()
    assert warnings and warnings[0][0] == "Calculation Directory Required"
    assert dialog.result() == dialog.DialogCode.Rejected

    monkeypatch.setattr(
        profiles.QFileDialog, "getExistingDirectory",
        lambda *_args: str(tmp_path),
    )
    dialog._browse_directory()
    assert dialog.directory_name() == str(tmp_path)
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()
