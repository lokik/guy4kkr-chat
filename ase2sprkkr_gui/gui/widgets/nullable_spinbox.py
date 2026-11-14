"""Numeric inputs where deleting the text really selects the unset value."""
from PyQt6.QtGui import QValidator
from PyQt6.QtWidgets import QDoubleSpinBox, QSpinBox


class _NullableSpinBox:
    _unset_value = None
    _showing_default = False
    _default_connected = False

    def show_default(self, value, text):
        """Show an effective default as a placeholder, retaining its stepping value."""
        self.setValue(value)
        if not self._default_connected:
            self.lineEdit().textEdited.connect(self._default_edited)
            self._default_connected = True
        self._showing_default = True
        self.lineEdit().setPlaceholderText(text)
        self.lineEdit().clear()

    def _default_edited(self, _text):
        self._showing_default = False

    def is_default_display(self):
        return self._showing_default and not self.lineEdit().text()

    def setValue(self, value):
        self._showing_default = False
        super().setValue(value)

    def stepBy(self, steps):
        self._showing_default = False
        super().stepBy(steps)

    def set_unset_value(self, value):
        self._unset_value = value
        self.setSpecialValueText("Not set")
        self.editingFinished.connect(self._finish_empty)

    def _finish_empty(self):
        if self.is_default_display():
            return
        if not self.cleanText().strip():
            self.setValue(self._unset_value)
            # Qt can leave the line edit blank when the value was already
            # updated to the sentinel during keyboard tracking.
            if self.value() == self._unset_value and not self.is_default_display():
                self.lineEdit().setText(self.specialValueText())

    def validate(self, text, position):
        if (self._unset_value is not None or self._showing_default) and not text.strip():
            return QValidator.State.Acceptable, text, position
        return super().validate(text, position)

    def valueFromText(self, text):
        if self._showing_default and not text.strip():
            return self.value()
        if self._unset_value is not None and not text.strip():
            return self._unset_value
        return super().valueFromText(text)

    def textFromValue(self, value):
        if self._showing_default:
            return ''
        return super().textFromValue(value)

    def keyPressEvent(self, event):
        if (
            self._unset_value is not None
            and self.value() == self._unset_value
            and self.cleanText() == self.specialValueText()
            and event.text()
        ):
            self.lineEdit().setText('')
            self._showing_default = False
            self.lineEdit().insert(event.text())
            try:
                self.setValue(float(self.lineEdit().text()))
            except ValueError:
                pass
            return
        super().keyPressEvent(event)


class NullableSpinBox(_NullableSpinBox, QSpinBox):
    pass


class NullableDoubleSpinBox(_NullableSpinBox, QDoubleSpinBox):
    pass
