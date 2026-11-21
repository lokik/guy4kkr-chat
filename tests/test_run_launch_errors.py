"""Rejected launches return to profile selection after worker cleanup."""
from __future__ import annotations

import sys

import pytest
from ase.build import bulk
from ase2sprkkr import InputParameters
from kkrunner import ExecutionSpec, Run
from kkrunner.backends import DirectBackend
from kkrunner.client import EndpointClient
from kkrunner.execution import MpiSpec
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QMessageBox, QWidget

from ase2sprkkr_gui.gui.application import sprkkr_execution
from ase2sprkkr_gui.gui.application.execution_cancellation import RunCancellation
from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.dialogs import run_calculation as run_dialog
from ase2sprkkr_gui.gui.dialogs.profiles import RunIdentification
from ase2sprkkr_gui.gui.flows import calculation


@pytest.mark.parametrize("use_mpi", [False, True])
def test_missing_executable_shows_error_then_reopens_same_run_setup(monkeypatch, tmp_path, use_mpi):
    parameters = InputParameters.create("SCF")
    controller = WorkspaceController(WorkspaceState(
        atoms=bulk("Fe", "bcc", a=2.87, cubic=True),
        input_parameters=parameters, directory=str(tmp_path),
    ))
    missing = tmp_path / ("embscfMPI" if use_mpi else "embscf")
    selected, errors, launched = [], [], []
    identification = RunIdentification("Fe_missing", "test-launch")
    parent = QWidget()
    loop = QEventLoop()

    def select_profile(_parent, **kwargs):
        selected.append(kwargs)
        if len(selected) == 1:
            return True, "broken-profile", identification, str(tmp_path), None
        assert errors, "Show the concrete error before reopening setup"
        assert kwargs["selected_profile_name"] == "broken-profile"
        assert kwargs["initial_identification"] == identification
        assert kwargs["directory"] == str(tmp_path)
        assert kwargs["directory_is_explicit"] is True
        loop.quit()
        return False, None, None, None, None

    class Calculator:
        def create_run(self, **_kwargs):
            spec = ExecutionSpec(
                argv=(sys.executable,) if use_mpi else (str(missing),),
                mpi_argv=(str(missing),) if use_mpi else None,
                mpi=MpiSpec(required=True, launcher=(sys.executable,)) if use_mpi else MpiSpec(),
                directory=str(tmp_path), output_file=str(tmp_path / "output.txt"),
            )
            runner = Run.untracked(EndpointClient(DirectBackend), spec)
            launched.append(runner)
            return runner

    def show_error(window, title, message):
        assert not window._thread.isRunning()
        assert title == "Could Not Start Calculation"
        assert "Executable not found" in message
        assert str(missing) in message
        assert message in window._output.toPlainText()
        errors.append(message)

    monkeypatch.setattr(calculation, "_select_profile", select_profile)
    monkeypatch.setattr(calculation, "profile_description", lambda _name: "Broken profile")
    monkeypatch.setattr(sprkkr_execution, "SPRKKR", lambda **_kwargs: Calculator())
    monkeypatch.setattr(QMessageBox, "critical", show_error)
    window = calculation.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), parent,
    )
    assert window is not None
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(5000)
    loop.exec()
    timer.stop()

    assert len(selected) == 2
    assert len(errors) == 1
    assert len(launched) == 1, "Cancelling the reopened picker must not retry automatically"
    assert controller.input_parameters is parameters
    assert controller.directory == str(tmp_path)
    parent.close()


def test_worker_keeps_execution_errors_out_of_profile_retry(monkeypatch):
    class Execution:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self):
            raise RuntimeError("SCF failed after starting")

    monkeypatch.setattr(run_dialog, "SprkkrExecution", Execution)
    worker = run_dialog._SprkkrRunWorker(object(), RunCancellation())
    errors, rejected = [], []
    worker.error.connect(errors.append)
    worker.submissionRejected.connect(rejected.append)
    worker.run()
    assert errors == ["SCF failed after starting"]
    assert rejected == []
