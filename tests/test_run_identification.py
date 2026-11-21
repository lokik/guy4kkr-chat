"""Regression tests for editing output identifiers at launch."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from ase import Atoms
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.dialogs.profiles import ProfileSelectionDialog, RunIdentification
from ase2sprkkr_gui.gui.flows import calculation as calculation_flow


def _Parameters(dataset="original", adsi="SCF"):
    parameters = InputParameters.create("SCF")
    parameters.CONTROL.DATASET = dataset
    parameters.CONTROL.ADSI = adsi
    return parameters


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


@pytest.mark.parametrize("field,value", [
    ("dataset_edit", "-3"), ("dataset_edit", "Fe$(id)"),
    ("dataset_edit", "Fe;id"), ("adsi_edit", "bad#name"),
    ("dataset_edit", " Fe "), ("adsi_edit", "bad$(id)"), ("adsi_edit", "bad name"),
])
def test_run_dialog_rejects_unsafe_identifiers(application, monkeypatch, tmp_path, field, value):
    from ase2sprkkr_gui.gui.dialogs import profiles

    dialog = ProfileSelectionDialog(
        input_parameters=_Parameters(), store=_Profiles(), directory=str(tmp_path),
    )
    warnings = []
    monkeypatch.setattr(profiles.QMessageBox, "warning", lambda *_args: warnings.append(_args))
    getattr(dialog, field).setText(value)
    dialog.accept()
    assert warnings
    assert dialog.result() == dialog.DialogCode.Rejected
    dialog.close()


@pytest.mark.parametrize("dataset,adsi", [
    ("sub/-Fe+@%!:^~", "SCF"), ("Fe", "labels/-run+@%!:^~"),
    ("Železo", "běh"), (".Fe", ""), ("../Fe", "-3"),
])
def test_run_dialog_accepts_native_identifiers(application, tmp_path, dataset, adsi):
    parameters = _Parameters()
    dialog = ProfileSelectionDialog(
        input_parameters=parameters, store=_Profiles(), directory=str(tmp_path),
    )
    dialog.dataset_edit.setText(dataset)
    dialog.adsi_edit.setText(adsi)
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.identification() == RunIdentification(dataset, adsi)
    assert parameters.CONTROL.DATASET() == "original"
    assert parameters.CONTROL.ADSI() == "SCF"


def test_run_dialog_validates_dataset_relative_to_run_directory(application, monkeypatch, tmp_path):
    from ase2sprkkr_gui.gui.dialogs import profiles

    warnings = []
    monkeypatch.setattr(profiles.QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog = ProfileSelectionDialog(
        input_parameters=_Parameters(), store=_Profiles(), directory=str(tmp_path),
    )
    dialog.dataset_edit.setText(str(tmp_path / "-3"))
    dialog.accept()
    assert warnings[0][1] == "Invalid CONTROL.DATASET"
    assert "hyphen" in warnings[0][2]
    assert dialog.result() == dialog.DialogCode.Rejected


def test_run_dialog_displays_option_validation_error(application, monkeypatch, tmp_path):
    from ase2sprkkr.common.options import Option
    from ase2sprkkr.common.warnings import DataValidityError
    from ase2sprkkr_gui.gui.dialogs import profiles

    original_validate = Option.validate

    def validate(option, *args, **kwargs):
        if option.name == "ADSI":
            raise DataValidityError("Native option validation message")
        return original_validate(option, *args, **kwargs)

    warnings = []
    monkeypatch.setattr(Option, "validate", validate)
    monkeypatch.setattr(profiles.QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog = ProfileSelectionDialog(
        input_parameters=_Parameters(), store=_Profiles(), directory=str(tmp_path),
    )
    dialog.accept()
    assert warnings[0][2] == "Native option validation message"
    assert dialog.result() == dialog.DialogCode.Rejected


def test_run_dialog_allows_empty_adsi(application, tmp_path):
    dialog = ProfileSelectionDialog(
        input_parameters=_Parameters(), store=_Profiles(), directory=str(tmp_path),
    )
    dialog.adsi_edit.clear()
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.identification().adsi == ""
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
            True, None, RunIdentification("new_dataset", "new_label"), str(tmp_path), None
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
        lambda _parent, **_kwargs: (False, None, None, None, None),
    )

    assert calculation_flow.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), object()
    ) is None
    assert controller.input_parameters is parameters
    assert controller.input_parameters_generation == generation



@pytest.mark.parametrize("edit_timing", ["none", "before_submission_ack", "after_submission_ack"])
def test_submitted_run_saves_only_the_input_revision_written_at_launch(
    application, monkeypatch, tmp_path, edit_timing,
):
    """The input is saved at submit(), not when DOS finishes or results load."""
    from ase2sprkkr_gui.gui.application.result_loading import LoadedResult
    from ase2sprkkr_gui.gui.application.workspace_controller import ResultAdoption

    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(dataset="dos"),
            directory=str(tmp_path),
        )
    )
    assert controller.has_unsaved_input_parameters

    launched = {}

    class Window:
        def __init__(self, **kwargs):
            launched.update(kwargs)

        def show(self):
            pass

        def start(self):
            pass

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(calculation_flow, "profile_description", lambda _name: None)

    assert calculation_flow.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), object(),
        select_profile=False,
        on_result_loaded=lambda _loaded, _request: ResultAdoption(),
    ) is not None
    # Preparing the monitor is not sufficient; the backend must accept submit.
    assert controller.has_unsaved_input_parameters

    if edit_timing == "before_submission_ack":
        controller.replace_input_parameters(_Parameters(dataset="changed_early"))

    launched["on_submitted"]()
    if edit_timing == "after_submission_ack":
        controller.replace_input_parameters(_Parameters(dataset="changed_later"))

    changed = edit_timing != "none"
    assert controller.has_unsaved_input_parameters is changed

    # Postprocessing completion does not change the saved revision again.
    launched["on_finished"](LoadedResult(
        result=None, output_path=None, potential_path=None, atoms=None,
        potential_error=None, directory=str(tmp_path),
    ))
    assert controller.has_unsaved_input_parameters is changed


def test_submitted_host_run_does_not_mark_unrelated_workspace_inputs_saved(
    application, monkeypatch, tmp_path,
):
    """An explicit request override is not the workspace's input document."""
    from ase2sprkkr_gui.gui.application.result_loading import LoadedResult
    from ase2sprkkr_gui.gui.application.workspace_controller import ResultAdoption

    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(dataset="workspace"),
            directory=str(tmp_path),
        )
    )
    host_request = controller.create_calculation_request()
    launched = {}

    class Window:
        def __init__(self, **kwargs):
            launched.update(kwargs)

        def show(self):
            pass

        def start(self):
            pass

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", Window)
    monkeypatch.setattr(calculation_flow, "profile_description", lambda _name: None)
    assert calculation_flow.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), object(),
        select_profile=False, request_override=host_request,
        on_result_loaded=lambda _loaded, _request: ResultAdoption(),
    ) is not None

    launched["on_submitted"]()
    assert controller.has_unsaved_input_parameters
    launched["on_finished"](LoadedResult(
        result=None, output_path=None, potential_path=None, atoms=None,
        potential_error=None, directory=str(tmp_path),
    ))
    assert controller.has_unsaved_input_parameters



