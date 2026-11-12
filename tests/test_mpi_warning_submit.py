from __future__ import annotations

import warnings

from ase import Atoms
from ase2sprkkr.execution import MpiNotFoundWarning

from guy4ase.gui.application import sprkkr_execution as execution_module
from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.application.workspace_controller import CalculationRequest


class _Cancellation:
    requested = False

    def register(self, _runner):
        return True


def test_execution_forwards_mpi_warning_from_submit(monkeypatch, tmp_path):
    request = CalculationRequest(
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=str(tmp_path),
        structure_id=1,
        state_id=1,
    )
    seen = []
    execution = SprkkrExecution(request, _Cancellation(), warning=seen.append)

    class Runner:
        reference = None
        id = "test-run"

        def submit(self):
            warnings.warn(
                "No MPI launcher on remote host",
                MpiNotFoundWarning,
            )

        def wait(self):
            return object()

    class Calculator:
        def create_run(self, **_kwargs):
            return Runner()

    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())
    monkeypatch.setattr(
        execution_module,
        "load_result",
        lambda _result, **_kwargs: object(),
    )

    execution.run()

    assert seen == ["No MPI launcher on remote host"]
