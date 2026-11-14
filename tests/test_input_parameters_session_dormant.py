"""Regressions for transactional input-parameter session state."""
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession
from ase2sprkkr_gui.gui.input_parameters.single_site_contour import SingleSiteContourPlugin

_NE = ("ENERGY", "NE")
_SPLITSS = ("ENERGY", "SPLITSS")


def _session() -> InputParametersSession:
    return InputParametersSession(
        InputParameters.create("scf"),
        plugins=(SingleSiteContourPlugin(),),
    )


def _remember_secondary_ne(session: InputParametersSession, value: int = 87) -> None:
    session.set_value(_SPLITSS, True)
    ne = list(session.value(_NE))
    ne[1] = value
    session.set_value(_NE, ne)
    session.set_value(_SPLITSS, False)
    assert session.display_value(_NE, 1) == value


def test_replace_parameters_discards_dormant_state() -> None:
    session = _session()
    _remember_secondary_ne(session)

    replacement = InputParameters.create("scf")
    assert session.replace_parameters(replacement)
    assert session.display_value(_NE, 1) is None

    session.set_value(_SPLITSS, True)
    ne = session.value(_NE)
    assert ne[1] == ne[0]
    assert ne[1] != 87


def test_replace_parameters_undo_restores_previous_dormant_state() -> None:
    session = _session()
    _remember_secondary_ne(session)

    replacement = InputParameters.create("scf")
    replacement.SCF.NITER.set(replacement.SCF.NITER() + 1)
    assert session.replace_parameters(replacement)
    assert session.display_value(_NE, 1) is None

    session.undo_stack.undo()
    assert session.display_value(_NE, 1) == 87

    session.undo_stack.redo()
    assert session.display_value(_NE, 1) is None


def test_replace_from_session_preserves_dormant_state() -> None:
    source = _session()
    _remember_secondary_ne(source)
    target = _session()

    assert target.replace_from_session(source)
    assert target.display_value(_NE, 1) == 87
