import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

import pytest
from ase2sprkkr.common.warnings import DataValidityError
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.dialogs import guided_input
from guy4ase.gui.dialogs.guided_input import GuidedInputParametersDialog
from guy4ase.gui.flows import files as workspace_file_flows
from guy4ase.gui.flows import input_parameters as input_parameter_flows
from guy4ase.gui.input_parameters.session import create_input_parameters_session
from guy4ase.gui.input_parameters.validation import (
    InputParametersValidationError,
    validate_setup,
)


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def _raise(error):
    raise error


def test_load_reports_parser_error(monkeypatch, tmp_path, application):
    session = create_input_parameters_session(InputParameters.create("scf"))
    messages = []
    monkeypatch.setattr(
        input_parameter_flows.InputParameters,
        "from_file",
        lambda _path: _raise(RuntimeError("broken input")),
    )
    monkeypatch.setattr(
        input_parameter_flows.QMessageBox,
        "critical",
        lambda _parent, _title, text: messages.append(text),
    )

    assert not input_parameter_flows.load_input_parameters(
        session, tmp_path / "broken.inp", None
    )
    assert messages == ["Failed to load input parameters:\nbroken input"]


def test_load_does_not_hide_session_error(monkeypatch, tmp_path, application):
    session = create_input_parameters_session(InputParameters.create("scf"))
    parameters = InputParameters.create("scf")
    monkeypatch.setattr(
        input_parameter_flows.InputParameters,
        "from_file",
        lambda _path: parameters,
    )
    monkeypatch.setattr(
        session,
        "replace_parameters",
        lambda *_args, **_kwargs: _raise(RuntimeError("session invariant")),
    )

    with pytest.raises(RuntimeError, match="session invariant"):
        input_parameter_flows.load_input_parameters(
            session, tmp_path / "valid.inp", None
        )


def test_wrong_task_is_a_user_facing_load_error(
    monkeypatch, tmp_path, application
):
    session = create_input_parameters_session(InputParameters.create("scf"))
    monkeypatch.setattr(
        input_parameter_flows.InputParameters,
        "from_file",
        lambda _path: InputParameters.create("dos"),
    )
    messages = []
    monkeypatch.setattr(
        input_parameter_flows.QMessageBox,
        "critical",
        lambda _parent, _title, text: messages.append(text),
    )

    assert not input_parameter_flows.load_input_parameters(
        session, tmp_path / "dos.inp", None
    )
    assert "Expected SCF input parameters, got DOS." in messages[0]


def test_text_editor_flow_does_not_hide_dialog_error(monkeypatch, application):
    session = create_input_parameters_session(InputParameters.create("scf"))

    class BrokenEditor:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            raise RuntimeError("dialog bug")

    monkeypatch.setattr(input_parameter_flows, "InputFileEditor", BrokenEditor)

    with pytest.raises(RuntimeError, match="dialog bug"):
        input_parameter_flows.edit_input_parameters_file(session, None)


def test_guided_expert_does_not_hide_dialog_error(monkeypatch, application):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    monkeypatch.setattr(dialog, "_commit_pending", lambda: True)
    monkeypatch.setattr(
        guided_input,
        "edit_input_parameters_session",
        lambda *_args, **_kwargs: _raise(RuntimeError("expert bug")),
    )

    with pytest.raises(RuntimeError, match="expert bug"):
        dialog._open_expert_settings()
    dialog.close()


def test_workspace_structure_load_does_not_hide_controller_error(
    monkeypatch, tmp_path, application
):
    class Controller:
        structure_generation = object()
        directory_generation = object()

        def replace_structure(self, *_args, **_kwargs):
            raise RuntimeError("controller invariant")

    monkeypatch.setattr(workspace_file_flows, "ase_read", lambda _path: object())
    messages = []
    monkeypatch.setattr(
        workspace_file_flows.QMessageBox,
        "critical",
        lambda _parent, _title, text: messages.append(text),
    )

    with pytest.raises(RuntimeError, match="controller invariant"):
        workspace_file_flows.load_structure(
            Controller(), object(), tmp_path / "Fe.cif", None
        )
    assert messages == []


