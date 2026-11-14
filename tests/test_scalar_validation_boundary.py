import pytest
from ase2sprkkr.common.warnings import DataValidityError

from ase2sprkkr_gui.gui.input_parameters.field_binding import FieldValue
from ase2sprkkr_gui.gui.widgets.input_parameters.scalar import IntegerEditor


def _editor(apply_value):
    value = {"current": 200}
    editor = IntegerEditor(nullable=False)
    editor.setRange(0, 1000)
    editor.bind(lambda: FieldValue(value["current"]), apply_value)
    return editor


def test_scalar_editor_reports_backend_data_validation_inline():
    def reject(_value):
        raise DataValidityError("NE must be at least 2")

    editor = _editor(reject)
    editor.setValue(1)

    assert not editor.commit()
    assert "NE must be at least 2" in editor.toolTip()


def test_scalar_editor_does_not_hide_programming_error():
    def broken(_value):
        raise RuntimeError("session invariant")

    editor = _editor(broken)
    editor.setValue(1)

    with pytest.raises(RuntimeError, match="session invariant"):
        editor.commit()
