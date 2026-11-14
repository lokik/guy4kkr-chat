"""Choose or create a project to hold selected imported results."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QInputDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from ase2sprkkr_gui.gui.application.imported_project_results import assign


class AssignResultsDialog(QDialog):
    def __init__(
        self, projects, count: int, parent=None, *,
        item_description: str = "result(s)", allow_unassigned: bool = False,
    ):
        super().__init__(parent)
        self.projects = projects
        self.allow_unassigned = allow_unassigned
        self.setWindowTitle("Move calculation records" if allow_unassigned else "Assign results to project")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Assign {count} selected {item_description} to:", self))
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
        if allow_unassigned:
            # Moving historical records requires an explicit destination choice.
            self.project.setCurrentIndex(-1)

    def _populate(self, selected=None):
        self.project.clear()
        if self.allow_unassigned:
            self.project.addItem("(Unassigned)", None)
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
        if self.project.currentIndex() < 0 or (
            self.project.currentData() is None and not self.allow_unassigned
        ):
            QMessageBox.warning(self, "Select project", "Choose or create a project.")
            return
        super().accept()


def assign_results_to_project(
    projects, result_store, result_ids, parent=None, *, run_source=None
) -> bool:
    """Assign results via their real run records or external file references.

    A tracked result changes its existing KKRunner project; an external result
    creates or updates a file reference. Never duplicate an executed run as an
    "imported" entry in the project history.
    """
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
    destination = dialog.project.currentData()
    tracked_ids = set()
    external = []
    for record in records:
        ref_id = record.persistent_ref
        job = (
            run_source.job(ref_id)
            if ref_id is not None and run_source is not None else None
        )
        if job is not None and job.imported_path is None:
            tracked_ids.add(ref_id)
        else:
            external.append(record)
    if any(record.output_path is None for record in external):
        QMessageBox.warning(
            parent, "Cannot assign results",
            "Some selected results have no output file. Only file-backed "
            "results can be assigned without a tracked calculation record.",
        )
        return False

    try:
        if tracked_ids:
            run_source.reassign_runs(
                projects, tuple(sorted(tracked_ids)), destination,
                expected_project_ids={
                    ref_id: run_source.job(ref_id).project_id
                    for ref_id in tracked_ids
                },
            )
        assigned = assign(projects, external, destination) if external else 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        QMessageBox.warning(parent, "Cannot assign results", str(exc))
        return False
    if not assigned and not tracked_ids:
        QMessageBox.warning(parent, "Cannot assign results", "No file-backed results selected.")
        return False
    QMessageBox.information(
        parent, "Project assignment",
        f"Assigned {assigned + len(tracked_ids)} result(s) to {dialog.project.currentText()}.",
    )
    return True
