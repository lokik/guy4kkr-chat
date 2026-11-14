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
    FileDeletionPlan, FileDeletionSnapshot,
)


def _last_modified(
    path: str, *, remote: bool = False, modified_ns: int | None = None,
) -> str:
    """Display modification date in local time, not inode change time."""
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
    """Let the user select individual local files, not an ambiguous global toggle.

    No file is checked initially.  Shared files may be deliberately selected,
    but are never included in the default unshared selection and require an
    additional explicit warning. Missing, remote and unsafe paths cannot be
    selected. The backend independently rechecks references and file identities.
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
            "Check individual local files to delete permanently. Unchecked files "
            "will be kept. Files shared with other runs are marked; selecting "
            "them requires another confirmation. Dates are last-modified times "
            "(local time), since creation dates are not universally available.",
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
        self._shared_files = frozenset(() if plan is None else plan.shared)
        if plan is not None:
            snapshots = {item.path: item for item in plan.selectable_snapshots}
            groups = (
                (plan.files, "Only this record", "No other saved run references this file", False, True),
                (plan.shared, "Shared", "Referenced by other runs or imported results", False, True),
                (plan.unsafe, "Cannot delete", "Symlink, directory, or other non-regular file", False, False),
                (plan.missing, "Missing", "File does not exist", False, False),
                (plan.remote, "Remote — keep", "Remote files cannot be deleted here", True, False),
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
                    if selectable and job.is_final:
                        row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        row.setCheckState(0, Qt.CheckState.Unchecked)
                        self._selectable_rows[filename] = row
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

        self.select_all_button = QPushButton("Select all local files", self)
        self.select_all_button.setToolTip(
            "Check every selectable local file, including files shared with "
            "other runs. An additional warning is required for shared files."
        )
        self.select_all_button.clicked.connect(self.select_all_local_files)
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
    def delete_files(self) -> bool:
        return bool(self.selected_files)

    def _select(self, filenames: set[str]) -> None:
        self.file_table.blockSignals(True)
        try:
            for name, row in self._selectable_rows.items():
                row.setCheckState(
                    0, Qt.CheckState.Checked if name in filenames
                    else Qt.CheckState.Unchecked
                )
        finally:
            self.file_table.blockSignals(False)
        self._update_selection_summary()

    def select_none(self) -> None:
        self._select(set())

    def select_unshared_files(self) -> None:
        self._select(set() if self._plan is None else set(self._plan.files))

    def select_all_local_files(self) -> None:
        self._select(set(self._selectable_rows))

    def _update_selection_summary(self, *_args) -> None:
        count = len(self.selected_files)
        shared = len(self.selected_shared_files)
        note = (
            f"{count} local file(s) selected for permanent deletion."
            if count else "No files selected. Only the record/reference will be removed."
        )
        if shared:
            note += (
                f" WARNING: {shared} selected file(s) are also referenced by "
                "other saved runs or imported results."
            )
        self.selection_summary.setText(note)
        self.confirm_button.setText(
            self._action_label + (f" and {count} file(s)" if count else "")
        )

    def _confirm_selection(self) -> None:
        shared = self.selected_shared_files
        if shared:
            details = []
            for path in shared:
                details.append(
                    path + "\n  " +
                    "\n  ".join(self._plan.referrers(path) or ("Other saved record",))
                )
            warning = (
                f"{len(shared)} selected file(s) are referenced by other run "
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
