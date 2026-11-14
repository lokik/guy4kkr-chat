from ase2sprkkr.input_parameters.input_parameters import InputParameters

from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession


def test_working_parameters_are_borrowed_but_result_is_detached():
    session = InputParametersSession(InputParameters.create("scf"))
    borrowed = session.working_parameters
    detached = session.result()
    original = borrowed.SCF.NITER()

    assert borrowed is session.working_parameters
    assert detached is not borrowed

    detached.SCF.NITER.set(original + 1)

    assert session.working_parameters.SCF.NITER() == original
