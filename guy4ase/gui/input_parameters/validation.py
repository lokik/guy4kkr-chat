"""Completion checks shared by both dialogs, without save-only I/O requirements."""
from __future__ import annotations

from ase2sprkkr.common.warnings import DataValidityError
from ase2sprkkr.input_parameters.definitions.arpes import angular_scan_errors
from ase2sprkkr.input_parameters.definitions._sections import energy_reference_error

from guy4ase.gui.input_parameters.bindings import InputParameterPath


class InputParametersValidationError(ValueError):
    """Validation failure caused by the current editable parameters."""

    def __init__(
        self,
        message: str,
        path: InputParameterPath | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path


def validate_setup(parameters):
    """Validate an accepted edit without requiring calculator-supplied POTFIL."""
    try:
        parameters.validate(why='set')
    except DataValidityError as error:
        raise InputParametersValidationError(str(error)) from error
    errors: list[tuple[str, InputParameterPath]] = []
    if 'ENERGY' in parameters:
        error = energy_reference_error(parameters.ENERGY)
        if error:
            errors.append((error, ('ENERGY', 'EMIN')))
    if parameters.task_definition.name.lower() == 'arpes':
        errors.extend(
            (error, ('SPEC_EL', 'THETA'))
            for error in angular_scan_errors(parameters)
        )
    if errors:
        raise InputParametersValidationError(
            '\n'.join(message for message, _path in errors),
            errors[0][1],
        )