@pytest.mark.parametrize("preparation_succeeds", [True, False])
def test_save_files_only_marks_inputs_saved_only_after_success(
    application, monkeypatch, tmp_path, preparation_succeeds,
):
    controller = WorkspaceController(WorkspaceState(
        atoms=Atoms("Fe"),
        input_parameters=_Parameters(dataset="dos"),
        directory=str(tmp_path),
    ))
    monkeypatch.setattr(
        calculation_flow, "_select_profile",
        lambda *_args, **_kwargs: (
            True, None, None, str(tmp_path), None, True, False,
        ),
    )
    monkeypatch.setattr(
        calculation_flow, "SprkkrRunWindow",
        lambda **_kwargs: pytest.fail("Save-only must not launch"),
    )

    class Preparation:
        def __init__(self, *_args, **_kwargs):
            pass

        def prepare_files(self):
            if not preparation_succeeds:
                raise OSError("input write failed")
            written = SimpleNamespace(
                CONTROL=SimpleNamespace(POTFIL_CLU=lambda: None)
            )
            return written, str(tmp_path / "dos.inp"), "Fe.pot", None

    monkeypatch.setattr(calculation_flow, "SprkkrExecution", Preparation)
    monkeypatch.setattr(calculation_flow.QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(calculation_flow.QMessageBox, "critical", lambda *_args: None)
    assert controller.has_unsaved_input_parameters
    assert calculation_flow.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), object(),
    ) is None
    assert controller.has_unsaved_input_parameters is not preparation_succeeds



def test_execution_dialog_requires_working_directory_and_can_browse(
    application, monkeypatch, tmp_path
):
    from ase2sprkkr_gui.gui.dialogs import profiles

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


def test_save_only_is_a_special_non_persistent_profile_choice(application, tmp_path):
    dialog = ProfileSelectionDialog(
        directory=str(tmp_path), store=_Profiles()
    )
    assert not hasattr(dialog, "prepare_only")
    assert dialog._confirm_button.text() == "Run"
    assert not dialog.save_only_selected()
    assert dialog.profiles.itemText(dialog.profiles.count() - 1) == (
        "<Save input files only>"
    )

    dialog.profiles.setCurrentIndex(dialog.profiles.count() - 1)
    assert dialog.save_only_selected()
    assert dialog.profile_name() is None
    assert dialog._confirm_button.text() == "Save files"
    assert "without starting" in dialog.description.text()
    assert dialog.identification() is None

    # Managing real profiles must preserve this special choice, but must not
    # add it to the store of actual executors.
    assert _Profiles().names() == []
    dialog._reload_profiles()
    assert dialog.save_only_selected()
    assert dialog._confirm_button.text() == "Save files"

    dialog.profiles.setCurrentIndex(0)
    assert not dialog.save_only_selected()
    assert dialog._confirm_button.text() == "Run"
    assert "Built-in local profile" in dialog.description.text()
    dialog.close()


def test_save_only_is_not_selected_as_default_when_no_default_profile(
    application, tmp_path,
):
    class NamedProfiles:
        def names(self):
            return ["local", "remote"]

        def resolved_name(self, _name):
            return None

        def describe(self, name):
            return f"Profile: {name}"

    dialog = ProfileSelectionDialog(
        directory=str(tmp_path), store=NamedProfiles()
    )
    assert dialog.profiles.currentText() == "local"
    assert dialog.profile_name() == "local"
    assert not dialog.save_only_selected()
    assert dialog._confirm_button.text() == "Run"

    dialog.profiles.setCurrentIndex(dialog.profiles.count() - 1)
    assert dialog.save_only_selected()
    assert dialog._confirm_button.text() == "Save files"
    dialog._reload_profiles()
    assert dialog.save_only_selected()
    assert dialog._confirm_button.text() == "Save files"
    dialog.close()



def test_profile_only_selector_does_not_offer_file_preparation(application):
    dialog = ProfileSelectionDialog(
        store=_Profiles(), require_directory=False,
    )
    assert dialog.profiles.count() == 1
    assert dialog.profiles.itemText(0) == "Automatic / built-in"
    assert not dialog.save_only_selected()
    dialog.close()
