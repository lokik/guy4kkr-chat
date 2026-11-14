"""Interactive resolution of competing calculation file reservations."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)


class SubmissionConflictDialog(QDialog):
    """Stay open until the user chooses Calculate or returns to run setup.

    Job actions are delegated to the monitor rather than performed on the GUI
    thread. A new reservation remains subject to KKRunner's normal atomic
    conflict check, including conflicts created while this dialog was open.
    """

    actionRequested = pyqtSignal(str, object)

    def __init__(self, conflict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Files in use by another calculation")
        self.resize(860, 520)
        self._conflict = conflict
        self._busy = False
        self._verified = True
        self._manual_override = False
        self._errors: dict[str, str] = {}

        layout = QVBoxLayout(self)
        introduction = QLabel(
            "Other recorded calculations reserve files needed by this run. "
            "Select jobs to stop, mark failed or delete their records. "
            "The window stays open until you choose Cancel or Calculate.",
            self,
        )
        introduction.setWordWrap(True)
        layout.addWidget(introduction)

        self.details = QTreeWidget(self)
        self.details.setHeaderLabels(("Conflicting job / file", "Status / access"))
        self.details.setAlternatingRowColors(True)
        self.details.setRootIsDecorated(True)
        self.details.setColumnWidth(0, 595)
        self.details.itemChanged.connect(self._update_buttons)
        layout.addWidget(self.details, 1)

        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        caution = QLabel(
            "Mark failed and Delete record change stored history ONLY. Neither "
            "action stops a process. A job with Unknown status may still be "
            "writing to these files. Calculate will require confirmation if "
            "you manually clear any reservation.",
            self,
        )
        caution.setWordWrap(True)
        layout.addWidget(caution)

        actions = QDialogButtonBox(self)
        self.stop_button = actions.addButton(
            "Stop selected jobs", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.failed_button = actions.addButton(
            "Mark failed…", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.delete_button = actions.addButton(
            "Delete records…", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.refresh_button = actions.addButton(
            "Refresh", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.cancel_button = actions.addButton(
            "Cancel — edit run setup", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.calculate_button = actions.addButton(
            "Calculate", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.cancel_button.setDefault(True)
        self.stop_button.clicked.connect(lambda: self._request("stop"))
        self.failed_button.clicked.connect(lambda: self._request("fail"))
        self.delete_button.clicked.connect(lambda: self._request("delete"))
        self.refresh_button.clicked.connect(lambda: self._request("refresh"))
        self.cancel_button.clicked.connect(self.reject)
        self.calculate_button.clicked.connect(self._calculate)
        layout.addWidget(actions)

        self.set_conflicts(conflict)

    @property
    def proposed_record(self):
        return self._conflict.record

    def selected_ids(self) -> tuple[str, ...]:
        return tuple(
            item.data(0, Qt.ItemDataRole.UserRole)
            for index in range(self.details.topLevelItemCount())
            for item in (self.details.topLevelItem(index),)
            if item.checkState(0) == Qt.CheckState.Checked
        )

    def set_conflicts(self, conflict, *, errors=None, manually_changed=False) -> None:
        """Replace the live blocker list, retaining checked jobs that remain."""
        selected = set(self.selected_ids()) if self.details.topLevelItemCount() else set()
        self._conflict = conflict
        self._verified = True
        self._manual_override |= manually_changed
        self._errors = dict(errors or {})
        self.details.blockSignals(True)
        self.details.clear()
        for record in conflict.conflicts:
            metadata = record.metadata.get("ase2sprkkr", {})
            dataset = metadata.get("dataset") or record.id[:12]
            task = metadata.get("task")
            title = f"{dataset} ({task})" if task else str(dataset)
            parent_item = QTreeWidgetItem(
                self.details, (f"{title} · {record.id[:12]}", str(record.state.value))
            )
            parent_item.setData(0, Qt.ItemDataRole.UserRole, record.id)
            parent_item.setCheckState(
                0, Qt.CheckState.Checked if record.id in selected else Qt.CheckState.Unchecked
            )
            parent_item.setToolTip(
                0, f"Run ID: {record.id}\nProject: {record.project_id or 'Unassigned'}"
            )
            if record.id in self._errors:
                QTreeWidgetItem(parent_item, ("Operation failed", self._errors[record.id]))
            overlaps = conflict.file_conflicts.get(record.id, ())
            if not overlaps:
                QTreeWidgetItem(parent_item, ("Overlapping files", "Details unavailable"))
            seen = set()
            for item in overlaps:
                key = (item.first_path, item.first_access, item.second_path, item.second_access)
                if key in seen:
                    continue
                seen.add(key)
                new_access = "writes" if item.first_access == "write" else "reads"
                old_access = "writes" if item.second_access == "write" else "reads"
                paths = (item.first_path if item.first_path == item.second_path else
                         f"{item.first_path} ↔ {item.second_path}")
                entry = QTreeWidgetItem(
                    parent_item,
                    (f"{item.namespace}: {paths}", f"New {new_access}; existing {old_access}"),
                )
                entry.setToolTip(0, paths)
        self.details.expandAll()
        self.details.blockSignals(False)
        if self._errors:
            self.status_label.setText(
                "Some operations failed: "
                + "; ".join(f"{key}: {message}" for key, message in self._errors.items())
            )
        elif conflict.conflicts:
            self.status_label.setText(
                f"{len(conflict.conflicts)} unresolved job conflict(s). "
                "Select jobs to resolve, or Refresh to recheck their status."
            )
        else:
            self.status_label.setText(
                "All recorded file conflicts resolved. You may now press Calculate."
            )
        self._update_buttons()

    def set_verification_error(self, errors: dict[str, str]) -> None:
        """Do not approve a launch if the latest reservation check failed."""
        self._verified = False
        self.status_label.setText(
            "Reservation check failed; calculation remains blocked. "
            + "; ".join(f"{key}: {value}" for key, value in errors.items())
        )
        self._update_buttons()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.status_label.setText("Checking or updating existing jobs…")
        self._update_buttons()

    def _update_buttons(self, *_args) -> None:
        selected = bool(self.selected_ids())
        for button in (self.stop_button, self.failed_button, self.delete_button):
            button.setEnabled(not self._busy and selected)
        self.refresh_button.setEnabled(not self._busy)
        self.calculate_button.setEnabled(
            not self._busy and self._verified and not self._conflict.conflicts
        )
        self.cancel_button.setEnabled(not self._busy)

    def _request(self, action: str) -> None:
        if self._busy:
            return
        selected = () if action == "refresh" else self.selected_ids()
        if action != "refresh" and not selected:
            return
        if action in ("fail", "delete"):
            label = "mark failed" if action == "fail" else "delete the records for"
            response = QMessageBox.warning(
                self,
                "Manually clear run reservations?",
                f"Really {label} {len(selected)} selected job(s)?\n\n"
                "THIS DOES NOT STOP THEIR PROCESSES. The old calculations "
                "might still be writing to the same files.\n\n"
                "Manually clearing their reservations may allow new calculations "
                "to overwrite their output files.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if response != QMessageBox.StandardButton.Yes:
                return
        self.set_busy(True)
        self.actionRequested.emit(action, selected)

    def _calculate(self) -> None:
        if self._busy or not self._verified or self._conflict.conflicts:
            return
        if self._manual_override:
            response = QMessageBox.warning(
                self,
                "Original processes may still be running",
                "You marked previous jobs failed or deleted their records. "
                "This does NOT prove their processes have stopped. Starting now "
                "may overwrite files that those processes still use.\n\n"
                "Start the new calculation anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if response != QMessageBox.StandardButton.Yes:
                return
        self.accept()

    def reject(self) -> None:
        if not self._busy:
            super().reject()

    def closeEvent(self, event) -> None:
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)
