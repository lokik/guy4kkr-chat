"""Shared editor for a project's name and optional working directory."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)


class ProjectEditDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, name: str = "",
                 directory: str | None = None, title: str = "Edit Project") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(self)
        self.name_edit.setText(name)
        form.addRow("Name:", self.name_edit)
        row = QHBoxLayout()
        self.directory_edit = QLineEdit(self)
        self.directory_edit.setText(directory or "")
        self.directory_edit.setPlaceholderText("Optional project working directory")
        row.addWidget(self.directory_edit)
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._browse_directory)
        row.addWidget(browse)
        form.addRow("Directory:", row)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def project_name(self) -> str:
        return self.name_edit.text().strip()

    def project_directory(self) -> str | None:
        value = self.directory_edit.text().strip()
        return str(Path(value).expanduser().resolve()) if value else None

    def _browse_directory(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Project Working Directory",
            self.project_directory() or str(Path.home()),
        )
        if chosen:
            self.directory_edit.setText(chosen)

    def accept(self) -> None:
        if not self.project_name():
            QMessageBox.warning(self, "Project Name", "Project name must not be empty.")
            return
        super().accept()
