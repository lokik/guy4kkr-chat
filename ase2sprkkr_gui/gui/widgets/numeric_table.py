"""Numeric table controls with fractions and lossless editing."""
import math
from fractions import Fraction

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QLineEdit, QStyledItemDelegate, QTableWidget


def coordinate_value(value):
    """Accept decimals, scientific notation and fractions, but not expressions."""
    if value is None or str(value).strip() == "":
        raise ValueError("Enter all coordinates (decimals or fractions such as 1/2).")
    number = float(Fraction(str(value).strip()))
    if not math.isfinite(number):
        raise ValueError("Coordinates must be finite numbers.")
    return number


def coordinate_text(value):
    """Shorten display text only; callers must keep the original numeric edit value."""
    if value is None:
        return ""
    try:
        number = float(value)
    except (ValueError, TypeError):
        return str(value)
    if number == 0:
        return "0"
    return "≈0" if abs(number) < 1e-12 else format(number, ".10g")


class CoordinateDelegate(QStyledItemDelegate):
    """Display compact numbers but edit raw values, retaining invalid text as a draft."""
    invalid = pyqtSignal(str)

    def displayText(self, value, locale):
        return coordinate_text(value)

    def createEditor(self, parent, option, index):
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        value = index.data(Qt.ItemDataRole.EditRole)
        editor.setText("" if value is None else str(value))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        try:
            number = coordinate_value(editor.text())
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            self.invalid.emit(str(exc))
            # Preserve the invalid draft visibly, without changing the session.
            model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)
            return
        model.setData(index, number, Qt.ItemDataRole.EditRole)


class CoordinateTable(QTableWidget):
    copyRequested = pyqtSignal()
    pasteRequested = pyqtSignal()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copyRequested.emit()
        elif event.matches(QKeySequence.StandardKey.Paste):
            self.pasteRequested.emit()
        else:
            super().keyPressEvent(event)
