"""Regression coverage for interactive submission-file conflicts."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from kkrunner import RunManager, RunStore
from kkrunner.files import FileEntry, FileManifest
from kkrunner.runs import DuplicateSubmissionError

from guy4ase.gui.application.execution_cancellation import RunCancellation
from guy4ase.gui.dialogs import run_calculation as calculation
from guy4ase.gui.dialogs.run_conflict import CancellationFailureDialog, SubmissionConflictDialog


def _conflict(tmp_path):
    manager = RunManager(RunStore(tmp_path / "history"))
    files = FileManifest(stdout=FileEntry(str(tmp_path / "same.out")))
    proposed = manager.new_record(directory=tmp_path, files=files)
    active = manager.new_record(
        directory=tmp_path,
        files=files,
        project_id="old-project",
        metadata={"ase2sprkkr": {"dataset": "Fe_SCF", "task": "SCF"}},
    )
    return DuplicateSubmissionError(proposed, (active,))


def test_conflict_dialog_shows_job_ids_and_exact_file_paths(tmp_path):
    app = QApplication.instance() or QApplication([])
    error = _conflict(tmp_path)
    dialog = SubmissionConflictDialog(error)

    assert "in use" in dialog.windowTitle()
    assert dialog.details.topLevelItemCount() == 1
    parent = dialog.details.topLevelItem(0)
    assert "Fe_SCF" in parent.text(0)
    assert "SCF" in parent.text(0)
    assert error.conflicts[0].id in parent.toolTip(0)
    assert parent.childCount() >= 1
    assert str(tmp_path / "same.out") in parent.child(0).text(0)
    assert "writes" in parent.child(0).text(1)
    assert dialog.keep_button.isDefault()

    dialog.keep_button.click()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert app is QApplication.instance()


def test_duplicate_submission_is_a_choice_not_a_red_error(monkeypatch, tmp_path):
    error = _conflict(tmp_path)

    class FakeExecution:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self):
            raise error

    monkeypatch.setattr(calculation, "SprkkrExecution", FakeExecution)
    worker = calculation._SprkkrRunWorker(object(), RunCancellation())
    reported = []
    errors = []
    ended = []
    worker.conflict.connect(reported.append)
    worker.error.connect(errors.append)
    worker.cancelled.connect(lambda: ended.append(True))
    worker.run()

    assert reported == [error]
    assert errors == []
    assert ended == [True]


def test_declining_conflict_keeps_existing_jobs_and_no_error(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    error = _conflict(tmp_path)
    window = calculation.SprkkrRunWindow(SimpleNamespace(directory=str(tmp_path)))
    monkeypatch.setattr(SubmissionConflictDialog, "exec", lambda _self: QDialog.DialogCode.Rejected)

    window._on_conflict(error)
    assert "existing jobs were kept" in window._status.text()
    assert "[ERROR]" not in window._output.toPlainText()
    assert app is QApplication.instance()


def test_stop_existing_runs_uses_manager_cancel_without_forgetting(tmp_path):
    app = QApplication.instance() or QApplication([])
    error = _conflict(tmp_path)
    calls = []
    active = SimpleNamespace(state=SimpleNamespace(is_terminal=False))
    terminal = SimpleNamespace(state=SimpleNamespace(is_terminal=True))
    manager = SimpleNamespace(
        store=SimpleNamespace(get=lambda run_id: calls.append(("get", run_id)) or active),
        cancel=lambda run_id: calls.append(("cancel", run_id)) or terminal,
    )
    window = calculation.SprkkrRunWindow(SimpleNamespace(directory=str(tmp_path)))
    window._execution_manager = manager
    outcomes = []
    window.conflictStopFinished.connect(outcomes.append)

    window._stop_existing_jobs(error)

    assert ("cancel", error.conflicts[0].id) in calls
    assert outcomes == [([error.conflicts[0].id], [], [])]
    assert app is QApplication.instance()


def test_stopping_existing_run_does_not_claim_unknown_status_is_terminal(tmp_path):
    app = QApplication.instance() or QApplication([])
    error = _conflict(tmp_path)
    active = SimpleNamespace(state=SimpleNamespace(is_terminal=False))
    manager = SimpleNamespace(
        store=SimpleNamespace(get=lambda _id: active),
        cancel=lambda _id: active,
    )
    window = calculation.SprkkrRunWindow(SimpleNamespace(directory=str(tmp_path)))
    window._execution_manager = manager
    outcomes = []
    window.conflictStopFinished.connect(outcomes.append)

    window._stop_existing_jobs(error)

    assert outcomes == [([], [error.conflicts[0].id], [])]


def test_confirmed_stop_retries_new_submission_with_fresh_monitor_state(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    window = calculation.SprkkrRunWindow(SimpleNamespace(directory=str(tmp_path)))
    started = []
    deleted = []

    class FinishedThread:
        @staticmethod
        def isRunning():
            return False

        def deleteLater(self):
            deleted.append(True)

    window._thread = FinishedThread()
    prior_cancellation = window._cancellation
    window._stop_btn.setEnabled(False)
    monkeypatch.setattr(window, "_start_worker", lambda: started.append(True))

    window._on_conflict_stop_finished((["old-run"], [], []))

    assert started == [True]
    assert deleted == [True]
    assert window._thread is None
    assert window._cancellation is not prior_cancellation
    assert window._stop_btn.isEnabled()
    assert "starting calculation" in window._status.text()
    assert app is QApplication.instance()


def test_pending_stop_never_resubmits(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    window = calculation.SprkkrRunWindow(SimpleNamespace(directory=str(tmp_path)))
    started = []
    monkeypatch.setattr(window, "_start_worker", lambda: started.append(True))

    window._on_conflict_stop_finished(([], ["still-running"], []))

    assert started == []
    assert "wait for existing jobs" in window._status.text()
    assert app is QApplication.instance()


def test_failed_cancellation_offers_checked_job_record_removal(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    error = _conflict(tmp_path)
    record = error.conflicts[0]
    dialog = CancellationFailureDialog(((record, "No safe PID identity"),))

    assert not dialog.remove_button.isEnabled()
    assert dialog.keep_button.isDefault()
    item = dialog.jobs.topLevelItem(0)
    assert record.id in item.toolTip(0)
    assert "No safe PID" in item.text(1)
    item.setCheckState(0, Qt.CheckState.Checked)
    assert dialog.selected_job_ids() == (record.id,)
    assert dialog.remove_button.isEnabled()

    confirmations = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda _parent, _title, message, *_args: (
            confirmations.append(message) or QMessageBox.StandardButton.Cancel
        ),
    )
    dialog.remove_button.click()
    assert dialog.result() != CancellationFailureDialog.REMOVE_SELECTED
    assert "DOES NOT STOP" in confirmations[0]
    assert app is QApplication.instance()

    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.StandardButton.Yes)
    dialog.remove_button.click()
    assert dialog.result() == CancellationFailureDialog.REMOVE_SELECTED


def test_cancel_failure_keeps_records_and_returns_to_run_setup(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    record = _conflict(tmp_path).conflicts[0]
    window = calculation.SprkkrRunWindow(SimpleNamespace(directory=str(tmp_path)))
    returned = []
    window._back_to_setup = lambda: returned.append(True)
    queued = []
    monkeypatch.setattr(calculation.QTimer, "singleShot", lambda _delay, call: queued.append(call))
    monkeypatch.setattr(CancellationFailureDialog, "exec", lambda _self: QDialog.DialogCode.Rejected)

    window._on_conflict_stop_finished(([], [], [(record, "No PID")]))
    assert len(queued) == 1
    queued.pop()()
    assert returned == [True]
    assert app is QApplication.instance()


def test_failed_cancellation_can_forget_only_explicitly_selected_records(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    conflict = _conflict(tmp_path)
    record = conflict.conflicts[0]
    calls = []
    manager = SimpleNamespace(forget=lambda job_id, *, force=False: calls.append((job_id, force)))
    window = calculation.SprkkrRunWindow(SimpleNamespace(directory=str(tmp_path)))
    window._execution_manager = manager
    outcomes = []
    window.conflictForgetFinished.connect(outcomes.append)
    returned = []
    monkeypatch.setattr(window, "_return_to_setup", lambda: returned.append(True))
    monkeypatch.setattr(
        CancellationFailureDialog, "exec",
        lambda dialog: (
            dialog.jobs.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
            or CancellationFailureDialog.REMOVE_SELECTED
        ),
    )

    class ImmediateThread:
        def __init__(self, *, target, **_options):
            self.target = target

        def start(self):
            self.target()

    window._background_thread_factory = ImmediateThread
    window._on_conflict_stop_finished(([], [], [(record, "Unsupported cancellation")]))

    assert calls == [(record.id, True)]
    assert outcomes == [([record.id], [])]
    assert returned == [True]
    assert "New calculation not started" in window._status.text()
    assert app is QApplication.instance()


def test_missing_conflicting_history_never_means_process_stopped(tmp_path):
    app = QApplication.instance() or QApplication([])
    conflict = _conflict(tmp_path)
    old_id = conflict.conflicts[0].id
    window = calculation.SprkkrRunWindow(SimpleNamespace(directory=str(tmp_path)))

    def missing(job_id):
        raise FileNotFoundError(job_id)

    window._execution_manager = SimpleNamespace(
        store=SimpleNamespace(get=missing),
        cancel=lambda _id: (_ for _ in ()).throw(AssertionError("cannot cancel")),
    )
    outcomes = []
    window.conflictStopFinished.connect(outcomes.append)

    window._stop_existing_jobs(conflict)

    assert outcomes == [([], [old_id], [])]
    assert app is QApplication.instance()


def test_keep_existing_conflicting_job_returns_to_run_picker(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    conflict = _conflict(tmp_path)
    returned = []
    window = calculation.SprkkrRunWindow(
        SimpleNamespace(directory=str(tmp_path)),
        on_back_to_setup=lambda: returned.append(True),
    )
    scheduled = []
    monkeypatch.setattr(calculation.QTimer, "singleShot", lambda delay, fn: scheduled.append((delay, fn)))
    monkeypatch.setattr(
        SubmissionConflictDialog, "exec", lambda _dialog: QDialog.DialogCode.Rejected
    )

    window._on_conflict(conflict)

    assert len(scheduled) == 1
    assert scheduled[0][0] == 0
    scheduled[0][1]()
    assert returned == [True]
    assert app is QApplication.instance()
