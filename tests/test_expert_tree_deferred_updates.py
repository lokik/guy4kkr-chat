"""Lifecycle coverage for deferred Expert-tree updates."""
from __future__ import annotations

from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.dialogs.expert_input import InputParametersDialog


def test_deferred_updates_are_owned_by_expert_editor() -> None:
    application = QApplication.instance()
    assert application is not None

    parameters = InputParameters.create("scf")
    parameters.MODE.SOC.set({"def": 1.0})
    dialog = InputParametersDialog(parameters)
    editor = dialog.tree_editor

    dialog.session.set_value(("MODE", "SOC"), {"def": 0.8, 2: 0.4})

    assert editor._session_update_timer.isActive()
    assert editor._session_update_timer.parent() is editor
    assert editor._append_focus_timer.parent() is editor

    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(dialog)

    # A deferred refresh from a destroyed editor must not survive in the global
    # event queue and run against deleted QTreeWidget/QTreeWidgetItem objects.
    application.processEvents()
