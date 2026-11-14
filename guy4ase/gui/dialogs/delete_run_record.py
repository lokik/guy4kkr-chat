"""Explicit, per-file confirmation of run history and local-file deletion."""
from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.application.run_file_deletion import (
    FileDeletionPlan, FileDeletionSnapshot, RemoteFileReview,
)


def _last_modified(
    path: str, *, remote: bool = False, modified_ns: int | None = None,
) -> str:
    """Display modification date in local time, not inode change time."""
    if remote and modified_ns is None:
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
    """Let the user select exact local and inspected SSH files individually.

    Remote inspection is asynchronous and optional; an unavailable connection
    never blocks confirmation, local-file deletion, or history removal.
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
        self._plan = plan
        self.setWindowTitle(
            "Remove imported result?" if imported else "Delete calculation record?"
        )
        self.resize(1050, 570)
        self.setMinimumWidth(700)

        root = QVBoxLayout(self)
        heading = QLabel(
            f"Remove the project reference to {job.imported_path}?"
            if imported
            else f"Permanently delete the run record for "
                 f"{job.dataset or job.id} ({job.id})?",
            self,
        )
        heading.setWordWrap(True)
        root.addWidget(heading)

        if not job.is_final:
            warning = QLabel(
                "WARNING: This calculation might still be running. Removing its "
                "record does not stop the process. Files cannot be deleted "
                "while the run is active or its state is unknown.",
                self,
            )
            warning.setWordWrap(True)
            root.addWidget(warning)

        summary = QLabel(
            "Check individual local or SSH files to delete permanently. SSH "
            "details load separately; local deletion does not require SSH. "
            "Shared files require another confirmation. Dates are last-modified "
            "times (local time), since creation dates are not universally available.",
            self,
        )
        summary.setWordWrap(True)
        root.addWidget(summary)

        self.file_table = QTreeWidget(self)
        self.file_table.setObjectName("referenced_files")
        self.file_table.setColumnCount(3)
        self.file_table.setHeaderLabels(
            ("Delete / Referenced file", "Last modified (local time)", "References")
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

        self._selectable_rows: dict[str, QTreeWidgetItem] = {}
        self._remote_rows: dict[str, QTreeWidgetItem] = {}
        self._remote_selectable: dict[str, QTreeWidgetItem] = {}
        self._remote_review: RemoteFileReview | None = None
        self._shared_files = frozenset(() if plan is None else plan.shared)
        if plan is not None:
            snapshots = {item.path: item for item in plan.selectable_snapshots}
            groups = (
                (plan.files, "Only this record", "No other saved run references this file", False, True),
                (plan.shared, "Shared", "Referenced by other runs or imported results", False, True),
                (plan.unsafe, "Cannot delete", "Symlink, directory, or other non-regular file", False, False),
                (plan.missing, "Missing", "File does not exist", False, False),
                (plan.remote, "SSH — checking", "Checking remote file metadata (local cleanup is available immediately)", True, False),
            )
            for paths, status, reason, remote, selectable in groups:
                for filename in paths:
                    snapshot = snapshots.get(filename)
                    referrers = plan.referrers(filename) if status == "Shared" else ()
                    references = (
                        f"Shared ({len(referrers)} other reference(s))"
                        if referrers else status
                    )
                    tooltip = (
                        "Also referenced by:\n" + "\n".join(referrers)
                        if referrers else reason
                    )
                    row = QTreeWidgetItem([
                        filename,
                        _last_modified(
                            filename, remote=remote,
                            modified_ns=(
                                None if snapshot is None else snapshot.modified_ns
                            ),
                        ),
                        references,
                    ])
                    row.setToolTip(0, filename)
                    row.setToolTip(2, tooltip)
                    # QTreeWidgetItem is user-checkable by default in Qt:
                    # explicitly disable every unsafe or uninspected row.
                    row.setFlags(row.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    if selectable and job.is_final:
                        row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        row.setCheckState(0, Qt.CheckState.Unchecked)
                        self._selectable_rows[filename] = row
                    if remote:
                        self._remote_rows[filename] = row
                    self.file_table.addTopLevelItem(row)
        if not self.file_table.topLevelItemCount():
            self.file_table.addTopLevelItem(
                QTreeWidgetItem(["(no referenced files available)", "—", "—"])
            )
        self.file_table.itemChanged.connect(self._update_selection_summary)

        selection_buttons = QHBoxLayout()
        self.select_none_button = QPushButton("Select none", self)
        self.select_none_button.setToolTip("Keep all files; remove only the record or reference.")
        self.select_none_button.clicked.connect(self.select_none)
        selection_buttons.addWidget(self.select_none_button)

        self.select_unshared_button = QPushButton("Select unshared files", self)
        self.select_unshared_button.setToolTip(
            "Check only files not referenced by another saved run or imported "
            "result, including runs in this or other projects."
        )
        self.select_unshared_button.clicked.connect(self.select_unshared_files)
        selection_buttons.addWidget(self.select_unshared_button)

        self.select_all_button = QPushButton("Select all files", self)
        self.select_all_button.setToolTip(
            "Check every selectable local and inspected SSH file, including "
            "files shared with other runs. Shared files require another confirmation."
        )
        self.select_all_button.clicked.connect(self.select_all_files)
        selection_buttons.addWidget(self.select_all_button)
        selection_buttons.addStretch(1)
        root.addLayout(selection_buttons)
        for button in (
            self.select_none_button, self.select_unshared_button,
            self.select_all_button,
        ):
            button.setEnabled(bool(self._selectable_rows))

        self.selection_summary = QLabel(self)
        self.selection_summary.setWordWrap(True)
        root.addWidget(self.selection_summary)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self.confirm_button = buttons.addButton(
            self._action_label, QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.confirm_button.setAutoDefault(False)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setDefault(True)
        buttons.accepted.connect(self._confirm_selection)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._update_selection_summary()

    @property
    def selected_files(self) -> tuple[str, ...]:
        return tuple(sorted(
            name for name, row in self._selectable_rows.items()
            if row.checkState(0) == Qt.CheckState.Checked
        ))

    @property
    def selected_shared_files(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.selected_files) & self._shared_files))

    @property
    def selected_file_snapshots(self) -> tuple[FileDeletionSnapshot, ...]:
        selected = set(self.selected_files)
        return tuple(
            snapshot for snapshot in self._plan.selectable_snapshots
            if snapshot.path in selected
        ) if self._plan is not None else ()

    @property
    def remote_review(self) -> RemoteFileReview | None:
        return self._remote_review

    @property
    def selected_remote_files(self) -> tuple[str, ...]:
        return tuple(sorted(
            name for name, row in self._remote_selectable.items()
            if row.checkState(0) == Qt.CheckState.Checked
        ))

    @property
    def selected_remote_shared_files(self) -> tuple[str, ...]:
        shared = () if self._remote_review is None else self._remote_review.shared
        return tuple(sorted(set(self.selected_remote_files).intersection(shared)))

    @property
    def selected_remote_snapshots(self) -> tuple[FileDeletionSnapshot, ...]:
        selected = set(self.selected_remote_files)
        return (
            tuple(item for item in self._remote_review.snapshots if item.path in selected)
            if self._remote_review is not None else ()
        )

    def set_remote_preview(self, review: RemoteFileReview) -> None:
        """Update remote rows on the Qt thread after background SSH inspection."""
        self._remote_review = review
        snapshots = {snapshot.path: snapshot for snapshot in review.snapshots}
        reasons = dict(review.unavailable)
        self.file_table.blockSignals(True)
        try:
            for path, row in self._remote_rows.items():
                snapshot = snapshots.get(path)
                if snapshot is None:
                    row.setText(2, "SSH — " + reasons.get(path, "Unavailable"))
                    row.setToolTip(2, "Not selectable for deletion")
                    continue
                other = review.referrers_for(path)
                row.setText(
                    1, _last_modified(path, remote=True, modified_ns=snapshot.modified_ns)
                )
                row.setText(
                    2, f"SSH · shared ({len(other)} other reference(s))"
                    if other else f"SSH · {review.host} · unshared",
                )
                row.setToolTip(
                    2, ("Referenced by:\n" + "\n".join(other)) if other
                    else f"On SSH host {review.host}; no other saved references",
                )
                row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                row.setCheckState(0, Qt.CheckState.Unchecked)
                self._remote_selectable[path] = row
        finally:
            self.file_table.blockSignals(False)
        self._update_selection_summary()

    def set_remote_error(self, message: str) -> None:
        """SSH inspection failure is informational, not a deletion blocker."""
        for row in self._remote_rows.values():
            row.setText(2, "SSH unavailable — kept")
            row.setToolTip(2, message)
        self._update_selection_summary()

    @property
    def delete_files(self) -> bool:
        return bool(self.selected_files or self.selected_remote_files)

    def _select(self, local: set[str], remote: set[str] | None = None) -> None:
        self.file_table.blockSignals(True)
        try:
            for rows, selected in (
                (self._selectable_rows, local),
                (self._remote_selectable, remote or set()),
            ):
                for name, row in rows.items():
                    row.setCheckState(
                        0, Qt.CheckState.Checked if name in selected
                        else Qt.CheckState.Unchecked
                    )
        finally:
            self.file_table.blockSignals(False)
        self._update_selection_summary()

    def select_none(self) -> None:
        self._select(set(), set())

    def select_unshared_files(self) -> None:
        remote = (
            set() if self._remote_review is None
            else {item.path for item in self._remote_review.snapshots}
                 - set(self._remote_review.shared)
        )
        self._select(set() if self._plan is None else set(self._plan.files), remote)

    def select_all_files(self) -> None:
        self._select(set(self._selectable_rows), set(self._remote_selectable))

    def _update_selection_summary(self, *_args) -> None:
        local_count = len(self.selected_files)
        remote_count = len(self.selected_remote_files)
        shared = len(self.selected_shared_files) + len(self.selected_remote_shared_files)
        count = local_count + remote_count
        note = (
            f"{local_count} local and {remote_count} SSH file(s) selected. "
            "SSH cleanup is best-effort and cannot prevent local deletion."
            if count else "No files selected. Only the record/reference will be removed."
        )
        if shared:
            note += f" WARNING: {shared} selected file(s) have other saved references."
        self.selection_summary.setText(note)
        self.confirm_button.setText(
            self._action_label + (f" and {count} file(s)" if count else "")
        )
        enabled = bool(self._selectable_rows or self._remote_selectable)
        for button in (
            self.select_none_button, self.select_unshared_button, self.select_all_button,
        ):
            button.setEnabled(enabled)

    def _confirm_selection(self) -> None:
        shared_local = self.selected_shared_files
        shared_remote = self.selected_remote_shared_files
        shared_count = len(shared_local) + len(shared_remote)
        if shared_count:
            details = [
                path + "\n  " +
                "\n  ".join(self._plan.referrers(path) or ("Other saved record",))
                for path in shared_local
            ]
            if self._remote_review is not None:
                details.extend(
                    f"SSH: {path}\n  " +
                    "\n  ".join(
                        self._remote_review.referrers_for(path)
                        or ("Other saved record",)
                    )
                    for path in shared_remote
                )
            warning = (
                f"{shared_count} selected file(s) are referenced by other run "
                "records or imported results. Deleting them may make those "
                "results unusable.\n\n"
                + "\n\n".join(details)
                + "\n\nDelete these shared files anyway?"
            )
            answer = QMessageBox.warning(
                self, "Delete shared files?", warning,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()
