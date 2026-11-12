from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application import sprkkr_execution as execution_module
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    CalculationRequest,
    WorkspaceController,
)


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters()


class _Cancellation:
    requested = False

    def register(self, _runner):
        return True


def test_workspace_restart_is_snapshotted_into_request_and_result(tmp_path):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
            restarted=True,
        )
    )

    request = controller.create_calculation_request()
    assert request.restart_scf is True

    adoption = controller.adopt_calculation_result(
        LoadedResult(
            result=SimpleNamespace(task_name="DOS", produces_potential=False),
            output_path=None,
            potential_path=None,
            atoms=None,
            potential_error=None,
            directory=str(tmp_path),
        ),
        request=request,
    )

    assert adoption.record is not None
    assert adoption.record.restart_scf is True
    assert controller.restarted


def test_execution_forwards_restart_scf_to_create_run(monkeypatch, tmp_path):
    request = CalculationRequest(
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=str(tmp_path),
        structure_id=1,
        state_id=1,
        restart_scf=True,
    )
    execution = SprkkrExecution(request, _Cancellation())

    submitted = []
    seen = {}

    class Runner:
        reference = None
        id = "test-run"

        def submit(self):
            submitted.append(True)

        def wait(self):
            return object()

        def cancel(self):  # pragma: no cover - cancellation is not expected
            raise AssertionError("runner must not be cancelled")

    class Calculator:
        def create_run(self, **kwargs):
            seen.update(kwargs)
            return Runner()

    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())
    monkeypatch.setattr(
        execution_module,
        "load_result",
        lambda _result, **_kwargs: object(),
    )

    execution.run()

    assert seen["restart_scf"] is True
    assert seen["atoms"] is execution.request.atoms
    assert seen["atoms"] is not request.atoms
    assert seen["input_parameters"] is request.input_parameters
    assert submitted == [True]
