import pytest

from ase2sprkkr_gui.gui.input_parameters.bindings import values_equal


def test_values_equal_propagates_equality_errors():
    class BrokenEquality:
        def __eq__(self, other):
            raise RuntimeError("broken equality")

    with pytest.raises(RuntimeError, match="broken equality"):
        values_equal(BrokenEquality(), BrokenEquality())
