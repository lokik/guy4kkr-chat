from __future__ import annotations

import pytest
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from ase2sprkkr_gui.gui.input_parameters.validation import validate_setup


def test_validate_setup_uses_effective_task_for_arpes_checks():
    parameters = InputParameters.create("SPLEED")
    assert parameters.task_name.upper() == "SPLEED"

    parameters.TASK.TASK = "ARPES"
    parameters.SPEC_EL.THETA = [-20.0, 20.0]

    assert parameters.task_definition.name.upper() == "ARPES"
    with pytest.raises(ValueError, match="consistent angular scan"):
        validate_setup(parameters)


def test_validate_setup_does_not_apply_arpes_checks_to_effective_spleed():
    parameters = InputParameters.create("ARPES")
    assert parameters.task_name.upper() == "ARPES"

    parameters.TASK.TASK = "SPLEED"
    parameters.SPEC_EL.THETA = [-20.0, 20.0]

    assert parameters.task_definition.name.upper() == "SPLEED"
    validate_setup(parameters)
