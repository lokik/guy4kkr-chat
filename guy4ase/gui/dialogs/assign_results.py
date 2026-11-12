"""Choose or create a project to hold selected imported results."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QInputDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from guy4ase.gui.application.imported_project_results import assign


class AssignResultsDialog(QDialog):
    def __init__(self, projects, count: int, parent=None):
        super().__init__(parent)
        self.projects = projects
        self.setWindowTitle("Assign results to project")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Assign {count} selected result(s) to:", self))
        form = QFormLayout()
        self.project = QComboBox(self)
        form.addRow("Project:", self.project)
        layout.addLayout(form)
        self.new_button = QPushButton("New project…", self)
        self.new_button.clicked.connect(self._new_project)
        layout.addWidget(self.new_button)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel, self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate()

    def _populate(self, selected=None):
        self.project.clear()
        for project in sorted(self.projects.projects(), key=lambda p: p.name.casefold()):
            self.project.addItem(project.name, project.id)
        if selected is not None:
            index = self.project.findData(selected)
            if index >= 0:
                self.project.setCurrentIndex(index)

    def _new_project(self):
        name, ok = QInputDialog.getText(self, "New project", "Project name:")
        if not ok or not name.strip():
            return
        try:
            project = self.projects.create(name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot create project", str(exc))
            return
        self._populate(project.id)

    def accept(self):
        if self.project.currentData() is None:
            QMessageBox.warning(self, "Select project", "Choose or create a project.")
            return
        super().accept()


def assign_results_to_project(projects, result_store, result_ids, parent=None) -> bool:
    records = []
    for result_id in result_ids:
        try:
            records.append(result_store.result(result_id))
        except KeyError:
            continue
    if not records:
        return False
    dialog = AssignResultsDialog(projects, len(records), parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    try:
        assigned = assign(projects, records, dialog.project.currentData())
    except (OSError, ValueError, KeyError) as exc:
        QMessageBox.warning(parent, "Cannot assign results", str(exc))
        return False
    QMessageBox.information(
        parent, "Project assignment",
        f"Assigned {assigned} result(s) to {dialog.project.currentText()}.",
    )
    return True
