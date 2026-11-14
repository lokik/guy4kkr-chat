"""Floating-point text input."""
from typing import Optional

from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import QLineEdit, QWidget


class QDoubleEdit(QLineEdit):

      def __init__(self, min_val: float, max_val: float, decimals: int, parent: Optional[QWidget] = None):
           super().__init__(parent)
           validator = QDoubleValidator(min_val, max_val, decimals, self)
           validator.setNotation(QDoubleValidator.Notation.StandardNotation)

      def value(self)->Optional[float]:
           try:
               return float(self.text())
           except ValueError:
               return None
