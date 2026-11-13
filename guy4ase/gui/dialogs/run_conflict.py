"""A file-conflict decision for a new tracked calculation."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)


class SubmissionConflictDialog(QDialog):
    """Show the existing runs and file accesses supplied by KKRunner.

    A conflict is a rejected preflight reservation, not a failed calculation.
    No existing job is stopped until the user explicitly chooses that action.
    """

    STOP_EXISTING = 1

    def __init__(self, conflict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Files in use by another calculation")
        self.resize(820, 450)

        layout = QVBoxLayout(self)
        summary = QLabel(
            "The new calculation was not started because existing jobs use "
            "some of the same files. Running both could overwrite inputs or results.",
            self,
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        self.details = QTreeWidget(self)
        self.details.setHeaderLabels(("Job / file", "Status / access"))
        self.details.setAlternatingRowColors(True)
        self.details.setRootIsDecorated(True)
        for record in conflict.conflicts:
            metadata = record.metadata.get("ase2sprkkr", {})
            name = metadata.get("dataset") or record.id[:12]
            task = metadata.get("task")
            title = f"{name} ({task})" if task else str(name)
            title += f" · {record.id[:12]}"
            state = record.state.value
            parent_item = QTreeWidgetItem(self.details, (title, str(state)))
            parent_item.setToolTip(0, f"Run ID: {record.id}\nProject: {record.project_id or 'Unassigned'}")
            details = conflict.file_conflicts.get(record.id, ())
            if not details:
                QTreeWidgetItem(parent_item, ("Overlapping declared files", "Details unavailable"))
            # Local jobs can report the same overlap twice (local/target).
            seen = set()
            for item in details:
                pair = (item.first_path, item.first_access, item.second_path, item.second_access)
                if pair in seen:
                    continue
                seen.add(pair)
                new_access = "writes" if item.first_access == "write" else "reads"
                old_access = "writes" if item.second_access == "write" else "reads"
                same_path = item.first_path == item.second_path
                description = item.first_path if same_path else (
                    f"{item.first_path} ↔ {item.second_path}"
                )
                file_item = QTreeWidgetItem(
                    parent_item,
                    (f"{item.namespace}: {description}",
                     f"New {new_access}; existing {old_access}"),
                )
                file_item.setToolTip(0, description)
        self.details.expandAll()
        self.details.header().setStretchLastSection(False)
        self.details.setColumnWidth(0, 590)
        layout.addWidget(self.details, 1)

        caution = QLabel(
            "Stopping existing jobs may interrupt their results. If every "
            "job is confirmed stopped, the new calculation will start. "
            "If cancellation is pending, the new calculation will remain unstarted. "
            "An Unknown status does not guarantee that a job has stopped.",
            self,
        )
        caution.setWordWrap(True)
        layout.addWidget(caution)

        buttons = QDialogButtonBox(self)
        self.stop_button = buttons.addButton(
            "Stop conflicting jobs", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.keep_button = buttons.addButton(
            "Keep existing jobs — edit new calculation", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.stop_button.clicked.connect(lambda: self.done(self.STOP_EXISTING))
        self.keep_button.clicked.connect(self.reject)
        self.keep_button.setDefault(True)
        layout.addWidget(buttons)


class CancellationFailureDialog(QDialog):
    """Let the user explicitly select failed jobs to forget from history.

    The run records are not processes: removing one cannot establish that a
    remote/native process has stopped. Selection and confirmation are required.
    """

    REMOVE_SELECTED = 1

    def __init__(self, errors, *, pending=(), parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Could not stop conflicting jobs")
        self.resize(850, 400)

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "The new calculation has not started. The following cancellations "
            "failed. You can keep the records or remove selected jobs from "
            "the project history.",
            self,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.jobs = QTreeWidget(self)
        self.jobs.setHeaderLabels(("Job", "Why cancellation failed"))
        self.jobs.setAlternatingRowColors(True)
        self.jobs.setColumnWidth(0, 330)
        for record, reason in errors:
            if record is None:
                item = QTreeWidgetItem(self.jobs, ("Cancellation service", str(reason)))
                item.setToolTip(1, str(reason))
                continue

            metadata = record.metadata.get("ase2sprkkr", {})
            name = metadata.get("dataset") or record.id[:12]
            task = metadata.get("task")
            label = f"{name} ({task})" if task else str(name)
            item = QTreeWidgetItem(
                self.jobs, (f"{label} · {record.id[:12]}", str(reason))
            )
            item.setData(0, Qt.ItemDataRole.UserRole, record.id)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setToolTip(0, f"Run ID: {record.id}")
            item.setToolTip(1, str(reason))
        layout.addWidget(self.jobs, 1)

        if pending:
            note = QLabel(
                f"Cancellation is still unconfirmed for {len(pending)} other "
                "job(s). Their records are not selected for removal.",
                self,
            )
            note.setWordWrap(True)
            layout.addWidget(note)

        warning = QLabel(
            "DANGER: Removing a job record does NOT stop its process or remove "
            "its output files. The process might still be writing to those "
            "files. The new calculation will NOT start automatically, even "
            "after the record is removed.",
            self,
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        buttons = QDialogButtonBox(self)
        self.remove_button = buttons.addButton(
            "Remove selected records…", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.keep_button = buttons.addButton(
            "Keep records", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.remove_button.setEnabled(False)
        self.keep_button.setDefault(True)
        self.keep_button.clicked.connect(self.reject)
        self.remove_button.clicked.connect(self._confirm_removal)
        self.jobs.itemChanged.connect(self._update_selection)
        layout.addWidget(buttons)

    def selected_job_ids(self) -> tuple[str, ...]:
        return tuple(
            str(item.data(0, Qt.ItemDataRole.UserRole))
            for index in range(self.jobs.topLevelItemCount())
            for item in (self.jobs.topLevelItem(index),)
            if item.data(0, Qt.ItemDataRole.UserRole) is not None
            and item.checkState(0) == Qt.CheckState.Checked
        )

    def _update_selection(self, _item, _column) -> None:
        self.remove_button.setEnabled(bool(self.selected_job_ids()))

    def _confirm_removal(self) -> None:
        selected = self.selected_job_ids()
        if not selected:
            return
        response = QMessageBox.warning(
            self,
            "Permanently remove job records?",
            f"Remove {len(selected)} selected job record(s) from history?\n\n"
            "THIS DOES NOT STOP THEIR PROCESSES. Those jobs may still run "
            "and write to the same files. Output files remain on disk.\n\n"
            "The new calculation will remain unstarted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if response == QMessageBox.StandardButton.Yes:
            self.done(self.REMOVE_SELECTED)
