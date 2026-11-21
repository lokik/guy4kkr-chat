"""Shared frameless section headings for the structure editor."""
from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ase2sprkkr_gui.gui.style import SPACE_SM, heading_font


class EditorSection(QWidget):
    """Section heading plus content, without an enclosing frame."""

    def __init__(self, title: str, parent=None, *, layout_type=QVBoxLayout):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, SPACE_SM, 0, SPACE_SM)
        root.setSpacing(SPACE_SM)

        self.heading = QLabel(title, self)
        self.heading.setObjectName("structureEditorSectionHeading")
        font = heading_font(self.heading.font(), "section")
        font.setBold(True)
        self.heading.setFont(font)
        root.addWidget(self.heading)

        self.content = QWidget(self)
        self.content_layout = layout_type(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.content)

    def title(self) -> str:
        return self.heading.text()

    def setTitle(self, title: str) -> None:
        self.heading.setText(title)
