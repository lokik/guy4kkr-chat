"""A scrollable, explicit confirmation of record and local-file deletion."""
from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.application.run_file_deletion import FileDeletionPlan


def _last_modified(path: str, *, remote: bool = False, modified_ns: int | None = None) -> str:
    """Display a portable local timestamp, not the Linux inode change time."""
    if remote:
        return "— (remote)"
    if modified_ns is not None:
        timestamp = modified_ns / 1_000_000_000
    else:
        try:
            timestamp = os.stat(path, follow_symlinks=False).st_mtime
        except OSError:
            return "—"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


class DeleteRunRecordDialog(QDialog):
    """List every affected file *before* an irreversible deletion.

    Removing the history record is the default. Files are removed only after
    checking an additional, initially unchecked option. Remote and shared files
    are always shown as kept, never silently included in a deletion.
    """

    def __init__(
        self,
        job: PersistentJob,
        plan: FileDeletionPlan | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        imported = job.imported_path is not None
        self._action_label = "Remove reference" if imported else "Delete run record"
        self.setWindowTitle(
            "Remove imported result?" if imported else "Delete calculation record?"
        )
        self.resize(950, 540)
        self.setMinimumWidth(700)

        root = QVBoxLayout(self)
        header = QLabel(
            f"Remove the project reference to {job.imported_path}?"
            if imported
            else f"Permanently delete the run record for "
                 f"{job.dataset or job.id} ({job.id})?",
            self,
        )
        header.setWordWrap(True)
        root.addWidget(header)

        if not job.is_final:
            warning = QLabel(
                "WARNING: This calculation might still be running. Removing the "
                "record does not stop its process. File deletion is unavailable "
                "for an active or unknown run.",
                self,
            )
            warning.setWordWrap(True)
            root.addWidget(warning)

        summary = QLabel(
            "The record/reference will be removed. Files are kept unless you "
            "explicitly enable deletion below. The table lists every referenced "
            "file and its last-modified date (local time); creation dates are "
            "not reliably available on all operating systems.",
            self,
        )
        summary.setWordWrap(True)
        root.addWidget(summary)

        self.file_table = QTreeWidget(self)
        self.file_table.setObjectName("referenced_files")
        self.file_table.setColumnCount(3)
        self.file_table.setHeaderLabels(
            ("Referenced file", "Last modified (local time)", "Action")
        )
        self.file_table.setRootIsDecorated(False)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.setUniformRowHeights(True)
        self.file_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.file_table.setSortingEnabled(False)
        table_header = self.file_table.header()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.file_table, 1)

        self._eligible_rows: list[QTreeWidgetItem] = []
        if plan is not None:
            snapshots = {item.path: item for item in plan.snapshots}
            groups = (
                (plan.files, "Eligible — keep", "Eligible for local deletion", False, True),
                (plan.shared, "Keep — shared", "Referenced by another run or imported result", False, False),
                (plan.unsafe, "Keep — unsafe", "Symlink, directory, or other non-regular file", False, False),
                (plan.missing, "Missing", "File does not exist", False, False),
                (plan.remote, "Keep — remote", "Remote files are not deleted here", True, False),
            )
            for paths, action, reason, remote, eligible in groups:
                for filename in paths:
                    snapshot = snapshots.get(filename)
                    row = QTreeWidgetItem(
                        [filename, _last_modified(
                            filename, remote=remote,
                            modified_ns=None if snapshot is None else snapshot.modified_ns,
                        ), action]
                    )
                    row.setToolTip(0, filename)
                    row.setToolTip(2, reason)
                    self.file_table.addTopLevelItem(row)
                    if eligible:
                        self._eligible_rows.append(row)
        if not self.file_table.topLevelItemCount():
            self.file_table.addTopLevelItem(
                QTreeWidgetItem(["(no referenced local files to review)", "—", "Keep"])
            )

        self.delete_files_checkbox = QCheckBox(
            "Also permanently delete the eligible local files", self,
        )
        self.delete_files_checkbox.setChecked(False)
        self.delete_files_checkbox.setEnabled(
            plan is not None and job.is_final and bool(plan.files)
        )
        self.delete_files_checkbox.toggled.connect(self._update_file_actions)
        root.addWidget(self.delete_files_checkbox)

        count = len(self._eligible_rows)
        self._count_label = QLabel(
            f"{count} local file(s) eligible for deletion. All other rows will be kept.",
            self,
        )
        self._count_label.setWordWrap(True)
        root.addWidget(self._count_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self.confirm_button = buttons.addButton(
            self._action_label,
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.confirm_button.setAutoDefault(False)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @property
    def delete_files(self) -> bool:
        return self.delete_files_checkbox.isEnabled() and self.delete_files_checkbox.isChecked()

    def _update_file_actions(self, checked: bool) -> None:
        for row in self._eligible_rows:
            row.setText(2, "Delete permanently" if checked else "Eligible — keep")
        self.confirm_button.setText(
            self._action_label
            + (f" and {len(self._eligible_rows)} file(s)" if checked else "")
        )
