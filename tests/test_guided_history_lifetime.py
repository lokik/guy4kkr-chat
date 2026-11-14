from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog


def test_deferred_history_navigation_dies_with_dialog():
    """A closed dialog must not leave a callback for a deleted Qt wrapper."""
    dialog = GuidedInputParametersDialog("bsf", InputParameters.create("bsfek"))
    calls = []
    dialog._reveal_history_field = lambda *args: calls.append(args)

    assert dialog.session.set_value(("ENERGY", "EMIN"), 0.25)
    dialog.session.undo_stack.undo()
    assert dialog._history_navigation_timer.isActive()

    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.instance().processEvents()

    assert calls == []
