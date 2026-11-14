import pytest

from ase2sprkkr.input_parameters.input_parameters import InputParameters

from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession


def test_is_changed_propagates_type_comparator_errors(monkeypatch):
    session = InputParametersSession(InputParameters.create("dos"))
    path = ("ENERGY", "NE")
    value_type = session.option(path)._definition.type

    def broken_comparator(left, right):
        raise RuntimeError("broken type comparator")

    monkeypatch.setattr(value_type, "is_the_same_value", broken_comparator)

    with pytest.raises(RuntimeError, match="broken type comparator"):
        session.is_changed(path)


def test_is_changed_compares_numbered_values_per_occurrence():
    session = InputParametersSession(InputParameters.create("arpes"))

    assert not session.is_changed(("SPEC_EL", "THETA"))
