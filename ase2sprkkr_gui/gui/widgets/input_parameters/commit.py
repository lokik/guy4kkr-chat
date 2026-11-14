"""Common draft/commit boundary for ordinary parameter controls."""
from copy import deepcopy
import weakref

from PyQt6.QtCore import QObject, pyqtSignal

from ase2sprkkr_gui.gui.input_parameters.bindings import values_equal


class EditorValidationError(ValueError):
    """A user-editable draft failed local conversion or validation."""


def _weak_callable(callback):
    """Keep bound callback targets out of the Qt ownership graph."""
    try:
        reference = weakref.WeakMethod(callback)
    except TypeError:
        return callback

    def call(*args, **kwargs):
        target = reference()
        if target is None:
            raise RuntimeError("Editor callback target no longer exists")
        return target(*args, **kwargs)

    return call


class EditorCommit(QObject):
    """Keep presentation drafts separate from storage and report input errors.

    The initial displayed value is a baseline, not a value to write back: it
    may be rounded or clamped. Call refresh only after an intentional model
    refresh. ``apply_value`` errors are programming/model failures and therefore
    propagate; only explicit ``EditorValidationError`` instances are presented
    as invalid user input.

    Qt owns this helper through the editor parent. Bound callbacks are weak so
    the helper does not create a Python cycle back to that parent; otherwise
    cyclic GC may tear down wrapped Qt objects in an unsafe order.
    """

    validationChanged = pyqtSignal(str)

    def __init__(self, widget, read_value, apply_value):
        super().__init__(widget)
        self.read_value = _weak_callable(read_value)
        self.apply_value = _weak_callable(apply_value)
        self.error = ''
        self._shown = deepcopy(self.read_value())

    @property
    def widget(self):
        widget = self.parent()
        if widget is None:
            raise RuntimeError("Editor widget no longer exists")
        return widget

    def refresh(self):
        self._shown = deepcopy(self.read_value())
        self._set_error('')

    def _set_error(self, message):
        self.error = message
        widget = self.widget
        widget.setStyleSheet('border: 2px solid palette(highlight);' if message else '')
        widget.setToolTip(message)
        self.validationChanged.emit(message)

    def commit(self, *_args):
        if not self.widget.isEnabled():
            return True
        try:
            draft = self.read_value()
            if not values_equal(draft, self._shown):
                self.apply_value(draft)
                self._shown = deepcopy(self.read_value())
        except EditorValidationError as error:
            self._set_error(str(error))
            return False
        self._set_error('')
        return True
