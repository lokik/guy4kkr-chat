"""Reusable presentation widget for persistent calculation jobs."""
from __future__ import annotations

from collections.abc import Collection, Callable
from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
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
    parsed = _local_datetime(job.started_at)
    return parsed.strftime("%Y-%m-%d") if parsed is not None else "Unknown date"


def _finished_date(job: PersistentJob) -> str:
    if job.finished_at is None:
        return "Not finished"
    parsed = _local_datetime(job.finished_at)
    return parsed.strftime("%Y-%m-%d") if parsed is not None else "Unknown date"


def _status_label(state: str) -> str:
    return state.replace("_", " ").title() or "Unknown"


_GROUPS: tuple[tuple[str, Callable[[PersistentJob], str]], ...] = (
    ("Started date", _started_date),
    ("Finished date", _finished_date),
    ("Status", lambda job: _status_label(job.state)),
    ("Task", lambda job: job.task or "Unknown task"),
    ("Execution target", lambda job: job.target),
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
    loadResultRequested = pyqtSignal(str)

    def __init__(
        self,
        value_action: Callable[[Any, Any], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._all_jobs: tuple[PersistentJob, ...] = ()
        self._jobs: tuple[PersistentJob, ...] = ()
        self._jobs_by_id: dict[str, PersistentJob] = {}
        self._visible_refs: frozenset[str] | None = None
        self._selected_job_id: str | None = None
        self._supports_results = False
        self._supports_attach = False
        self._supports_retry_download = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Group by:"))
        self.group_by = QComboBox(self)
        for label, _group in _GROUPS:
            self.group_by.addItem(label)
        self.group_by.currentIndexChanged.connect(self._populate_tree)
        controls.addWidget(self.group_by)
        controls.addStretch(1)
        self.refresh_button = QPushButton("Refresh statuses", self)
        self.refresh_button.setEnabled(False)
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        controls.addWidget(self.refresh_button)
        root.addLayout(controls)

        self.backend_notice = QLabel(self)
        self.backend_notice.setWordWrap(True)
        self.backend_notice.hide()
        root.addWidget(self.backend_notice)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        self.tree = QTreeWidget(self.splitter)
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(
            ("Job", "Status", "Started", "Finished", "Task", "Target")
        )
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(self._item_double_clicked)

        details = QWidget(self.splitter)
        details_layout = QVBoxLayout(details)
        self.detail_title = QLabel("Select a calculation job", details)
        font = self.detail_title.font()
        font.setBold(True)
        self.detail_title.setFont(font)
        details_layout.addWidget(self.detail_title)

        self.detail_form = QFormLayout()
        self.status_value = QLabel("—", details)
        self.task_value = QLabel("—", details)
        self.target_value = QLabel("—", details)
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
            ("Directory", self.directory_value),
            ("Dataset", self.dataset_value),
            ("Started", self.started_value),
            ("Finished", self.finished_value),
            ("Last update", self.updated_value),
            ("Return code", self.return_code_value),
            ("Result files", self.result_files_value),
        ):
            self.detail_form.addRow(f"{label}:", widget)
        details_layout.addLayout(self.detail_form)

        self.message_value = QLabel(details)
        self.message_value.setWordWrap(True)
        self.message_value.hide()
        details_layout.addWidget(self.message_value)

        self.monitor_button = QPushButton("Monitor output", details)
        self.monitor_button.clicked.connect(self._request_monitor)
        self.monitor_button.hide()
        details_layout.addWidget(self.monitor_button)

        self.retry_download_button = QPushButton("Retry download", details)
        self.retry_download_button.clicked.connect(self._request_retry_download)
        self.retry_download_button.hide()
        details_layout.addWidget(self.retry_download_button)

        self.load_result_button = QPushButton("Load result", details)
        self.load_result_button.clicked.connect(self._request_result)
        self.load_result_button.hide()
        details_layout.addWidget(self.load_result_button)

        self.result_widget = ResultActionsWidget(
            value_action,
            show_values_without_actions=True,
            show_history_button=False,
            empty_text="No historical result loaded.",
            parent=details,
        )
        details_layout.addWidget(self.result_widget, 1)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([540, 560])

    @property
    def all_jobs(self) -> tuple[PersistentJob, ...]:
        return self._all_jobs

    @property
    def visible_jobs(self) -> tuple[PersistentJob, ...]:
        return self._jobs

    @property
    def selected_persistent_ref(self) -> str | None:
        return self._selected_job_id

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
    ) -> None:
        """Render a complete source snapshot while preserving view selection."""
        self._all_jobs = tuple(
            sorted(jobs, key=lambda job: job.started_at, reverse=True)
        )
        self._jobs_by_id = {job.id: job for job in self._all_jobs}
        self._supports_results = supports_results
        self._supports_attach = supports_attach
        self._supports_retry_download = supports_retry_download
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

    def _clear_loaded_result(self) -> None:
        self.result_widget.set_result(None)

    def _group_for(self, job: PersistentJob) -> str:
        return _GROUPS[self.group_by.currentIndex()][1](job)

    def _populate_tree(self) -> None:
        selected = self._selected_job_id
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            groups: dict[str, QTreeWidgetItem] = {}
            selected_item: QTreeWidgetItem | None = None
            for job in self._jobs:
                group_name = self._group_for(job)
                group = groups.get(group_name)
                if group is None:
                    group = QTreeWidgetItem([group_name])
                    group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    self.tree.addTopLevelItem(group)
                    groups[group_name] = group

                title = job.dataset or job.id[:12]
                item = QTreeWidgetItem(
                    [
                        title,
                        _status_label(job.state),
                        _timestamp_label(job.started_at),
                        _timestamp_label(job.finished_at),
                        job.task,
                        job.target,
                    ]
                )
                item.setData(0, _JOB_ID_ROLE, job.id)
                item.setToolTip(0, job.id)
                group.addChild(item)
                if job.id == selected:
                    selected_item = item

            self.tree.expandAll()
            if selected_item is None and self._jobs:
                selected_item = self._first_job_item()
            if selected_item is not None:
                self.tree.setCurrentItem(selected_item)
        finally:
            self.tree.blockSignals(False)

        self._show_job(self._job_for_item(self.tree.currentItem()))

    def _first_job_item(self) -> QTreeWidgetItem | None:
        if self.tree.topLevelItemCount() == 0:
            return None
        group = self.tree.topLevelItem(0)
        return group.child(0) if group.childCount() else None

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
            self.retry_download_button.hide()
            self.load_result_button.hide()
            if selection_changed:
                self.jobSelected.emit(None)
            return

        self._selected_job_id = job.id
        self.detail_title.setText(job.dataset or f"Calculation {job.id[:12]}")
        self.status_value.setText(_status_label(job.state))
        self.task_value.setText(job.task or "—")
        self.target_value.setText(job.target)
        self.directory_value.setText(job.directory or "—")
        self.directory_value.setToolTip(job.directory or "")
        self.dataset_value.setText(job.dataset or "—")
        self.started_value.setText(_timestamp_label(job.started_at))
        self.finished_value.setText(_timestamp_label(job.finished_at))
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
        self.monitor_button.setVisible(job.attachable and self._supports_attach)
        self.retry_download_button.setVisible(
            job.can_retry_download and self._supports_retry_download
        )
        self.load_result_button.setVisible(
            job.is_final
            and not job.can_retry_download
            and self._supports_results
        )
        if selection_changed:
            self.jobSelected.emit(job.id)

    def _request_monitor(self) -> None:
        job_id = self._selected_job_id
        if job_id is not None:
            self.monitorRequested.emit(job_id)

    def _request_retry_download(self) -> None:
        job_id = self._selected_job_id
        if job_id is not None:
            self.retryDownloadRequested.emit(job_id)

    def _request_result(self) -> None:
        job_id = self._selected_job_id
        if job_id is not None:
            self.loadResultRequested.emit(job_id)

    def _item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        job = self._job_for_item(item)
        if job is None:
            return
        if job.can_retry_download and self._supports_retry_download:
            self.retryDownloadRequested.emit(job.id)
        elif job.is_final and self._supports_results:
            self.loadResultRequested.emit(job.id)
        elif job.attachable and self._supports_attach:
            self.monitorRequested.emit(job.id)
