"""Regression tests for the persistent file-conflict resolution workflow."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from kkrunner import RunManager, RunState, RunStore
from kkrunner.files import FileEntry, FileManifest
from kkrunner.runs import DuplicateSubmissionError

from ase2sprkkr_gui.gui.application.execution_cancellation import RunCancellation
from ase2sprkkr_gui.gui.dialogs import run_calculation as calculation
from ase2sprkkr_gui.gui.dialogs.run_conflict import SubmissionConflictDialog


def _conflict(tmp_path, *, count=1):
    manager = RunManager(RunStore(tmp_path / "history"))
    files = FileManifest(stdout=FileEntry(str(tmp_path / "same.out")))
    proposed = manager.new_record(directory=tmp_path, files=files)
    active = []
    for index in range(count):
        record = manager.new_record(
            directory=tmp_path,
            files=files,
            project_id="old-project",
            metadata={
                "ase2sprkkr": {"dataset": f"Fe_SCF_{index}", "task": "SCF"}
            },
        )
        active.append(manager.transition(record, state=RunState.RUNNING))
    return manager, DuplicateSubmissionError(proposed, tuple(active))


def _window(tmp_path, manager, conflict):
    window = calculation.SprkkrRunWindow(
        SimpleNamespace(directory=str(tmp_path))
    )
    window._execution_manager = manager
    dialog = SubmissionConflictDialog(conflict, parent=window)
    window._conflict_dialog = dialog
    dialog.actionRequested.connect(window._on_conflict_action)

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self._target = target

        def start(self):
            self._target()

    window._background_thread_factory = ImmediateThread
    return window, dialog


def _select(dialog, index=0):
    dialog.details.topLevelItem(index).setCheckState(
        0, Qt.CheckState.Checked
    )


def test_conflict_list_has_job_ids_file_paths_and_disabled_calculate(tmp_path):
    app = QApplication.instance() or QApplication([])
    _manager, conflict = _conflict(tmp_path)
    dialog = SubmissionConflictDialog(conflict)

    assert dialog.details.topLevelItemCount() == 1
    item = dialog.details.topLevelItem(0)
    assert "Fe_SCF_0" in item.text(0)
    assert conflict.conflicts[0].id in item.toolTip(0)
    assert item.childCount() >= 1
    assert str(tmp_path / "same.out") in item.child(0).text(0)
    assert "writes" in item.child(0).text(1)
    assert not dialog.calculate_button.isEnabled()
    assert not dialog.failed_button.isEnabled()
    assert not dialog.delete_button.isEnabled()
    assert dialog.cancel_button.isDefault()

    requests = []
    dialog.actionRequested.connect(lambda action, ids: requests.append((action, ids)))
    _select(dialog)
    assert dialog.failed_button.isEnabled()
    assert dialog.delete_button.isEnabled()
    dialog.stop_button.click()
    assert requests == [("stop", (conflict.conflicts[0].id,))]
    assert not dialog.calculate_button.isEnabled()
    assert app is QApplication.instance()


def test_worker_routes_duplicate_submission_to_conflict_not_error(monkeypatch, tmp_path):
    _manager, conflict = _conflict(tmp_path)

    class FakeExecution:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self):
            raise conflict

    monkeypatch.setattr(calculation, "SprkkrExecution", FakeExecution)
    worker = calculation._SprkkrRunWorker(object(), RunCancellation())
    seen, errors, ended = [], [], []
    worker.conflict.connect(seen.append)
    worker.error.connect(errors.append)
    worker.cancelled.connect(lambda: ended.append(True))
    worker.run()

    assert seen == [conflict]
    assert errors == []
    assert ended == [True]


def test_mark_failed_updates_only_history_and_keeps_dialog_open(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    manager, conflict = _conflict(tmp_path, count=2)
    window, dialog = _window(tmp_path, manager, conflict)
    ids = [record.id for record in conflict.conflicts]
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )

    _select(dialog)
    dialog.failed_button.click()

    failed = manager.store.get(ids[0])
    assert failed.state == RunState.FAILED
    assert "Manually marked failed" in failed.message
    assert failed.return_code is None
    assert manager.store.get(ids[1]).state == RunState.RUNNING
    assert dialog.details.topLevelItemCount() == 1
    assert not dialog.calculate_button.isEnabled()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not window._conflict_cancellation_pending
    assert app is QApplication.instance()


def test_delete_only_selected_job_preserves_other_conflicts(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    manager, conflict = _conflict(tmp_path, count=2)
    _window_obj, dialog = _window(tmp_path, manager, conflict)
    first, second = (r.id for r in conflict.conflicts)
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )

    _select(dialog, 0)
    dialog.delete_button.click()

    try:
        manager.store.get(first)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("selected record must be removed")
    assert manager.store.get(second).state == RunState.RUNNING
    assert dialog.details.topLevelItemCount() == 1
    assert not dialog.calculate_button.isEnabled()
    assert dialog.result() == QDialog.DialogCode.Rejected

    _select(dialog)
    dialog.failed_button.click()
    assert not dialog._conflict.conflicts
    assert dialog.calculate_button.isEnabled()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert app is QApplication.instance()


def test_failed_cancellation_remains_selectable_for_other_actions(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    manager, conflict = _conflict(tmp_path)
    _window_obj, dialog = _window(tmp_path, manager, conflict)
    old_id = conflict.conflicts[0].id

    def cannot_cancel(run_id):
        assert run_id == old_id
        raise NotImplementedError("No verified PID")

    monkeypatch.setattr(manager, "cancel", cannot_cancel)
    _select(dialog)
    dialog.stop_button.click()

    assert not dialog.calculate_button.isEnabled()
    assert dialog.details.topLevelItemCount() == 1
    assert "No verified PID" in dialog.details.topLevelItem(0).child(0).text(1)
    assert dialog.failed_button.isEnabled()
    assert dialog.delete_button.isEnabled()
    assert manager.store.get(old_id).state == RunState.RUNNING
    assert app is QApplication.instance()


def test_confirmed_cancellation_enables_calculate_but_does_not_autostart(
    monkeypatch, tmp_path
):
    app = QApplication.instance() or QApplication([])
    manager, conflict = _conflict(tmp_path)
    _window_obj, dialog = _window(tmp_path, manager, conflict)
    old_id = conflict.conflicts[0].id

    def confirmed_cancel(run_id):
        assert run_id == old_id
        record = manager.store.get(run_id)
        return manager.transition(record, state=RunState.CANCELLED)

    monkeypatch.setattr(manager, "cancel", confirmed_cancel)
    _select(dialog)
    dialog.stop_button.click()

    assert manager.store.get(old_id).state == RunState.CANCELLED
    assert dialog.calculate_button.isEnabled()
    assert dialog.result() == QDialog.DialogCode.Rejected
    # Confirmed cancellation did not manually override job history.
    assert not dialog._manual_override
    dialog.calculate_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert app is QApplication.instance()


def test_manual_clear_requires_second_confirmation_before_calculate(
    monkeypatch, tmp_path
):
    app = QApplication.instance() or QApplication([])
    _manager, conflict = _conflict(tmp_path)
    dialog = SubmissionConflictDialog(conflict)
    dialog.set_conflicts(DuplicateSubmissionError(conflict.record, ()),
                         manually_changed=True)
    responses = [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes]
    warnings = []

    def warn(_parent, _title, message, *_args):
        warnings.append(message)
        return responses.pop(0)

    monkeypatch.setattr(QMessageBox, "warning", warn)
    assert dialog.calculate_button.isEnabled()
    dialog.calculate_button.click()
    assert dialog.result() == QDialog.DialogCode.Rejected
    dialog.calculate_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert all("still" in warning and "processes" in warning for warning in warnings)
    assert app is QApplication.instance()


def test_refresh_rechecks_new_conflicts_not_only_initial_ids(tmp_path):
    app = QApplication.instance() or QApplication([])
    manager, conflict = _conflict(tmp_path)
    window, dialog = _window(tmp_path, manager, conflict)
    first = conflict.conflicts[0]
    # A separate process reserves the same files after opening the dialog.
    second = manager.new_record(
        directory=tmp_path, files=first.files,
        metadata={"ase2sprkkr": {"dataset": "Other", "task": "SCF"}},
    )
    second = manager.transition(second, state=RunState.RUNNING)
    dialog.refresh_button.click()
    ids = {record.id for record in dialog._conflict.conflicts}

    assert ids == {first.id, second.id}
    assert not dialog.calculate_button.isEnabled()
    assert not window._conflict_cancellation_pending
    assert app is QApplication.instance()


def test_failed_conflict_recheck_never_enables_calculate(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    manager, conflict = _conflict(tmp_path)
    window, dialog = _window(tmp_path, manager, conflict)
    dialog.set_conflicts(DuplicateSubmissionError(conflict.record, ()))
    assert dialog.calculate_button.isEnabled()

    def unreadable(*_args, **_kwargs):
        raise OSError("history unavailable")

    monkeypatch.setattr(manager.store, "runs", unreadable)
    dialog.refresh_button.click()

    assert "history unavailable" in dialog.status_label.text()
    assert not dialog.calculate_button.isEnabled()
    assert not window._conflict_cancellation_pending
    assert app is QApplication.instance()


def test_destructive_action_cancel_confirmation_changes_nothing(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    manager, conflict = _conflict(tmp_path)
    dialog = SubmissionConflictDialog(conflict)
    _select(dialog)
    calls = []
    dialog.actionRequested.connect(lambda *args: calls.append(args))
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *_args: QMessageBox.StandardButton.Cancel,
    )
    dialog.failed_button.click()
    dialog.delete_button.click()
    assert calls == []
    assert manager.store.get(conflict.conflicts[0].id).state == RunState.RUNNING
    assert app is QApplication.instance()


def test_cancel_from_conflict_dialog_returns_to_run_setup(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    _manager, conflict = _conflict(tmp_path)
    window = calculation.SprkkrRunWindow(SimpleNamespace(directory=str(tmp_path)))
    returned = []
    monkeypatch.setattr(window, "_return_to_setup", lambda: returned.append(True))
    monkeypatch.setattr(
        SubmissionConflictDialog, "exec",
        lambda dialog: (dialog.cancel_button.click() or dialog.result()),
    )
    window._on_conflict(conflict)

    assert returned == [True]
    assert app is QApplication.instance()


def test_calculate_action_launches_only_after_resolution(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    _manager, conflict = _conflict(tmp_path)
    window = calculation.SprkkrRunWindow(SimpleNamespace(directory=str(tmp_path)))
    started = []
    monkeypatch.setattr(window, "_retry_after_conflict", lambda: started.append(True))

    def user_resolves_and_calculates(dialog):
        assert not dialog.calculate_button.isEnabled()
        dialog.set_conflicts(DuplicateSubmissionError(conflict.record, ()))
        dialog.calculate_button.click()
        return dialog.result()

    monkeypatch.setattr(SubmissionConflictDialog, "exec", user_resolves_and_calculates)
    window._on_conflict(conflict)

    assert started == [True]
    assert app is QApplication.instance()



def test_pending_backend_stop_does_not_close_dialog_or_allow_calculation(
    monkeypatch, tmp_path
):
    app = QApplication.instance() or QApplication([])
    manager, conflict = _conflict(tmp_path)
    _window_obj, dialog = _window(tmp_path, manager, conflict)
    original = conflict.conflicts[0]

    def pending_cancel(run_id):
        assert run_id == original.id
        return manager.store.get(run_id)

    monkeypatch.setattr(manager, "cancel", pending_cancel)
    _select(dialog)
    dialog.stop_button.click()

    assert manager.store.get(original.id).state == RunState.RUNNING
    assert dialog.details.topLevelItemCount() == 1
    assert not dialog.calculate_button.isEnabled()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert app is QApplication.instance()