def test_workspace_input_load_does_not_hide_controller_error(
    monkeypatch, tmp_path, application
):
    parameters = object()

    class Controller:
        input_parameters_generation = object()
        directory_generation = object()

        def replace_input_parameters(self, *_args, **_kwargs):
            raise RuntimeError("controller invariant")

    monkeypatch.setattr(
        workspace_file_flows.InputParameters,
        "from_file",
        lambda _path: parameters,
    )
    messages = []
    monkeypatch.setattr(
        workspace_file_flows.QMessageBox,
        "critical",
        lambda _parent, _title, text: messages.append(text),
    )

    with pytest.raises(RuntimeError, match="controller invariant"):
        workspace_file_flows.load_input_parameters(
            Controller(), object(), tmp_path / "Fe.inp", None
        )
    assert messages == []


def test_workspace_output_load_does_not_hide_controller_error(
    monkeypatch, tmp_path, application
):
    loaded = object()

    class Controller:
        generation = 1

        def adopt_external_result(self, *_args, **_kwargs):
            raise RuntimeError("controller invariant")

    monkeypatch.setattr(
        workspace_file_flows, "load_result_file", lambda _path: loaded
    )
    messages = []
    monkeypatch.setattr(
        workspace_file_flows.QMessageBox,
        "critical",
        lambda _parent, _title, text: messages.append(text),
    )

    with pytest.raises(RuntimeError, match="controller invariant"):
        workspace_file_flows.load_output(
            Controller(), object(), tmp_path / "Fe.out", None
        )
    assert messages == []


def test_workspace_structure_save_does_not_hide_controller_error(
    monkeypatch, tmp_path, application
):
    path = tmp_path / "Fe.xyz"

    class Controller:
        @property
        def atoms(self):
            raise RuntimeError("controller invariant")

    monkeypatch.setattr(
        workspace_file_flows.QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(path), ""),
    )
    messages = []
    monkeypatch.setattr(
        workspace_file_flows.QMessageBox,
        "critical",
        lambda _parent, _title, text: messages.append(text),
    )

    with pytest.raises(RuntimeError, match="controller invariant"):
        workspace_file_flows.save_structure(Controller(), object(), None)
    assert messages == []


def test_workspace_file_loads_still_report_backend_errors(
    monkeypatch, tmp_path, application
):
    controller = type("Controller", (), {
        "structure_generation": object(),
        "input_parameters_generation": object(),
        "directory_generation": object(),
    })()
    messages = []
    monkeypatch.setattr(
        workspace_file_flows.QMessageBox,
        "critical",
        lambda _parent, _title, text: messages.append(text),
    )

    monkeypatch.setattr(
        workspace_file_flows,
        "ase_read",
        lambda _path: _raise(RuntimeError("structure parse")),
    )
    assert not workspace_file_flows.load_structure(
        controller, object(), tmp_path / "Fe.cif", None
    )

    monkeypatch.setattr(
        workspace_file_flows.InputParameters,
        "from_file",
        lambda _path: _raise(RuntimeError("input parse")),
    )
    assert not workspace_file_flows.load_input_parameters(
        controller, object(), tmp_path / "Fe.inp", None
    )

    monkeypatch.setattr(
        workspace_file_flows,
        "load_result_file",
        lambda _path: _raise(RuntimeError("output parse")),
    )
    assert not workspace_file_flows.load_output(
        controller, object(), tmp_path / "Fe.out", None
    )

    assert messages == [
        "Failed to load structure:\nstructure parse",
        "Failed to load input parameters:\ninput parse",
        "Failed to load SPR-KKR output:\noutput parse",
    ]


class _ValidationParameters:
    task_name = "scf"

    def __init__(self, error):
        self.error = error

    def validate(self, **_kwargs):
        raise self.error

    def __contains__(self, _name):
        return False


def test_validate_setup_wraps_expected_validation_error():
    parameters = _ValidationParameters(DataValidityError("bad value"))

    with pytest.raises(InputParametersValidationError, match="bad value"):
        validate_setup(parameters)


def test_validate_setup_does_not_hide_programming_error():
    parameters = _ValidationParameters(RuntimeError("validation bug"))

    with pytest.raises(RuntimeError, match="validation bug"):
        validate_setup(parameters)
