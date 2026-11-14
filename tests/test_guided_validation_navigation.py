import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

import pytest
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.dialogs import guided_input
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.input_parameters.validation import (
    InputParametersValidationError,
    validate_setup,
)


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_validate_setup_exposes_structured_energy_path():
    parameters = InputParameters.create("scf")
    parameters.ENERGY.EMINEV = -3.0

    with pytest.raises(InputParametersValidationError) as exc_info:
        validate_setup(parameters)

    assert exc_info.value.path == ("ENERGY", "EMIN")


def test_guided_model_error_navigates_by_structured_path(
    monkeypatch, application
):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    selected_pages = []
    messages = []
    monkeypatch.setattr(dialog, "select_page", selected_pages.append)
    monkeypatch.setattr(
        guided_input.QMessageBox,
        "critical",
        lambda _parent, _title, text: messages.append(text),
    )

    path = ("SCF", "MIX")
    dialog._show_model_error(
        InputParametersValidationError(
            "The wording deliberately does not name the option.",
            path,
        )
    )

    assert selected_pages == [dialog.form.primary_pages[path]]
    assert messages == ["The wording deliberately does not name the option."]
    dialog.close()


def test_guided_model_error_does_not_infer_path_from_message(
    monkeypatch, application
):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    selected_pages = []
    monkeypatch.setattr(dialog, "select_page", selected_pages.append)
    monkeypatch.setattr(
        guided_input.QMessageBox,
        "critical",
        lambda *_args: None,
    )

    dialog._show_model_error(
        InputParametersValidationError("SCF.MIX appears only in human-readable text")
    )

    assert selected_pages == []
    dialog.close()
