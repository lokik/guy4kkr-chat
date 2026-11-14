import gc
import os
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from ase2sprkkr_gui.gui.widgets.input_parameters.commit import (
    EditorCommit,
    EditorValidationError,
)


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_editor_commit_reports_explicit_validation_error(application):
    widget = QWidget()
    value = {"current": "old"}

    def read_value():
        return value["current"]

    def apply_value(_draft):
        raise EditorValidationError("invalid user value")

    commit = EditorCommit(widget, read_value, apply_value)
    value["current"] = "draft"

    assert not commit.commit()
    assert commit.error == "invalid user value"
    assert widget.toolTip() == "invalid user value"


def test_editor_commit_does_not_hide_apply_programming_error(application):
    widget = QWidget()
    value = {"current": "old"}

    def read_value():
        return value["current"]

    def apply_value(_draft):
        raise RuntimeError("session invariant")

    commit = EditorCommit(widget, read_value, apply_value)
    value["current"] = "draft"

    with pytest.raises(RuntimeError, match="session invariant"):
        commit.commit()

    assert commit.error == ""
    assert widget.toolTip() == ""


def test_editor_commit_does_not_retain_bound_callback_target(application):
    class CallbackOwner:
        def read_value(self):
            return "old"

        def apply_value(self, _draft):
            pass

    widget = QWidget()
    owner = CallbackOwner()
    owner_ref = weakref.ref(owner)
    commit = EditorCommit(widget, owner.read_value, owner.apply_value)

    del owner
    gc.collect()

    assert owner_ref() is None
    with pytest.raises(RuntimeError, match="callback target no longer exists"):
        commit.refresh()
