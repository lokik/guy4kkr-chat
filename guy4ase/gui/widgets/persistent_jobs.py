"""Reusable presentation widget for persistent calculation jobs."""
from __future__ import annotations

from collections.abc import Collection, Callable
from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGridLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QSizePolicy,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.widgets.result_actions import ResultActionsWidget

_JOB_ID_ROLE = int(Qt.ItemDataRole.UserRole)


def _local_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed


def _timestamp_label(value: str | None) -> str:
    if value is None:
        return "—"
    parsed = _local_datetime(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed is not None else value


def _started_date(job: PersistentJob) -> str:
    if job.imported_path is not None:
        return "Not recorded"
    parsed = _local_datetime(job.started_at)
    return parsed.strftime("%Y-%m-%d") if parsed is not None else "Unknown date"


def _finished_date(job: PersistentJob) -> str:
    if job.finished_at is None:
        return "Not recorded" if job.imported_path is not None else "Not finished"
    parsed = _local_datetime(job.finished_at)
    return parsed.strftime("%Y-%m-%d") if parsed is not None else "Unknown date"


def _finished_tooltip(job: PersistentJob) -> str:
    """Imported results have a file timestamp, not a recorded process end."""
    if job.imported_path is None:
        return ""
    if job.finished_at is None:
        return "The output file is missing; its modification time is unavailable."
    return (
        "Estimated from the output file's last modification time; "
        "the actual calculation finish time was not recorded."
    )


def _status_label(state: str) -> str:
    return state.replace("_", " ").title() or "Unknown"


def _profile_label(job: PersistentJob) -> str:
    return job.profile or "—"


# Group using the relevant column header; Job (column 0) displays a flat list.
_GROUP_BY_COLUMN: dict[int, Callable[[PersistentJob], str]] = {
    1: lambda job: _status_label(job.state),
    2: _started_date,
    3: _finished_date,
    4: lambda job: job.task or "Unknown task",
    5: lambda job: job.target,
    6: _profile_label,
}
_GROUP_TOOLTIPS = (
    "Show all jobs and results without grouping.",
    "Group jobs and results by status.",
    "Group jobs and results by start date.",
    "Group jobs and results by finish date.",
    "Group jobs and results by task.",
    "Group jobs and results by execution target.",
    "Group jobs and results by run profile.",
)


class PersistentJobsWidget(QWidget):
    """Render persistent jobs and emit user intents.

    Backend lifecycle, source subscriptions, result-file verification, result
    loading, and monitor ownership deliberately live outside this reusable view.
    """

    jobsChanged = pyqtSignal()
    jobSelected = pyqtSignal(object)
    refreshRequested = pyqtSignal()
    monitorRequested = pyqtSignal(str)
    retryDownloadRequested = pyqtSignal(str)
    retryPostprocessingRequested = pyqtSignal(str)
    loadResultRequested = pyqtSignal(str)
    refreshResultRequested = pyqtSignal(str)
    moveRunsRequested = pyqtSignal(object)
    addResultRequested = pyqtSignal()
    cancelRequested = pyqtSignal(str)
    forgetRequested = pyqtSignal(str)

    def __init__(
        self,
        value_action: Callable[[Any, Any], None],
        parent: QWidget | None = None,
        *,
        auto_load_results: bool = False,
        show_project_actions: bool = False,
    ) -> None:
        super().__init__(parent)
        self.auto_load_results = auto_load_results
        self._all_jobs: tuple[PersistentJob, ...] = ()
        self._jobs: tuple[PersistentJob, ...] = ()
        self._jobs_by_id: dict[str, PersistentJob] = {}
        self._visible_refs: frozenset[str] | None = None
        self._selected_job_id: str | None = None
        self._group_column = 2  # Initially group by start date as before.
        self._supports_results = False
        self._supports_attach = False
        self._supports_retry_download = False
        self._supports_retry_postprocessing = False
        self._supports_cancel = False
        self._supports_forget = False
        self._supports_reassignment = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        job_list_panel = QWidget(self.splitter)
        job_list_layout = QVBoxLayout(job_list_panel)
        job_list_layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Jobs", job_list_panel)
        heading_font = heading.font()
        heading_font.setBold(True)
        heading.setFont(heading_font)
        job_list_layout.addWidget(heading)
        # Status notices belong to the Jobs pane, below the common heading line.
        self.backend_notice = QLabel(job_list_panel)
        self.backend_notice.setWordWrap(True)
        self.backend_notice.hide()
        job_list_layout.addWidget(self.backend_notice)
        self.tree = QTreeWidget(job_list_panel)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels(
            ("Job", "Status", "Started", "Finished", "Task", "Target", "Profile")
        )
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._group_by_header)
        self._update_group_header()
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(self._item_double_clicked)
        self.tree.itemSelectionChanged.connect(self._update_project_actions)
        job_list_layout.addWidget(self.tree, 1)

        self.select_all_jobs_button = QPushButton("Select all", job_list_panel)
        self.select_all_jobs_button.setToolTip("Select every job and imported result shown in the table.")
        self.select_all_jobs_button.clicked.connect(self.tree.selectAll)
        self.move_jobs_button = QPushButton("Assign to project…", job_list_panel)
        self.move_jobs_button.setIcon(QIcon.fromTheme(
            "go-jump", self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight),
        ))
        self.move_jobs_button.clicked.connect(self._request_move_runs)

        self.add_result_button = QPushButton("Add result…", job_list_panel)
        self.add_result_button.setIcon(QIcon.fromTheme(
            "document-open",
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
        ))
        self.add_result_button.setToolTip(
            "Import an existing SPR-KKR output into the selected project."
        )
        self.add_result_button.setEnabled(False)
        self.add_result_button.clicked.connect(
            lambda _checked=False: self.addResultRequested.emit()
        )

        if show_project_actions:
            project_actions = QGridLayout()
            for column, button in enumerate((
                self.select_all_jobs_button,
                self.move_jobs_button,
                self.add_result_button,
            )):
                project_actions.addWidget(button, 0, column)
                project_actions.setColumnStretch(column, 1)
                button.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
                )
            job_list_layout.addLayout(project_actions)
        else:
            self.select_all_jobs_button.hide()
            self.move_jobs_button.hide()
            self.add_result_button.hide()

        self.refresh_button = QPushButton("Refresh statuses", job_list_panel)
        self.refresh_button.setIcon(QIcon.fromTheme(
            "view-refresh", self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
        ))
        self.refresh_button.setToolTip("Check saved calculations for status updates.")
        self.refresh_button.setEnabled(False)
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        job_list_layout.addWidget(self.refresh_button)

        details = QWidget(self.splitter)
        detail_contents = QVBoxLayout(details)
        # Match the zero top margins of the Projects and Jobs panes.
        detail_contents.setContentsMargins(0, 0, 0, 0)
        result_heading = QLabel("Result", details)
        heading_font = result_heading.font()
        heading_font.setBold(True)
        result_heading.setFont(heading_font)
        detail_contents.addWidget(result_heading)
        self.detail_title = QLabel("Select a calculation job", details)
        font = self.detail_title.font()
        font.setBold(True)
        self.detail_title.setFont(font)
        detail_contents.addWidget(self.detail_title)

        self.detail_form = QFormLayout()
        self.status_value = QLabel("—", details)
        self.task_value = QLabel("—", details)
        self.target_value = QLabel("—", details)
        self.profile_value = QLabel("—", details)
        self.directory_value = QLabel("—", details)
        self.directory_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.dataset_value = QLabel("—", details)
        self.started_value = QLabel("—", details)
        self.finished_value = QLabel("—", details)
        self.updated_value = QLabel("—", details)
        self.return_code_value = QLabel("—", details)
        self.result_files_value = QLabel("—", details)
        for label, widget in (
            ("Status", self.status_value),
            ("Task", self.task_value),
            ("Execution target", self.target_value),
            ("Run profile", self.profile_value),
            ("Directory", self.directory_value),
            ("Dataset", self.dataset_value),
            ("Started", self.started_value),
            ("Finished", self.finished_value),
            ("Last update", self.updated_value),
            ("Return code", self.return_code_value),
            ("Result files", self.result_files_value),
        ):
            self.detail_form.addRow(f"{label}:", widget)
        detail_contents.addLayout(self.detail_form)

        self.message_value = QLabel(details)
        self.message_value.setWordWrap(True)
        self.message_value.hide()
        detail_contents.addWidget(self.message_value)

        self.load_result_button = QPushButton("Use result", details)
        self.load_result_button.setIcon(QIcon.fromTheme(
            "document-open", self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
        ))
        self.load_result_button.setToolTip(
            "Add this calculation result to the main window and select it."
        )
        self.load_result_button.clicked.connect(self._request_result)
        self.load_result_button.hide()

        self.refresh_result_button = QPushButton("Refresh result", details)
        self.refresh_result_button.setIcon(QIcon.fromTheme(
            "view-refresh", self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
        ))
        self.refresh_result_button.setToolTip(
            "Read the output files again and update the preview without selecting it in the main window."
        )
        self.refresh_result_button.clicked.connect(self._request_refresh_result)
        self.refresh_result_button.hide()

        self.monitor_button = QPushButton("Reattach / monitor", details)
        self.monitor_button.setIcon(QIcon.fromTheme(
            "network-connect", self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton),
        ))
        self.monitor_button.setToolTip(
            "Reconnect to this calculation without submitting it again."
        )
        self.monitor_button.clicked.connect(self._request_monitor)
        self.monitor_button.hide()

        self.retry_postprocessing_button = QPushButton("Retry postprocessing", details)
        self.retry_postprocessing_button.setIcon(QIcon.fromTheme(
            "view-refresh", self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
        ))
        self.retry_postprocessing_button.clicked.connect(self._request_retry_postprocessing)
        self.retry_postprocessing_button.hide()

        self.retry_download_button = QPushButton("Retry download", details)
        self.retry_download_button.setIcon(QIcon.fromTheme(
            "go-down", self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown),
        ))
        self.retry_download_button.clicked.connect(self._request_retry_download)
        self.retry_download_button.hide()

        self.reattach_notice = QLabel(details)
        self.reattach_notice.setWordWrap(True)
        self.reattach_notice.hide()
        detail_contents.addWidget(self.reattach_notice)

        self.cancel_button = QPushButton("Cancel process", details)
        self.cancel_button.setIcon(QIcon.fromTheme(
            "process-stop", self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton),
        ))
        self.cancel_button.clicked.connect(self._request_cancel)
        self.forget_button = QPushButton("Delete run record…", details)
        self.forget_button.setIcon(QIcon.fromTheme(
            "edit-delete", self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon),
        ))
        self.forget_button.clicked.connect(self._request_forget)

        self.result_widget = ResultActionsWidget(
            value_action,
            show_values_without_actions=True,
            show_history_button=False,
            show_assignment_controls=False,
            empty_text="No historical result loaded.",
            parent=details,
        )
        detail_contents.addWidget(self.result_widget, 1)

        # All single-result operations share a footer, separated from bulk job actions.
        supplementary_actions = QGridLayout()
        for index, button in enumerate((
            self.monitor_button, self.retry_download_button,
            self.retry_postprocessing_button, self.cancel_button,
        )):
            supplementary_actions.addWidget(button, index // 2, index % 2)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
        supplementary_actions.setColumnStretch(0, 1)
        supplementary_actions.setColumnStretch(1, 1)
        detail_contents.addLayout(supplementary_actions)

        main_actions = QGridLayout()
        for column, button in enumerate((
            self.load_result_button,
            self.refresh_result_button,
            self.forget_button,
        )):
            main_actions.addWidget(button, 0, column)
            main_actions.setColumnStretch(column, 1)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
        detail_contents.addLayout(main_actions)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([600, 500])
        self._update_project_actions()

    @property
    def all_jobs(self) -> tuple[PersistentJob, ...]:
        return self._all_jobs

    @property
    def visible_jobs(self) -> tuple[PersistentJob, ...]:
        return self._jobs

    @property
    def selected_persistent_ref(self) -> str | None:
        return self._selected_job_id

    @property
    def selected_persistent_refs(self) -> tuple[str, ...]:
        """Selected run IDs, excluding non-selectable group headers."""
        return tuple(sorted({
            str(value) for item in self.tree.selectedItems()
            if (value := item.data(0, _JOB_ID_ROLE)) is not None
        }))

    def set_project_assignment_available(self, available: bool) -> None:
        self._supports_reassignment = available
        self._update_project_actions()

    def set_add_result_available(self, available: bool) -> None:
        """Allow external-result import only when a real project is selected."""
        self.add_result_button.setEnabled(available)

    def _update_project_actions(self) -> None:
        selected = self.selected_persistent_refs
        self.select_all_jobs_button.setEnabled(bool(self._jobs))
        self.move_jobs_button.setEnabled(bool(selected) and self._supports_reassignment)
        if not self._supports_reassignment:
            reason = "This kkrunner version cannot reassign calculation records."
        else:
            reason = "Move selected jobs or imported results to another project without changing their files or processes."
        self.move_jobs_button.setToolTip(reason)

    def _request_move_runs(self) -> None:
        selected = self.selected_persistent_refs
        if selected and self.move_jobs_button.isEnabled():
            self.moveRunsRequested.emit(selected)

    def set_jobs(
        self,
        jobs: Collection[PersistentJob],
        *,
        available: bool,
        unavailable_reason: str | None,
        supports_refresh: bool,
        supports_results: bool,
        supports_attach: bool,
        supports_retry_download: bool,
        supports_retry_postprocessing: bool = False,
        supports_cancel: bool = False,
        supports_forget: bool = False,
    ) -> None:
        """Render a complete source snapshot while preserving view selection."""
        self._all_jobs = tuple(
            sorted(jobs, key=lambda job: job.started_at, reverse=True)
        )
        self._jobs_by_id = {job.id: job for job in self._all_jobs}
        self._supports_results = supports_results
        self._supports_attach = supports_attach
        self._supports_retry_download = supports_retry_download
        self._supports_retry_postprocessing = supports_retry_postprocessing
        self._supports_cancel = supports_cancel
        self._supports_forget = supports_forget
        self.refresh_button.setEnabled(supports_refresh)

        if not available:
            self.backend_notice.setText(
                unavailable_reason
                or "Persistent calculation jobs are not available in this "
                "ASE2SPRKKR version yet."
            )
            self.backend_notice.show()
        elif not self._all_jobs:
            self.backend_notice.setText(
                "No persistent calculation jobs have been recorded yet."
            )
            self.backend_notice.show()
        else:
            self.backend_notice.hide()

        self._apply_filter()
        self.jobsChanged.emit()

    def set_visible_refs(self, persistent_refs: Collection[str] | None) -> None:
        self._visible_refs = (
            None
            if persistent_refs is None
            else frozenset(str(value) for value in persistent_refs)
        )
        self._apply_filter()

    def update_job(self, job: PersistentJob) -> None:
        """Upsert one newer source snapshot without disturbing loaded results."""
        self._jobs_by_id[job.id] = job
        by_id = {current.id: current for current in self._all_jobs}
        by_id[job.id] = job
        self._all_jobs = tuple(
            sorted(by_id.values(), key=lambda current: current.started_at, reverse=True)
        )
        self._apply_filter()
        self.jobsChanged.emit()

    def set_result(self, job_id: str, result: Any) -> None:
        """Show a loaded result only while its job remains selected."""
        if self._selected_job_id == job_id:
            self.result_widget.set_result(result)

    def set_result_pending(self, job_id: str) -> None:
        if self._selected_job_id == job_id:
            self.result_widget.set_status("Loading result in background…")

    def set_result_error(self, job_id: str, error: str) -> None:
        if self._selected_job_id == job_id:
            self.result_widget.set_status(f"Result unavailable: {error}. Use Refresh result to retry.")

    def _apply_filter(self) -> None:
        if self._visible_refs is None:
            self._jobs = self._all_jobs
        else:
            visible = self._visible_refs
            self._jobs = tuple(job for job in self._all_jobs if job.id in visible)
        visible_ids = {job.id for job in self._jobs}
        if self._selected_job_id not in visible_ids:
            self._selected_job_id = None
            self._clear_loaded_result()
        self._populate_tree()
        self._update_project_actions()

    def _clear_loaded_result(self) -> None:
        self.result_widget.set_result(None)

    def _group_by_header(self, column: int) -> None:
        if column == self._group_column or column not in range(7):
            return
        self._group_column = column
        self._update_group_header()
        self._populate_tree()

    def _update_group_header(self) -> None:
        header_item = self.tree.headerItem()
        selected_icon = QIcon.fromTheme(
            "emblem-default",
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton),
        )
        for column, description in enumerate(_GROUP_TOOLTIPS):
            selected = column == self._group_column
            header_item.setIcon(column, selected_icon if selected else QIcon())
            header_item.setToolTip(
                column,
                description + (" (current grouping)" if selected else "") + " Click to choose.",
            )

    def _group_for(self, job: PersistentJob) -> str | None:
        grouper = _GROUP_BY_COLUMN.get(self._group_column)
        return None if grouper is None else grouper(job)

    def _populate_tree(self) -> None:
        selected = self._selected_job_id
        selected_refs = set(self.selected_persistent_refs)
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            groups: dict[str, QTreeWidgetItem] = {}
            items_by_id: dict[str, QTreeWidgetItem] = {}
            for job in self._jobs:
                group_name = self._group_for(job)
                group = None
                if group_name is not None:
                    group = groups.get(group_name)
                    if group is None:
                        group = QTreeWidgetItem([group_name])
                        group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                        self.tree.addTopLevelItem(group)
                        groups[group_name] = group

                item = QTreeWidgetItem([
                    job.dataset or job.id[:12],
                    _status_label(job.state),
                    _timestamp_label(None if job.imported_path else job.started_at),
                    _timestamp_label(job.finished_at),
                    job.task,
                    job.target,
                    _profile_label(job),
                ])
                item.setData(0, _JOB_ID_ROLE, job.id)
                item.setToolTip(0, job.id if job.imported_path is None else job.imported_path)
                item.setToolTip(3, _finished_tooltip(job))
                if group is None:
                    self.tree.addTopLevelItem(item)
                else:
                    group.addChild(item)
                items_by_id[job.id] = item

            self.tree.expandAll()
            current = items_by_id.get(selected)
            if current is None and self._jobs:
                current = items_by_id[self._jobs[0].id]
            if current is not None:
                self.tree.setCurrentItem(current)
            for job_id in selected_refs:
                if job_id in items_by_id:
                    items_by_id[job_id].setSelected(True)
        finally:
            self.tree.blockSignals(False)

        self._update_project_actions()
        self._show_job(self._job_for_item(self.tree.currentItem()))

    def _job_for_item(self, item: QTreeWidgetItem | None) -> PersistentJob | None:
        if item is None:
            return None
        job_id = item.data(0, _JOB_ID_ROLE)
        if job_id is None:
            return None
        return self._jobs_by_id.get(str(job_id))

    def _selection_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        self._show_job(self._job_for_item(current))

    def _show_job(self, job: PersistentJob | None) -> None:
        previous_job_id = self._selected_job_id
        next_job_id = None if job is None else job.id
        selection_changed = next_job_id != previous_job_id
        if selection_changed:
            self._clear_loaded_result()

        if job is None:
            self._selected_job_id = None
            self.detail_title.setText("Select a calculation job")
            for widget in (
                self.status_value,
                self.task_value,
                self.target_value,
                self.profile_value,
                self.directory_value,
                self.dataset_value,
                self.started_value,
                self.finished_value,
                self.updated_value,
                self.return_code_value,
                self.result_files_value,
            ):
                widget.setText("—")
            self.message_value.hide()
            self.monitor_button.hide()
            self.cancel_button.hide()
            self.forget_button.hide()
            self.reattach_notice.hide()
            self.retry_download_button.hide()
            self.retry_postprocessing_button.hide()
            self.load_result_button.hide()
            self.refresh_result_button.hide()
            if selection_changed:
                self.jobSelected.emit(None)
            return

        self._selected_job_id = job.id
        self.detail_title.setText(job.dataset or f"Calculation {job.id[:12]}")
        self.status_value.setText(
            "Unknown — status unverified"
            if job.state == "unknown" else _status_label(job.state)
        )
        self.task_value.setText(job.task or "—")
        self.target_value.setText(job.target)
        self.profile_value.setText(_profile_label(job))
        self.directory_value.setText(job.directory or "—")
        self.directory_value.setToolTip(job.directory or "")
        self.dataset_value.setText(job.dataset or "—")
        self.started_value.setText(
            _timestamp_label(None if job.imported_path else job.started_at)
        )
        self.finished_value.setText(_timestamp_label(job.finished_at))
        self.finished_value.setToolTip(_finished_tooltip(job))
        self.updated_value.setText(_timestamp_label(job.updated_at))
        self.return_code_value.setText(
            "—" if job.return_code is None else str(job.return_code)
        )
        if not job.is_final or not job.result_files_state:
            result_files_label = "—"
        else:
            result_files_label = _status_label(job.result_files_state)
            if not job.result_files_verified:
                result_files_label += " (stored, not checked)"
        self.result_files_value.setText(result_files_label)
        self.message_value.setText(job.message or "")
        self.message_value.setVisible(bool(job.message))
        # Keep the action visible for unverified jobs. Otherwise users have
        # no explanation why a still-running direct SSH job cannot be reopened.
        self.monitor_button.setVisible(not job.is_final)
        self.monitor_button.setEnabled(job.attachable and self._supports_attach)
        reason = (
            job.reattach_unavailable_reason
            if self._supports_attach
            else "This installation cannot reattach to persistent calculations."
        )
        self.monitor_button.setToolTip(
            "Reconnect without submitting another calculation."
            if job.attachable and self._supports_attach
            else (reason or "Reattachment is not available for this calculation.")
        )
        self.cancel_button.setVisible(not job.is_final)
        self.cancel_button.setEnabled(
            not job.is_final and job.cancelable and self._supports_cancel
        )
        self.cancel_button.setToolTip(
            "Request termination of the original calculation process."
            if job.cancelable and self._supports_cancel
            else (
                job.cancel_unavailable_reason
                or "Cancelling persisted processes is not supported by this installation."
            )
        )
        self.forget_button.setVisible(self._supports_forget)
        self.forget_button.setEnabled(self._supports_forget)
        if job.imported_path is not None:
            self.forget_button.setText("Remove result reference…")
            self.forget_button.setToolTip(
                "Remove this project reference without deleting the external output file."
            )
        else:
            self.forget_button.setText("Delete run record…")
            self.forget_button.setToolTip(
                "Remove only this calculation's history entry; keep the process and output files."
            )
        self.reattach_notice.setText(reason or "")
        self.reattach_notice.setVisible(not job.is_final and bool(reason))
        self.retry_download_button.setVisible(
            job.can_retry_download and self._supports_retry_download
        )
        self.retry_postprocessing_button.setVisible(
            job.can_retry_postprocessing and self._supports_retry_postprocessing
        )
        can_load_result = (
            job.is_final
            and not job.can_retry_download
            and self._supports_results
        )
        self.load_result_button.setVisible(can_load_result)
        self.refresh_result_button.setVisible(can_load_result)
        if selection_changed:
            self.jobSelected.emit(job.id)

    def _request_cancel(self) -> None:
        if self._selected_job_id is not None:
            self.cancelRequested.emit(self._selected_job_id)

    def _request_forget(self) -> None:
        if self._selected_job_id is not None:
            self.forgetRequested.emit(self._selected_job_id)

    def _request_monitor(self) -> None:
        job_id = self._selected_job_id
        if job_id is not None:
            self.monitorRequested.emit(job_id)

    def _request_retry_postprocessing(self) -> None:
        if self._selected_job_id is not None:
            self.retryPostprocessingRequested.emit(self._selected_job_id)

    def _request_retry_download(self) -> None:
        job_id = self._selected_job_id
        if job_id is not None:
            self.retryDownloadRequested.emit(job_id)

    def _request_result(self) -> None:
        job_id = self._selected_job_id
        if job_id is not None:
            self.loadResultRequested.emit(job_id)

    def _request_refresh_result(self) -> None:
        job_id = self._selected_job_id
        if job_id is not None:
            self.refreshResultRequested.emit(job_id)

    def _item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        job = self._job_for_item(item)
        if job is None:
            return
        if job.can_retry_download and self._supports_retry_download:
            self.retryDownloadRequested.emit(job.id)
        elif job.can_retry_postprocessing and self._supports_retry_postprocessing:
            self.retryPostprocessingRequested.emit(job.id)
        elif job.is_final and self._supports_results:
            self.loadResultRequested.emit(job.id)
        elif job.attachable and self._supports_attach:
            self.monitorRequested.emit(job.id)
